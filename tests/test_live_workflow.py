"""Real graph/checkpoint boundaries with injected provider and scoring adapters.

Rubric and citation validation have dedicated assessment tests. These tests exercise
stage orchestration, retries, usage accounting, persistence, and API behavior.
"""
from copy import deepcopy
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from backend.domain import SCENARIOS, scope_for, leads_for
from backend.live import LiveResearchError
from backend.main import create_app
from backend.store import Conflict
from backend.workflows import Engine


def usage(searches=0):
    return dict(model_calls=1,search_calls=searches,search_queries=searches*2,input_tokens=20,output_tokens=10,total_tokens=30,models=['test-model'])


@pytest.fixture(autouse=True)
def workflow_calculator(monkeypatch):
    """Isolate checkpoint tests from rubric fixtures while enforcing stage contracts."""
    calls=[]

    def calculate(candidate,assessment,scope,chunks,metadata=None):
        calls.append((deepcopy(candidate),deepcopy(assessment),deepcopy(metadata)))
        assert candidate['facts'][0]['id']=='F1'
        assert assessment['candidate_id']==candidate['id']
        assert chunks and all(chunk['product_id']==scope['product_id'] for chunk in chunks)
        lead=deepcopy(leads_for('assemblies-de')[0])
        lead.update(id=candidate['id'],name=candidate['name'],country=candidate['country'],
                    scoring_policy='commercial-fit-v2',requirements=[])
        return lead

    monkeypatch.setattr('backend.workflows.calculate_lead',calculate)
    return calls


class Adapter:
    def __init__(self):
        self.calls=[]
        self.prior_usages=[]
        self.entered=Event()
        self.release=Event()
        self.release.set()
        self.fail_stage=None

    def account_for_usage(self,prior):
        self.prior_usages.append(deepcopy(prior))

    def fail_if_requested(self,stage):
        if self.fail_stage==stage:
            self.fail_stage=None
            raise LiveResearchError('The live provider is temporarily unavailable.',usage=usage(stage=='discover'))

    def parse_scope(self,query,product_id):
        self.calls.append(('scope',query,product_id))
        scope=scope_for(SCENARIOS[0]);scope['geography']='France';scope['limitations']=['Test live sources require qualification.']
        return {'scope':scope,'usage':usage()}

    def discover(self,scope,chunks):
        self.calls.append(('discover',deepcopy(scope),deepcopy(chunks)))
        self.entered.set()
        assert self.release.wait(4)
        self.fail_if_requested('discover')
        return {'answer':'A newly researched public finding.','sources':[{'id':'source-1','url':'https://example.org/public','title':'Live test source'}],'search_queries':['French assembly assembly'],'usage':usage(1),'search_entry_point':''}

    def extract(self,scope,chunks,research):
        self.calls.append(('extract',deepcopy(chunks),deepcopy(research)))
        self.fail_if_requested('extract')
        return {'candidates':[{'id':'live-only-lead','name':'Newly discovered company','country':'France',
                               'facts':[{'id':'F1','source_id':'source-1','claim':'The company assembles assembly packs.'}]}],
                'metadata':{'prompt_version':'evidence-extraction-v2'},
                'raw_extraction':{'candidates':[{'name':'Unvalidated model extraction'}]},'usage':usage()}

    def assess(self,scope,chunks,extracted):
        self.calls.append(('assess',deepcopy(chunks),deepcopy(extracted)))
        self.fail_if_requested('assess')
        return {'assessments':[{'candidate_id':extracted['candidates'][0]['id'],'criteria':[]}],
                'metadata':{'prompt_version':'commercial-assessment-v2'},'usage':usage()}

    def close(self):pass


def terminal(engine,run_id):
    deadline=monotonic()+5
    while monotonic()<deadline:
        run=engine.store.get_run(run_id)
        if run['status'] in {'failed','completed'}:return run
        sleep(.015)
    raise AssertionError('Research did not reach a terminal state.')


