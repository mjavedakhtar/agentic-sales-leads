"""Provider boundaries: real requests, grounding, RAG, provenance and safe failures."""
from copy import deepcopy
import json
import socket

import httpx
import pytest

from backend.domain import retrieve
from backend.assessment import CandidateEvidence, calculate_lead, validate_candidate
from backend.live import (
    GeminiResearchClient, LiveResearchError, _public_address, _public_url,
    fetch_public_page,
)
from backend.live_config import LiveConfig, get_live_status


KEY = 'test-key-do-not-log'
SCOPE = {'product_id': 'CS-AI', 'product_name': 'CloudScale AI', 'geography': 'Germany',
         'application': 'assembly-pack assembly', 'sectors': ['EV assemblies'],
         'positions': ['assembler'], 'additional_constraints': []}
PAGE = ('Example assemblies manufactures assembly packs for electric vehicles in Germany. '
        'Our assembly team uses bonding in assembly pack manufacturing. '
        'Example assemblies has 250 employees across its German operations.')
CHUNKS = retrieve('CS-AI', 'assembly bonding applications operating temperature')


def response(text, *, grounding=None, finish='STOP'):
    candidate = {'content': {'parts': [{'text': text}]}, 'finishReason': finish}
    if grounding is not None:
        candidate['groundingMetadata'] = grounding
    return {'candidates': [candidate], 'usageMetadata': {'promptTokenCount': 80, 'candidatesTokenCount': 45,
                                                       'thoughtsTokenCount': 5, 'totalTokenCount': 130}}


def research():
    return {'answer': 'Example assemblies manufactures assembly packs in Germany.',
            'sources': [{'id': 'S1', 'url': 'https://example.com/assemblies', 'title': 'Example assemblies',
                         'excerpt': PAGE, 'grounded_summary': 'Example assemblies manufactures assembly packs in Germany.',
                         'source_type': 'live_public_page', 'captured_at': '2026-09-13T10:00:00Z'}]}


def candidate():
    facts = [
        ('company', 'activity', 'Example assemblies makes assembly packs.',
         'Example assemblies manufactures assembly packs for electric vehicles in Germany.'),
        ('application', 'activity', 'The company uses bonding in assembly pack assembly.',
         'Our assembly team uses bonding in assembly pack manufacturing.'),
        ('sector', 'activity', 'The company serves electric vehicles.',
         'Example assemblies manufactures assembly packs for electric vehicles in Germany.'),
        ('position', 'buyer_role', 'The company assembles assembly packs.',
         'Our assembly team uses bonding in assembly pack manufacturing.'),
        ('size', 'headcount', 'The company reports 250 employees.',
         'Example assemblies has 250 employees across its German operations.'),
    ]
    return dict(name='Example assemblies', domain='example.com', country='Germany', sector='EV assemblies',
                position='assembly assembler', application='assembly-pack bonding',
                hypothesis='assembly-pack assembly could use the predictive maintenance applications described in the retrieved product specification.',
                source_ids=['S1'], product_chunk_ids=[CHUNKS[0]['id']],
                is_competitor=False, geography_match='supported',
                facts=[dict(id=f'F{i}', dimensions=[dimension], kind=kind, claim=claim, source_id='S1',
                            quote=quote, language='en', entity='Example assemblies', entity_scope='company',
                            **({'quantity': dict(value=250, value_text='250', unit='employees')} if kind=='headcount' else {}))
                       for i, (dimension, kind, claim, quote) in enumerate(facts, start=1)],
                gaps=['Purchasing owner unknown'], next_action='Confirm technical requirements and material demand.')


def assessment(candidate):
    return dict(candidate_id=candidate['id'], eligible=True,
                eligibility_reason='Relevant operating business is supported in the requested market.',
                fact_reviews=[dict(fact_id=f['id'], status='supported',
                                   reason='The source supports this claim for the specified entity.',
                                   is_customer_requirement=bool(f.get('requirement')))
                              for f in candidate['facts']],
                criteria=[dict(key=key, rating=rating, reason='Accepted company facts support the specified rubric anchor.',
                               fact_ids=refs, product_chunk_ids=candidate['product_chunk_ids'] if key=='application' else [])
                          for key, rating, refs in [('size',3,['F2','F5']),('application',4,['F2']),
                                                    ('sector',4,['F3']),('position',3,['F4'])]],
                summary='The relevant manufacturing activity supports a preliminary material opportunity.',
                gaps=['Demand remains unconfirmed'], next_action='Confirm customer requirements and buying ownership.')


