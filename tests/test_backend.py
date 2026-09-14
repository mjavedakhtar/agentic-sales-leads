"""Boundary tests: persistent interrupts, decisions, evidence and pipeline invariants."""
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.domain import COMPANIES, leads_for, score_criteria, technical_gate, retrieve
from backend.workflows import Engine

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'test.db')) as client:
        yield client

def completed(client, scenario='assemblies-de'):
    response=client.post('/api/runs',json={'scenario_id':scenario})
    assert response.status_code==201,response.text
    run=response.json()
    assert run['status']=='awaiting_scope' and run['leads']==[]
    response=client.post(f"/api/runs/{run['id']}/scope",json={'confirmed':True})
    assert response.status_code==200,response.text
    assert response.json()['status']=='completed'
    return response.json()

def test_checkpoint_resume_after_restart(tmp_path):
    db=tmp_path/'durable.db'
    engine=Engine(db)
    run=engine.start('assemblies-de')
    snapshot=engine.research.get_state(engine.config(run['id']))
    assert snapshot.next==('confirm_scope',)
    assert snapshot.tasks[0].interrupts
    engine.close()
    restarted=Engine(db)
    result=restarted.confirm(run['id'])
    assert len(result['leads'])==4
    assert [e['node'] for e in result['trace']]==['confirm_scope','confirm_scope','retrieve_product','discover_candidates','extract_evidence','technical_gate','rank_candidates']
    lead=result['leads'][0]
    cfg=restarted.config(f"review:{run['id']}:{lead['id']}")
    assert restarted.qualification.get_state(cfg).tasks[0].interrupts
    restarted.close()
    resumed=Engine(db)
    reviewed=resumed.decide(run['id'],lead['id'],'approve','Confirm purchase owner in discovery call.')
    assert reviewed['leads'][0]['review']['decision']=='approve'
    assert resumed.qualification.get_state(cfg).next==()
    assert len(resumed.store.pipeline())==1
    resumed.close()

def test_approve_idempotency_and_required_note(client):
    run=completed(client)
    url=f"/api/runs/{run['id']}/leads/{run['leads'][0]['id']}/decision"
    assert client.post(url,json={'decision':'approve','note':'   '}).status_code==422
    body={'decision':'approve','note':'Application plausible; confirm demand and purchasing.'}
    assert client.post(url,json=body).status_code==200
    assert client.post(url,json=body).status_code==200
    assert len(client.get('/api/pipeline').json()['items'])==1
    assert client.post(url,json={'decision':'reject','note':'Changed my mind'}).status_code==409

def test_hard_gate_cannot_approve(client):
    run=completed(client,'molders-de')
    lead=next(l for l in run['leads'] if l['gate']['status']=='blocked')
    assert lead['synthetic'] is True and lead['score']==sum(c['score'] for c in lead['criteria'])
    url=f"/api/runs/{run['id']}/leads/{lead['id']}/decision"
    assert client.post(url,json={'decision':'approve','note':'Try to override mismatch'}).status_code==409
    assert client.post(url,json={'decision':'reject','note':'Wrong flammability grade'}).status_code==200
    assert client.get('/api/pipeline').json()['items']==[]

@pytest.mark.parametrize('decision',['reject','needs_research'])
def test_non_approval_decisions_persist_without_pipeline(client,decision):
    run=completed(client)
    lead=run['leads'][0]
    url=f"/api/runs/{run['id']}/leads/{lead['id']}/decision"
    assert client.post(url,json={'decision':decision,'note':'Need current source and application details.'}).status_code==200
    reread=client.get(f"/api/runs/{run['id']}").json()
    assert reread['leads'][0]['review']['decision']==decision
    assert client.get('/api/pipeline').json()['items']==[]

