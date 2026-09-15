"""LangGraph scope and qualification checkpoints with explicit live and replay paths.

Scope and qualification are separate graphs so each lead can be reviewed independently.
Live research nodes call the provider and persist progress. Review writes are idempotent.
"""
from typing import TypedDict
from time import perf_counter
import sqlite3
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from .domain import choose_scenario, scope_for, retrieve, COMPANIES, PRODUCTS, build_lead, synthetic_lead, technical_gate
from .live import GeminiResearchClient, LiveResearchError
from .assessment import calculate_lead, apply_technical_gate
from .live_config import get_live_status
from copy import deepcopy
from .store import Store, Conflict, now


class ResearchState(TypedDict, total=False):
    id: str
    title: str
    query: str
    scenario_id: str
    status: str
    created_at: str
    updated_at: str
    scope: dict
    leads: list
    trace: list
    retrieved_chunks: list
    captured_candidates: list
    confirmed: bool
    mode: str
    usage: dict
    usage_complete: bool
    live_research: dict
    extracted_evidence: dict
    llm_assessments: list
    extraction_metadata: dict
    assessment_metadata: dict
    workflow_version: str
    sources: list
    search_queries: list
    search_entry_point: str
    current_node: str
    error: str | None


def add_usage(previous, incoming):
    previous=previous or {}; incoming=incoming or {}
    return {**{key:previous.get(key,0)+incoming.get(key,0) for key in ('model_calls','search_calls','search_queries','input_tokens','output_tokens','total_tokens')},
            'models':list(dict.fromkeys(previous.get('models',[])+incoming.get('models',[])))}


class ReviewState(TypedDict, total=False):
    run_id: str
    lead_id: str
    decision: str
    note: str
    saved: bool


def event(node,label,detail,status='completed',started=None):
    return {'node':node,'label':label,'status':status,'detail':detail,'at':now(),'duration_ms':round((perf_counter()-started)*1000,2) if started else 0}


