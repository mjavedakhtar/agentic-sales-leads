"""Buyer qualification safeguards with injected semantic judgments, no live API calls.

These tests check source validation, rule enforcement and provider contracts. They
are not a measurement of model accuracy at judging procurement responsibilities.
"""
from copy import deepcopy
import json

import httpx
import pytest

from backend.buyers import (
    ROLE_KEYS, BuyerJudgment, BuyerResearchClient, followup_questions,
    illustrative_comparison, prepare_comparison, qualify_buyer,
)
from backend.live import LiveResearchError
from backend.live_config import LiveConfig


SCOPE = {'product_id': 'DS-PRO', 'product_name': 'DataStream Pro',
         'geography': 'Germany', 'application': 'Automotive injection manufacturing',
         'additional_constraints': ['Exclude distributors.']}
QUOTE = ('Delta Components purchases PA66-GF30 granulate for its operating injection '
         'manufacturing plant in Germany. Its materials purchasing team owns resin sourcing.')


def candidate(**overrides):
    return dict(id='delta', name='Delta Components', country='Germany', domain='example.com',
                application='Automotive PA66 housings', score=72, score_upper=92,
                score_status='provisional', scoring_version='llm-rubric-v2',
                original_rank=1, origin='original', **overrides)


def source(**overrides):
    result = dict(id='B1', url='https://example.com/delta', title='Delta Components procurement',
                  text=QUOTE, source_type='live_public_page', captured_at='2026-09-14T10:00:00Z',
                  phase='initial', candidate_ids=['delta'])
    result.update(overrides)
    return result


def citation(item=None, **overrides):
    item = item or source()
    result = dict(source_id=item['id'], quote=item['text'], entity_matches=True,
                  material_matches=True, current_applicable=True, relation_matches=True,
                  reason='The quoted source explicitly assigns PA66 resin purchasing to this business.')
    result.update(overrides)
    return result


def role(status='unknown', evidence=None):
    return dict(status=status, reason='Responsibility is assessed for this specific material and operating entity.',
                evidence=evidence or [])


def judgment(candidate_id='delta', **roles):
    result = dict(candidate_id=candidate_id, **{key: role() for key in ROLE_KEYS},
                  contradictions=[], summary='Material procurement is evaluated separately from commercial fit.',
                  next_search_question='Who owns PA66 purchasing at this manufacturing site?')
    result.update(roles)
    return BuyerJudgment.model_validate(result).model_dump()


def supported_judgment(item=None):
    return judgment(procurement=role('supported', [citation(item)]))


def response(data, *, grounding=None):
    content = {'content': {'parts': [{'text': json.dumps(data) if isinstance(data, dict) else data}]},
               'finishReason': 'STOP'}
    if grounding is not None:
        content['groundingMetadata'] = grounding
    return {'candidates': [content], 'usageMetadata': {'promptTokenCount': 60,
                                                     'candidatesTokenCount': 30, 'totalTokenCount': 90}}


def client(handler, page_fetcher=None):
    return BuyerResearchClient(LiveConfig(api_key='test-only-placeholder', models=('gemini-test',)),
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                               page_fetcher=page_fetcher or (lambda url: None))


@pytest.mark.parametrize('language,quote', [
    ('en', QUOTE),
    ('de', 'Delta Components Einkauf beschafft PA66-GF30-Granulat fuer die eigene laufende Spritzgussfertigung in Deutschland.'),
])
def test_applicable_original_procurement_evidence_supports_buyer_in_either_language(language, quote):
    original = source(text=quote)
    lead = candidate()
    result = qualify_buyer(lead, supported_judgment(original), [original])
    assert result['buyer_status'] == 'supported_buyer' and result['eligible'] is True
    proof = result['roles']['procurement']['evidence'][0]
    assert proof['quote'] == quote and proof['original_quote_matched'] is True
    assert proof['phase'] == 'initial' and proof['source_type'] == 'live_public_page'
    assert result['score'] == 72 and result['score_upper'] == 92


@pytest.mark.parametrize('kind,expected', [
    ('finished_components', 'downstream_buyer'),
    ('material_use', 'material_user_or_specifier'),
    ('specification', 'material_user_or_specifier'),
])
def test_other_responsibilities_cannot_substitute_for_material_procurement(kind, expected):
    result = qualify_buyer(candidate(), judgment(**{kind: role('supported', [citation()])}), [source()])
    assert result['buyer_status'] == expected and result['eligible'] is False
    assert result['roles']['procurement']['status'] == 'unknown'
    assert result['score'] == 72


