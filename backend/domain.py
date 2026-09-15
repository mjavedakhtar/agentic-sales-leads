"""Reviewable domain policy. Deterministic priorities are not purchase probabilities."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json
import math
import re

DATA = Path(__file__).parent / "data"
PRODUCTS = json.loads((DATA / "products.json").read_text())
COMPANIES = json.loads((DATA / "companies.json").read_text())
CRITERIA = [
    {"key": "size", "label": "Workload scale", "weight": 20},
    {"key": "application", "label": "Technical & stack fit", "weight": 40},
    {"key": "sector", "label": "In-market intent", "weight": 20},
    {"key": "position", "label": "Buying committee & commercial motion", "weight": 20},
]
SCENARIOS = [
    dict(id="assemblies-de", title="Automotive Assembly in Germany", description="Find assembly plants that look like CloudScale ICP, then look for hiring, programs, and who licenses the platform.", query="Find German automotive assembly plants for CloudScale AI predictive maintenance.", product_id="CS-AI", geography="Germany", sector="Automotive", application="Predictive maintenance and visual defect detection", sectors=["Automotive", "Assembly"], positions=["Plant operators", "System integrators"]),
    dict(id="electronics-dach", title="Robotics and QA across DACH", description="Find robotics manufacturers, then qualify stack fit, in-market intent, and buying motion.", query="Find robotics and automation companies in DACH for CloudScale AI.", product_id="CS-AI", geography="Germany, Austria and Switzerland", sector="Robotics", application="Automated quality assurance and anomaly detection", sectors=["Robotics", "Automation manufacturing"], positions=["OEM", "System Integrator", "Plant operator"]),
    dict(id="molders-de", title="Industrial IoT in Germany", description="Match edge telemetry ICP, then expose hard deployment mismatch and who actually licenses the platform.", query="Find German industrial IoT manufacturers for DataStream Pro.", product_id="DS-PRO", geography="Germany", sector="Industrial", application="High-frequency sensor ingestion and edge telemetry", sectors=["Industrial", "Smart manufacturing"], positions=["Plant operator", "System Integrator", "Tier 1"]),
]
DISCLOSURE = "Live mode uses Gemini and public web research. Captured replay uses saved public-page snapshots without model calls. Company suitability is a research hypothesis. Product specifications are fictional."


def product(product_id):
    return next((deepcopy(x) for x in PRODUCTS if x['id'] == product_id), None)


def scope_for(scenario):
    return {
        "product_id": scenario['product_id'], "product_name": product(scenario['product_id'])['name'],
        **{k: scenario[k] for k in ('geography', 'application', 'sectors', 'positions')},
        "criteria": CRITERIA,
        "limitations": [
            "Search and extraction replay a fixed, curated capture set, not an exhaustive market scan.",
            "Saved metadata is a company claim, not independent verification. Geography marked 'research scope' is not verified by the quoted page.",
            "Workload scale, current stack, named buying owner, and in-market intent remain unknown until qualified.",
            "Weights are an explicit demo policy. Missing size earns no size points, which does not imply a small customer.",
        ],
    }


def parse_replay_query(query):
    """Conservative rule parser for three captured scopes, not open-ended research.

    Accepts ordinary paraphrases, then validates every remaining word against a
    scope-specific vocabulary. Unknown words are never silently dropped: they
    may encode a country, technical constraint, company-size filter or negation.
    A human still confirms the fully expanded scope before the graph continues.
    """
    text=query.lower().replace('–','-').replace(chr(0x2014),'-')
    product_patterns={
        'CS-AI':r'\b(?:cloudscale(?:\s+ai)?|cs\s*-?\s*ai)\b',
        'DS-PRO':r'\b(?:datastream(?:\s+pro)?|ds\s*-?\s*pro)\b',
    }
    found={pid for pid,pattern in product_patterns.items() if re.search(pattern,text)}
    if len(found)!=1:
        raise ValueError("Name one supported product: CloudScale AI or DataStream Pro. This replay cannot research other products or compare product families in one run.")
    product_id=next(iter(found))
    text=re.sub(product_patterns[product_id],' ',text)
    text=re.sub(r'\btier\s*-?\s*[12]\b','tier',text)
    words=set(re.findall(r'[a-z0-9]+',text))
    countries=set()
    if words & {'germany','german','deutschland','de'}:countries.add('DE')
    if words & {'austria','austrian','at'}:countries.add('AT')
    if words & {'switzerland','swiss','ch'}:countries.add('CH')
    if 'dach' in words:countries.update({'DE','AT','CH'})
    assembly=bool(words & {'assembly','assemblies','plant','plants','factory','factories','pack','packs','cell','cells','module','modules','powertrain'})
    electronics=bool(words & {'electronics','electronic','ems','robotics','robot','robots','inverters','inverter','qa','quality','anomaly','heatsink','heatsinks'})
    molding=bool(words & {'molder','molders','moulders','moulder','molding','moulding','spritzguss','injection','iot','telemetry','sensor','sensors'})
    if product_id=='CS-AI' and (assembly or not electronics) and not molding and countries=={'DE'}:
        scenario_id='assemblies-de'
    elif product_id=='CS-AI' and electronics and not assembly and not molding and countries=={'DE','AT','CH'}:
        scenario_id='electronics-dach'
    elif product_id=='DS-PRO' and molding and not electronics and countries=={'DE'}:
        scenario_id='molders-de'
    else:
        raise ValueError("The requested product, application and geography must match one captured scope: CloudScale for German automotive assembly; CloudScale for DACH robotics and QA; or DataStream for German industrial IoT. Additional markets or narrower geography need a new capture set.")
    common=set("find show me identify search research discover list companies company customers customer prospects potential prospective relevant possible likely manufacturers manufacturer makers maker providers provider firms businesses suppliers supplier producers producer producing produce developed develop developing builds build manufacture manufactures manufacturing assembly assemblers assembler assembling assemblies products product application applications for in across throughout within the region based located of to a an on suitable target targeting use uses using used help please opportunities get shortlist best fit good match and or that which who with predictive analytics maintenance visual defect detection edge telemetry sensor ingestion data cloud software germany german deutschland de austria austrian at switzerland swiss ch dach market markets supply chain partners partner i want would like can you could need looking am please".split())
    per_scope={
        'assemblies-de':set("ev electric vehicle vehicles automotive plant plants factory factories assembly assemblies pack packs cell cells module modules powertrain mobility systems system ai predictive maintenance visual defect detection".split()),
        'electronics-dach':set("power electronics electronic ems pcb boards board robotics robot robots inverter inverters cooling device devices services service ai quality assurance anomaly detection".split()),
        'molders-de':set("automotive auto industrial iot injection mold molding molder molders mould moulding moulder moulders spritzguss tier under hood coolant thermostat housings housing connectors connector brackets bracket edge telemetry streaming sensor ingestion data high frequency latency".split()),
    }
    unknown=words-common-per_scope[scenario_id]
    if unknown:
        terms=', '.join(sorted(unknown)[:6])
        raise ValueError(f"This replay cannot honor additional or unrecognized qualifiers: {terms}. Remove size, revenue, technical or other extra filters, or choose a captured scenario. No unsupported constraint has been silently dropped.")
    return scenario_id


def choose_scenario(scenario_id=None, query=None):
    selected=next((x for x in SCENARIOS if x['id']==scenario_id),None) if scenario_id else None
    if scenario_id and selected is None:
        raise ValueError("Unknown research scenario. Choose one of the three available capture sets.")
    if query and query.strip():
        parsed_id=parse_replay_query(query)
        if selected and selected['id']!=parsed_id:
            raise ValueError("The request differs from the selected capture set. Choose the matching scenario and confirm its displayed scope.")
        return deepcopy(next(x for x in SCENARIOS if x['id']==parsed_id))
    if selected:return deepcopy(selected)
    raise ValueError("This replay covers German automotive assembly, DACH robotics and QA, and German industrial IoT. Enter a request for one of these scopes or choose a scenario to confirm its scope.")


def tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())


def retrieve(product_id, query, limit=4):
    """Small-corpus BM25, filtered by product before retrieval. Scores are not confidence."""
    selected = product(product_id)
    if selected is None:
        raise ValueError("Unknown product.")
    chunks = selected['chunks']
    terms = set(tokens(query))
    if not terms:
        return []
    docs = [Counter(tokens(c['text'])) for c in chunks]
    avg_len = sum(sum(d.values()) for d in docs) / len(docs)
    results = []
    for chunk, doc in zip(chunks, docs):
        value = 0.0
        length = sum(doc.values())
        for term in terms:
            frequency = doc[term]
            n = sum(term in d for d in docs)
            if frequency:
                inverse = math.log(1 + (len(docs) - n + .5) / (n + .5))
                value += inverse * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * length / avg_len))
        if value > 0:
            results.append({**chunk, "score": round(value, 4)})
    return sorted(results, key=lambda c: (-c['score'], c['id']))[:limit]


def technical_gate(product_id, requirements):
    """Hard requirement violations veto commercial score; unknowns never become passes."""
    if requirements.get('deployment') == 'cloud_only' and product_id == 'DS-PRO':
        return {"status": "blocked", "reason": "Required cloud_only deployment conflicts with DataStream's strictly On-Premises Edge architecture. Human approval cannot override this product mismatch."}
    if requirements.get('max_latency_ms', 0) > 0 and requirements.get('max_latency_ms', 0) < 10 and product_id == 'CS-AI':
        return {"status": "blocked", "reason": "Required max latency is < 10ms, which exceeds CloudScale AI's P99 latency of < 15ms."}
    supported = {'deployment', 'max_latency_ms'}
    if (not requirements or not set(requirements).issubset(supported) or requirements.get('deployment') not in (None, 'on_prem', 'cloud_only', 'hybrid')):
        return {"status": "review", "reason": "No confirmed customer technical requirements. No known mismatch was found; suitability requires technical qualification."}
    return {"status": "pass", "reason": "The supplied illustrative requirements are within the listed product limits. Application testing is still required."}


def score_criteria(row):
    size = {"key": "size", "label": "Workload scale", "score": 0, "max": 20, "reason": "No validated workload-scale input is included in this assessment. Scale is unknown, not assumed small.", "provenance": "unknown"}
    if row.get('employees_min') is not None:
        size.update(score=12 if row['employees_min'] >= 100 else 6, provenance='observed', reason=f"Company structured metadata reports at least {row['employees_min']} employees. The demo gives a conservative 12/20 size contribution for a sourced 100+ employee organization (6 below 100). This is a headcount proxy, not annual software throughput, telemetry volume, or license revenue.")
    # Application credit is deliberately capped when a source only shows adjacent products/processes.
    app_score = {'direct': 34, 'adjacent': 26, 'process': 18, 'weak': 8, 'none': 0}[row['application_level']]
    app = {"key": "application", "label": "Technical & stack fit", "score": app_score, "max": 40, "reason": row['hypothesis'], "provenance": "inferred" if app_score else "unknown"}
    sector_level = row['sector_level']
    sector = {"key": "sector", "label": "In-market intent", "score": {'observed':20, 'inferred':10, 'unknown':0}[sector_level], "max":20, "reason": "Captured replay treats named industry presence as a conservative proxy; live research requires a job post, RFP, or timed program for this criterion." if sector_level == 'observed' else ("Industry fit is a research hypothesis, not a dated buying signal." if sector_level == 'inferred' else "No in-market intent signal is evidenced in this capture."), "provenance":sector_level}
    pos_level = row['position_level']
    position = {"key":"position", "label":"Buying committee & commercial motion", "score":{'observed':18, 'inferred':10, 'unknown':0}[pos_level], "max":20, "reason": f"{row['position']}. " + ("Company-level operating role is supported by the description; a named software buying owner remains unconfirmed." if pos_level == 'observed' else "Treat the buying committee and commercial motion as a hypothesis until confirmed."), "provenance":pos_level}
    return [size, app, sector, position]


def build_lead(row, product_id):
    criteria = score_criteria(row)
    source = dict(url=row['url'], title=f"{row['name']} / saved company metadata", captured_at=row['captured_at'], source_type="captured_company_metadata")
    evidence = [
        dict(id=f"{row['id']}-source", claim=row['claim'], provenance='observed', quote=row['quote'], **source),
        dict(id=f"{row['id']}-fit", claim=row['hypothesis'], provenance='inferred', quote='', **source),
        dict(id=f"{row['id']}-size", claim="Validated customer scale, telemetry volume and software purchasing authority are not included in this assessment.", provenance='unknown', quote='', url='', title="Missing qualification evidence", captured_at=row['captured_at'], source_type='missing'),
    ]
    if row.get('extra_quote'):
        evidence.insert(1,dict(id=f"{row['id']}-source-extra",claim="Additional captured company description supporting the research interpretation.",provenance='observed',quote=row['extra_quote'],**source))
    if row.get('size_quote'):
        evidence.insert(1,dict(id=f"{row['id']}-headcount",claim=f"Company structured metadata self-reports at least {row['employees_min']} employees. This does not establish telemetry stream scale or software license demand.",provenance='observed',quote=row['size_quote'],**(source | {'source_type':'captured_structured_metadata'})))
        evidence[-1]['claim'] = 'Telemetry stream scale and software purchasing authority are not included in this assessment.'
    gate = technical_gate(product_id, {})
    if row.get('hold'):
        gate = {"status":"review", "reason":"Source evidence is insufficient to establish the target application or buying role. Resolve the evidence gap before qualification."}
    return {
        **{k:row[k] for k in ('id','name','country','sector','position','application')},
        "domain": row['url'].replace('https://','').replace('www.','').rstrip('/'),
        "summary":row['hypothesis'], "score":sum(c['score'] for c in criteria),
        "coverage":round(sum(c['provenance']=='observed' for c in criteria)/len(criteria)*100),
        "coverage_description":"Share of the four ranking criteria directly supported by a matching source excerpt. This is not model confidence.",
        "gate":gate, "criteria":criteria, "evidence":evidence,
        "gaps":["Telemetry event volume and plant scale", "Current stack or incumbent platform", "Named OT/IT buying owner and commercial motion", "In-market intent (job post, RFP, or digital program)"],
        "next_action": "Find an application-specific source before pursuing this lead." if row.get('hold') else "Confirm the application, current stack, named buying owner, and whether a job, RFP, or program shows they are in-market.",
        "review":None, "synthetic":False,
    }


def synthetic_lead():
    row = dict(id="illustrative-cloud",name="Illustrative Cloud-Only request",country="Synthetic test case",sector="Illustrative automotive application",position="Illustrative plant operator",application="Cloud-based sensor dashboard",application_level="direct",sector_level="inferred",position_level="inferred",hypothesis="An illustrative request requires cloud_only. DataStream Pro is strictly on-premises edge, so a commercial ranking must never approve it.")
    criteria=score_criteria(row)
    return {**{k:row[k] for k in ('id','name','country','sector','position','application')},"domain":"Synthetic policy example", "summary":row['hypothesis'],"score":sum(c['score'] for c in criteria),"raw_score":sum(c['score'] for c in criteria),"coverage":0,"coverage_description":"Synthetic policy example; no company evidence.","gate":technical_gate('DS-PRO',{'deployment':'cloud_only'}),"criteria":criteria,"evidence":[dict(id='synthetic-requirement',claim="Illustrative customer requirement: cloud_only deployment. This is not a statement about any real company.",provenance='inferred',quote='',url='',title='Authored policy test',captured_at=None,source_type='synthetic_test'),dict(id='synthetic-product',claim='DataStream Pro is listed as On-Premises Edge Only.',provenance='observed',quote='Deployment: Strictly On-Premises Edge (requires local hardware deployment, no public cloud dependency).',url=product('DS-PRO')['document_url']+'#page=2',title='Fictional product spec sheet, page 2',captured_at=None,source_type='product_pdf')],"gaps":["A different cloud gateway would need evaluation"],"next_action":"Reject this product match. Do not compensate for a hard mismatch with commercial score.","review":None,"synthetic":True}


def leads_for(scenario_id):
    scenario=choose_scenario(scenario_id)
    leads=[build_lead(row,scenario['product_id']) for row in COMPANIES[scenario_id]]
    if scenario_id=='molders-de': leads.append(synthetic_lead())
    return sorted(leads,key=lambda x:(x['gate']['status']=='blocked',-x['score'],x['name']))
