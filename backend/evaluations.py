"""Real deterministic regressions. These are contract checks, not model-quality evals."""
from time import perf_counter
from .assessment import CandidateEvidence, LeadAssessment, calculate_lead, numeric_value, validate_candidate
from .domain import COMPANIES, PRODUCTS, leads_for, technical_gate, retrieve, choose_scenario, score_criteria
from .store import now


def run_evaluations():
    checks=[]
    def check(name, detail, fn):
        start=perf_counter()
        try: passed=bool(fn())
        except Exception: passed=False
        checks.append(dict(name=name,detail=detail,passed=passed,duration_ms=round((perf_counter()-start)*1000,2)))
    check('Hard mismatch is blocked','DataStream cloud_only cannot satisfy an On-Prem requirement.',lambda:technical_gate('DS-PRO',{'deployment':'cloud_only'})['status']=='blocked')
    check('Latency is respected','Max latency is enforced for CloudScale.',lambda:technical_gate('DS-PRO',{'deployment':'cloud_only'})['status']=='blocked' and technical_gate('CS-AI',{'max_latency_ms':5})['status']=='blocked')
    check('Unknown requirements stay open','Absent or unsupported requirements require qualification.',lambda:technical_gate('CS-AI',{})['status']=='review' and technical_gate('CS-AI',{'unknown_property':10})['status']=='review')
    check('Legacy replay: unknown size earns zero points','The captured v1 policy is retained for historical comparisons; live v2 uses explicit unknown ratings.',lambda:all(score_criteria(row)[0]['score']==0 for rows in COMPANIES.values() for row in rows if row.get('employees_min') is None))
    check('Expected priority survives replay','Phoenix PHD outranks a placeholder-only source; direct application evidence improves priority.',lambda:leads_for('electronics-dach')[0]['id']=='phoenix' and leads_for('electronics-dach')[-1]['id']=='quantec')
    check('Source excerpts exist in captures','Every curated observed company excerpt, including headcount evidence, matches its saved, normalized source text.',lambda:all(all(not row.get(key) or row[key] in row['source_capture']['page_text'] for key in ('quote','extra_quote','size_quote')) for rows in COMPANIES.values() for row in rows))
    check('Legacy replay: observed-dimension coverage','Captured v1 coverage remains directly observed ranking dimensions; live v2 measures supported assessed criteria.',lambda:all(l['coverage']==round(100*sum(c['provenance']=='observed' for c in l['criteria'])/4) for sid in COMPANIES for l in leads_for(sid) if not l['synthetic']))
    check('Retrieval stays inside the product','A DataStream Kafka query retrieves Kafka evidence and never CloudScale evidence.',lambda:(lambda hits:bool(hits) and all(h['product_id']=='DS-PRO' for h in hits) and any('Kafka' in h['text'] for h in hits))(retrieve('DS-PRO','MQTT Kafka')))
    check('Scope parsing preserves constraints','Ordinary scope paraphrases are accepted; unsupported geography and size filters are rejected.',_unsupported)
    check('Synthetic gate is visibly synthetic','The illustrative cloud example retains commercial score but is blocked and excluded from priority ordering.',lambda:(lambda x:x['synthetic'] and x['score']==sum(c['score'] for c in x['criteria']) and x['gate']['status']=='blocked')(leads_for('molders-de')[-1]))
    check('V2: German and English quantities agree','Localized original values normalize without employee keyword scoring.',lambda:numeric_value('23.000','de')==numeric_value('23,000','en')==23000 and numeric_value('1,5 Mio.','de')==1500000)
    check('V2: full rubric and evidence coverage are reachable','Injected supported judgments reach 100 points and 100% fetched evidence coverage while fit remains an inference.',_v2_maximum)
    check('V2: unknown is distinct from negative fit','Missing criteria retain null points and an unresolved range; supported zero is an assessed result.',_v2_unknown)
    check('V2: quote matching is not semantic support','An injected contradicted review prevents its quoted claim from supporting fit points.',_v2_support)
    return {'passed':sum(x['passed'] for x in checks),'total':len(checks),'at':now(),'checks':checks,'scope':'Offline deterministic contracts for live rubric v2, labeled legacy replay v1, retrieval and technical gates. Semantic judgments are injected fixtures, not measured LLM accuracy or expert commercial calibration.'}