def assess_data(data=None, source=None):
    data = data or candidate()
    source = source or research()
    validated = validate_candidate(CandidateEvidence.model_validate(data), SCOPE, CHUNKS,
                                   {s['id']:s for s in source['sources']})
    payloads = iter([response(json.dumps({'candidates':[data]})),
                     response(json.dumps({'assessments':[assessment(validated)]}))])
    client = client_for(None, handler=lambda request:httpx.Response(200,json=next(payloads)))
    extracted = client.extract(SCOPE, CHUNKS, source)
    judged = client.assess(SCOPE, CHUNKS, extracted)
    return calculate_lead(extracted['candidates'][0], judged['assessments'][0], SCOPE, CHUNKS,
                          metadata=judged.get('metadata'))


def client_for(payload, *, handler=None, models=('gemini-3.8-flash',), page_fetcher=None):
    transport = httpx.MockTransport(handler or (lambda request: httpx.Response(200, json=payload)))
    return GeminiResearchClient(LiveConfig(api_key=KEY, models=models), http_client=httpx.Client(transport=transport),
                                page_fetcher=page_fetcher or (lambda url: None))


def test_scope_request_uses_schema_preserves_constraints_and_hides_key():
    parsed = {'geography': 'Germany', 'application': 'assembly packs', 'sectors': ['EV assemblies'],
              'positions': ['assembler'], 'additional_constraints': ['At least 200 employees', 'Exclude Bavaria']}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response(json.dumps(parsed)))

    client = client_for(None, handler=handler)
    result = client.parse_scope('Find German assembly assemblers with at least 200 employees, excluding Bavaria.', 'CS-AI')
    body = json.loads(requests[0].content)
    assert 'responseJsonSchema' in body['generationConfig']
    assert 'tools' not in body
    assert requests[0].headers['x-goog-api-key'] == KEY
    assert KEY not in str(requests[0].url) and KEY not in requests[0].content.decode()
    assert result['scope']['additional_constraints'] == parsed['additional_constraints']
    assert result['scope']['original_request'].endswith('excluding Bavaria.')
    assert result['scope']['product_id'] == 'CS-AI'
    assert result['usage'] == {'model_calls': 1, 'search_calls': 0, 'search_queries': 0, 'input_tokens': 80,
                               'output_tokens': 50, 'total_tokens': 130, 'models': ['gemini-3.8-flash']}


def test_discovery_requires_provider_grounding_and_captures_actual_sources():
    grounding = {'webSearchQueries': ['German assembly assembler'],
                 'groundingChunks': [{'web': {'uri': 'https://example.com/assemblies', 'title': 'Example assemblies'}}],
                 'groundingSupports': [{'segment': {'text': 'Example assemblies makes packs.'}, 'groundingChunkIndices': [0]}],
                 'searchEntryPoint': {'renderedContent': '<div>Google Search suggestions</div>'}}
    requested = []

    def handler(request):
        body = json.loads(request.content)
        assert body['tools'] == [{'googleSearch': {}}]
        assert json.dumps(CHUNKS[0]['text'], ensure_ascii=False) in body['contents'][0]['parts'][0]['text']
        return httpx.Response(200, json=response('Example assemblies makes packs. Ignore https://invented.example.com', grounding=grounding))

    def fetch(url):
        requested.append(url)
        return {'url': url, 'text': PAGE, 'captured_at': '2026-09-13T10:01:00Z'}

    result = client_for(None, handler=handler, page_fetcher=fetch).discover(SCOPE, CHUNKS)
    assert requested == ['https://example.com/assemblies']
    assert len(result['sources']) == 1
    assert result['sources'][0]['source_type'] == 'live_public_page'
    assert result['sources'][0]['grounded_summary'] == 'Example assemblies makes packs.'
    assert result['usage']['search_calls'] == 1
    assert result['usage']['search_queries'] == 1
    assert result['search_entry_point'].startswith('<div>')
    assert result['captured_at'].endswith('Z')