def test_live_scope_interrupt_background_progress_and_rag_context(tmp_path,workflow_calculator):
    adapter=Adapter();adapter.release.clear()
    engine=Engine(tmp_path/'live.db',live_factory=lambda:adapter)
    try:
        run=engine.start(query='Find assembly assemblers in France',mode='live',product_id='CS-AI')
        assert run['mode']=='live' and run['status']=='awaiting_scope'
        assert run['workflow_version']=='controlled-assessment-v2'
        assert [x[0] for x in adapter.calls]==['scope']
        assert run['scope']['original_request']=='Find assembly assemblers in France'
        pending=engine.confirm(run['id'])
        assert pending['status']=='researching'
        assert adapter.entered.wait(2)
        assert engine.store.get_run(run['id'])['current_node']=='discover_candidates'
        # Reads and repeated confirmation stay available while a provider is slow.
        assert engine.confirm(run['id'])['status']=='researching'
        adapter.release.set();done=terminal(engine,run['id'])
        assert done['status']=='completed' and done['leads'][0]['id']=='live-only-lead',done.get('error')
        assert done['usage']['model_calls']==4 and done['usage']['search_calls']==1
        assert done['usage']['search_queries']==2
        assert done['usage']['total_tokens']==120
        assert [value.get('model_calls',0) for value in adapter.prior_usages]==[0,1,2,3]
        assert done['sources'][0]['url']=='https://example.org/public'
        for private_key in ('live_research','captured_candidates','extracted_evidence','llm_assessments'):
            assert private_key not in done
        assert [call[0] for call in adapter.calls]==['scope','discover','extract','assess']
        assert adapter.calls[2][2]['answer']=='A newly researched public finding.'
        assert adapter.calls[3][2]['candidates'][0]['facts'][0]['id']=='F1'
        assert 'answer' not in adapter.calls[3][2]
        assert all(c['product_id']=='CS-AI' for c in adapter.calls[3][1])
        completed=[event['node'] for event in done['trace'] if event['status']=='completed']
        assert completed==['parse_scope','confirm_scope','retrieve_product','discover_candidates','extract_evidence','assess_fit','calculate_scores','technical_gate','rank_candidates']
        assert len(workflow_calculator)==1
        assert workflow_calculator[0][2]['extraction']==done['extraction_metadata']
        assert workflow_calculator[0][2]['assessment']==done['assessment_metadata']
        snapshot=engine.research.get_state(engine.config(run['id']))
        assert snapshot.values['extracted_evidence']['candidates']
        assert snapshot.values['extracted_evidence']['raw_extraction']=={'candidates':[{'name':'Unvalidated model extraction'}]}
        assert 'raw_extraction' not in done['extraction_metadata']
        assert 'raw_extraction' not in workflow_calculator[0][2]['extraction']
        assert snapshot.values['llm_assessments']
        reviewed=engine.decide(run['id'],'live-only-lead','approve','Confirm the customer process and buyer.')
        assert reviewed['leads'][0]['review']['decision']=='approve'
        assert len(engine.store.pipeline())==1
    finally:
        adapter.release.set();engine.close()


@pytest.mark.parametrize('stage,node,counts',[
    ('discover','discover_candidates',{'scope':1,'discover':2,'extract':1,'assess':1}),
    ('extract','extract_evidence',{'scope':1,'discover':1,'extract':2,'assess':1}),
    ('assess','assess_fit',{'scope':1,'discover':1,'extract':1,'assess':2}),
])
def test_failed_live_run_retries_its_stage_without_repeating_saved_work(tmp_path,stage,node,counts,workflow_calculator):
    adapter=Adapter();adapter.fail_stage=stage
    path=tmp_path/'retry.db';engine=Engine(path,live_factory=lambda:adapter)
    run=engine.start(query='Research assembly companies in France',mode='live',product_id='CS-AI')
    engine.confirm(run['id']);failed=terminal(engine,run['id'])
    assert failed['status']=='failed' and not failed['leads']
    assert failed['current_node']==node
    assert failed['trace'][-1]['node']==node and failed['trace'][-1]['status']=='failed'
    assert 'temporarily unavailable' in failed['error']
    assert failed['mode']=='live' and failed['usage_complete'] is False
    expected_failed_calls={'discover':2,'extract':3,'assess':4}[stage]
    assert failed['usage']['model_calls']==expected_failed_calls
    assert engine.research.get_state(engine.config(run['id'])).next==(node,)
    engine.close()
    restarted=Engine(path,live_factory=lambda:adapter)
    try:
        restarted.retry(run['id']);done=terminal(restarted,run['id'])
        assert done['status']=='completed',done.get('error')
        assert {name:sum(call[0]==name for call in adapter.calls) for name in counts}==counts
        assert done['usage']['model_calls']==5 and done['usage']['total_tokens']==150
        assert adapter.prior_usages[-1]['model_calls']==4
        assert len(workflow_calculator)==1
        assert all(not item['synthetic'] for item in done['leads'])
    finally:restarted.close()


