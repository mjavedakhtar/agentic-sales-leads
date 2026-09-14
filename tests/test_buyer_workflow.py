"""Buyer-comparison persistence, call limits, recovery and API boundaries."""
from copy import deepcopy
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from backend.buyer_workflow import BuyerEngine
from backend.live import LiveResearchError
from backend.main import create_app
from backend.store import Conflict, Store


def usage(search=False):
    return {'model_calls': 1, 'search_calls': int(search), 'search_queries': int(search),
            'input_tokens': 15, 'output_tokens': 10, 'total_tokens': 25, 'models': ['test-model']}


def saved_run(path, run_id='run-1'):
    record = {'id': run_id, 'title': 'Saved company shortlist', 'mode': 'live', 'status': 'completed',
              'created_at': '2026-09-14T12:00:00Z', 'updated_at': '2026-09-14T12:00:00Z',
              'scenario_id': None, 'scope': {'product_id': 'DS-PRO', 'geography': 'Germany'},
              'trace': [], 'leads': [{'id': 'company-1', 'name': 'Company One', 'score': 70,
                                     'gate': {'status': 'review'}, 'review': None, 'evidence': []}]}
    Store(path).save_run(record)
    return record


@pytest.fixture(autouse=True)
def policy_adapters(monkeypatch):
    # Policy/schema tests separately verify evidence strength. Here the policy is
    # injected so graph tests can focus on paid-call and persistence guarantees.
    def prepare(run):
        return {'baseline': {'run_id': run['id'], 'title': run['title'], 'scope': run['scope'],
                             'lead_count': len(run['leads'])},
                'candidates': deepcopy(run['leads']), 'sources': [{'id': 'S1', 'phase': 'saved'}]}

    def questions(results):
        return [{'candidate_id': item['id'], 'company': item['name'], 'question': 'Who purchases PA66?'}
                for item in results if item['buyer_status'] == 'unclear']

    monkeypatch.setattr('backend.buyer_workflow.prepare_comparison', prepare)
    monkeypatch.setattr('backend.buyer_workflow.followup_questions', questions)


class Adapter:
    def __init__(self, needs_research=True):
        self.needs_research = needs_research
        self.calls = []
        self.prior_usages = []
        self.fail_stage = None
        self.unexpected = False
        self.entered = Event()
        self.release = Event()
        self.release.set()

    def account_for_usage(self, prior):
        self.prior_usages.append(deepcopy(prior))

    def fail_if_requested(self, stage):
        if self.fail_stage == stage:
            self.fail_stage = None
            if self.unexpected:
                raise RuntimeError('Uncertain provider interruption')
            raise LiveResearchError('The buyer provider is temporarily unavailable.', usage=usage(stage == 'search'))

    def assess_buyers(self, scope, candidates, sources):
        stage = 'followup' if any(source['id'].startswith('F') for source in sources) else 'initial'
        self.calls.append((stage, deepcopy(scope), deepcopy(candidates), deepcopy(sources)))
        self.entered.set()
        assert self.release.wait(5)
        self.fail_if_requested(stage)
        supported = not self.needs_research or stage == 'followup'
        roles = {'procurement': {'status': 'supported' if supported else 'unknown', 'evidence': [
            {'source_id': 'F1' if stage == 'followup' else 'S1',
             'phase': 'followup' if stage == 'followup' else 'saved', 'original_quote_matched': True}] if supported else []}}
        rows = [{**candidate, 'buyer_status': 'supported_buyer' if supported else 'unclear',
                 'eligible': supported, 'roles': deepcopy(roles), 'summary': 'Test buying responsibility result.'}
                for candidate in candidates]
        return {'candidates': rows, 'usage': usage(), 'metadata': {'test': True}}

    def research_buyers(self, scope, candidates, sources, questions):
        self.calls.append(('search', deepcopy(scope), deepcopy(candidates), deepcopy(questions)))
        self.fail_if_requested('search')
        return {'sources': [{'id': 'F1', 'phase': 'followup'}], 'queries': ['Company One PA66 procurement'],
                'search_entry_point': '', 'usage': usage(True)}

    def close(self):
        pass