def test_customer_supplied_resin_retains_material_user_but_not_material_buyer():
    original = source(text='Delta Components molds PA66 parts using resin owned and supplied by its customers. Its contract excludes resin procurement.')
    proof = [citation(original)]
    assessment = judgment(material_use=role('supported', proof), customer_supplied=role('supported', proof),
                          procurement=role('contradicted', proof))
    result = qualify_buyer(candidate(), assessment, [original])
    assert result['buyer_status'] == 'material_user_or_specifier'
    assert result['roles']['procurement']['status'] == 'contradicted'
    assert result['eligible'] is False
    assert followup_questions([result]) == []


def test_conflicting_purchasing_and_customer_supplied_roles_cannot_qualify():
    assessment = supported_judgment()
    assessment['customer_supplied'] = role('supported', [citation()])
    result = qualify_buyer(candidate(), assessment, [source()])
    assert result['eligible'] is False and result['roles']['procurement']['status'] == 'unknown'
    assert any('customer-supplied' in issue for issue in result['validation_issues'])


def test_unresolved_source_conflict_overrides_positive_procurement_judgment():
    assessment = supported_judgment()
    assessment['contradictions'] = ['A current contract states that the customer supplies all resin at the same site.']
    result = qualify_buyer(candidate(), assessment, [source()])
    assert result['eligible'] is False
    assert result['contradictions'] == assessment['contradictions']
    assert result['roles']['procurement']['status'] == 'unknown'


@pytest.mark.parametrize('field', ['entity_matches', 'material_matches', 'current_applicable', 'relation_matches'])
def test_failed_semantic_scope_check_cannot_be_overridden_by_quote_occurrence(field):
    assessment = judgment(procurement=role('supported', [citation(**{field: False})]))
    result = qualify_buyer(candidate(), assessment, [source()])
    assert result['eligible'] is False
    assert result['roles']['procurement']['status'] == 'unknown'
    assert result['validation_issues']


@pytest.mark.parametrize('mutation', ['unknown_source', 'fabricated_quote', 'other_candidate', 'private_url', 'missing_quote', 'short_quote'])
def test_unverifiable_buyer_evidence_fails_closed(mutation):
    original, assessment = source(), supported_judgment()
    proof = assessment['procurement']['evidence'][0]
    if mutation == 'unknown_source': proof['source_id'] = 'invented'
    if mutation == 'fabricated_quote': proof['quote'] = 'An invented procurement statement that does not appear in the source.'
    if mutation == 'other_candidate': original['candidate_ids'] = ['unrelated-company']
    if mutation == 'private_url': original['url'] = 'http://127.0.0.1/private'
    if mutation == 'missing_quote': proof['quote'] = ''
    if mutation == 'short_quote': proof['quote'] = 'Delta Components'
    result = qualify_buyer(candidate(), assessment, [original])
    assert result['eligible'] is False and result['roles']['procurement']['status'] == 'unknown'
    assert result['validation_issues']


@pytest.mark.parametrize('kind', ['grounded_search_summary', 'saved_claim'])
def test_summary_only_material_use_is_tentative_and_cannot_establish_purchasing(kind):
    original = source(source_type=kind)
    proof = [citation(original, quote='')]
    result = qualify_buyer(candidate(), judgment(material_use=role('supported', proof),
                                                procurement=role('supported', proof)), [original])
    assert result['buyer_status'] == 'material_user_or_specifier' and result['eligible'] is False
    assert result['roles']['material_use']['status'] == 'supported'
    assert result['roles']['procurement']['status'] == 'unknown'
    assert result['roles']['material_use']['evidence'][0]['original_quote_matched'] is False


@pytest.mark.parametrize('assessment', [None, judgment(candidate_id='wrong-company')])
def test_absent_or_wrong_company_judgment_stays_unresolved(assessment):
    result = qualify_buyer(candidate(), assessment, [source()])
    assert result['buyer_status'] == 'unclear' and result['eligible'] is False
    assert all(result['roles'][key]['status'] == 'unknown' for key in ROLE_KEYS)


def test_followup_evidence_is_visible_and_does_not_mutate_initial_commercial_assessment():
    initial = source()
    additional = source(id='F1', phase='followup', candidate_ids=[])
    lead = candidate()
    lead['gate'] = {'status': 'blocked', 'reason': 'Illustrative product mismatch remains a technical block.'}
    assessment = supported_judgment(additional)
    before = deepcopy((lead, assessment, initial, additional))
    result = qualify_buyer(lead, assessment, [initial, additional])
    assert (lead, assessment, initial, additional) == before
    assert result['roles']['procurement']['evidence'][0]['phase'] == 'followup'
    assert result['gate'] == lead['gate']
    result['gate']['status'] = 'changed-in-test'
    assert lead['gate']['status'] == 'blocked'