def test_stale_live_job_is_recoverable_after_process_restart(tmp_path):
    path=tmp_path/'stale.db';adapter=Adapter();engine=Engine(path,live_factory=lambda:adapter)
    run=engine.start(query='assembly assembly in France',mode='live',product_id='CS-AI')
    run['status']='researching';engine.store.save_run(run);engine.close()
    recovered=Engine(path,live_factory=lambda:adapter)
    try:
        assert recovered.store.get_run(run['id'])['status']=='failed'
        recovered.retry(run['id'])
        assert terminal(recovered,run['id'])['status']=='completed'
    finally:recovered.close()


@pytest.mark.parametrize('status',['awaiting_scope','failed'])
def test_old_live_checkpoint_requires_new_run_and_preserves_saved_record(tmp_path,status):
    adapter=Adapter();engine=Engine(tmp_path/'legacy.db',live_factory=lambda:adapter)
    try:
        run=engine.start(query='assembly assembly in France',mode='live',product_id='CS-AI')
        run.pop('workflow_version');run['status']=status
        engine.store.save_run(run)
        before=engine.store.get_run(run['id'])
        action=engine.confirm if status=='awaiting_scope' else engine.retry
        with pytest.raises(Conflict,match='Start a new research run'):
            action(run['id'])
        assert engine.store.get_run(run['id'])==before
        assert [call[0] for call in adapter.calls]==['scope']
    finally:engine.close()


def test_completed_historical_run_is_returned_without_reassessment(tmp_path):
    adapter=Adapter();engine=Engine(tmp_path/'history.db',live_factory=lambda:adapter)
    try:
        run=engine.start(query='assembly assembly in France',mode='live',product_id='CS-AI')
        engine.confirm(run['id']);done=terminal(engine,run['id'])
        engine.decide(run['id'],'live-only-lead','needs_research','Keep the historical decision.')
        saved=engine.store.get_run(run['id']);saved.pop('workflow_version')
        saved['leads'][0]['score']=36
        engine.store.save_run(saved)
        before=engine.store.get_run(run['id']);call_count=len(adapter.calls)
        assert engine.confirm(run['id'])==before
        assert engine.store.get_run(run['id'])['leads'][0]['review']['decision']=='needs_research'
        assert len(adapter.calls)==call_count
    finally:engine.close()


def test_live_api_routes_and_explicit_mode(tmp_path):
    app=create_app(tmp_path/'api.db');adapter=Adapter()
    with TestClient(app) as client:
        app.state.engine.live_factory=lambda:adapter
        response=client.post('/api/runs',json={'query':'French assembly assemblers','product_id':'CS-AI','mode':'live'})
        assert response.status_code==201,response.text
        run=response.json()
        assert client.post(f"/api/runs/{run['id']}/scope",json={'confirmed':True}).json()['status']=='researching'
        done=terminal(app.state.engine,run['id'])
        assert done['mode']=='live' and done['leads'][0]['country']=='France'
        assert client.post(f"/api/runs/{run['id']}/retry").status_code==409
        assert client.post('/api/runs',json={'mode':'unexpected','query':'x'}).status_code==422
        assert client.post('/api/runs',json={'mode':'live','query':'French assembly assemblers'}).status_code==422
        assert client.get('/api/health').json()['app']=='leadgen'