def test_pipeline_transitions_and_saved_capture_check_persist(tmp_path):
    path=tmp_path/'pipe.db'
    with TestClient(create_app(path)) as client:
        run=completed(client,'electronics-dach')
        client.post(f"/api/runs/{run['id']}/leads/{run['leads'][0]['id']}/decision",json={'decision':'approve','note':'Confirm telemetry requirements with application engineer.'})
        item=client.get('/api/pipeline').json()['items'][0]
        url=f"/api/pipeline/{item['id']}"
        assert client.patch(url,json={'status':'discovery','note':'Skip contact'}).status_code==409
        assert client.patch(url,json={'status':'contacted'}).status_code==409
        assert client.patch(url,json={'status':'contacted','note':'Customer asked for a technical conversation.'}).status_code==200
        assert client.patch(url,json={'note':'Customer uses outsourced telemetry. Buyer is EMS.'}).status_code==200
        checked=client.post(url+'/refresh').json()
        assert checked['refresh']['captured_at']==item['refresh']['captured_at']
        assert checked['refresh']['checked_at'] and checked['refresh']['status']=='saved_evidence_checked'
    with TestClient(create_app(path)) as client:
        saved=client.get(url).json()
        assert saved['status']=='contacted'
        assert len(saved['notes'])==3
        assert saved['history'][-1]['event']=='saved_evidence_checked'

def test_scoring_changes_with_evidence_and_retains_unknown_size():
    phoenix=leads_for('electronics-dach')[0]
    assert phoenix['id']=='phoenix' and phoenix['score']==72
    assert sum(c['score'] for c in phoenix['criteria'])==phoenix['score']
    assert sum(c['max'] for c in phoenix['criteria'])==100
    assert phoenix['criteria'][0]['score']==0 and phoenix['coverage']==50
    row=deepcopy(COMPANIES['electronics-dach'][0])
    row['application_level']='none'
    assert sum(c['score'] for c in score_criteria(row))==38
    sourced=next(l for l in leads_for('molders-de') if l['id']=='schroeder')
    assert sourced['criteria'][0]['score']==12 and sourced['coverage']==50
    assert any('115' in e['quote'] and e['provenance']=='observed' for e in sourced['evidence'])
    assert technical_gate('DS-PRO',{'deployment':'cloud_only'})['status']=='blocked'
    assert technical_gate('CS-AI',{'max_latency_ms':5})['status']=='blocked'
    assert technical_gate('CS-AI',{'unexpected':10})['status']=='review'

def test_evidence_observation_contract_and_product_filter():
    for rows in COMPANIES.values():
        for row in rows:
            assert row['quote'] in row['source_capture']['page_text']
            if row.get('extra_quote'):assert row['extra_quote'] in row['source_capture']['page_text']
    hits=retrieve('DS-PRO','MQTT Kafka')
    assert hits and all(h['product_id']=='DS-PRO' for h in hits)
    assert any(h['page']==1 and 'Kafka' in h['text'] for h in hits)
    assert retrieve('CS-AI','zyxwvnotinthecorpus')==[]

def test_scope_and_api_validation(client):
    assert client.post('/api/runs',json={'query':'Find all aerospace customers in Brazil'}).status_code==422
    assert client.post('/api/runs',json={'scenario_id':'assemblies-de','query':'Actually find only billion-dollar customers'}).status_code==422
    run=client.post('/api/runs',json={'scenario_id':'assemblies-de'}).json()
    assert client.post(f"/api/runs/{run['id']}/scope",json={'confirmed':False}).status_code==422
    assert client.get('/api/runs/does-not-exist').status_code==404
    assert client.get('/api/products/unknown/retrieve',params={'q':'bonding'}).status_code==404
    assert client.get('/api/unknown').status_code==404
    assert client.get('/api/documents/unknown.pdf').status_code==404
    assert client.post('/api/runs',json={'scenario_id':'assemblies-de','surprise':True}).status_code==422