def test_preparing_comparison_preserves_history_and_cannot_promote_legacy_claim_cards():
    lead = candidate()
    lead['review'] = {'decision': 'needs_research', 'notes': 'Preserve this decision.'}
    lead['evidence'] = [dict(id='legacy-fact', url='https://example.com/delta', title='Saved source',
                             quote=QUOTE, claim='The company purchases PA66 resin.',
                             source_type='captured_company_metadata', provenance='observed')]
    run = dict(id='saved-run', title='Saved shortlist', scope=deepcopy(SCOPE), mode='live', leads=[lead])
    before = deepcopy(run)
    prepared = prepare_comparison(run)
    assert run == before
    assert prepared['baseline']['lead_count'] == 1
    assert prepared['candidates'][0]['score_upper'] == 92
    assert prepared['sources'][0]['source_type'] == 'saved_claim'
    assert 'text' in prepared['sources'][0] and prepared['sources'][0]['text'] != QUOTE
    result = qualify_buyer(prepared['candidates'][0], supported_judgment(prepared['sources'][0]), prepared['sources'])
    assert result['eligible'] is False


def test_preparing_comparison_attaches_fetched_sources_to_their_actual_saved_candidate():
    lead = candidate()
    lead['evidence'] = [{'source_id': 'S1'}]
    run = dict(id='saved-run', title='Saved shortlist', scope=deepcopy(SCOPE), mode='live', leads=[lead],
               sources=[dict(id='S1', url='https://example.com/delta', title='Company source',
                             source_type='live_public_page', excerpt=QUOTE),
                        dict(id='S2', url='https://example.com/other', title='Unrelated source',
                             source_type='live_public_page', excerpt='Some unrelated company source.')])
    prepared = prepare_comparison(run)
    assert len(prepared['sources']) == 1
    assert prepared['sources'][0]['candidate_ids'] == ['delta']
    assert prepared['sources'][0]['original_source_id'] == 'S1'
    assert prepared['sources'][0]['text'] == QUOTE


def test_offline_illustration_explains_same_candidates_then_additional_evidence_without_api_calls():
    preview = illustrative_comparison()
    assert preview['mode'] == 'illustrative' and preview['usage']['model_calls'] == 0
    initial, final = preview['initial_candidates'], preview['candidates']
    assert [row['id'] for row in initial] == [row['id'] for row in final]
    assert [row['score'] for row in initial] == [row['score'] for row in final] == [84, 80, 76, 72, 68]
    assert [row['name'] for row in initial if row['eligible']] == ['Delta Components']
    assert [row['name'] for row in final if row['eligible']] == ['Delta Components', 'Elm Plastics']
    assert final[0]['buyer_status'] == 'downstream_buyer'
    assert final[1]['roles']['customer_supplied']['status'] == 'supported'
    assert final[2]['roles']['specification']['status'] == 'supported'
    assert final[4]['roles']['procurement']['evidence'][0]['phase'] == 'followup'
    for row in initial + final:
        assert row['illustrative'] is True
        for responsibility in row['roles'].values():
            for proof in responsibility['evidence']:
                assert proof['illustrative'] is True and proof['url'] == ''
                assert proof['source_type'] == 'illustrative'
    assert 'Fictional' in preview['disclosure'] and 'No search' in preview['disclosure']


def test_followup_targets_unknown_buyers_and_actual_upstream_buyers_of_downstream_prospects():
    known = qualify_buyer(candidate(), supported_judgment(), [source()])
    unknown = qualify_buyer(candidate(), None, [source()])
    downstream = qualify_buyer(candidate(), judgment(finished_components=role('supported', [citation()]),
                                                    procurement=role('contradicted', [citation()])), [source()])
    assert followup_questions([known]) == []
    assert len(followup_questions([unknown])) == len(followup_questions([downstream])) == 1
    assert len(followup_questions([unknown] * 12)) == 6


def test_buyer_provider_assessment_uses_schema_without_search_tools_or_score_fields():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response({'assessments': [supported_judgment()]}))
    adapter = client(handler)
    result = adapter.assess_buyers(SCOPE, [candidate()], [source()])
    body = requests[0]
    assert 'tools' not in body
    assert 'responseJsonSchema' in body['generationConfig']
    assert 'Do not change commercial scores' in body['contents'][0]['parts'][0]['text']
    assert 'untrusted data' in body['systemInstruction']['parts'][0]['text']
    assert result['candidates'][0]['eligible'] is True
    assert result['usage']['model_calls'] == 1 and result['usage']['search_calls'] == 0