def terminal(engine, run_id='run-1'):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        result = engine.get(run_id)
        if result and result['status'] in {'completed', 'failed'}:
            # Let the terminal callback release its job slot before explicit retries.
            with engine.job_lock:
                active = result['id'] in engine.jobs
            if not active:
                return result
        sleep(.015)
    raise AssertionError('Buyer comparison did not reach a terminal state.')


def test_same_evidence_then_bounded_followup_preserves_original_records(tmp_path):
    path = tmp_path / 'buyers.db'
    original = saved_run(path)
    adapter = Adapter()
    adapter.release.clear()
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        assert engine.get(original['id']) is None
        pending = engine.start(original['id'])
        assert pending['status'] == 'running'
        assert adapter.entered.wait(2)
        assert engine.get(original['id'])['current_node'] == 'assess_existing'
        assert engine.start(original['id'])['id'] == pending['id']
        adapter.release.set()
        done = terminal(engine)
        assert done['status'] == 'completed', done['error']
        assert [call[0] for call in adapter.calls] == ['initial', 'search', 'followup']
        assert done['initial_candidates'][0]['buyer_status'] == 'unclear'
        assert done['candidates'][0]['buyer_status'] == 'supported_buyer'
        assert done['followup']['performed'] is True
        assert done['followup']['sources'] == [{'id': 'F1', 'phase': 'followup'}]
        assert done['usage']['model_calls'] == 3 and done['usage']['search_calls'] == 1
        assert done['budget']['accounted_model_attempts'] == 3
        assert done['budget']['usage_complete'] is True
        assert [prior['model_calls'] for prior in adapter.prior_usages] == [0, 1, 2]
        assert adapter.calls[0][3] == [{'id': 'S1', 'phase': 'saved'}]
        assert adapter.calls[2][3] == [{'id': 'S1', 'phase': 'saved'}, {'id': 'F1', 'phase': 'followup'}]
        assert engine.store.get_run(original['id']) == original
        assert engine.store.pipeline() == []
        assert not any(key.startswith('_') for key in done)
        assert engine.start(original['id']) == done
        assert len(adapter.calls) == 3
        assert [item['node'] for item in done['trace']] == ['assess_existing', 'targeted_research', 'assess_followup', 'complete']
    finally:
        adapter.release.set()
        engine.close()
    reopened = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        assert reopened.get(original['id']) == done
        assert len(adapter.calls) == 3
    finally:
        reopened.close()


def test_supported_saved_evidence_does_not_trigger_search(tmp_path):
    path = tmp_path / 'known.db'
    saved_run(path)
    adapter = Adapter(needs_research=False)
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.start('run-1')
        done = terminal(engine)
        assert done['status'] == 'completed'
        assert [call[0] for call in adapter.calls] == ['initial']
        assert done['followup']['performed'] is False
        assert done['initial_candidates'] == done['candidates']
        assert done['usage']['model_calls'] == 1 and done['usage']['search_calls'] == 0
    finally:
        engine.close()


@pytest.mark.parametrize('stage,expected', [('initial', ['initial', 'initial', 'search', 'followup']),
                                           ('followup', ['initial', 'search', 'followup', 'followup'])])
def test_failed_assessment_resumes_after_restart_without_repeating_search(tmp_path, stage, expected):
    path = tmp_path / 'retry.db'
    saved_run(path)
    adapter = Adapter()
    adapter.fail_stage = stage
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    engine.start('run-1')
    failed = terminal(engine)
    assert failed['status'] == 'failed' and failed['can_retry'] is True
    calls_before = len(adapter.calls)
    assert engine.start('run-1') == failed
    assert len(adapter.calls) == calls_before
    engine.close()
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.retry('run-1')
        done = terminal(engine)
        assert done['status'] == 'completed', done['error']
        assert [call[0] for call in adapter.calls] == expected
        assert done['usage']['model_calls'] == 4
        assert done['usage']['search_calls'] == 1
        assert done['budget']['remaining_model_attempts'] == 0
    finally:
        engine.close()


