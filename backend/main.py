from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, ConfigDict
from .domain import SCENARIOS, PRODUCTS, DISCLOSURE, product, retrieve
from .store import Conflict
from .workflows import Engine
from .buyer_workflow import BuyerEngine
from .buyers import illustrative_comparison
from .evaluations import run_evaluations
from .live import LiveResearchError
from .live_config import get_live_status

ROOT=Path(__file__).resolve().parents[1]


class Body(BaseModel):
    model_config=ConfigDict(extra='forbid')


class StartBody(Body):
    scenario_id: str | None=Field(default=None,max_length=80)
    query: str | None=Field(default=None,max_length=1500)
    mode: Literal['live','replay']='replay'
    product_id: Literal['CS-AI','DS-PRO'] | None=None


class ScopeBody(Body):
    confirmed: Literal[True]


class DecisionBody(Body):
    decision: Literal['approve','reject','needs_research']
    note: str=Field(min_length=3,max_length=2000)
    @field_validator('note')
    @classmethod
    def trim_note(cls,value):
        value=value.strip()
        if len(value)<3:raise ValueError('Add a short note explaining the decision.')
        return value


class PipelineBody(Body):
    status: Literal['qualified','contacted','discovery','closed'] | None=None
    note: str | None=Field(default=None,min_length=3,max_length=2000)
    @field_validator('note')
    @classmethod
    def trim_note(cls,value):
        if value is not None:
            value=value.strip()
            if len(value)<3:raise ValueError('Add a short customer note.')
        return value


def create_app(db_path=None):
    selected_path=Path(db_path or os.environ.get('LEADGEN_DB_PATH',str(ROOT/'backend/data/leadgen.db')))
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine=Engine(selected_path)
        app.state.buyer_engine=BuyerEngine(selected_path)
        try:
            yield
        finally:
            app.state.buyer_engine.close()
            app.state.engine.close()
    app=FastAPI(title='TechNova LeadGenPlatform',version='0.1.0',lifespan=lifespan)

    @app.exception_handler(Conflict)
    async def conflict(request,exc):return JSONResponse(status_code=409,content={'detail':str(exc)})

    @app.exception_handler(LiveResearchError)
    async def live_error(request,exc):return JSONResponse(status_code=502,content={'detail':str(exc)})

    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse(status_code=404,content={'detail':'The requested record was not found.'})

    def engine(request):return request.app.state.engine

    @app.get('/api/health')
    def health():return {'status':'ok','app':'leadgen','modes':['live','replay'],'live_configured':get_live_status()['configured']}

    @app.get('/api/bootstrap')
    def bootstrap(request:Request):
        store=engine(request).store
        runs=store.runs(); pipeline=store.pipeline()
        live=get_live_status()
        return {'default_mode':'live' if live['configured'] else 'replay','capabilities':{'live':live,'buyer_checks':{'enabled':True,'configured':live['configured'],'max_model_attempts':4,'max_search_passes':1}},'disclosure':DISCLOSURE,'scenarios':SCENARIOS,'products':PRODUCTS,'runs':[{k:r[k] for k in ('id','title','status','created_at','scenario_id')}|{'mode':r.get('mode','replay'),'lead_count':len(r['leads'])} for r in runs], 'stats':{'runs':len(runs),'pipeline':len(pipeline),'awaiting_review':sum(sum(l['review'] is None for l in store.get_run(r['id'])['leads']) for r in runs)}}

    @app.post('/api/runs',status_code=201)
    def start(body:StartBody,request:Request):
        try:return engine(request).start(body.scenario_id,body.query,body.mode,body.product_id)
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.get('/api/runs/{run_id}')
    def run_detail(run_id:str,request:Request):
        run=engine(request).store.get_run(run_id)
        if not run:raise HTTPException(404,'Research run not found.')
        return run

    @app.get('/api/buyer-checks/example')
    def buyer_example():
        return illustrative_comparison()

    @app.get('/api/runs/{run_id}/buyer-check')
    def buyer_check(run_id:str,request:Request):
        return request.app.state.buyer_engine.get(run_id)

    @app.post('/api/runs/{run_id}/buyer-check',status_code=202)
    def start_buyer_check(run_id:str,request:Request):
        return request.app.state.buyer_engine.start(run_id)

    @app.post('/api/runs/{run_id}/buyer-check/retry',status_code=202)
    def retry_buyer_check(run_id:str,request:Request):
        return request.app.state.buyer_engine.retry(run_id)

    @app.post('/api/runs/{run_id}/scope')
    def confirm(run_id:str,body:ScopeBody,request:Request):return engine(request).confirm(run_id)

    @app.post('/api/runs/{run_id}/retry',status_code=202)
    def retry(run_id:str,request:Request):return engine(request).retry(run_id)

    @app.post('/api/runs/{run_id}/leads/{lead_id}/decision')
    def decision(run_id:str,lead_id:str,body:DecisionBody,request:Request):return engine(request).decide(run_id,lead_id,body.decision,body.note)

    @app.get('/api/pipeline')
    def pipeline(request:Request):return {'items':engine(request).store.pipeline()}

    @app.get('/api/pipeline/{item_id}')
    def pipeline_detail(item_id:str,request:Request):
        item=engine(request).store.pipeline_item(item_id)
        if not item:raise HTTPException(404,'Pipeline lead not found.')
        return item

    @app.patch('/api/pipeline/{item_id}')
    def pipeline_update(item_id:str,body:PipelineBody,request:Request):
        if body.note is None and body.status is None:raise HTTPException(422,'Add a note or select a status transition.')
        return engine(request).store.update_pipeline(item_id,body.status,body.note)

    @app.post('/api/pipeline/{item_id}/refresh')
    def pipeline_refresh(item_id:str,request:Request):return engine(request).store.update_pipeline(item_id,refresh=True)

    @app.get('/api/products')
    def products():return {'products':PRODUCTS}

    @app.get('/api/products/{product_id}/retrieve')
    def product_retrieve(product_id:str,q:str=Query(min_length=1,max_length=500)):
        if not product(product_id):raise HTTPException(404,'Product not found.')
        if not q.strip():raise HTTPException(422,'Enter a product question or keyword.')
        return {'chunks':retrieve(product_id,q),'method':'lexical','algorithm':'BM25','query':q,'product_id':product_id,'disclosure':'Retrieves saved PDF passages. No answer generation or live model call.'}

    @app.get('/api/documents/{filename}')
    def document(filename:str):
        allowed={Path(p['document_url']).name for p in PRODUCTS}
        if filename not in allowed:raise HTTPException(404,'Document not found.')
        return FileResponse(ROOT/'backend/data/documents'/filename,media_type='application/pdf')

    @app.post('/api/evals')
    def evaluate(request:Request):return engine(request).store.save_eval(run_evaluations())

    @app.get('/api/evals')
    def evaluations(request:Request):return engine(request).store.latest_eval()

    dist=ROOT/'frontend/dist'
    if (dist/'assets').exists():app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')

    @app.get('/{path:path}',include_in_schema=False)
    def frontend(path:str):
        if path.startswith('api/') or path=='api':raise HTTPException(404,'API endpoint not found.')
        target=(dist/path).resolve()
        if target.is_relative_to(dist.resolve()) and target.is_file():return FileResponse(target)
        if (dist/'index.html').exists():return FileResponse(dist/'index.html')
        return JSONResponse({'detail':'Frontend build is not present. Build frontend with npm run build, then restart the server.'},status_code=503)
    return app


app=create_app()
