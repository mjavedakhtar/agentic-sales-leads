"""Versioned commercial rubric and evidence contracts for the controlled workflow.

Models extract facts and judge their meaning. Code validates references, calculates
points, preserves unknowns and enforces gates. Matching a quote is not entailment.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain import product, technical_gate


POLICY_VERSION = 'llm-rubric-v2'
EXTRACTION_VERSION = 'evidence-v2'
ASSESSMENT_VERSION = 'criterion-assessment-v2'
CRITERIA_KEYS = ('size', 'application', 'sector', 'position')
RUBRIC = [
    {'key': 'size', 'label': 'Workload scale', 'weight': 20, 'anchors': [
        'Evidence establishes no addressable software, streaming telemetry, or automated inspection activity.',
        'Relevant activity is limited to small-scale pilots, isolated lab benches, or one-off trials.',
        'Relevant manufacturing operations exist; telemetry frequency, continuous data streaming, and inference scale remain unclear.',
        'Established continuous plant operations create a plausible ongoing workload for edge telemetry or AI inference.',
        'Quantified relevant production throughput, high sensor counts, or multiple automated lines support a substantial addressable opportunity.',
        'Quantified high-throughput telemetry (>10k events/sec), plant-wide automated QA, or multi-site deployment establish a strong enterprise opportunity.'
    ]},
    {'key': 'application', 'label': 'Technical & stack fit', 'weight': 40, 'anchors': [
        'Evidence establishes that the activity has no relevant operational use case for this software product.',
        'A remote possible application requires several unsupported assumptions about their technology architecture.',
        'The source establishes generic plant automation or digital manufacturing but no specific telemetry, inspection, or incumbent-stack evidence.',
        'The company operates relevant automated lines; real-time sensor ingestion, visual defect detection, or a displaceable historian/IIoT stack is inferred.',
        'The source explicitly establishes a target software use case (predictive maintenance, edge streaming, defect inspection) and/or names a relevant incumbent stack.',
        'Explicit application, protocol (MQTT/Kafka/OPC UA), latency, deployment topology, or named incumbent (PI, AWS IoT, Splunk) closely match the product specifications.'
    ]},
    {'key': 'sector', 'label': 'In-market intent', 'weight': 20, 'anchors': [
        'Evidence establishes no current hiring, tender, digital program, or other timed reason to buy.',
        'Only a distant or stale connection to a buying process is established.',
        'The industry is relevant, but there is no job post, RFP, transformation program, or event signal in-period.',
        'A digital-factory, Industry 4.0, or OT modernization program is evidenced; active procurement is still unconfirmed.',
        'A current job posting, public RFP/tender, or named in-period buying program supports that the account is in-market.',
        'Quantified or dated buying-process evidence (open RFP, budgeted program, multiple relevant open roles) establishes strong in-market intent.'
    ]},
    {'key': 'position', 'label': 'Buying committee & commercial motion', 'weight': 20, 'anchors': [
        'The evidenced role neither deploys, specifies, nor procures industrial software or OT infrastructure.',
        'The role has only a remote or indirect connection to software and technology platform selection.',
        'The company operates relevant production equipment, but OT/IT software responsibility is unclear or outsourced.',
        'The company operates the relevant factory floor; a named software buying owner remains unconfirmed.',
        'Evidence names an OT architect, plant IT, VP Operations, or similar role that specifies or deploys industrial software.',
        'Evidence establishes direct platform-architecture specification or commercial software procurement authority for this category.'
    ]},
]
POLICY = {
    'version': POLICY_VERSION, 'label': 'Demo rubric v2', 'rating_scale': [0, 5],
    'calibration': 'Authored demo rubric for industrial software ICP plus intent; not calibrated with Sales or a software systems expert.',
    'formula': 'Criterion points = weight * rating / 5. Unknown ratings have no point value.',
    'unknowns': 'Show known-point subtotal to subtotal plus unresolved weights. Never normalize over only known criteria.',
    'criteria': RUBRIC,
}


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Quantity(Contract):
    value: float = Field(allow_inf_nan=False)
    value_text: str = Field(min_length=1, max_length=100, description='Exact numeric expression from the original quote, including a multiplier if present.')
    unit: str = Field(min_length=1, max_length=80)
    approximate: bool = False


class TechnicalRequirement(Contract):
    name: Literal['deployment', 'max_latency_ms']
    value: str = Field(min_length=1, max_length=30)


class ExtractedFact(Contract):
    id: str = Field(min_length=1, max_length=80)
    dimensions: list[Literal['company', 'geography', 'size', 'application', 'sector', 'position', 'technical_requirement']] = Field(min_length=1, max_length=7)
    kind: Literal['activity', 'headcount', 'revenue', 'production_capacity', 'workload_scale', 'platform_demand', 'geography', 'buyer_role', 'technical_requirement', 'installed_stack', 'intent_signal', 'buying_committee', 'other']
    claim: str = Field(min_length=1, max_length=650)
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(default='', max_length=1600)
    language: str = Field(min_length=2, max_length=40)
    entity: str = Field(min_length=1, max_length=180)
    entity_scope: Literal['group', 'company', 'subsidiary', 'site', 'line', 'unknown']
    as_of: str | None = Field(default=None, max_length=120)
    quantity: Quantity | None = None
    requirement: TechnicalRequirement | None = None


class CandidateEvidence(Contract):
    name: str = Field(min_length=2, max_length=150)
    domain: str = Field(default='', max_length=240)
    country: str = Field(max_length=120)
    sector: str = Field(max_length=180)
    position: str = Field(max_length=180)
    application: str = Field(max_length=250)
    hypothesis: str = Field(min_length=10, max_length=850)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    product_chunk_ids: list[str] = Field(min_length=1, max_length=6)
    is_competitor: bool = False
    geography_match: Literal['supported', 'uncertain', 'outside_scope']
    facts: list[ExtractedFact] = Field(min_length=1, max_length=16)
    gaps: list[str] = Field(default_factory=list, max_length=12)
    next_action: str = Field(min_length=1, max_length=450)


class ExtractionResult(Contract):
    candidates: list[CandidateEvidence] = Field(max_length=6)


class FactReview(Contract):
    fact_id: str = Field(min_length=1, max_length=80)
    status: Literal['supported', 'contradicted', 'insufficient']
    reason: str = Field(min_length=10, max_length=650)
    is_customer_requirement: bool = Field(default=False, description='True only for an affirmative, applicable customer requirement, not a product property, negation, HDT, or generic norm.')


class CriterionJudgment(Contract):
    key: Literal['size', 'application', 'sector', 'position']
    rating: int | None = Field(ge=0, le=5, strict=True)
    reason: str = Field(min_length=10, max_length=850)
    fact_ids: list[str] = Field(default_factory=list, max_length=16)
    product_chunk_ids: list[str] = Field(default_factory=list, max_length=6)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    contradiction_fact_ids: list[str] = Field(default_factory=list, max_length=16)


class LeadAssessment(Contract):
    candidate_id: str = Field(min_length=1, max_length=100)
    eligible: bool
    eligibility_reason: str = Field(min_length=10, max_length=650)
    fact_reviews: list[FactReview] = Field(max_length=16)
    criteria: list[CriterionJudgment] = Field(max_length=4)
    summary: str = Field(min_length=10, max_length=850)
    gaps: list[str] = Field(default_factory=list, max_length=12)
    next_action: str = Field(min_length=1, max_length=450)


class AssessmentResult(Contract):
    assessments: list[LeadAssessment] = Field(max_length=6)


def clean(value, limit=16000):
    return str(value or '').replace(chr(0x2014), ' - ').strip()[:limit]


def normal(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()


def candidate_id(name):
    return 'live-' + sha256(normal(name).encode()).hexdigest()[:12]


def numeric_value(value_text, language):
    """Parse only the quoted numeric expression, preserving decimal/group separators."""
    text = unicodedata.normalize('NFKC', value_text).strip().casefold()
    german = language.casefold().startswith(('de', 'german', 'deutsch'))
    multiplier = Decimal(1)
    scale = re.search(r'\s*(million(?:en)?|mio\.?|billion(?:en)?|milliarden?)$', text)
    if scale:
        if scale[1].startswith('billion'):
            multiplier = Decimal(10**12 if german else 10**9)
        else:
            multiplier = Decimal(10**9 if scale[1].startswith('milliard') else 10**6)
        text = text[:scale.start()].strip()
    text = re.sub(r"[ '\u2019]", '', text).replace('\u2212', '-')
    decimal, group = (',', '.') if german else ('.', ',')
    if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)*', text):
        return None
    if group in text:
        integer = text.split(decimal)[0]
        if not re.fullmatch(r'[+-]?\d{1,3}(?:' + re.escape(group) + r'\d{3})+', integer):
            return None
    try:
        return Decimal(text.replace(group, '').replace(decimal, '.')) * multiplier
    except InvalidOperation:
        return None


def quantity_matches(quantity, quote, language):
    token = normal(quantity['value_text'])
    if not re.search(r'(?<![\w.,])' + re.escape(token) + r'(?!\w|[.,]\d)', normal(quote)):
        return False
    value = numeric_value(quantity['value_text'], language)
    return value is not None and value == Decimal(str(quantity['value']))


def validate_candidate(row, scope, chunks, sources):
    """Deterministic validation before the second model sees candidate facts.