def test_ambiguous_search_failure_cannot_repeat_paid_search(tmp_path):
    path = tmp_path / 'search.db'
    original = saved_run(path)
    adapter = Adapter()
    adapter.fail_stage = 'search'
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.start('run-1')
        failed = terminal(engine)
        assert failed['status'] == 'failed' and failed['can_retry'] is False
        assert failed['initial_candidates'][0]['buyer_status'] == 'unclear'
        assert failed['budget']['search_pass_consumed'] is True
        assert failed['followup']['performed'] is False
        with pytest.raises(Conflict, match='cannot be repeated'):
            engine.retry('run-1')
        assert engine.store.get_run('run-1') == original
        assert [call[0] for call in adapter.calls] == ['initial', 'search']
        # Restart recovery must retain the already-consumed search pass.
        record = engine.store.get_buyer_check('run-1')
        record['status'] = 'running'
        engine.store.save_buyer_check(record)
    finally:
        engine.close()
    recovered = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        assert recovered.get('run-1')['status'] == 'failed'
        assert recovered.get('run-1')['can_retry'] is False
        with pytest.raises(Conflict):
            recovered.retry('run-1')
        assert len(adapter.calls) == 2
    finally:
        recovered.close()


def test_response_saved_before_graph_checkpoint_is_reused_without_provider_call(tmp_path):
    path = tmp_path / 'cache.db'
    saved_run(path)
    adapter = Adapter()
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    original_call = engine.provider_call
    interrupted = False

    def interrupted_after_response(state, stage, method, *args):
        nonlocal interrupted
        result = original_call(state, stage, method, *args)
        if stage == 'assess_existing' and not interrupted:
            interrupted = True
            raise RuntimeError('Simulate process interruption before graph checkpoint')
        return result

    engine.provider_call = interrupted_after_response
    try:
        engine.start('run-1')
        assert terminal(engine)['status'] == 'failed'
        engine.retry('run-1')
        done = terminal(engine)
        assert done['status'] == 'completed', done['error']
        assert [call[0] for call in adapter.calls] == ['initial', 'search', 'followup']
        assert done['usage']['model_calls'] == 3
    finally:
        engine.close()


def test_unknown_attempts_remain_reserved_and_prevent_unfunded_search(tmp_path):
    path = tmp_path / 'budget.db'
    saved_run(path)
    adapter = Adapter()
    adapter.fail_stage = 'initial'
    adapter.unexpected = True
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.start('run-1')
        failed = terminal(engine)
        assert failed['budget']['accounted_model_attempts'] == 2
        assert failed['budget']['usage_complete'] is False
        engine.retry('run-1')
        failed = terminal(engine)
        assert failed['status'] == 'failed'
        assert 'cannot cover both' in failed['error']
        assert [call[0] for call in adapter.calls] == ['initial', 'initial']
        assert failed['budget']['accounted_model_attempts'] == 3
        assert failed['budget']['search_pass_consumed'] is False
    finally:
        engine.close()


def test_api_read_only_example_idempotency_and_configuration(tmp_path, monkeypatch):
    path = tmp_path / 'api.db'
    saved_run(path)
    adapter = Adapter(needs_research=False)
    monkeypatch.setattr('backend.main.illustrative_comparison', lambda: {'mode': 'illustrative', 'status': 'completed'})
    app = create_app(path)
    with TestClient(app) as client:
        manager = app.state.buyer_engine
        manager.client_factory = lambda: adapter
        manager.configured = lambda: False
        url = '/api/runs/run-1/buyer-check'
        assert client.get(url).json() is None
        assert client.get('/api/buyer-checks/example').json()['mode'] == 'illustrative'
        assert not adapter.calls
        assert client.post(url).status_code == 409
        manager.configured = lambda: True
        response = client.post(url)
        assert response.status_code == 202
        done = terminal(manager)
        assert client.get(url).json() == done
        assert client.post(url).json() == done
        assert client.post(url + '/retry').status_code == 409
        assert len(adapter.calls) == 1
        assert client.get('/api/runs/missing/buyer-check').status_code == 404
        assert client.post('/api/runs/missing/buyer-check').status_code == 404
        run = manager.store.get_run('run-1')
        run['id'] = 'pending'
        run['status'] = 'awaiting_scope'
        manager.store.save_run(run)
        assert client.post('/api/runs/pending/buyer-check').status_code == 409


