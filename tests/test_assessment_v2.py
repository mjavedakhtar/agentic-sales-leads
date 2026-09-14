"""Offline safeguards for v2. Model judgments are injected, not quality-evaluated."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.assessment import (
    CandidateEvidence, CriterionJudgment, LeadAssessment, POLICY_VERSION,
    calculate_lead, numeric_value, validate_candidate,
)
from backend.domain import retrieve


SCOPE = {'product_id': 'CS-AI'}
CHUNKS = retrieve('CS-AI', 'assembly bonding applications operating temperature')
ACTIVITY = 'Example assemblies repeatedly manufactures and bonds assembly packs for electric vehicles in Germany.'
CAPACITY = 'Our Example assemblies site manufactures 50000 assembly packs annually on its operating production lines.'


def fixture():
    facts = [dict(id='F1', dimensions=['application'], kind='activity', claim=ACTIVITY,
                  source_id='S1', quote=ACTIVITY, language='en', entity='Example assemblies',
                  entity_scope='site'),
             dict(id='F2', dimensions=['size'], kind='production_capacity', claim=CAPACITY,
                  source_id='S1', quote=CAPACITY, language='en', entity='Example assemblies',
                  entity_scope='site', quantity=dict(value=50000, value_text='50000',
                                                    unit='assembly packs/year', approximate=False))]
    row = dict(name='Example assemblies', domain='example.com', country='Germany', sector='EV assemblies',
               position='assembly assembler', application='assembly-pack bonding', hypothesis='assembly pack bonding may fit the retrieved product application.',
               source_ids=['S1'], product_chunk_ids=[CHUNKS[0]['id']], is_material_supplier=False,
               geography_match='supported', facts=facts, gaps=['Purchase volume still needs qualification.'],
               next_action='Confirm the material demand and application requirements.')
    source = dict(id='S1', url='https://example.com/assemblies', title='Example assemblies',
                  excerpt=ACTIVITY + ' ' + CAPACITY, grounded_summary=ACTIVITY,
                  source_type='live_public_page', captured_at='2026-09-14T10:00:00Z')
    return row, {'S1': source}


def validated(row=None, sources=None, scope=None, chunks=None):
    if row is None:
        row, sources = fixture()
    return validate_candidate(CandidateEvidence.model_validate(row), scope or SCOPE,
                              chunks or CHUNKS, sources)


def judgment(candidate, ratings=(5, 5, 5, 5)):
    return LeadAssessment.model_validate(dict(
        candidate_id=candidate['id'], eligible=True, eligibility_reason='The evidenced business is in the research scope.',
        fact_reviews=[dict(fact_id=f['id'], status='supported', reason='The quoted source supports this scoped claim.') for f in candidate['facts']],
        criteria=[dict(key=key, rating=rating, reason='The accepted activity supports this authored rubric judgment.',
                       fact_ids=['F2'] if key == 'size' else ['F1'],
                       product_chunk_ids=candidate['product_chunk_ids'] if key == 'application' else [])
                  for key, rating in zip(('size', 'application', 'sector', 'position'), ratings)],
        summary='A hypothetical rubric assessment based on public manufacturing evidence.', gaps=[],
        next_action='Confirm requirements and ownership before outreach.')).model_dump()


def assessed(candidate=None, assessment=None, scope=None, chunks=None):
    candidate = candidate or validated()
    return calculate_lead(candidate, assessment if assessment is not None else judgment(candidate),
                          scope or SCOPE, chunks or CHUNKS)


def criterion(lead, key):
    return next(c for c in lead['criteria'] if c['key'] == key)


@pytest.mark.parametrize('language,numeric,word', [('de', '23.000', 'Mitarbeitende'), ('en', '23,000', 'employees')])
def test_headcount_is_locale_independent_and_keeps_site_scope(language, numeric, word):
    row, sources = fixture()
    quote = f'Example assemblies has approximately {numeric} {word} at the Untertuerkheim site.'
    row['facts'].append(dict(id='F3', dimensions=['size'], kind='headcount', claim='Approximately 23,000 people work at this site.',
                             source_id='S1', quote=quote, language=language, entity='Untertuerkheim site',
                             entity_scope='site', as_of='2026', quantity=dict(value=23000, value_text=numeric,
                                                                           unit='employees', approximate=True)))
    sources['S1']['excerpt'] += ' ' + quote
    candidate = validated(row, sources)
    fact = next(f for f in candidate['facts'] if f['id'] == 'F3')
    assert fact['quantity']['value'] == 23000 and fact['quantity']['approximate'] is True
    assert fact['entity_scope'] == 'site' and fact['entity'] == 'Untertuerkheim site'
    assert fact['quote'] == quote and fact['language'] == language and fact['as_of'] == '2026'
    assessment = judgment(candidate)
    assessment['criteria'][0].update(fact_ids=['F3'], rating=3)
    lead = assessed(candidate, assessment)
    assert criterion(lead, 'size')['rating'] is None
    assert any('alone does not establish' in issue for issue in lead['validation_issues'])


@pytest.mark.parametrize('quoted,value_text,value,language', [
    ('250', '25', 25, 'en'), ('23.000', '23', 23, 'de'), ('23.000', '23.000', 23, 'de'),
    ('1,5', '1,5', 15, 'de'), ('23,000', '23,000', 23, 'en')])
def test_quantities_cannot_use_substrings_or_wrong_locale_values(quoted, value_text, value, language):
    row, sources = fixture()
    quote = f'Example assemblies reports {quoted} employees at its identified manufacturing site.'
    row['facts'][1].update(kind='headcount', quote=quote, language=language,
                           quantity=dict(value=value, value_text=value_text, unit='employees'))
    sources['S1']['excerpt'] += ' ' + quote
    candidate = validated(row, sources)
    assert [f['id'] for f in candidate['facts']] == ['F1']
    assert candidate['validation_issues']


def test_localized_decimal_and_million_values_are_not_conflated():
    assert numeric_value('1,5 Mio.', 'de') == numeric_value('1.5 million', 'en') == 1500000
    assert numeric_value('1.500', 'de') == numeric_value('1,500', 'en') == 1500
    assert numeric_value('1,5', 'de') == numeric_value('1.5', 'en') == 1.5
    assert numeric_value('1,50', 'en') is None


def test_full_rubric_and_fetched_coverage_are_reachable_without_observed_fit():
    lead = assessed()
    assert lead['score'] == lead['score_upper'] == 100
    assert [c['score'] for c in lead['criteria']] == [20, 40, 20, 20]
    assert lead['coverage'] == lead['assessment_completeness'] == 100
    assert lead['score_status'] == 'complete' and lead['scoring_version'] == POLICY_VERSION
    assert all(c['provenance'] == 'inferred' for c in lead['criteria'])
    # F1 has only an application dimension. Its meaning can still support other business questions.
    assert criterion(lead, 'sector')['fact_ids'] == ['F1']
    assert criterion(lead, 'position')['fact_ids'] == ['F1']


def test_unknown_and_supported_negative_have_distinct_points_ranges_and_coverage():
    candidate = validated()
    unknown = assessed(candidate, judgment(candidate, (None, 5, None, None)))
    negative = assessed(candidate, judgment(candidate, (0, 5, 0, 0)))
    assert criterion(unknown, 'size')['score'] is None
    assert criterion(negative, 'size')['score'] == 0
    assert unknown['score'] == 40 and unknown['score_upper'] == 100
    assert negative['score'] == negative['score_upper'] == 40
    assert unknown['score_status'] == 'provisional' and unknown['coverage'] == 25
    assert negative['score_status'] == 'complete' and negative['coverage'] == 100
    assert unknown['assessment_completeness'] == 25  # No known-only normalization to 100.


@pytest.mark.parametrize('mutation', ['unknown_fact', 'wrong_chunk', 'no_product_evidence', 'contradiction', 'duplicate_criterion', 'missing_review', 'duplicate_review'])
def test_unsupported_assessment_cannot_earn_application_points(mutation):
    candidate = validated()
    assessment = judgment(candidate)
    app = assessment['criteria'][1]
    if mutation == 'unknown_fact': app['fact_ids'] = ['invented']
    if mutation == 'wrong_chunk': app['product_chunk_ids'] = ['DS-PRO-p2-c1']
    if mutation == 'no_product_evidence': app['product_chunk_ids'] = []
    if mutation == 'contradiction': app['contradiction_fact_ids'] = ['F1']
    if mutation == 'duplicate_criterion': assessment['criteria'][2] = deepcopy(app)
    if mutation == 'missing_review': assessment['fact_reviews'] = [r for r in assessment['fact_reviews'] if r['fact_id'] != 'F1']
    if mutation == 'duplicate_review': assessment['fact_reviews'].append(deepcopy(assessment['fact_reviews'][0]))
    lead = assessed(candidate, assessment)
    assert criterion(lead, 'application')['rating'] is None
    assert criterion(lead, 'application')['score'] is None


@pytest.mark.parametrize('rating', [-1, 6, 1.5, True, '4'])
def test_schema_rejects_unbounded_or_coerced_rating(rating):
    with pytest.raises(ValidationError):
        CriterionJudgment(key='application', rating=rating, reason='This is a sufficiently long reason.')


@pytest.mark.parametrize('mutation', ['invented_quote', 'invented_source', 'duplicate_fact'])
def test_unverifiable_extraction_is_removed_before_model_assessment(mutation):
    row, sources = fixture()
    if mutation == 'invented_quote': row['facts'][1]['quote'] = 'This page contains a fabricated statement about an annual production volume.'
    if mutation == 'invented_source': row['facts'][1]['source_id'] = 'invented'
    if mutation == 'duplicate_fact': row['facts'].append(deepcopy(row['facts'][1]))
    candidate = validated(row, sources)
    assert [f['id'] for f in candidate['facts']] == ['F1']
    assert candidate['validation_issues']


def test_grounded_summary_support_remains_separate_from_fetched_coverage():
    row, sources = fixture()
    row['facts'] = [row['facts'][0]]
    row['facts'][0]['quote'] = ''
    sources['S1'].update(source_type='grounded_search_summary', excerpt='')
    candidate = validated(row, sources)
    assessment = judgment(candidate, (None, 3, 3, 3))
    lead = assessed(candidate, assessment)
    assert lead['score'] == 48 and lead['coverage'] == 0
    assert lead['assessment_completeness'] == 75
    assert all(e['quote'] == '' and e['provenance'] == 'inferred' for e in lead['evidence'] if e['source_type'] == 'grounded_search_summary')
    assert all(c['evidence_basis'] == 'summary' for c in lead['criteria'] if c['rating'] is not None)


@pytest.mark.parametrize('text,status', [
    ('Example assemblies does not manufacture assembly packs at its German site.', 'contradicted'),
    ('Example assemblies plans assembly pack production but the new site has not started operations.', 'insufficient'),
    ('Other Company makes assembly packs; Example assemblies provides administrative consulting.', 'contradicted'),
    ('Example assemblies closed assembly pack manufacturing at this site during 2020.', 'insufficient')])
def test_quote_occurrence_does_not_override_semantic_support_review(text, status):
    row, sources = fixture()
    row['facts'][0]['quote'] = text
    sources['S1']['excerpt'] = text + ' ' + CAPACITY
    candidate = validated(row, sources)
    assert candidate['facts'][0]['validation'] == 'quote_and_value_matched'
    assessment = judgment(candidate)
    assessment['fact_reviews'][0].update(status=status, reason='This source does not establish current relevant operations for this entity.')
    lead = assessed(candidate, assessment)
    assert criterion(lead, 'application')['rating'] is None
    fact = next(e for e in lead['evidence'] if e.get('fact_id') == 'F1')
    assert fact['quote'] == text and fact['provenance'] == 'unknown'
    assert fact['support_status'] == status


@pytest.mark.parametrize('applicable,expected', [(True, 'blocked'), (False, 'review')])
def test_technical_veto_needs_applicable_requirement_even_when_quote_matches(applicable, expected):
    row, sources = fixture()
    quote = 'Example assemblies requires a max latency of 5 ms for this application.'
    row['facts'].append(dict(id='F3', dimensions=['technical_requirement'], kind='technical_requirement', claim=quote,
                             source_id='S1', quote=quote, language='en', entity='Example assemblies', entity_scope='line',
                             quantity=dict(value=5, value_text='5', unit='ms'),
                             requirement=dict(name='max_latency_ms', value='5')))
    sources['S1']['excerpt'] += ' ' + quote
    candidate = validated(row, sources)
    assessment = judgment(candidate)
    assessment['fact_reviews'][-1]['is_customer_requirement'] = applicable
    lead = assessed(candidate, assessment)
    assert lead['score'] == 100 and lead['gate']['status'] == expected


def test_every_requirement_is_gated_so_later_compatible_value_cannot_hide_mismatch():
    row, sources = fixture()
    for index, value in enumerate((5, 120), start=3):
        quote = f'Example assemblies requires max latency at {value} ms for line {index}.'
        row['facts'].append(dict(id=f'F{index}', dimensions=['technical_requirement'], kind='technical_requirement', claim=quote,
                                 source_id='S1', quote=quote, language='en', entity=f'Example assemblies line {index}', entity_scope='line',
                                 quantity=dict(value=value, value_text=str(value), unit='ms'),
                                 requirement=dict(name='max_latency_ms', value=str(value))))
        sources['S1']['excerpt'] += ' ' + quote
    candidate = validated(row, sources)
    assessment = judgment(candidate)
    for review in assessment['fact_reviews'][2:]: review['is_customer_requirement'] = True
    assert assessed(candidate, assessment)['gate']['status'] == 'blocked'


def test_metadata_preserves_rubric_and_structured_judgment_without_mutating_inputs():
    candidate = validated()
    assessment = judgment(candidate)
    before = deepcopy((candidate, assessment))
    lead = calculate_lead(candidate, assessment, SCOPE, CHUNKS, metadata={'model': 'test-model', 'prompt_version': 'test-v2'})
    assert (candidate, assessment) == before
    assert lead['assessment_metadata']['structured_assessment'] == assessment
    assert lead['assessment_metadata']['rubric_version'] == POLICY_VERSION
    assert lead['assessment_metadata']['model'] == 'test-model'
    assert 'not calibrated' in lead['scoring_policy']['calibration']


@pytest.mark.parametrize('kind,value', [('headcount',-25),('headcount',2.5),('production_capacity',-50),('material_demand',-3)])
def test_invalid_count_or_material_quantity_is_not_accepted(kind, value):
    row, sources = fixture()
    quote = f'Example assemblies reports {value} units for this identified production activity.'
    row['facts'][1].update(kind=kind, quote=quote, quantity=dict(value=value,value_text=str(value),unit='units'))
    sources['S1']['excerpt'] += ' ' + quote
    assert [fact['id'] for fact in validated(row,sources)['facts']] == ['F1']


def test_sentence_punctuation_does_not_invalidate_original_numeric_value():
    row, sources = fixture()
    quote = 'The annual assembly pack capacity reported by Example assemblies is 50000.'
    row['facts'][1]['quote'] = quote
    sources['S1']['excerpt'] += ' ' + quote
    assert next(f for f in validated(row,sources)['facts'] if f['id']=='F2')['quantity']['value']==50000


def test_german_and_english_billion_have_different_scales():
    assert numeric_value('1 Billion','de') == 10**12
    assert numeric_value('1 billion','en') == 10**9
    assert numeric_value('1 Milliarde','de') == 10**9


@pytest.mark.parametrize('source_name,accepted', [('ZF',True),('SUPERZFOPERATIONS',False)])
def test_short_company_name_requires_a_complete_source_token(source_name, accepted):
    row,sources=fixture()
    row['name']='ZF'
    for fact in row['facts']:
        fact['claim']=fact['claim'].replace('Example assemblies',source_name)
        fact['quote']=fact['quote'].replace('Example assemblies',source_name)
        fact['entity']='ZF'
    for key in ('excerpt','grounded_summary'):
        sources['S1'][key]=sources['S1'][key].replace('Example assemblies',source_name)
    result=validated(row,sources)
    assert (result is not None) is accepted
    if accepted: assert result['name']=='ZF'


@pytest.mark.parametrize('key',['size','application'])
def test_assessment_can_use_additional_retrieved_chunks_from_the_selected_product(key):
    candidate=validated()
    assert len(CHUNKS) > 1, "Expected at least 2 chunks"
    assert CHUNKS[1]['id'] not in candidate['product_chunk_ids']
    assessment=judgment(candidate)
    next(c for c in assessment['criteria'] if c['key']==key)['product_chunk_ids']=[CHUNKS[1]['id']]
    lead=assessed(candidate,assessment)
    assert criterion(lead,key)['rating']==5
    assert criterion(lead,key)['product_chunk_ids']==[CHUNKS[1]['id']]
    assert CHUNKS[1]['id'] in lead['product_chunk_ids']
    assert any(e.get('chunk_id')==CHUNKS[1]['id'] for e in lead['evidence'])