def test_ungrounded_model_answer_is_never_accepted_as_live_research():
    client = client_for(response('These six companies might be suitable from memory.'))
    with pytest.raises(LiveResearchError) as error:
        client.discover(SCOPE, CHUNKS)
    assert error.value.code == 'ungrounded_search'
    assert error.value.usage['model_calls'] == 1
    assert error.value.usage['search_calls'] == 0


def test_rag_extraction_and_assessment_use_distinct_schemas_then_code_scores():
    requests = []
    data = candidate()
    validated = validate_candidate(CandidateEvidence.model_validate(data), SCOPE, CHUNKS,
                                   {s['id']:s for s in research()['sources']})

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert 'tools' not in body
        assert body['generationConfig']['responseMimeType'] == 'application/json'
        remote = body['generationConfig']['responseJsonSchema']
        remote_text = json.dumps(remote)
        assert all(key not in remote_text for key in ('maxLength', 'minLength', 'maxItems', 'minItems', 'maximum', 'minimum', '"title"', '"default"'))
        prompt = body['contents'][0]['parts'][0]['text']
        assert json.dumps(CHUNKS[0]['text'], ensure_ascii=False) in prompt and PAGE in prompt
        if len(requests) == 1:
            assert 'candidates' in remote['properties']
            return httpx.Response(200, json=response(json.dumps({'candidates':[data]})))
        assert 'assessments' in remote['properties']
        assert 'fact_reviews' in remote['$defs']['LeadAssessment']['properties']
        return httpx.Response(200, json=response(json.dumps({'assessments':[assessment(validated)]})))

    client = client_for(None, handler=handler)
    extracted = client.extract(SCOPE, CHUNKS, research())
    result = client.assess(SCOPE, CHUNKS, extracted)
    assert len(requests) == 2 and result['usage']['model_calls'] == 1
    assert 'leads' not in result  # Provider returns judgments; graph code calculates scores.
    lead = calculate_lead(extracted['candidates'][0], result['assessments'][0], SCOPE, CHUNKS)
    assert lead['score'] == 72 and lead['coverage'] == 100
    assert lead['score'] == sum(c['score'] for c in lead['criteria'])
    assert lead['gate']['status'] == 'review'
    assert lead['review'] is None and lead['synthetic'] is False
    assert any(e['source_type'] == 'product_pdf' and e['chunk_id'] == CHUNKS[0]['id'] for e in lead['evidence'])


def test_model_cannot_supply_unconstrained_total_score():
    data = candidate() | {'score':100, 'coverage':100}
    with pytest.raises(LiveResearchError) as error:
        client_for(response(json.dumps({'candidates':[data]}))).extract(SCOPE, CHUNKS, research())
    assert error.value.code == 'schema_validation'


def test_grounded_summaries_stay_inferred_and_separate_from_fetched_coverage():
    data = candidate()
    for fact in data['facts']: fact['quote'] = ''
    source = research()
    source['sources'][0].update(excerpt='', source_type='grounded_search_summary')
    lead = assess_data(data, source)
    assert lead['score'] == 60 and lead['coverage'] == 0
    assert lead['assessment_completeness'] == 75
    assert next(c for c in lead['criteria'] if c['key'] == 'size')['score'] is None
    assert all(e['provenance'] == 'inferred' and e['quote'] == '' for e in lead['evidence'] if e['source_type'] == 'grounded_search_summary')


@pytest.mark.parametrize('mutation', ['unknown_source', 'unknown_product_chunk', 'fabricated_company', 'supplier', 'outside_scope', 'fabricated_quotes'])
def test_unsupported_or_irrelevant_candidates_are_excluded(mutation):
    data = candidate()
    if mutation == 'unknown_source': data['source_ids'] = ['invented']
    elif mutation == 'unknown_product_chunk': data['product_chunk_ids'] = ['DS-PRO-p1-c1']
    elif mutation == 'fabricated_company': data['name'] = 'Fabricatotron Unlimited'
    elif mutation == 'supplier': data['is_competitor'] = True
    elif mutation == 'outside_scope': data['geography_match'] = 'outside_scope'
    else:
        for fact in data['facts']: fact['quote'] = 'This quotation was invented and does not occur on the public page.'
    result = client_for(response(json.dumps({'candidates':[data]}))).extract(SCOPE, CHUNKS, research())
    assert result['candidates'] == []