def _unsupported():
    if choose_scenario(query='Find German automotive assembly plants for CloudScale AI predictive maintenance')['id'] not in ('assemblies-de', 'batteries-de'):
        return False
    for query in (
        'Find aerospace customers in Brazil with more than one billion revenue',
        'Find automotive manufacturers in Germany and France for CloudScale AI',
        'Find large German automotive manufacturers for CloudScale AI',
    ):
        try:choose_scenario(query=query)
        except ValueError:continue
        return False
    return True


def _v2_example():
    """Synthetic contract fixture. These judgments are not an LLM quality benchmark."""
    scope = {'product_id':'CS-AI'}
    chunks = retrieve('CS-AI','predictive maintenance defect detection')
    activity = 'Example Auto deploys robotic assembly lines for vehicles at its operating German production site.'
    capacity = 'Example Auto processes 50000 telemetry events per second at this identified site.'
    intent = 'Example Auto is hiring an OT data engineer for predictive maintenance at the same German site.'
    committee = 'The VP of Operations owns platform selection for the German assembly site.'
    facts = [dict(id='F1',dimensions=['application'],kind='activity',claim=activity,source_id='S1',quote=activity,
                  language='en',entity='Example Auto',entity_scope='site'),
             dict(id='F2',dimensions=['size'],kind='workload_scale',claim=capacity,source_id='S1',quote=capacity,
                  language='en',entity='Example Auto',entity_scope='site',
                  quantity=dict(value=50000,value_text='50000',unit='events/sec')),
             dict(id='F3',dimensions=['sector'],kind='intent_signal',claim=intent,source_id='S1',quote=intent,
                  language='en',entity='Example Auto',entity_scope='site'),
             dict(id='F4',dimensions=['position'],kind='buying_committee',claim=committee,source_id='S1',quote=committee,
                  language='en',entity='Example Auto',entity_scope='site')]
    row = CandidateEvidence(name='Example Auto',domain='example.com',country='Germany',sector='Automotive',
                            position='Automotive manufacturer',application='Predictive maintenance',hypothesis='Automated lines fit the retrieved product application.',
                            source_ids=['S1'],product_chunk_ids=[chunks[0]['id']],is_competitor=False,
                            geography_match='supported',facts=facts,next_action='Confirm workload scale and qualification requirements.')
    sources = {'S1':dict(id='S1',url='https://example.com/auto',title='Synthetic contract source',
                         excerpt=activity+' '+capacity+' '+intent+' '+committee,grounded_summary='',source_type='live_public_page',captured_at=None)}
    candidate = validate_candidate(row,scope,chunks,sources)
    assessment = LeadAssessment(candidate_id=candidate['id'],eligible=True,eligibility_reason='Synthetic fixture assumes this entity is eligible.',
                                 fact_reviews=[dict(fact_id=f['id'],status='supported',reason='Injected support verdict for the deterministic contract fixture.') for f in candidate['facts']],
                                 criteria=[dict(key=key,rating=5,reason='Injected maximum anchor rating for deterministic contract coverage.',
                                                fact_ids=[{'size':'F2','application':'F1','sector':'F3','position':'F4'}[key]],
                                                product_chunk_ids=[chunks[0]['id']] if key=='application' else [])
                                           for key in ('size','application','sector','position')],
                                 summary='Synthetic assessment exercises arithmetic and evidence boundaries.',next_action='Confirm the real commercial opportunity.').model_dump()
    return candidate,assessment,scope,chunks


def _v2_maximum():
    lead = calculate_lead(*_v2_example())
    return lead['score']==lead['score_upper']==lead['coverage']==100 and all(c['provenance']=='inferred' for c in lead['criteria'])


def _v2_unknown():
    candidate,assessment,scope,chunks = _v2_example()
    for criterion in assessment['criteria']:
        if criterion['key']!='application': criterion['rating']=None
    missing = calculate_lead(candidate,assessment,scope,chunks)
    for criterion in assessment['criteria']:
        if criterion['key']!='application': criterion['rating']=0
    negative = calculate_lead(candidate,assessment,scope,chunks)
    return (missing['score']==40 and missing['score_upper']==100 and missing['criteria'][0]['score'] is None
            and negative['score']==negative['score_upper']==40 and negative['criteria'][0]['score']==0)


def _v2_support():
    candidate,assessment,scope,chunks = _v2_example()
    assessment['fact_reviews'][0].update(status='contradicted',reason='Injected contradiction: the text does not establish current operations.')
    lead = calculate_lead(candidate,assessment,scope,chunks)
    return lead['criteria'][1]['rating'] is None and lead['evidence'][0]['quote'] and lead['evidence'][0]['provenance']=='unknown'