Retain source context for semantic review. A validated capture is still a claim,
not independently verified truth. Invalid quantities invalidate their fact.
    """
    if isinstance(row, CandidateEvidence):
        row = row.model_dump()
    if row['is_competitor'] or row['geography_match'] == 'outside_scope':
        return None
    refs = [sources[sid] for sid in dict.fromkeys(row['source_ids']) if sid in sources]
    valid_chunks = {c['id']: c for c in chunks if c.get('product_id') == scope['product_id']}
    chunk_ids = [cid for cid in dict.fromkeys(row['product_chunk_ids']) if cid in valid_chunks]
    if not refs or not chunk_ids:
        return None
    name_tokens = [t for t in re.findall(r'\w+', normal(row['name'])) if len(t) >= 2 and t not in {'gmbh', 'group', 'inc', 'company', 'limited', 'the', 'ag', 'co', 'kg'}]
    source_text = normal(' '.join(s.get('excerpt', '') + ' ' + s.get('grounded_summary', '') for s in refs))
    if not name_tokens or not any(re.search(r'(?<!\w)' + re.escape(t) + r'(?!\w)', source_text) for t in name_tokens):
        return None
    facts, issues, seen = [], [], set()
    duplicate_ids = {f['id'] for f in row['facts'] if sum(x['id'] == f['id'] for x in row['facts']) > 1}
    for raw in row['facts']:
        fact = deepcopy(raw)
        fid = fact['id']
        source = sources.get(fact['source_id'])
        issue = None
        if fid in duplicate_ids or fid in seen:
            issue = f'{fid}: duplicate fact identifier; fact excluded.'
        elif not source or fact['source_id'] not in row['source_ids']:
            issue = f'{fid}: source reference is outside this candidate evidence; fact excluded.'
        quote = fact.get('quote', '')
        fetched = bool(source and source.get('source_type') == 'live_public_page' and len(normal(quote)) >= 24 and normal(quote) in normal(source.get('excerpt', '')))
        if not issue and quote and not fetched:
            issue = f'{fid}: quotation does not match captured page text; fact excluded.'
        if not issue and not fetched and not source.get('grounded_summary'):
            issue = f'{fid}: no matching quotation or grounded summary; fact excluded.'
        if not issue and fact.get('quantity') and (not fetched or not quantity_matches(fact['quantity'], quote, fact['language'])):
            issue = f'{fid}: numeric value is not validated against its original quote and locale; fact excluded.'
        if not issue and fact['kind'] in ('headcount', 'revenue', 'production_capacity', 'workload_scale', 'platform_demand') and not fact.get('quantity'):
            issue = f'{fid}: quantitative fact lacks a scoped numeric value; fact excluded.'
        if not issue and fact.get('quantity') and fact['kind'] in ('headcount', 'production_capacity', 'workload_scale', 'platform_demand'):
            value = Decimal(str(fact['quantity']['value']))
            if value < 0 or (fact['kind'] == 'headcount' and value != value.to_integral_value()):
                issue = f'{fid}: counts, production capacity and workload scale must be nonnegative; headcount must be a whole number.'
        if not issue and fact.get('requirement'):
            req = fact['requirement']
            if fact['kind'] != 'technical_requirement' or not fetched:
                issue = f'{fid}: customer requirement lacks a fetched quotation; fact excluded.'
            elif req['name'] == 'deployment' and (req['value'] not in ('cloud_only', 'on_prem', 'hybrid') or not re.search(r'(?<!\w)' + re.escape(req['value'].replace('_', '')) + r'(?!\w)', normal(quote), re.I)):
                issue = f'{fid}: deployment value is absent from the supporting quote; fact excluded.'
            elif req['name'] == 'max_latency_ms':
                try:
                    value = Decimal(req['value'])
                    valid = value.is_finite() and 0 <= value < 100000 and fact.get('quantity') and Decimal(str(fact['quantity']['value'])) == value and fact['quantity']['unit'] in ('ms', 'milliseconds')
                except InvalidOperation:
                    valid = False
                if not valid:
                    issue = f'{fid}: latency requirement lacks a matching ms quantity; fact excluded.'
        if issue:
            issues.append(issue)
            continue
        seen.add(fid)
        fact.update(quote=quote if fetched else '', provenance='observed' if fetched else 'inferred',
                    source_type='live_public_page' if fetched else 'grounded_search_summary',
                    url=source['url'], title=source.get('title', 'Public source'), captured_at=source.get('captured_at'),
                    source_context=source.get('excerpt', '') if fetched else source.get('grounded_summary', ''),
                    validation='quote_and_value_matched' if fetched else 'grounded_summary_reference')
        facts.append(fact)
    if not facts:
        return None
    return {**{key: clean(row[key], 850) for key in ('name', 'domain', 'country', 'sector', 'position', 'application', 'hypothesis', 'next_action')},
            'id': candidate_id(row['name']), 'geography_match': row['geography_match'], 'facts': facts,
            'product_chunk_ids': chunk_ids, 'source_ids': [s['id'] for s in refs],
            'gaps': [clean(g, 450) for g in row.get('gaps', [])], 'validation_issues': issues,
            'extraction_version': EXTRACTION_VERSION}


def _unknown(rule, reason, gaps=None):
    return {'key': rule['key'], 'label': rule['label'], 'max': rule['weight'], 'rating': None,
            'score': None, 'status': 'unknown', 'reason': reason, 'rubric_anchor': 'Unknown: insufficient or conflicting evidence to apply a rating.',
            'fact_ids': [], 'source_ids': [], 'product_chunk_ids': [], 'provenance': 'unknown',
            'evidence_basis': 'unknown', 'gaps': gaps or [reason]}


def calculate_lead(candidate, assessment, scope, chunks, metadata=None):
    """No model calls. Judge support has already been supplied; code enforces it."""
    if isinstance(assessment, LeadAssessment):
        assessment = assessment.model_dump()
    if assessment and assessment.get('candidate_id') != candidate['id']:
        assessment = None
    if assessment and not assessment['eligible']:
        return None
    data = assessment or {}
    issues = list(candidate.get('validation_issues', []))
    reviews = data.get('fact_reviews', [])
    review_ids = [r['fact_id'] for r in reviews]
    facts, requirements, evidence = {}, [], []
    for original in candidate['facts']:
        fact = deepcopy(original)
        matches = [r for r in reviews if r['fact_id'] == fact['id']]
        review = matches[0] if len(matches) == 1 else None
        status = review['status'] if review else 'insufficient'
        reason = clean(review['reason']) if review else 'Semantic support review is missing or ambiguous.'
        fact.update(support_status=status, support_reason=reason)
        facts[fact['id']] = fact
        # Only supported source claims are observed; contradictions retain the quote for inspection.
        evidence.append({**{k: v for k, v in fact.items() if k != 'source_context'},
                         'id': candidate['id'] + '-' + fact['id'], 'fact_id': fact['id'],
                         'provenance': fact['provenance'] if status == 'supported' else 'unknown',
                         'quantitative': fact.get('quantity')})
        if review and status == 'supported' and review.get('is_customer_requirement') and fact.get('requirement') and fact['source_type'] == 'live_public_page':
            requirements.append({**fact['requirement'], 'fact_id': fact['id']})
    if any(fid not in facts or review_ids.count(fid) > 1 for fid in review_ids):
        issues.append('Semantic review contains unknown or duplicate fact IDs; affected facts cannot support a score.')
    criteria = []
    # The assessment sees all retrieved passages, including commercial context
    # that extraction did not need for its initial application hypothesis.
    allowed_chunks = {c['id'] for c in chunks if c.get('product_id') == scope['product_id']}
    for rule in RUBRIC:
        matches = [j for j in data.get('criteria', []) if j['key'] == rule['key']]
        if len(matches) != 1:
            criteria.append(_unknown(rule, 'Criterion assessment is missing or duplicated.'))
            continue
        judgment = matches[0]
        rating = judgment['rating']
        reason = clean(judgment['reason'], 850)
        gaps = [clean(g, 450) for g in judgment.get('gaps', [])]
        refs = list(dict.fromkeys(judgment.get('fact_ids', [])))
        support = [facts[fid] for fid in refs if fid in facts and facts[fid]['support_status'] == 'supported']
        chunk_refs = list(dict.fromkeys(judgment.get('product_chunk_ids', [])))
        rejection = None
        if rating is None:
            criteria.append(_unknown(rule, reason, gaps or None))
            continue
        if type(rating) is not int or not 0 <= rating <= 5:
            rejection = 'Rating is outside the 0-5 rubric.'
        elif not refs or len(support) != len(refs):
            rejection = 'One or more cited facts are missing, contradicted, or not sufficiently supported.'
        elif judgment.get('contradiction_fact_ids'):
            rejection = 'Conflicting evidence must be resolved before assigning this criterion a rating.'
        elif any(cid not in allowed_chunks for cid in chunk_refs):
            rejection = 'Product evidence is outside the retrieved, selected-product passages.'
        elif rule['key'] == 'application' and not chunk_refs:
            rejection = 'Application fit needs a link to retrieved product evidence.'
        elif rule['key'] == 'size' and all(f['kind'] in ('headcount', 'revenue', 'geography') for f in support):
            rejection = 'Headcount, revenue, or location alone does not establish addressable workload scale.'
        elif rule['key'] == 'size' and rating >= 4 and not any(f['kind'] in ('production_capacity', 'workload_scale', 'platform_demand') and f.get('quantity') for f in support):
            rejection = 'Ratings 4-5 for workload scale need quantified throughput, sensor count, or production volume.'
        elif rule['key'] == 'sector' and rating >= 4 and not any(f['kind'] == 'intent_signal' for f in support):
            rejection = 'Ratings 4-5 for in-market intent need a job posting, RFP, digital program, trade-show, or similar timed buying signal.'
        elif rule['key'] == 'position' and rating >= 4 and not any(f['kind'] in ('buyer_role', 'buying_committee') for f in support):
            rejection = 'Ratings 4-5 for buying committee need a named role or evidenced commercial motion, not a company label alone.'
        if rejection:
            issues.append(rule['key'] + ': ' + rejection)
            criteria.append(_unknown(rule, rejection, gaps + [reason]))
            continue
        basis = {f['source_type'] for f in support}
        criteria.append({'key': rule['key'], 'label': rule['label'], 'max': rule['weight'], 'rating': rating,
                         'score': rule['weight'] * rating // 5, 'status': 'assessed', 'reason': reason,
                         'rubric_anchor': rule['anchors'][rating], 'fact_ids': refs,
                         'source_ids': list(dict.fromkeys(f['source_id'] for f in support)), 'product_chunk_ids': chunk_refs,
                         'provenance': 'inferred', 'evidence_basis': 'fetched' if basis == {'live_public_page'} else ('summary' if basis == {'grounded_search_summary'} else 'mixed'),
                         'gaps': gaps})
    subtotal = sum(c['score'] for c in criteria if c['score'] is not None)
    unresolved = sum(c['max'] for c in criteria if c['rating'] is None)
    rated = sum(c['rating'] is not None for c in criteria)
    direct = sum(c['rating'] is not None and c['evidence_basis'] in ('fetched', 'mixed') for c in criteria)
    selected = product(scope['product_id'])
    for chunk in chunks:
        if chunk['id'] in allowed_chunks:
            evidence.append({'id': candidate['id'] + '-' + chunk['id'], 'chunk_id': chunk['id'],
                             'claim': 'Retrieved fictional product evidence used in this assessment.', 'provenance': 'observed',
                             'quote': clean(chunk['text'], 1600), 'url': selected['document_url'] + f'#page={chunk["page"]}',
                             'title': chunk.get('title', 'Product specification'), 'captured_at': None, 'source_type': 'product_pdf'})
    gaps = candidate.get('gaps', []) + data.get('gaps', []) + [g for c in criteria for g in c['gaps']]
    gaps += [f"{f['id']}: {f['support_reason']}" for f in facts.values() if f['support_status'] != 'supported']
    gaps += ['Complete customer technical requirements and application testing', 'Telemetry throughput, current stack/incumbent, named buying owner, and in-market intent (job post, RFP, or program) require qualification unless explicitly sourced.']
    if candidate.get('geography_match') == 'uncertain':
        gaps.append('Requested geography remains unconfirmed.')
    lead = {**{k: candidate[k] for k in ('id', 'name', 'domain', 'country', 'sector', 'position', 'application')},
            'summary': clean(data.get('summary') or candidate['hypothesis'], 850),
            'score': subtotal, 'score_upper': subtotal + unresolved,
            'score_status': 'complete' if rated == 4 else ('provisional' if rated else 'unassessed'),
            'score_explanation': 'Points from assessed criteria, with unresolved weights shown as a range. This is rubric uncertainty, not a probability or statistical confidence interval. Ranking uses the lower bound.',
            'scoring_version': POLICY_VERSION, 'scoring_policy': deepcopy(POLICY),
            'coverage': round(direct / 4 * 100),
            'coverage_description': f'{direct} of 4 criteria have an accepted rating supported by a matched public-page quotation and LLM support review. Fit judgments remain inferences. Search summaries and product PDFs alone do not count; this is not factual certainty.',
            'assessment_completeness': round(rated / 4 * 100), 'assessed_criteria': rated, 'criterion_count': 4,
            'criteria': criteria, 'evidence': evidence, 'gaps': list(dict.fromkeys(clean(g, 650) for g in gaps)),
            'validation_issues': issues, 'customer_requirements': requirements,
            'next_action': clean(data.get('next_action') or candidate['next_action'], 450),
            'review': None, 'synthetic': False, 'research_mode': 'live',
            'product_chunk_ids': sorted(allowed_chunks),
            'assessment_metadata': {**(metadata or {}), 'rubric_version': POLICY_VERSION,
                                    'extraction_version': EXTRACTION_VERSION, 'assessment_version': ASSESSMENT_VERSION,
                                    'structured_assessment': deepcopy(assessment)},
            'geography_provenance': 'observed' if any('geography' in f['dimensions'] and f['support_status'] == 'supported' and f['source_type'] == 'live_public_page' for f in facts.values()) else 'unknown'}
    lead['gate'] = apply_technical_gate(lead, scope['product_id'])
    return lead


def apply_technical_gate(lead, product_id):
    """Evaluate every applicable requirement so a compatible value cannot hide a veto."""
    for requirement in lead.get('customer_requirements', []):
        value = requirement['value']
        if requirement['name'] == 'max_latency_ms':
            value = float(value)
        gate = technical_gate(product_id, {requirement['name']: value})
        if gate['status'] == 'blocked':
            return gate
    return {'status': 'review', 'reason': 'No supported technical mismatch detected. Complete customer architecture requirements and deployment validation are still needed; commercial fit does not establish technical qualification.'}