def requirement_fact(quote):
    return dict(id='F6', dimensions=['technical_requirement'], kind='technical_requirement',
                claim='This application requires 5 ms max latency.', source_id='S1', quote=quote,
                language='en', entity='Example assemblies', entity_scope='line',
                quantity=dict(value=5,value_text='5',unit='ms'),
                requirement=dict(name='max_latency_ms',value='5'))


def test_unsourced_customer_requirement_cannot_create_a_technical_veto():
    data = candidate()
    data['facts'].append(requirement_fact('The customer requires a max latency of 5 ms.'))
    lead = assess_data(data)
    assert lead['gate']['status'] == 'review' and not lead['customer_requirements']


def test_sourced_customer_requirement_creates_a_technical_veto():
    data = candidate()
    quote = 'Our assembly pack application requires a max latency of 5 ms.'
    data['facts'].append(requirement_fact(quote))
    source = research()
    source['sources'][0]['excerpt'] += ' ' + quote
    lead = assess_data(data, source)
    assert lead['gate']['status'] == 'blocked'
    assert lead['customer_requirements'] == [{'name':'max_latency_ms','value':'5','fact_id':'F6'}]


@pytest.mark.parametrize('status,code', [(400, 'invalid_request'), (401, 'authentication'), (403, 'authentication'), (429, 'rate_limit'), (503, 'provider_error')])
def test_provider_failures_are_sanitized_and_never_silently_fallback(status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text=f'private raw response {KEY} prompt contents')

    client = client_for(None, handler=handler, models=('gemini-3.8-flash', 'gemini-3.5-flash'))
    with pytest.raises(LiveResearchError) as error:
        client.parse_scope('Find assembly assemblers in Germany.', 'CS-AI')
    assert error.value.code == code
    assert KEY not in str(error.value) and 'private raw response' not in str(error.value)
    assert len(requests) == 1 and error.value.usage['model_calls'] == 1


def test_only_model_not_found_uses_fallback_and_records_both_attempts():
    requests = []
    parsed = {key: SCOPE[key] for key in ('geography', 'application', 'sectors', 'positions', 'additional_constraints')}

    def handler(request):
        requests.append(request)
        return httpx.Response(404) if len(requests) == 1 else httpx.Response(200, json=response(json.dumps(parsed)))

    client = client_for(None, handler=handler, models=('gemini-3.8-flash', 'gemini-3.5-flash'))
    result = client.parse_scope('Find German assembly assemblers.', 'CS-AI')
    assert result['usage']['model_calls'] == 2
    assert result['usage']['models'] == ['gemini-3.8-flash', 'gemini-3.5-flash']


def test_checkpointed_fallback_does_not_repeat_missing_primary():
    requests = []
    parsed = {key: SCOPE[key] for key in ('geography', 'application', 'sectors', 'positions', 'additional_constraints')}

    def handler(request):
        requests.append(str(request.url))
        if 'gemini-3.8-flash' in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json=response(json.dumps(parsed)))

    client = client_for(None, handler=handler, models=('gemini-3.8-flash', 'gemini-3.5-flash'))
    client.account_for_usage({'model_calls': 2, 'models': ['gemini-3.8-flash', 'gemini-3.5-flash']})
    result = client.parse_scope('Find German assembly assemblers.', 'CS-AI')
    assert len(requests) == 1 and 'gemini-3.5-flash' in requests[0]
    assert result['usage']['model_calls'] == 1


def test_employee_number_cannot_match_substring_of_actual_headcount():
    data = candidate()
    data['facts'][-1]['quantity'] = dict(value=25, value_text='25', unit='employees')
    lead = assess_data(data)
    size = next(criterion for criterion in lead['criteria'] if criterion['key'] == 'size')
    assert size['score'] is None and size['provenance'] == 'unknown'
    assert not any(e.get('fact_id')=='F5' for e in lead['evidence'])