def test_regression_suite_executes_and_persists(client):
    assert client.get('/api/evals').json() is None
    response=client.post('/api/evals')
    assert response.status_code==200,response.text
    result=response.json()
    assert result['passed']==result['total']==14,result
    assert sum(check['name'].startswith('V2:') for check in result['checks'])==4
    assert 'injected fixtures' in result['scope']
    assert client.get('/api/evals').json()==result


def test_crash_after_decision_commit_retries_without_duplicate_effect(tmp_path):
    path=tmp_path/'crash.db'
    engine=Engine(path)
    run=engine.confirm(engine.start('assemblies-de')['id'])
    lead_id=run['leads'][0]['id']
    original=engine.store.save_decision
    def commit_then_crash(*args):
        original(*args)
        raise RuntimeError('Simulated process failure after commit')
    engine.store.save_decision=commit_then_crash
    with pytest.raises(RuntimeError):
        engine.decide(run['id'],lead_id,'approve','Confirm demand with the technical buyer.')
    engine.close()
    recovered=Engine(path)
    result=recovered.decide(run['id'],lead_id,'approve','Confirm demand with the technical buyer.')
    assert len(recovered.store.pipeline())==1
    assert sum(e['node']=='human_decision' for e in result['trace'])==1
    config=recovered.config(f"review:{run['id']}:{lead_id}")
    assert recovered.qualification.get_state(config).next==()
    recovered.close()


@pytest.mark.parametrize('query,expected',[
    ('Find EV assembly pack manufacturers in Germany for CloudScale AI...', 'assemblies-de'),
    ('Show me potential German assembly module assemblers for CS-AI predictive maintenance', 'assemblies-de'),
    ('Find power electronics manufacturers and EMS providers across Germany, Austria and Switzerland for CloudScale AI', 'electronics-dach'),
    ('Identify DACH EMS companies for CloudScale AI quality assurance', 'electronics-dach'),
    ('Find German automotive injection moulders for DataStream Pro', 'molders-de'),
    ('Show me automotive injection manufacturing companies in Germany for DS-PRO edge telemetry', 'molders-de'),
])
def test_paraphrases_parse_but_still_interrupt_for_scope(client,query,expected):
    response=client.post('/api/runs',json={'query':query})
    assert response.status_code==201,response.text
    run=response.json()
    assert run['scenario_id']==expected and run['status']=='awaiting_scope'
    assert run['query']==query and not run['leads']


@pytest.mark.parametrize('query',[
    'Find EV assembly pack manufacturers in Germany and France for CloudScale AI',
    'Find EV assembly manufacturers in Germany for CloudScale AI with revenue above 100 million',
    'Find large German EV assembly manufacturers for CloudScale AI',
    'Find EV assembly manufacturers in Germany for CloudScale AI with over 500 employees',
    'Find EV assembly manufacturers in Germany for DataStream Pro',
    'Find power electronics manufacturers in Germany for CloudScale AI',
    'Find EV assembly manufacturers in Germany for CloudScale AI that require V-0',
    'Find EV assembly manufacturers outside Germany for CloudScale AI',
    'Find EV assembly manufacturers in Germany for CloudScale AI but not assemblers',
    'Find DACH EMS companies for CloudScale AI, excluding Austria',
    'Find German automotive molders for DataStream Pro with annual demand 100 tonnes',
])
def test_extra_qualifiers_are_never_silently_discarded(client,query):
    response=client.post('/api/runs',json={'query':query})
    assert response.status_code==422,response.text
    assert client.get('/api/bootstrap').json()['runs']==[]


def test_temperature_lower_bound_and_all_observed_excerpts():
    assert technical_gate('CS-AI', {'max_latency_ms': 5})['status'] == 'blocked'
    assert technical_gate('CS-AI', {'max_latency_ms': 20})['status'] == 'pass'
    for rows in COMPANIES.values():
        for row in rows:
            if row.get('size_quote'):
                assert row['size_quote'] in row['source_capture']['page_text']