class Engine:
    def __init__(self,db_path,live_factory=None):
        self.store=Store(db_path)
        self.lock=RLock()
        self.job_lock=RLock()
        self.jobs=set()
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='leadgen-research')
        self.live_factory=live_factory or GeminiResearchClient
        self.connection=sqlite3.connect(str(db_path)+'.checkpoints',check_same_thread=False)
        self.checkpointer=SqliteSaver(self.connection)
        graph=StateGraph(ResearchState)
        for name,node in [('confirm_scope',self.confirm_scope_node),('retrieve_product',self.retrieve_node),('discover_candidates',self.discover_node),('extract_evidence',self.extract_node),('assess_fit',self.assess_node),('calculate_scores',self.calculate_node),('technical_gate',self.gate_node),('rank_candidates',self.rank_node)]:
            graph.add_node(name,node)
        chain=['confirm_scope','retrieve_product','discover_candidates','extract_evidence','assess_fit','calculate_scores','technical_gate','rank_candidates']
        graph.add_edge(START,chain[0])
        for left,right in zip(chain,chain[1:]): graph.add_edge(left,right)
        graph.add_edge(chain[-1],END)
        self.research=graph.compile(checkpointer=self.checkpointer)
        review=StateGraph(ReviewState)
        review.add_node('human_decision',self.review_node)
        review.add_node('persist_decision',self.persist_review_node)
        review.add_edge(START,'human_decision')
        review.add_edge('human_decision','persist_decision')
        review.add_edge('persist_decision',END)
        self.qualification=review.compile(checkpointer=self.checkpointer)
        for run in self.store.runs():
            if run.get('mode')=='live' and run['status']=='researching':
                run.update(status='failed',error='The server stopped during live research. Retry to resume from the last saved checkpoint.',updated_at=now(),usage_complete=False)
                self.store.save_run(run)

    def close(self):
        self.executor.shutdown(wait=True)
        self.connection.close()

    @staticmethod
    def public_state(state):
        return {k:v for k,v in state.items() if k not in ('captured_candidates','live_research','extracted_evidence','llm_assessments','__interrupt__','confirmed')}

    def progress(self,state,node,label):
        if state.get('mode')!='live':return
        run=self.public_state(state)
        run.update(status='researching',current_node=node,error=None,updated_at=now(),trace=state['trace']+[event(node,label,'Live research is executing this step.','running')])
        self.store.save_run(run)

    def live_call(self,method,*args,prior_usage=None):
        client=self.live_factory()
        try:
            if hasattr(client,'account_for_usage'):client.account_for_usage(prior_usage or {})
            return getattr(client,method)(*args)
        finally:
            if hasattr(client,'close'):client.close()

    def config(self,thread_id):return {'configurable':{'thread_id':thread_id}}

    def confirm_scope_node(self,state):
        confirmed=interrupt({'kind':'scope_confirmation','scope':state['scope'],'query':state['query']})
        if confirmed is not True:raise Conflict('Confirm the displayed research scope to continue.')
        return {'confirmed':True,'status':'researching','trace':state['trace']+[event('confirm_scope','Scope confirmed',f"Human confirmed the product, geography, application and {state.get('mode','replay')} research scope.")]}

    def retrieve_node(self,state):
        start=perf_counter()
        self.progress(state,'retrieve_product','Retrieve product evidence')
        chunks=retrieve(state['scope']['product_id'],state['scope']['application']+' applications commercial deployment latency throughput specifications')
        return {'retrieved_chunks':chunks,'trace':state['trace']+[event('retrieve_product','Retrieve product evidence',f"BM25 retrieved {len(chunks)} product-filtered PDF chunks with page citations. No embedding or model call.",started=start)]}

    def discover_node(self,state):
        if state.get('mode')=='live':
            start=perf_counter();self.progress(state,'discover_candidates','Search companies, jobs, RFPs and stack evidence')
            result=self.live_call('discover',state['scope'],state['retrieved_chunks'],prior_usage=state.get('usage'))
            return {'live_research':result,'sources':result.get('sources',[]),'search_queries':result.get('search_queries',[]),'search_entry_point':result.get('search_entry_point',''),
                    'usage':add_usage(state.get('usage'),result.get('usage')),
                    'trace':state['trace']+[event('discover_candidates','Live Google Search research',f"Gemini returned {len(result.get('sources',[]))} grounded source references from a new web research call.",started=start)]}
        start=perf_counter(); candidates=deepcopy(COMPANIES[state['scenario_id']])
        return {'captured_candidates':candidates,'trace':state['trace']+[event('discover_candidates','Replay captured discovery',f"Loaded {len(candidates)} curated company captures. This is a saved shortlist, not current web discovery.",started=start)]}

    def extract_node(self,state):
        if state.get('mode')=='live':
            start=perf_counter();self.progress(state,'extract_evidence','Extract and validate source evidence')
            result=self.live_call('extract',state['scope'],state['retrieved_chunks'],state['live_research'],prior_usage=state.get('usage'))
            extracted={'candidates':result['candidates'],'metadata':result.get('metadata',{}),
                       'raw_extraction':result.get('raw_extraction')}
            return {'extracted_evidence':extracted,'extraction_metadata':extracted['metadata'],
                    'usage':add_usage(state.get('usage'),result.get('usage')),'current_node':'extract_evidence',
                    'trace':state['trace']+[event('extract_evidence','Extract and validate evidence',f"Extracted {len(result['candidates'])} candidate evidence packs. Source, quotation and product-reference checks run before criterion assessment; semantic support remains a model judgment.",started=start)]}
        start=perf_counter(); candidates=[build_lead(row,state['scope']['product_id']) for row in state['captured_candidates']]
        if state['scenario_id']=='molders-de': candidates.append(synthetic_lead())
        observed=sum(e['provenance']=='observed' for c in candidates for e in c['evidence'])
        return {'leads':candidates,'trace':state['trace']+[event('extract_evidence','Attach evidence and unknowns',f"Attached {observed} source excerpts. Suitability hypotheses, self-reported size leadgens and unknowns are explicitly separate. Extraction is curated replay, not a new model response.",started=start)]}

    def assess_node(self,state):
        # Replay retains its captured scoring policy without claiming new model work.
        if state.get('mode')!='live':return {}
        start=perf_counter();self.progress(state,'assess_fit','Assess commercial fit against the rubric')
        result=self.live_call('assess',state['scope'],state['retrieved_chunks'],state['extracted_evidence'],prior_usage=state.get('usage'))
        return {'llm_assessments':result['assessments'],'assessment_metadata':result.get('metadata',{}),
                'usage':add_usage(state.get('usage'),result.get('usage')),'current_node':'assess_fit',
                'trace':state['trace']+[event('assess_fit','LLM criterion assessment',f"Assessed {len(result['assessments'])} candidates against the versioned rubric with evidence references, reasons and unknowns. The model does not set the final score.",started=start)]}

    def calculate_node(self,state):
        if state.get('mode')!='live':return {}
        start=perf_counter();self.progress(state,'calculate_scores','Calculate scores and evidence support')
        assessments={item['candidate_id']:item for item in state.get('llm_assessments',[])}
        metadata={'workflow_version':state['workflow_version'],
                  'extraction':state['extracted_evidence'].get('metadata',{}),
                  'assessment':state.get('assessment_metadata',{})}
        leads=[]
        for candidate in state['extracted_evidence']['candidates']:
            lead=calculate_lead(candidate,assessments.get(candidate['id']),state['scope'],state['retrieved_chunks'],metadata)
            if lead is not None:leads.append(lead)
        return {'leads':leads,'current_node':'calculate_scores',
                'trace':state['trace']+[event('calculate_scores','Calculate scores in code',f"Calculated {len(leads)} lead scores using validated criterion ratings and fixed weights. Unknown criteria remain explicit; evidence support and completeness are measured separately from fit. No model call.",started=start)]}

    def gate_node(self,state):
        start=perf_counter()
        self.progress(state,'technical_gate','Check technical constraints')
        checked=deepcopy(state['leads'])
        for lead in checked:
            if state.get('mode')=='live':
                lead['gate']=apply_technical_gate(lead,state['scope']['product_id'])
            else:
                lead['gate']=technical_gate(state['scope']['product_id'],{'deployment':'cloud_only'} if lead['synthetic'] else {})
        blocked=sum(l['gate']['status']=='blocked' for l in checked)
        return {'leads':checked,'current_node':'technical_gate','trace':state['trace']+[event('technical_gate','Apply technical constraints',f"{blocked} hard mismatch blocked. Unknown customer requirements remain pending qualification. Commercial score cannot override a hard mismatch.",started=start)]}

    def rank_node(self,state):
        start=perf_counter();self.progress(state,'rank_candidates','Rank candidates for human review')
        ranked=sorted(state['leads'],key=lambda x:(x['gate']['status']=='blocked',-(x.get('score') or 0),x['name']))
        detail=('Versioned rubric scores ranked by their lower bound; unresolved criteria cannot inflate a lead to a normalized perfect score. Human review remains required.' if state.get('mode')=='live' else 'Captured replay keeps its original 20 / 40 / 20 / 20 scoring policy and observed-coverage labels.')
        return {'leads':ranked,'status':'completed','current_node':'complete','error':None,'updated_at':now(),'trace':state['trace']+[event('rank_candidates','Rank for human review',detail,started=start)]}

    def review_node(self,state):
        answer=interrupt({'kind':'lead_qualification','run_id':state['run_id'],'lead_id':state['lead_id'],'decisions':['approve','reject','needs_research']})
        return {'decision':answer['decision'],'note':answer['note']}

    def persist_review_node(self,state):
        self.store.save_decision(state['run_id'],state['lead_id'],state['decision'],state['note'])
        return {'saved':True}

    def start(self,scenario_id=None,query=None,mode='replay',product_id=None):
        if mode not in {'live','replay'}:raise ValueError('Select live research or captured replay.')
        parsed_usage={};trace=[]
        if mode=='live':
            scenario=choose_scenario(scenario_id) if scenario_id else None
            query=(query or (scenario['query'] if scenario else '')).strip()
            if not query:raise ValueError('Describe the companies, application and market you want to research.')
            product_id=product_id or (scenario['product_id'] if scenario else None)
            if product_id not in {p['id'] for p in PRODUCTS}:raise ValueError('Select CloudScale AI or DataStream Pro for live research.')
            start=perf_counter();parsed=self.live_call('parse_scope',query,product_id)
            scope=parsed['scope'];scope['original_request']=query
            scope['product_id']=product_id
            parsed_usage=parsed.get('usage',{})
            title=f"{scope['product_name']} · {scope['geography']}"
            trace=[event('parse_scope','Interpret brief with Gemini','Generated a structured scope from the request. Public web search waits for human confirmation.',started=start)]
        else:
            scenario=choose_scenario(scenario_id,query);scope=scope_for(scenario);query=query or scenario['query'];title=scenario['title']
        at=now(); run_id=uuid4().hex
        state={'id':run_id,'title':title,'query':query,'scenario_id':scenario['id'] if scenario else None,'mode':mode,'workflow_version':'controlled-assessment-v2' if mode=='live' else 'captured-replay-v1','status':'awaiting_scope','created_at':at,'updated_at':at,'scope':scope,'leads':[],'retrieved_chunks':[],'usage':add_usage({},parsed_usage),'usage_complete':True,'error':None,'sources':[],'search_queries':[],'search_entry_point':'','trace':trace+[event('confirm_scope','Awaiting scope confirmation','LangGraph checkpoint saved. Public-source research has not run.','waiting')]}
        with self.lock:
            self.research.invoke(state,self.config(run_id))
            self.store.save_run(state)
        return state

    def confirm(self,run_id):
        run=self.store.get_run(run_id)
        if run is None:raise KeyError(run_id)
        if run.get('mode')=='live':
            if run['status'] in {'completed','researching'}:return run
            self.require_current_workflow(run)
            if run['status']=='failed':raise Conflict('This live run stopped. Use Retry live to resume its checkpoint.')
            return self.schedule_live(run)
        with self.lock:
            run=self.store.get_run(run_id)
            if run is None:raise KeyError(run_id)
            config=self.config(run_id)
            snapshot=self.research.get_state(config)
            if run['status']=='completed':return run
            if snapshot.next:
                result=self.research.invoke(Command(resume=True),config)
            else:
                # Handles crash after graph completed but before run materialization.
                result=snapshot.values
            public=self.public_state(result)
            self.store.save_run(public)
            for lead in public['leads']:
                review_config=self.config(f"review:{run_id}:{lead['id']}")
                if not self.qualification.get_state(review_config).values:
                    self.qualification.invoke({'run_id':run_id,'lead_id':lead['id']},review_config)
            return self.store.get_run(run_id)

    @staticmethod
    def require_current_workflow(run):
        if run.get('workflow_version')!='controlled-assessment-v2':
            raise Conflict('This saved run uses the earlier scoring workflow and cannot resume under scoring v2. Start a new research run. Its existing evidence, scores and decisions are preserved.')

    def schedule_live(self,run):
        self.require_current_workflow(run)
        with self.job_lock:
            current=self.store.get_run(run['id'])
            if current['id'] in self.jobs:return current
            if self.jobs:raise Conflict('Another live research run is active. Wait for it to finish before starting the next one.')
            self.jobs.add(run['id'])
            current.update(status='researching',error=None,current_node=current.get('current_node','confirm_scope'),updated_at=now())
            self.store.save_run(current)
            self.executor.submit(self.execute_live,run['id'])
            return current

    def retry(self,run_id):
        run=self.store.get_run(run_id)
        if not run:raise KeyError(run_id)
        if run.get('mode')!='live' or run['status']!='failed':raise Conflict('Only a failed live research run can be retried.')
        return self.schedule_live(run)

    def execute_live(self,run_id):
        try:
            with self.lock:
                config=self.config(run_id);snapshot=self.research.get_state(config)
                run=self.store.get_run(run_id)
                if run.get('usage_complete') is False:
                    self.research.update_state(config,{'usage':run.get('usage',{}),'usage_complete':False,'trace':run['trace']+[event('retry','Resume live research','Retrying from the last completed checkpoint. Failed-attempt usage remains visible.')]})
                    snapshot=self.research.get_state(config)
                if snapshot.next:
                    initial=Command(resume=True) if snapshot.next==('confirm_scope',) else None
                    for _ in self.research.stream(initial,config,stream_mode='updates'):
                        saved=self.research.get_state(config).values
                        if saved:
                            public=self.public_state(saved)
                            if public.get('status')!='completed':public['status']='researching'
                            self.store.save_run(public)
                saved=self.research.get_state(config).values
                public=self.public_state(saved)
                if public.get('status')!='completed':raise RuntimeError('Research did not finish.')
                self.store.save_run(public)
                for lead in public['leads']:
                    review_config=self.config(f"review:{run_id}:{lead['id']}")
                    if not self.qualification.get_state(review_config).values:
                        self.qualification.invoke({'run_id':run_id,'lead_id':lead['id']},review_config)
        except Exception as exc:
            run=self.store.get_run(run_id)
            detail=str(exc) if isinstance(exc,LiveResearchError) else 'Live research stopped unexpectedly. Retry from the saved checkpoint or choose captured replay explicitly.'
            if run:
                if isinstance(exc,LiveResearchError):run['usage']=add_usage(run.get('usage'),getattr(exc,'usage',{}))
                run.update(status='failed',error=detail,updated_at=now(),usage_complete=False)
                run['trace'].append(event(run.get('current_node','research'),'Live research stopped',detail,'failed'))
                self.store.save_run(run)
        finally:
            with self.job_lock:self.jobs.discard(run_id)

    def decide(self,run_id,lead_id,decision,note):
        with self.lock:
            run=self.store.get_run(run_id)
            if not run:raise KeyError(run_id)
            lead=next((l for l in run['leads'] if l['id']==lead_id),None)
            if not lead:raise KeyError(lead_id)
            if run['status']!='completed':raise Conflict('Complete research before reviewing a lead.')
            if lead['gate']['status']=='blocked' and decision=='approve':raise Conflict('This product has a hard technical mismatch and cannot be approved.')
            existing=self.store.review(run_id,lead_id)
            if existing:
                if existing['decision']==decision and existing['note']==note:
                    # Recover a crash after the transaction committed but before graph checkpoint finalization.
                    config=self.config(f"review:{run_id}:{lead_id}")
                    snapshot=self.qualification.get_state(config)
                    if snapshot.next:
                        self.qualification.invoke(None,config)
                    return self.store.get_run(run_id)
                raise Conflict('This lead already has a final decision. Start a new research run to reassess it with new evidence.')
            config=self.config(f"review:{run_id}:{lead_id}")
            snapshot=self.qualification.get_state(config)
            if not snapshot.values:
                self.qualification.invoke({'run_id':run_id,'lead_id':lead_id},config)
            self.qualification.invoke(Command(resume={'decision':decision,'note':note}),config)
            return self.store.get_run(run_id)