@pytest.mark.parametrize('mutation', ['unknown', 'duplicate'])
def test_buyer_provider_rejects_unknown_and_duplicate_candidate_references(mutation):
    assessments = [supported_judgment()]
    if mutation == 'unknown': assessments[0]['candidate_id'] = 'invented-company'
    if mutation == 'duplicate': assessments.append(deepcopy(assessments[0]))
    adapter = client(lambda request: httpx.Response(200, json=response({'assessments': assessments})))
    with pytest.raises(LiveResearchError) as error:
        adapter.assess_buyers(SCOPE, [candidate()], [source()])
    assert error.value.code == 'buyer_reference' and error.value.usage['model_calls'] == 1


def test_empty_comparison_avoids_provider_calls_and_budget_is_separate_and_bounded():
    def fail_if_called(request):
        raise AssertionError('No provider request should be sent.')
    adapter = client(fail_if_called)
    result = adapter.assess_buyers(SCOPE, [], [])
    assert result['candidates'] == [] and result['usage']['model_calls'] == 0
    adapter.account_for_usage({'model_calls': 4, 'models': ['gemini-test']})
    with pytest.raises(LiveResearchError) as error:
        adapter.assess_buyers(SCOPE, [candidate()], [source()])
    assert error.value.code == 'budget' and error.value.usage['model_calls'] == 0


def test_followup_search_preserves_scope_and_records_new_sources_separately():
    requests = []
    grounding = {'webSearchQueries': ['Delta Components PA66 procurement Germany'],
                 'groundingChunks': [{'web': {'uri': 'https://example.com/delta', 'title': 'Delta Components'}}],
                 'groundingSupports': [{'segment': {'text': 'Delta Components sources PA66 resin.'},
                                        'groundingChunkIndices': [0]}]}
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response('Delta Components sources PA66 resin.', grounding=grounding))
    adapter = client(handler, page_fetcher=lambda url: {'url': url, 'text': QUOTE})
    before = deepcopy(SCOPE)
    result = adapter.research_buyers(SCOPE, [candidate()], [source()],
                                     [{'candidate_id': 'delta', 'company': 'Delta Components',
                                       'question': 'Who purchases PA66 for the German manufacturing plant?'}])
    assert SCOPE == before
    assert requests[0]['tools'] == [{'googleSearch': {}}]
    prompt = requests[0]['contents'][0]['parts'][0]['text']
    assert 'Exclude distributors.' in prompt and 'Germany' in prompt
    assert 'Who purchases PA66 for the German manufacturing plant?' in prompt
    assert result['usage']['search_calls'] == 1
    assert result['sources'][0]['id'] == 'F1'
    assert result['sources'][0]['phase'] == 'followup'
    assert result['sources'][0]['text'] == QUOTE
    assert result['sources'][0]['source_type'] == 'live_public_page'


def discovered_payload(original, *, scope_matches=True, procurement=True):
    other = deepcopy(original)
    other['candidate_ids'] = []
    found_judgment = judgment(candidate_id='buyer-upstream', procurement=role('supported', [citation(other)]) if procurement else role())
    return {'assessments': [judgment()], 'discovered_buyers': [
        dict(name='New Resin Processor', country='Germany', domain='example.com', scope_matches=scope_matches,
             scope_evidence=[citation(other)], judgment=found_judgment)]}


@pytest.mark.parametrize('phase,scope_matches,procurement,expected_count', [
    ('initial', True, True, 1), ('followup', False, True, 1),
    ('followup', True, False, 1), ('followup', True, True, 2),
])
def test_new_actual_buyers_need_followup_scope_evidence_and_supported_procurement(phase, scope_matches, procurement, expected_count):
    text = 'New Resin Processor purchases PA66 compounds for its operating injection manufacturing plant in Germany.'
    original = source(id='F1', text=text, phase=phase, candidate_ids=[])
    payload = discovered_payload(original, scope_matches=scope_matches, procurement=procurement)
    adapter = client(lambda request: httpx.Response(200, json=response(payload)))
    result = adapter.assess_buyers(SCOPE, [candidate()], [original])
    assert len(result['candidates']) == expected_count
    if expected_count == 2:
        found = result['candidates'][1]
        assert found['name'] == 'New Resin Processor' and found['eligible'] is True
        assert found['origin'] == 'followup' and found['original_rank'] is None
        assert found['score'] is None and found['score_upper'] is None
        assert found['score_status'] == 'unassessed'
        assert found['scope_evidence'][0]['phase'] == 'followup'