def test_incomplete_and_malformed_json_responses_fail_closed():
    with pytest.raises(LiveResearchError, match='response limit'):
        client_for(response('{"candidates": [', finish='MAX_TOKENS')).extract(SCOPE, CHUNKS, research())
    with pytest.raises(LiveResearchError) as error:
        client_for(response('not json')).extract(SCOPE, CHUNKS, research())
    assert error.value.code == 'schema_validation' and error.value.usage['model_calls'] == 1


def test_missing_configuration_never_contacts_provider():
    def handler(request):
        pytest.fail('Provider must not be contacted without a key')

    client = GeminiResearchClient(LiveConfig(api_key=''), http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LiveResearchError) as error:
        client.parse_scope('Find companies.', 'CS-AI')
    assert error.value.code == 'not_configured' and error.value.usage['model_calls'] == 0


def test_checkpoint_usage_enforces_run_budget():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(404)

    client = client_for(None, handler=handler, models=('gemini-3.8-flash', 'gemini-3.5-flash'))
    client.account_for_usage({'model_calls': 4})
    with pytest.raises(LiveResearchError) as error:
        client.parse_scope('Find German assembly assemblers.', 'CS-AI')
    assert error.value.code == 'budget'
    assert error.value.usage['model_calls'] == 1 and len(requests) == 1


@pytest.mark.parametrize('url', ['http://127.0.0.1/', 'http://169.254.169.254/latest/meta-data', 'http://10.0.0.1/',
                               'http://[::1]/', 'file:///etc/passwd', 'https://user:password@example.com',
                               'https://example.com:8080', 'http://internal.local/', 'javascript:alert(1)'])
def test_private_or_non_http_urls_are_rejected(url):
    assert _public_url(url) is None
    assert fetch_public_page(url) is None


def test_dns_private_destination_is_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.8', 443))])
    with pytest.raises(ValueError, match='Non-public'):
        _public_address('public-looking.example.com', 443)
    assert fetch_public_page('https://public-looking.example.com/') is None


def test_public_source_redirect_cannot_reach_private_destination(monkeypatch):
    from backend import live
    connections = []

    class RedirectResponse:
        status = 302

        def getheader(self, name, default=None):
            return 'http://169.254.169.254/latest/meta-data' if name == 'Location' else default

    class Connection:
        def __init__(self, address, port, timeout):
            connections.append((address, port))

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return RedirectResponse()

        def close(self):
            pass

    monkeypatch.setattr(live, '_public_address', lambda host, port: '93.184.216.34')
    monkeypatch.setattr(live.http.client, 'HTTPConnection', Connection)
    assert fetch_public_page('http://example.com/') is None
    assert connections == [('93.184.216.34', 80)]


def test_public_capture_has_byte_limit_and_ignores_script_text(monkeypatch):
    from backend import live
    payload = ('<html><body>' + PAGE + '<script>Fabricated secret claim</script></body></html>').encode()

    class PageResponse:
        status = 200

        def getheader(self, name, default=None):
            return 'text/html; charset=utf-8' if name == 'Content-Type' else default

        def read(self, amount):
            return payload[:amount]

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return PageResponse()

        def close(self):
            pass

    monkeypatch.setattr(live, '_public_address', lambda host, port: '93.184.216.34')
    monkeypatch.setattr(live.http.client, 'HTTPConnection', Connection)
    assert fetch_public_page('http://example.com/', max_bytes=80) is None
    capture = fetch_public_page('http://example.com/')
    assert PAGE in capture['text'] and 'Fabricated secret claim' not in capture['text']


def test_tls_fetch_pins_validated_address_but_verifies_original_hostname(monkeypatch):
    from backend import live
    calls = []
    raw_socket = object()
    wrapped_socket = object()

    class Context:
        def wrap_socket(self, connection, *, server_hostname):
            calls.append(('tls', server_hostname))
            assert connection is raw_socket
            return wrapped_socket

    def connect(address, timeout):
        calls.append(('socket', address))
        return raw_socket

    monkeypatch.setattr(live.socket, 'create_connection', connect)
    connection = live._PinnedHTTPSConnection('example.com', 443, '93.184.216.34', 2)
    connection._context = Context()
    connection.connect()
    assert connection.sock is wrapped_socket
    assert calls == [('socket', ('93.184.216.34', 443)), ('tls', 'example.com')]