def test_controlled_graph_uses_real_evidence_validation_and_rubric_calculation(tmp_path,monkeypatch):
    from backend.assessment import CandidateEvidence, LeadAssessment, calculate_lead, validate_candidate
    monkeypatch.setattr('backend.workflows.calculate_lead',calculate_lead)
    page=('Newly discovered company assembles 20,000 electric vehicle assembly packs each year in France. '
          'Its module assembly process uses automated predictive maintenance.')

    class EvidenceAdapter(Adapter):
        def extract(self,scope,chunks,research):
            self.calls.append(('extract',deepcopy(chunks),deepcopy(research)))
            row=CandidateEvidence.model_validate({
                'name':'Newly discovered company','domain':'example.org','country':'France',
                'sector':'EV assemblies','position':'assembly assembler','application':'assembly-module bonding',
                'hypothesis':'The reported module-assembly process may fit the retrieved predictive maintenance application.',
                'source_ids':['source-1'],'product_chunk_ids':[chunks[0]['id']],
                'is_competitor':False,'geography_match':'supported',
                'facts':[{'id':'F1','dimensions':['company','geography','size','application','sector','position'],
                          'kind':'production_capacity','claim':'The company reports recurring EV assembly production and module assembly.',
                          'source_id':'source-1','quote':page,'language':'en','entity':'Newly discovered company',
                          'entity_scope':'company','as_of':None,
                          'quantity':{'value':20000,'value_text':'20,000','unit':'packs/year','approximate':False}}],
                'gaps':['Customer technical requirements need qualification.'],
                'next_action':'Verify deployment requirements and annual platform demand.'})
            source={'id':'source-1','url':'https://example.org/public','title':'Company operations',
                    'source_type':'live_public_page','excerpt':page,'captured_at':'2026-09-14T10:00:00Z'}
            candidate=validate_candidate(row,scope,chunks,{'source-1':source})
            assert candidate is not None
            return {'candidates':[candidate],'usage':usage(),'metadata':{'model':'test-model'}}

        def assess(self,scope,chunks,extracted):
            self.calls.append(('assess',deepcopy(chunks),deepcopy(extracted)))
            candidate=extracted['candidates'][0]
            judgment=LeadAssessment.model_validate({
                'candidate_id':candidate['id'],'eligible':True,
                'eligibility_reason':'The company operates relevant assembly production in the requested market.',
                'fact_reviews':[{'fact_id':'F1','status':'supported','reason':'The quoted source supports the company production and assembly claims.'}],
                'criteria':[{'key':key,'rating':rating,'reason':'The company activity supports this anchored rubric judgment.',
                             'fact_ids':['F1'],'product_chunk_ids':[chunks[0]['id']] if key=='application' else []}
                            for key,rating in [('size',4),('application',4),('sector',4),('position',3)]],
                'summary':'EV assembly production and module assembly create a plausible application to qualify.',
                'gaps':['Confirm the buying owner and application conditions.'],
                'next_action':'Verify deployment requirements and annual platform demand.'})
            return {'assessments':[judgment.model_dump()],'usage':usage(),'metadata':{'model':'test-model'}}

    adapter=EvidenceAdapter();engine=Engine(tmp_path/'actual-scoring.db',live_factory=lambda:adapter)
    try:
        run=engine.start(query='assembly assemblers in France',mode='live',product_id='CS-AI')
        engine.confirm(run['id']);done=terminal(engine,run['id'])
        assert done['status']=='completed',done.get('error')
        lead=done['leads'][0]
        assert lead['scoring_version']=='llm-rubric-v2'
        assert lead['score']==76 and lead['score_upper']==76
        assert lead['coverage']==100 and lead['assessment_completeness']==100
        assert next(item for item in lead['criteria'] if item['key']=='application')['provenance']=='inferred'
        assert lead['gate']['status']=='review'
        assert lead['assessment_metadata']['structured_assessment']['candidate_id']==lead['id']
        assert done['usage']['model_calls']==4
        assert all('source_context' not in item for item in lead['evidence'])
    finally:engine.close()
