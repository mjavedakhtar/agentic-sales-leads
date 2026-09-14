"""Seed an isolated SQLite DB for browser_scoring_v2.mjs without model calls.

Run from the repo: .venv/bin/python tests/seed_scoring_browser.py
The JSON output includes the disposable DB path for LEADGEN_DB_PATH and the
fixture context file for LEADGEN_V2_FIXTURE. No application database is touched.
"""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.assessment import POLICY
from backend.domain import SCENARIOS, scope_for
from backend.store import Store
from backend.workflows import Engine


def seed():
    directory = Path(mkdtemp(prefix='leadgen-v2-browser-'))
    store = Store(directory / 'leadgen.db')
    helpers = runpy.run_path(str(ROOT / 'tests/test_assessment_v2.py'))
    row, sources = helpers['fixture']()
    quote = 'Example assemblies beschäftigt rund 23.000 Mitarbeitende am Standort Untertürkheim.'
    row['facts'].append(dict(id='F3', dimensions=['size'], kind='headcount',
                            claim='Approximately 23,000 employees work at the Untertürkheim site.',
                            source_id='S1', quote=quote, language='de', entity='Untertürkheim site',
                            entity_scope='site', as_of='2026',
                            quantity=dict(value=23000, value_text='23.000', unit='employees', approximate=True)))
    sources['S1']['excerpt'] += ' ' + quote
    candidate = helpers['validated'](row, sources)
    leads = []
    for suffix, label, ratings in [('complete', 'QA Complete assemblies', (5, 5, 5, 5)),
                                   ('provisional', 'QA Partial assemblies', (None, 4, 3, 3)),
                                   ('unknown', 'QA Unknown assemblies', (None, None, None, None))]:
        lead = helpers['assessed'](candidate, helpers['judgment'](candidate, ratings))
        lead.update(id='qa-' + suffix, name=label)
        leads.append(lead)
    scope = scope_for(SCENARIOS[0])
    scope['criteria'] = [{key: rule[key] for key in ('key', 'label', 'weight')} for rule in POLICY['criteria']]
    run = dict(id='qa-v2', title='QA fixture: rubric v2',
               query='Disposable browser fixtures, no public research or LLM calls.',
               scenario_id=None, mode='live', workflow_version='controlled-assessment-v2', status='completed',
               created_at='2026-09-14T23:00:00Z', updated_at='2026-09-14T23:00:00Z', scope=scope, leads=leads,
               retrieved_chunks=helpers['CHUNKS'], usage={'model_calls': 0, 'search_calls': 0, 'models': []},
               usage_complete=True, error=None, sources=list(sources.values()), search_queries=[],
               trace=[dict(node='calculate_scores', label='Offline QA fixture', status='completed',
                           detail='Injected rubric judgments for isolated browser checks. No live model calls.',
                           at='2026-09-14T23:00:00Z')])
    store.save_run(run)

    row, sources = helpers['fixture']()
    row['facts'] = row['facts'][:1]
    row['facts'][0]['quote'] = ''
    sources['S1'].update(source_type='grounded_search_summary', excerpt='')
    candidate = helpers['validated'](row, sources)
    judgment = helpers['judgment'](candidate, (None, 4, 3, 3))
    judgment['criteria'][0]['fact_ids'] = []
    lead = helpers['assessed'](candidate, judgment)
    lead.update(id='qa-summary', name='QA Summary assemblies')
    summary = deepcopy(run)
    summary.update(id='qa-summary', title='QA fixture: summaries only', created_at='2026-09-14T09:00:00Z',
                   leads=[lead], sources=list(sources.values()))
    store.save_run(summary)

    engine = Engine(directory / 'leadgen.db')
    try:
        legacy = engine.start(SCENARIOS[0]['id'])
        legacy = engine.confirm(legacy['id'])
        legacy.update(created_at='2026-09-14T10:00:00Z', title='QA fixture: captured policy v1')
        engine.store.save_run(legacy)
    finally:
        engine.close()
    historical = deepcopy(legacy)
    historical.update(id='qa-legacy-live', mode='live', title='QA fixture: historical live policy v1',
                      created_at='2026-09-14T08:00:00Z')
    store.save_run(historical)

    context = dict(db=str(directory / 'leadgen.db'), artifacts=str(directory / 'artifacts'), liveRun='qa-v2',
                   legacyRun=legacy['id'], legacyLead=legacy['leads'][0]['id'], legacyScore=legacy['leads'][0]['score'],
                   completePath='/leads/qa-v2/qa-complete', provisionalPath='/leads/qa-v2/qa-provisional',
                   unknownPath='/leads/qa-v2/qa-unknown')
    context_path = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/leadgen-v2-browser-context.json')
    context_path.write_text(json.dumps(context, indent=2))
    print(json.dumps({**context, 'fixtureFile': str(context_path)}, indent=2))


if __name__ == '__main__':
    seed()