def test_local_config_status_never_returns_key_and_environment_wins(monkeypatch, tmp_path):
    from backend import live_config
    path = tmp_path / '.env'
    path.write_text('GEMINI_API_KEY="test-local-key"\nLEADGEN_GEMINI_MODEL=gemini-3.8-flash\nUNRELATED_SECRET=ignored\n')
    monkeypatch.setattr(live_config, 'ENV_FILE', path)
    for name in live_config._NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', KEY)
    config = LiveConfig.from_environment()
    assert config.api_key == KEY
    assert KEY not in repr(config)
    status = get_live_status()
    assert status['configured'] is True and status['model'] == 'gemini-3.8-flash'
    assert KEY not in json.dumps(status) and 'test-local-key' not in json.dumps(status)


def test_scope_rejects_employee_job_titles_as_company_supply_chain_roles():
    parsed = {key: SCOPE[key] for key in ('geography', 'application', 'sectors', 'positions', 'additional_constraints')}
    parsed['positions'] = ['Procurement Manager', 'assembly Design Engineer']
    client = client_for(response(json.dumps(parsed)))
    with pytest.raises(LiveResearchError) as caught:
        client.parse_scope('Find German assembly assemblers.', 'CS-AI')
    assert caught.value.code == 'schema_validation'


def test_assessment_preserves_page_and_summary_context_from_the_same_source():
    data = candidate()
    data['facts'][2]['quote'] = ''
    source = research()
    summary = 'Example assemblies also serves industrial stationary storage customers.'
    source['sources'][0]['grounded_summary'] = summary
    candidate_pack = validate_candidate(CandidateEvidence.model_validate(data),SCOPE,CHUNKS,
                                        {s['id']:s for s in source['sources']})

    def handler(request):
        prompt=json.loads(request.content)['contents'][0]['parts'][0]['text']
        assert PAGE in prompt and summary in prompt
        assert 'live_public_page' in prompt and 'grounded_search_summary' in prompt
        return httpx.Response(200,json=response(json.dumps({'assessments':[assessment(candidate_pack)]})))

    result=client_for(None,handler=handler).assess(SCOPE,CHUNKS,{'candidates':[candidate_pack]})
    assert len(result['assessments'])==1


@pytest.mark.parametrize('mutation',['unknown','duplicate'])
def test_assessment_rejects_unknown_or_duplicate_candidate_ids(mutation):
    data=candidate()
    candidate_pack=validate_candidate(CandidateEvidence.model_validate(data),SCOPE,CHUNKS,
                                       {s['id']:s for s in research()['sources']})
    judged=assessment(candidate_pack)
    if mutation=='unknown': judged['candidate_id']='invented-company'
    rows=[judged,deepcopy(judged)] if mutation=='duplicate' else [judged]
    with pytest.raises(LiveResearchError) as error:
        client_for(response(json.dumps({'assessments':rows}))).assess(SCOPE,CHUNKS,{'candidates':[candidate_pack]})
    assert error.value.code=='assessment_reference' and error.value.usage['model_calls']==1


def test_empty_extraction_does_not_spend_an_assessment_call():
    def handler(request):
        pytest.fail('No model call is needed when extraction yielded no candidates.')
    result=client_for(None,handler=handler).assess(SCOPE,CHUNKS,{'candidates':[]})
    assert result['assessments']==[] and result['usage']['model_calls']==0


def test_grounding_redirect_retains_official_domain_from_source_title():
    data=candidate()
    for fact in data['facts']: fact['quote']=''
    source=research()
    source['sources'][0].update(url='https://vertexaisearch.cloud.google.com/grounding-api-redirect/example',
                                title='example.com',source_type='grounded_search_summary',excerpt='')
    result=client_for(response(json.dumps({'candidates':[data]}))).extract(SCOPE,CHUNKS,source)
    assert result['candidates'][0]['domain']=='example.com'
    assert all(f['url'].startswith('https://vertexaisearch.cloud.google.com/') for f in result['candidates'][0]['facts'])
