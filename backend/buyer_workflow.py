"""An optional, persisted buying-responsibility comparison.

This graph reads a frozen shortlist. It never changes scores, decisions or pipeline
records. The only research branch has one search pass and a four-attempt model
budget. Saved provider responses let retries avoid repeating completed calls.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import TypedDict
from uuid import uuid4
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END

from .buyers import BuyerResearchClient, followup_questions, prepare_comparison
from .live import LiveResearchError
from .live_config import get_live_status
from .store import Conflict, Store, now
from .workflows import add_usage, event


MAX_MODEL_ATTEMPTS = 4
MAX_SEARCH_PASSES = 1
MAX_EXECUTION_SECONDS = 360
POLICY_VERSION = 'buyer-qualification-v1'


class BuyerState(TypedDict, total=False):
    id: str
    run_id: str
    mode: str
    policy_version: str
    status: str
    current_node: str
    baseline: dict
    initial_candidates: list
    candidates: list
    followup: dict
    trace: list
    usage: dict
    budget: dict
    error: str | None
    can_retry: bool
    created_at: str
    updated_at: str
    _candidates: list
    _sources: list


class BuyerEngine:
    def __init__(self, db_path, client_factory=None):
        self.store = Store(db_path)
        self.client_factory = client_factory or BuyerResearchClient
        self.configured = (lambda: True) if client_factory else (lambda: get_live_status()['configured'])
        self.job_lock = RLock()
        self.graph_lock = RLock()
        self.jobs = set()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='leadgen-buyers')
        self.connection = sqlite3.connect(str(db_path) + '.buyer-checkpoints', check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.deadline = None
        graph = StateGraph(BuyerState)
        graph.add_node('assess_existing', self.assess_existing)
        graph.add_node('targeted_research', self.targeted_research)
        graph.add_node('assess_followup', self.assess_followup)
        graph.add_node('complete', self.complete)
        graph.add_edge(START, 'assess_existing')
        graph.add_conditional_edges('assess_existing', self.next_step,
                                    {'research': 'targeted_research', 'complete': 'complete'})
        graph.add_conditional_edges('targeted_research', self.after_research,
                                    {'assess': 'assess_followup', 'complete': 'complete'})
        graph.add_edge('assess_followup', 'complete')
        graph.add_edge('complete', END)
        self.graph = graph.compile(checkpointer=self.checkpointer)
        for record in self.store.buyer_checks():
            if record['status'] == 'running':
                record.update(status='failed', error='The server stopped during the buyer check. Saved work is preserved.',
                              updated_at=now())
                record['can_retry'] = self.can_retry(record)
                record['budget'] = self.budget(record)
                self.store.save_buyer_check(record)

    def close(self):
        self.executor.shutdown(wait=True)
        self.connection.close()

    @staticmethod
    def config(check_id):
        return {'configurable': {'thread_id': check_id}}

    @staticmethod
    def public(record):
        if record is None:
            return None
        return deepcopy({key: value for key, value in record.items() if not key.startswith('_')})

    @staticmethod
    def budget(record):
        attempts = sum(item['attempts'] for item in record.get('_reservations', []))
        return {'max_model_attempts': MAX_MODEL_ATTEMPTS,
                'accounted_model_attempts': attempts,
                'remaining_model_attempts': max(0, MAX_MODEL_ATTEMPTS - attempts),
                'max_search_passes': MAX_SEARCH_PASSES,
                'search_pass_consumed': bool(record.get('_search_attempted')),
                'usage_complete': not any(item['status'] == 'reserved' for item in record.get('_reservations', []))}

    @classmethod
    def can_retry(cls, record):
        if record.get('_search_attempted') and 'targeted_research' not in record.get('_completed_calls', {}):
            return False
        # Cached responses can still be materialized with an exhausted provider budget.
        stage = record.get('current_node')
        if stage == 'targeted_research' and stage not in record.get('_completed_calls', {}):
            return cls.budget(record)['remaining_model_attempts'] >= 2
        return (stage in record.get('_completed_calls', {}) or stage == 'complete'
                or cls.budget(record)['remaining_model_attempts'] > 0)

    def get(self, run_id):
        if not self.store.get_run(run_id):
            raise KeyError(run_id)
        return self.public(self.store.get_buyer_check(run_id))

    def require_configured(self):
        if not self.configured():
            raise Conflict('Live buyer checks need the configured Gemini connection. The illustrative comparison is available without a model call.')

    def start(self, run_id):
        with self.job_lock:
            run = self.store.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            existing = self.store.get_buyer_check(run_id)
            if existing:
                return self.public(existing)
            if run['status'] != 'completed':
                raise Conflict('Complete the research shortlist before checking buying responsibility.')
            self.require_configured()
            if self.jobs:
                raise Conflict('Another buyer check is running. Wait for it to finish before starting another one.')
            pack = prepare_comparison(deepcopy(run))
            if not pack['candidates']:
                raise Conflict('This shortlist has no eligible company records to assess.')
            stamp = now()
            record = {'id': uuid4().hex, 'run_id': run_id, 'mode': 'live',
                      'policy_version': POLICY_VERSION, 'status': 'running',
                      'current_node': 'assess_existing', 'baseline': pack['baseline'],
                      'initial_candidates': [], 'candidates': [],
                      'followup': {'performed': False, 'questions': [], 'queries': [],
                                   'sources': [], 'search_entry_point': ''},
                      'trace': [], 'usage': add_usage({}, {}), 'error': None,
                      'can_retry': False, 'created_at': stamp, 'updated_at': stamp,
                      '_candidates': pack['candidates'], '_sources': pack['sources'],
                      '_reservations': [], '_completed_calls': {}, '_search_attempted': False}
            record['budget'] = self.budget(record)
            self.store.save_buyer_check(record)
            return self.schedule(record)

    def retry(self, run_id):
        with self.job_lock:
            record = self.store.get_buyer_check(run_id)
            if record is None:
                raise KeyError(run_id)
            if record['status'] != 'failed':
                raise Conflict('Only a failed buyer check can be retried.')
            if not self.can_retry(record):
                if record.get('_search_attempted') and 'targeted_research' not in record.get('_completed_calls', {}):
                    raise Conflict('The one search pass was started but no response was saved. It cannot be repeated in this check. The original shortlist and any completed evidence assessment remain available.')
                raise Conflict('This buyer check has exhausted its four-attempt model budget. Its saved results remain available.')
            self.require_configured()
            return self.schedule(record)

    def schedule(self, record):
        with self.job_lock:
            if record['id'] in self.jobs:
                return self.public(self.store.get_buyer_check(record['run_id']))
            if self.jobs:
                raise Conflict('Another buyer check is running. Wait for it to finish before retrying.')
            self.jobs.add(record['id'])
            record.update(status='running', error=None, can_retry=False, updated_at=now())
            self.store.save_buyer_check(record)
            response = self.public(record)
            self.executor.submit(self.execute, record['run_id'])
            return response

    def persist(self, state, **updates):
        previous = self.store.get_buyer_check(state['run_id'])
        saved = {**deepcopy(state), **deepcopy(updates), 'updated_at': now()}
        # The provider ledger is written before graph checkpoint completion.
        for key in ('_reservations', '_completed_calls', '_search_attempted'):
            saved[key] = deepcopy(previous.get(key, [] if key == '_reservations' else {} if key == '_completed_calls' else False))
        saved['usage'] = deepcopy(previous.get('usage', saved.get('usage', {})))
        saved['budget'] = self.budget(saved)
        self.store.save_buyer_check(saved)
        return saved

    def progress(self, state, node, label):
        self.persist(state, status='running', current_node=node, error=None,
                     trace=state['trace'] + [event(node, label, 'Checking the saved scope and evidence.', 'running')])

    def provider_call(self, state, stage, method, *args):
        record = self.store.get_buyer_check(state['run_id'])
        if stage in record.get('_completed_calls', {}):
            return deepcopy(record['_completed_calls'][stage])
        if self.deadline is not None and monotonic() >= self.deadline:
            raise LiveResearchError('The buyer-check execution window ended. Saved stages are preserved.', code='deadline')
        if stage == 'targeted_research' and record.get('_search_attempted'):
            raise Conflict('The one targeted search was already started without a saved response. No second search will run.')
        used = self.budget(record)['accounted_model_attempts']
        if used >= MAX_MODEL_ATTEMPTS:
            raise LiveResearchError('The buyer check reached its four-attempt model budget. Saved evidence remains available.', code='budget')
        # Reserve up to two requests before entering the client, including a possible
        # model-not-found fallback. A crash keeps the conservative reservation.
        reservation = {'id': uuid4().hex, 'stage': stage, 'attempts': min(2, MAX_MODEL_ATTEMPTS - used),
                       'status': 'reserved', 'at': now()}
        record.setdefault('_reservations', []).append(reservation)
        if stage == 'targeted_research':
            record['_search_attempted'] = True
        record['budget'] = self.budget(record)
        self.store.save_buyer_check(record)
        prior = deepcopy(record.get('usage', {}))
        prior['model_calls'] = used
        client = None
        try:
            client = self.client_factory()
            if hasattr(client, 'account_for_usage'):
                client.account_for_usage(prior)
            result = getattr(client, method)(*args)
            self.record_call(state['run_id'], reservation['id'], result.get('usage', {}), result, stage)
            return result
        except LiveResearchError as exc:
            self.record_call(state['run_id'], reservation['id'], exc.usage, None, stage)
            raise
        finally:
            if client is not None and hasattr(client, 'close'):
                client.close()

    def record_call(self, run_id, reservation_id, usage, result, stage):
        record = self.store.get_buyer_check(run_id)
        entry = next(item for item in record['_reservations'] if item['id'] == reservation_id)
        entry.update(attempts=max(0, int(usage.get('model_calls', 0))), status='accounted')
        record['usage'] = add_usage(record.get('usage'), usage)
        if result is not None:
            record['_completed_calls'][stage] = deepcopy(result)
        record['budget'] = self.budget(record)
        record['updated_at'] = now()
        self.store.save_buyer_check(record)

    def assess_existing(self, state):
        self.progress(state, 'assess_existing', 'Assess the saved evidence')
        result = self.provider_call(state, 'assess_existing', 'assess_buyers',
                                    state['baseline']['scope'], state['_candidates'], state['_sources'])
        candidates = result['candidates']
        questions = followup_questions(candidates)[:6]
        return {'initial_candidates': candidates, 'candidates': deepcopy(candidates),
                'followup': {**state['followup'], 'questions': questions},
                'current_node': 'assess_existing',
                'trace': state['trace'] + [event('assess_existing', 'Assess the saved evidence',
                                                f"Assessed {len(candidates)} companies against the buying-responsibility rule using the same saved evidence. Commercial scores are unchanged.")]}

    @staticmethod
    def next_step(state):
        return 'research' if state['followup']['questions'] else 'complete'

    def targeted_research(self, state):
        self.progress(state, 'targeted_research', 'Research missing purchasing evidence')
        record = self.store.get_buyer_check(state['run_id'])
        if ('targeted_research' not in record['_completed_calls']
                and self.budget(record)['remaining_model_attempts'] < 2):
            raise LiveResearchError('The remaining model budget cannot cover both targeted research and its assessment. No additional search was started.', code='budget')
        result = self.provider_call(state, 'targeted_research', 'research_buyers',
                                    state['baseline']['scope'], state['_candidates'], state['_sources'],
                                    state['followup']['questions'])
        followup = {**state['followup'], 'performed': True, 'queries': result.get('queries', []),
                    'sources': result.get('sources', []), 'search_entry_point': result.get('search_entry_point', '')}
        detail = (f"Searched the unresolved purchasing questions once and captured {len(followup['sources'])} additional source references."
                  if followup['sources'] else 'No additional evidence captured; original buyer findings retained.')
        return {'followup': followup, 'current_node': 'targeted_research',
                'trace': state['trace'] + [event('targeted_research', 'One targeted research pass', detail)]}

    @staticmethod
    def after_research(state):
        return 'assess' if state['followup']['sources'] else 'complete'

    def assess_followup(self, state):
        self.progress(state, 'assess_followup', 'Assess the additional evidence')
        sources = state['_sources'] + state['followup']['sources']
        result = self.provider_call(state, 'assess_followup', 'assess_buyers',
                                    state['baseline']['scope'], state['_candidates'], sources)
        candidates = self.require_new_evidence_for_promotion(state, result['candidates'])
        return {'candidates': candidates, 'current_node': 'assess_followup',
                'trace': state['trace'] + [event('assess_followup', 'Assess the additional evidence',
                                                'Applied the same qualification rule to saved and newly captured sources. Missing purchasing evidence remains explicit.') ]}

    @staticmethod
    def require_new_evidence_for_promotion(state, results):
        """Do not present a second model opinion as a research improvement."""
        initial = {candidate['id']: candidate for candidate in state['initial_candidates']}
        followup_ids = {source['id'] for source in state['followup']['sources']}
        candidates = []
        for result in results:
            previous = initial.get(result['id'])
            if previous and not previous.get('eligible') and result.get('eligible'):
                procurement = result.get('roles', {}).get('procurement', {})
                supported_by_followup = any(evidence.get('phase') == 'followup'
                                           and evidence.get('source_id') in followup_ids
                                           and evidence.get('original_quote_matched') is True
                                           for evidence in procurement.get('evidence', []))
                if not supported_by_followup:
                    result = deepcopy(previous)
                    result['validation_issues'] = result.get('validation_issues', []) + [
                        'No new source evidence supports this promotion; saved-evidence status retained.']
            candidates.append(result)
        return candidates

    @staticmethod
    def complete(state):
        supported = sum(candidate.get('eligible', False) for candidate in state['candidates'])
        return {'status': 'completed', 'current_node': 'complete', 'error': None, 'can_retry': False,
                'updated_at': now(), 'trace': state['trace'] + [event('complete', 'Buyer comparison ready',
                    f"{supported} companies qualify under the direct-material-buyer rule. Original scores, technical gates, human decisions and pipeline records are unchanged.")]}

    def execute(self, run_id):
        record = self.store.get_buyer_check(run_id)
        try:
            with self.graph_lock:
                self.deadline = monotonic() + MAX_EXECUTION_SECONDS
                config = self.config(record['id'])
                snapshot = self.graph.get_state(config)
                initial = {key: value for key, value in record.items() if key in BuyerState.__annotations__} if not snapshot.values else None
                if initial is not None or snapshot.next:
                    for _ in self.graph.stream(initial, config, stream_mode='updates'):
                        saved = self.graph.get_state(config).values
                        if saved:
                            self.persist(saved, status='completed' if saved.get('status') == 'completed' else 'running')
                saved = self.graph.get_state(config).values
                if saved.get('status') != 'completed':
                    raise RuntimeError('Buyer comparison did not finish.')
                self.persist(saved)
        except Exception as exc:
            record = self.store.get_buyer_check(run_id)
            detail = str(exc) if isinstance(exc, (LiveResearchError, Conflict)) else 'The buyer check stopped unexpectedly. Completed stages and the original shortlist are preserved.'
            record.update(status='failed', error=detail, updated_at=now())
            record['can_retry'] = self.can_retry(record)
            if record.get('_search_attempted') and 'targeted_research' not in record.get('_completed_calls', {}):
                detail += ' The single search pass was started without a saved response and will not be repeated in this check.'
                record['error'] = detail
            record['budget'] = self.budget(record)
            record['trace'].append(event(record.get('current_node', 'buyer_check'), 'Buyer check stopped', detail, 'failed'))
            self.store.save_buyer_check(record)
        finally:
            self.deadline = None
            with self.job_lock:
                self.jobs.discard(record['id'])