def test_only_one_buyer_job_runs_at_a_time(tmp_path):
    path = tmp_path / 'concurrent.db'
    saved_run(path)
    saved_run(path, 'run-2')
    adapter = Adapter(needs_research=False)
    adapter.release.clear()
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.start('run-1')
        assert adapter.entered.wait(2)
        with pytest.raises(Conflict, match='Another buyer check'):
            engine.start('run-2')
        assert engine.get('run-2') is None
        adapter.release.set()
        assert terminal(engine)['status'] == 'completed'
        engine.start('run-2')
        assert terminal(engine, 'run-2')['status'] == 'completed'
    finally:
        adapter.release.set()
        engine.close()


@pytest.mark.parametrize('citation', [
    {'source_id': 'S1', 'phase': 'saved', 'original_quote_matched': True},
    {'source_id': 'missing', 'phase': 'followup', 'original_quote_matched': True},
    {'source_id': 'F1', 'phase': 'followup', 'original_quote_matched': False},
])
def test_second_model_opinion_alone_cannot_promote_a_buyer(citation):
    initial = {'id': 'c1', 'eligible': False, 'buyer_status': 'unclear', 'roles': {}, 'validation_issues': []}
    state = {'initial_candidates': [initial], 'followup': {'sources': [{'id': 'F1'}]}}
    proposal = {**deepcopy(initial), 'eligible': True, 'buyer_status': 'supported_buyer',
                'roles': {'procurement': {'status': 'supported', 'evidence': [citation]}}}
    result = BuyerEngine.require_new_evidence_for_promotion(state, [proposal])[0]
    assert result['eligible'] is False
    assert result['buyer_status'] == 'unclear'
    assert 'saved-evidence status retained' in result['validation_issues'][0]
    assert initial['validation_issues'] == []


def test_new_followup_buyers_are_distinct_and_not_assigned_original_scores():
    original = {'id': 'c1', 'eligible': False, 'buyer_status': 'unclear'}
    found = {'id': 'buyer-new', 'eligible': True, 'buyer_status': 'supported_buyer',
             'score': None, 'origin': 'followup'}
    state = {'initial_candidates': [original], 'followup': {'sources': [{'id': 'F1'}]}}
    result = BuyerEngine.require_new_evidence_for_promotion(state, [original, found])
    assert result[0] == original
    assert result[1]['origin'] == 'followup' and result[1]['score'] is None



def test_no_additional_sources_retains_initial_findings_without_paid_reassessment(tmp_path):
    path = tmp_path / 'no-followup-evidence.db'
    original = saved_run(path)
    adapter = Adapter()
    research = adapter.research_buyers

    def no_sources(*args):
        result = research(*args)
        result['sources'] = []
        return result

    adapter.research_buyers = no_sources
    engine = BuyerEngine(path, client_factory=lambda: adapter)
    try:
        engine.start('run-1')
        done = terminal(engine)
        assert done['status'] == 'completed', done['error']
        assert [call[0] for call in adapter.calls] == ['initial', 'search']
        assert done['usage']['model_calls'] == 2
        assert done['usage']['search_calls'] == 1
        assert done['followup']['performed'] is True
        assert done['followup']['sources'] == []
        assert done['initial_candidates'] == done['candidates']
        assert done['candidates'][0]['buyer_status'] == 'unclear'
        assert [item['node'] for item in done['trace']] == ['assess_existing', 'targeted_research', 'complete']
        assert done['trace'][1]['detail'] == 'No additional evidence captured; original buyer findings retained.'
        assert engine.store.get_run('run-1') == original
    finally:
        engine.close()
