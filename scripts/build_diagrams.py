"""Rebuild readable offline SVG diagrams and equivalent Mermaid relationships."""
from pathlib import Path
from html import escape
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/diagrams'
COLORS = {'app': ('#f0ebfb', '#7256b0'), 'human': ('#fff3dc', '#966419'),
          'data': ('#e6f3ee', '#327b67'), 'external': ('#faeaf0', '#a4486a'),
          'cloud': ('#e8effc', '#426eb0'), 'neutral': ('#f3f3f6', '#616777')}


def text(x, y, lines, size=22, color='#292c3c', weight=400):
    if isinstance(lines, str): lines = lines.split('|')
    return '<text x="%s" y="%s" fill="%s" font-size="%s" font-weight="%s">%s</text>' % (x, y, color, size, weight, ''.join(f'<tspan x="{x}" dy="{0 if i == 0 else size * 1.35}">{escape(s)}</tspan>' for i, s in enumerate(lines)))


def node(id, x, y, w, h, title, body='', tone='app'):
    return dict(id=id, x=x, y=y, w=w, h=h, title=title, body=body, tone=tone)


def edge(a, b, points, label='', at=None):
    return dict(a=a, b=b, points=points, label=label, at=at)


def group(x, y, w, h, label, label_x=None): return (x, y, w, h, label, x + 20 if label_x is None else label_x)


DIAGRAMS = []


def add(id, title, subtitle, status, nodes, edges, groups=(), notes=()):
    DIAGRAMS.append(dict(id=id, title=title, subtitle=subtitle, status=status,
                         nodes=nodes, edges=edges, groups=groups, notes=notes))


add('current-workflow', 'The workflow running today',
    'Fixed research stages, a separate human decision, and an optional buying-responsibility check.', 'IMPLEMENTED', [
    node('scope', 55, 210, 270, 154, 'Confirm the scope', 'Gemini interprets the brief|Human reviews before search|Product, application, geography', 'human'),
    node('research', 360, 210, 270, 154, 'Retrieve and research', 'BM25 product passages|Google-grounded discovery|Bounded cited-page capture', 'external'),
    node('extract', 665, 210, 270, 154, 'Extract source facts', 'Gemini structured extraction|Code checks quote and value|Original language and entity', 'app'),
    node('assess', 970, 210, 270, 154, 'Assess against rubric', 'Gemini checks fact meaning|Four criterion ratings, 0-5|Reasons, citations, unknowns', 'app'),
    node('calculate', 1275, 210, 270, 154, 'Calculate and gate', 'Code applies fixed weights|Score range; evidence support|Known mismatch blocks', 'app'),
    node('shortlist', 885, 475, 660, 130, 'Saved commercial shortlist', 'Rank by score lower bound, with technical blocks last|Coverage and completeness remain separate from fit|Original evidence, scores and later decisions are retained', 'data'),
    node('buyer', 55, 475, 660, 130, 'Optional: check buying responsibility', 'Assess the same saved evidence before seeking anything new|At most one targeted search, then reassess its evidence|Purchasing, software use and specification are separate', 'app'),
    node('comparison', 55, 670, 395, 112, 'Buyer comparison', 'Original evidence / new evidence|Commercial scores stay unchanged', 'data'),
    node('review', 690, 670, 395, 112, 'Human qualification', 'Approve, reject or needs research|A separate review thread per lead', 'human'),
    node('persist', 1150, 670, 395, 112, 'Persist the decision', 'Review + note in SQLite|Only approved leads enter pipeline', 'data')], [
    edge('scope', 'research', [(325, 285), (360, 285)]), edge('research', 'extract', [(630, 285), (665, 285)]),
    edge('extract', 'assess', [(935, 285), (970, 285)]), edge('assess', 'calculate', [(1240, 285), (1275, 285)]),
    edge('calculate', 'shortlist', [(1410, 364), (1410, 475)]),
    edge('shortlist', 'buyer', [(885, 540), (715, 540)], 'Button', (765, 522)),
    edge('buyer', 'comparison', [(252, 605), (252, 670)]),
    edge('shortlist', 'review', [(1030, 605), (1030, 635), (890, 635), (890, 670)]),
    edge('review', 'persist', [(1085, 725), (1150, 725)])], notes=[
    'Three compiled graphs: research has 8 custom nodes, qualification 2, and buyer comparison 4. START / END are excluded.',
    'Normal live research uses 4 model calls with a 5-attempt limit. Buyer checks have a separate 4-attempt / 1-search limit.'])

add('current-architecture', 'The architecture on this laptop',
    'One FastAPI process, two independent background executors, and three checkpointed graphs.', 'IMPLEMENTED', [
    node('browser', 60, 215, 290, 112, 'React application', 'Separate task routes|Polling reads over local HTTP'),
    node('api', 435, 215, 650, 112, 'FastAPI + static UI', 'Localhost :8040; request validation and application APIs|parse_scope runs before the research graph and run ID'),
    node('engine', 435, 430, 300, 140, 'Engine', 'Research graph: 8 nodes|Qualification graph: 2 nodes|1 worker; shared graph lock'),
    node('buyers', 790, 430, 320, 140, 'BuyerEngine', 'Optional buyer graph: 4 nodes|1 separate worker and graph lock|Own queue-admission job lock'),
    node('product', 60, 440, 290, 130, 'Product corpus', 'Two fictional PDFs|Product-filtered BM25|Page-addressable chunks', 'data'),
    node('db', 435, 655, 675, 125, 'SQLite: business state and two checkpoint files', 'leadgen.db: runs, reviews, pipeline, buyer checks|leadgen.db.checkpoints: research + qualification|leadgen.db.buyer-checkpoints: buyer graph', 'data'),
    node('config', 60, 655, 290, 115, 'Local configuration', 'Ignored .env; server-side key|Browser never receives the key', 'neutral'),
    node('gemini', 1190, 215, 345, 140, 'Gemini API', 'Scope, discovery, extraction, fit|Optional buying-role assessment|Google Search only on search calls', 'external'),
    node('web', 1190, 455, 345, 130, 'Public websites', 'Fetch grounded citations only|Public-IP and redirect checks|Captures remain untrusted input', 'external')], [
    edge('browser', 'api', [(350, 270), (435, 270)], 'HTTP', (365, 250)),
    edge('api', 'engine', [(585, 327), (585, 430)]), edge('api', 'buyers', [(950, 327), (950, 430)]),
    edge('api', 'gemini', [(1085, 270), (1190, 270)], 'Scope', (1100, 250)),
    edge('engine', 'gemini', [(735, 470), (760, 470), (760, 385), (1150, 385), (1150, 320), (1190, 320)]),
    edge('buyers', 'gemini', [(1110, 470), (1165, 470), (1165, 340), (1190, 340)]),
    edge('engine', 'product', [(435, 515), (350, 515)]),
    edge('engine', 'db', [(585, 570), (585, 655)]), edge('buyers', 'db', [(950, 570), (950, 655)]),
    edge('buyers', 'web', [(1110, 530), (1190, 530)]),
    edge('engine', 'web', [(735, 550), (760, 550), (760, 615), (1150, 615), (1150, 565), (1190, 565)])],
    [group(35, 170, 1100, 620, 'LOCAL PROCESS AND STORAGE'), group(1160, 170, 405, 440, 'EXTERNAL NETWORK')], [
    'Research and buyer checks can run concurrently. Research/review share one graph lock; buyer checks use another.',
    'The executors and admission locks are local, not a durable distributed queue. No cloud resources are deployed.'])

add('langgraph-detail', 'Research graph: the exact code path',
    'backend/workflows.py: Engine.research. Eight custom nodes; fixed edges; one scope interrupt.', 'IMPLEMENTED', [
    node('parse_scope', 60, 180, 390, 112, 'parse_scope (before graph)', 'Gemini call 1 of 4; no web search|Runs before generating run_id', 'external'),
    node('START', 505, 207, 135, 56, 'START', '', 'neutral'),
    node('resume_scope', 735, 180, 800, 112, 'Human confirms the displayed scope', 'confirm_scope calls interrupt(...); confirmation resumes that same thread|Command(resume=True); thread_id = run_id; no worker held while waiting', 'human'),
    node('confirm_scope', 60, 360, 320, 130, 'confirm_scope', 'interrupt: scope_confirmation|Resume must be exactly True|Then mark scope confirmed', 'human'),
    node('retrieve_product', 445, 360, 320, 130, 'retrieve_product', 'BM25 over selected-product chunks|Page citations; no model call|Store retrieved_chunks', 'data'),
    node('discover_candidates', 830, 360, 320, 130, 'discover_candidates', 'Gemini call 2: Google Search|Bounded cited-page capture|Store research + grounded sources', 'external'),
    node('extract_evidence', 1215, 360, 320, 130, 'extract_evidence', 'Gemini call 3: extract scoped facts|Code checks citations and quantities|Store validated extraction', 'app'),
    node('assess_fit', 1215, 590, 320, 130, 'assess_fit', 'Gemini call 4: semantic review|Criterion ratings with evidence IDs|Empty extraction skips model call', 'app'),
    node('calculate_scores', 830, 590, 320, 130, 'calculate_scores', 'Code applies 20 / 40 / 20 / 20|Unknowns create a score range|Coverage differs from completeness', 'app'),
    node('technical_gate', 445, 590, 320, 130, 'technical_gate', 'Code checks sourced requirements|Known mismatch remains blocked|Unknown suitability needs review', 'app'),
    node('rank_candidates', 60, 590, 320, 130, 'rank_candidates', 'Blocked last, then score lower bound|Return the completed shortlist|Runner creates review threads later', 'data'),
    node('END', 145, 750, 135, 54, 'END', '', 'neutral')], [
    edge('parse_scope', 'START', [(450, 235), (505, 235)]),
    edge('START', 'confirm_scope', [(570, 263), (570, 350), (220, 350), (220, 360)]),
    edge('resume_scope', 'confirm_scope', [(1135, 292), (1135, 343), (350, 343), (350, 360)], 'Resume same checkpoint', (680, 325)),
    edge('confirm_scope', 'retrieve_product', [(380, 425), (445, 425)]),
    edge('retrieve_product', 'discover_candidates', [(765, 425), (830, 425)]),
    edge('discover_candidates', 'extract_evidence', [(1150, 425), (1215, 425)]),
    edge('extract_evidence', 'assess_fit', [(1375, 490), (1375, 590)]),
    edge('assess_fit', 'calculate_scores', [(1215, 655), (1150, 655)]),
    edge('calculate_scores', 'technical_gate', [(830, 655), (765, 655)]),
    edge('technical_gate', 'rank_candidates', [(445, 655), (380, 655)]),
    edge('rank_candidates', 'END', [(212, 720), (212, 750)])],
    [group(35, 305, 1530, 430, 'RESEARCH GRAPH / 8 CUSTOM NODES')], [
    'Each successful node checkpoints. Retry resumes snapshot.next. The 5-attempt budget includes failures and model fallback.',
    'Replay uses the same graph with captured inputs: assess_fit and calculate_scores are no-ops; no fresh model calls.'])

add('buyer-workflow', 'Buyer graph: one bounded research branch',
    'backend/buyer_workflow.py: BuyerEngine.graph. Separate checkpoint thread; original shortlist stays frozen.', 'IMPLEMENTED', [
    node('frozen_input', 60, 180, 650, 112, 'Button: Check buying responsibility', 'Copy existing candidates, scope and allowed source captures|Persist a buyer-check record with its own check_id and budget', 'data'),
    node('bounds', 795, 180, 740, 112, 'Independent limits', 'At most 4 model attempts and 1 targeted search pass|360-second execution window checked before uncached calls', 'neutral'),
    node('START', 60, 390, 130, 56, 'START', '', 'neutral'),
    node('assess_existing', 270, 355, 400, 145, 'assess_existing', 'LLM assesses five separate buying roles|Code requires applicable original quotes|Freeze initial_candidates for comparison', 'app'),
    node('targeted_research', 865, 355, 405, 145, 'targeted_research', 'One Google-grounded follow-up search|Reserve budget before provider call|Keep new sources marked followup', 'external'),
    node('assess_followup', 865, 600, 405, 145, 'assess_followup', 'LLM assesses original + new evidence|Promotion requires new purchasing proof|At most 2 new buyers; no invented score', 'app'),
    node('complete', 270, 600, 400, 145, 'complete', 'Save comparison, evidence and usage|Unknowns remain visible for review|Scores, decisions and pipeline unchanged', 'data'),
    node('END', 60, 645, 130, 56, 'END', '', 'neutral')], [
    edge('frozen_input', 'START', [(110, 292), (110, 390)]),
    edge('START', 'assess_existing', [(190, 418), (270, 418)]),
    edge('assess_existing', 'targeted_research', [(670, 425), (865, 425)], 'Questions remain', (690, 408)),
    edge('assess_existing', 'complete', [(470, 500), (470, 600)], 'No questions', (485, 555)),
    edge('targeted_research', 'assess_followup', [(1067, 500), (1067, 600)], 'New sources', (1085, 555)),
    edge('targeted_research', 'complete', [(1270, 425), (1440, 425), (1440, 780), (620, 780), (620, 745)], 'No sources', (1310, 555)),
    edge('assess_followup', 'complete', [(865, 672), (670, 672)]),
    edge('complete', 'END', [(270, 673), (190, 673)])],
    [group(35, 315, 1530, 480, 'BUYER GRAPH: 4 CUSTOM NODES; CONDITIONAL EDGES, NO RESEARCH LOOP', label_x=270)], [
    'Normal path: 1 assessment call, or 3 calls with follow-up. Saved responses support retries; an uncertain search is not repeated.',
    'A buyer claim needs product match, entity, timing and relation support. Buying responsibility does not establish buying intent.'])

add('qualification-graph', 'Qualification graph: the human decision',
    'backend/workflows.py: Engine.qualification. Two custom nodes, one thread per original run and lead.', 'IMPLEMENTED', [
    node('human_resume', 355, 180, 905, 130, 'Engine.decide validates the action before resuming', 'Research must be complete; a technical block prevents approval; an existing decision is final|Command(resume={decision, note}); thread_id = review:{run_id}:{lead_id}|No LLM call; no human wait occupies a background worker', 'human'),
    node('START', 60, 400, 145, 56, 'START', '', 'neutral'),
    node('human_decision', 355, 360, 390, 145, 'human_decision', 'interrupt: lead_qualification|Allowed: approve / reject / needs_research|Resume stores the decision and note', 'human'),
    node('persist_decision', 905, 360, 390, 145, 'persist_decision', 'Store.save_decision(...)|Transactional review + pipeline update|Return saved=True', 'data'),
    node('END', 1400, 400, 145, 56, 'END', '', 'neutral'),
    node('decision_record', 70, 635, 440, 130, 'Decision record', 'Key: run_id + lead_id|Decision, note, recorded timestamp|Reload and restart retain it', 'data'),
    node('approved', 585, 635, 440, 130, 'Approve', 'Create a local pipeline opportunity|Same transaction as review persistence|Idempotent matching resubmission', 'data'),
    node('other_decisions', 1100, 635, 440, 130, 'Reject or needs research', 'Save the decision and note|No pipeline entry or automatic research|A new run does not inherit this review', 'neutral')], [
    edge('START', 'human_decision', [(205, 428), (355, 428)]),
    edge('human_resume', 'human_decision', [(550, 310), (550, 360)]),
    edge('human_decision', 'persist_decision', [(745, 432), (905, 432)], 'Resume', (786, 412)),
    edge('persist_decision', 'END', [(1295, 428), (1400, 428)]),
    edge('persist_decision', 'decision_record', [(960, 505), (960, 570), (290, 570), (290, 635)]),
    edge('persist_decision', 'approved', [(1060, 505), (1060, 595), (805, 595), (805, 635)], 'approve', (815, 622)),
    edge('persist_decision', 'other_decisions', [(1190, 505), (1190, 570), (1320, 570), (1320, 635)], 'other decisions', (1280, 552))],
    [group(35, 330, 1530, 205, 'QUALIFICATION GRAPH / 2 CUSTOM NODES')], [
    'The buyer-check button starts a different graph. A needs_research decision does not trigger that graph or a follow-up task.',
    'Current decisions are final within the run. Production needs reviewer identity, evidence versions and authorized reassessment.'])

add('rag-evidence', 'From source capture to a scored hypothesis',
    'Extraction, semantic assessment and score calculation have different responsibilities.', 'IMPLEMENTED', [
    node('product', 60, 205, 390, 140, 'Product evidence', 'Selected fictional software product; BM25|Page-cited, product-filtered PDF chunks|No embeddings or external vector store', 'data'),
    node('public', 60, 480, 390, 155, 'Company source evidence', 'Grounding IDs; captured original text|Separate search-summary provenance|Untrusted content and citation allowlist', 'external'),
    node('extract', 565, 205, 415, 140, 'Gemini: extract_evidence', 'Scoped facts, not commercial scores|Original quote, entity, site and date|Value + unit + original numeric text', 'app'),
    node('validate', 1095, 205, 440, 155, 'Code: validate_candidate', 'Allowlisted source and product IDs|Quote occurrence in captured text|Locale-aware number validation|Reject unsupported fact captures', 'app'),
    node('assess', 565, 480, 415, 165, 'Gemini: assess_fit', 'Review every fact against source context|Entailment, negation, entity, contradictions|Anchored 0-5 ratings with fact references|Unknown is null, not a negative score', 'app'),
    node('score', 1095, 480, 440, 165, 'Code: calculate_scores', 'Validate judgment and reference contracts|Weights 20 / 40 / 20 / 20|Known subtotal to unresolved upper bound|Coverage and completeness are separate', 'data'),
    node('gate', 1095, 705, 440, 95, 'Code: technical_gate', 'Sourced hard requirements can veto fit', 'human')], [
    edge('product', 'extract', [(450, 275), (565, 275)]),
    edge('public', 'extract', [(450, 545), (500, 545), (500, 315), (565, 315)]),
    edge('extract', 'validate', [(980, 275), (1095, 275)]),
    edge('validate', 'assess', [(1315, 360), (1315, 410), (770, 410), (770, 480)]),
    edge('product', 'assess', [(300, 345), (300, 390), (620, 390), (620, 480)], 'Retrieved context', (315, 377)),
    edge('assess', 'score', [(980, 565), (1095, 565)]),
    edge('score', 'gate', [(1315, 645), (1315, 705)])], notes=[
    'Quote occurrence is not entailment. Semantic support remains an LLM judgment, even when a source quotation is valid.',
    '100% criterion coverage is not technical approval, a probability of sale, or proof of software purchasing responsibility.'])

add('human-review', 'Human waits, saved decisions and production resume',
    'The demo persists scope and qualification interrupts. Production adds identity, version checks and durable dispatch.', 'DEMO TO PRODUCTION', [
    node('wait_now', 60, 245, 435, 150, 'Persist an interrupt', 'Scope: confirm_scope in research|Lead: human_decision in qualification|SQLite checkpoint; release execution', 'human'),
    node('resume_now', 580, 245, 435, 150, 'Resume the same thread', 'Command(resume=...)|Backend validates completed research|A hard mismatch prevents approval', 'app'),
    node('save_now', 1100, 245, 435, 150, 'Save the current decision', 'Review and note persist by run + lead|Approve also creates local opportunity|Needs research records a decision only', 'data'),
    node('authorize', 60, 605, 435, 150, 'Authorize the returning reviewer', 'Product / account permissions|Current evidence and policy version|Stale decisions require fresh review', 'cloud'),
    node('resume_job', 580, 605, 435, 150, 'Dispatch a durable resume job', 'New short-lived job and lease|Load the matching saved checkpoint|No long-lived worker for human waits', 'cloud'),
    node('commit', 1100, 605, 435, 150, 'Commit decision and consequence', 'Atomic decision + CRM outbox|Idempotent downstream delivery|Retain review and evidence history', 'data')], [
    edge('wait_now', 'resume_now', [(495, 320), (580, 320)]),
    edge('resume_now', 'save_now', [(1015, 320), (1100, 320)]),
    edge('authorize', 'resume_job', [(495, 680), (580, 680)]),
    edge('resume_job', 'commit', [(1015, 680), (1100, 680)])],
    [group(35, 190, 1530, 235, 'IMPLEMENTED: LOCAL HUMAN-IN-THE-LOOP'),
     group(35, 550, 1530, 235, 'PROPOSED AWS: AUTHORIZED AND VERSIONED RESUME')], [
    'Current decisions are final for that run. New runs do not automatically carry a company review forward.',
    'The optional buyer comparison preserves original human decisions; it does not authorize outreach or CRM writes.'])

add('production-workflow', 'The workflow after production hardening',
    'Persist work before dispatch; release resources during human waits; apply the same explicit qualification rules.', 'PROPOSED AWS', [
    node('identity', 60, 210, 330, 135, 'Approve research scope', 'Identity and product permissions|Human confirms interpreted scope|Fixed graph stages and clear gates', 'human'),
    node('job', 440, 210, 330, 135, 'Persist job + outbox', 'Database commit before enqueue|Queue carries job and version IDs|Leases and idempotency on execution', 'data'),
    node('worker', 820, 210, 330, 135, 'Execute research stages', 'Retrieve / search / extract / assess|Code calculates scores and gates|Budgeted retries; durable checkpoints', 'cloud'),
    node('ready', 1200, 210, 330, 135, 'Persist the shortlist', 'Evidence, model and policy versions|Release task and queue message|Preserve original assessment', 'data'),
    node('buyer_job', 820, 425, 330, 120, 'Optional buyer-check job', 'Same evidence before new research|Bounded search and role qualification|Separate versioned comparison', 'cloud'),
    node('crm', 60, 635, 330, 120, 'Deliver to SAP C4C', 'Connector with idempotency key|Reconcile ambiguous responses|Approved, mapped records only', 'external'),
    node('decision', 440, 635, 330, 120, 'Decision + CRM outbox', 'Atomic business transaction|Backend gate and version check|Auditable reviewer identity', 'data'),
    node('human', 820, 635, 330, 120, 'Reviewer returns later', 'Fresh authorization and rationale|Separate resumable review job|No waiting worker task', 'human'),
    node('refresh', 1200, 635, 330, 120, 'Schedule evidence refresh', 'Create a new evidence version|Do not silently rewrite old decisions|Re-review significant changes', 'cloud')], [
    edge('identity', 'job', [(390, 277), (440, 277)]), edge('job', 'worker', [(770, 277), (820, 277)]),
    edge('worker', 'ready', [(1150, 277), (1200, 277)]),
    edge('ready', 'buyer_job', [(1245, 345), (1245, 390), (985, 390), (985, 425)], 'Optional', (1005, 377)),
    edge('buyer_job', 'human', [(985, 545), (985, 635)]),
    edge('ready', 'human', [(1355, 345), (1355, 585), (1100, 585), (1100, 635)], 'Without buyer check', (1115, 572)),
    edge('human', 'decision', [(820, 695), (770, 695)]), edge('decision', 'crm', [(440, 695), (390, 695)]),
    edge('ready', 'refresh', [(1490, 345), (1548, 345), (1548, 580), (1420, 580), (1420, 635)]),
    edge('refresh', 'human', [(1200, 695), (1150, 695)])], notes=[
    'At-least-once queue delivery requires leases, stale-version checks and idempotent side effects; exhausted jobs enter a DLQ.',
    'Multiple autonomous agents are a later option only if measured quality improves enough to justify added cost and complexity.'])

add('production-architecture', 'A restrained AWS production architecture',
    'ECS Fargate preserves the Python application. Managed state and durable jobs replace local executors.', 'PROPOSED AWS', [
    node('user', 50, 215, 250, 112, 'Sales browser', 'Corporate user / HTTPS', 'human'),
    node('alb', 390, 215, 285, 112, 'Internal ALB + OIDC', 'Corporate network access|Approved identity provider', 'cloud'),
    node('api', 390, 400, 285, 125, 'ECS Fargate API / UI', 'Private subnets across two AZs|Authorization; job submission|Human decisions; read APIs', 'cloud'),
    node('queue', 770, 215, 285, 112, 'SQS queues + DLQ', 'Research, buyer, review and CRM|Dispatcher reads DB outbox', 'cloud'),
    node('worker', 770, 400, 285, 125, 'ECS Fargate workers', 'Leases + LangGraph adapter|Budgeted versioned workflows|Independent scaling', 'cloud'),
    node('rds', 390, 650, 285, 112, 'RDS PostgreSQL', 'Business / jobs / audit / outbox|Checkpoints / Multi-AZ', 'data'),
    node('s3', 770, 650, 285, 112, 'S3 evidence + products', 'Versioned, permitted objects|BM25 runs in the worker', 'data'),
    node('search', 1190, 215, 345, 112, 'Approved search / data API', 'Discovery and content-use rights|Controlled outbound access', 'external'),
    node('model', 1190, 400, 345, 125, 'Approved model endpoint', 'Gemini remains external to AWS|Bedrock requires a separate adapter|Evaluate model and prompt changes', 'external'),
    node('sap', 1190, 650, 345, 112, 'SAP C4C', 'Connector consumes CRM outbox|Edition, API and mapping to confirm', 'external')], [
    edge('user', 'alb', [(300, 270), (390, 270)]), edge('alb', 'api', [(532, 327), (532, 400)]),
    edge('api', 'rds', [(532, 525), (532, 650)], 'Commit job / decision', (550, 590)),
    edge('queue', 'worker', [(912, 327), (912, 400)], 'Receive', (928, 375)),
    edge('rds', 'queue', [(675, 705), (720, 705), (720, 270), (770, 270)], 'Outbox', (720, 365)),
    edge('worker', 'rds', [(820, 525), (820, 615), (645, 615), (645, 650)]),
    edge('worker', 's3', [(970, 525), (970, 650)]),
    edge('worker', 'search', [(1055, 425), (1125, 425), (1125, 270), (1190, 270)]),
    edge('worker', 'model', [(1055, 470), (1190, 470)]),
    edge('worker', 'sap', [(1055, 510), (1100, 510), (1100, 705), (1190, 705)])],
    [group(355, 175, 735, 615, 'AWS ACCOUNT: PROPOSED EU REGION'), group(1155, 175, 410, 615, 'EXTERNAL / APPROVED ENDPOINTS')], [
    'Across services: scoped IAM roles, Secrets Manager, KMS, controlled egress, CloudWatch / OpenTelemetry and CI/CD.',
    'Private subnets do not make external Gemini or search traffic private. Provider, region and data-use choices need approval.'])

add('evolution', 'What changes on the way to production',
    'Keep the controlled workflow. Add operating controls and complexity when measured needs justify them.', 'EVOLUTION', [
    node('demo', 65, 200, 440, 150, '01 / Defensible local demo', 'One user; two fictional products|Live research and explicit captured replay|LLM rubric, code gates, human decisions|Optional bounded buyer comparison', 'app'),
    node('pilot', 580, 200, 440, 150, '02 / Controlled AWS pilot', 'Small named Sales cohort|SSO, queues, managed state and audit|Approved search and model contracts|Versioned evidence and buyer decisions', 'cloud'),
    node('scale', 1095, 200, 440, 150, '03 / Wider operation', 'Useful leads and adoption demonstrated|Freshness and CRM reconciliation|Capacity, on-call and restore drills|Monitored evidence and buyer quality', 'data'),
    node('proof1', 65, 465, 440, 210, 'Evidence to leave this stage', 'Verify citation and workflow safeguards|Expert-label fit and buying responsibilities|Test German / English equivalence|Establish manual research baseline|Record unknowns and technical constraints', 'neutral'),
    node('proof2', 580, 465, 440, 210, 'Evidence to leave this stage', 'Useful accepted leads per Sales hour|Unsupported buyer claims and missed buyers|Ranking quality and correction rates|Successful restore and retry exercises|SAP sandbox duplicates handled', 'neutral'),
    node('proof3', 1095, 465, 440, 210, 'Add complexity conditionally', 'Hybrid retrieval: demonstrated retrieval gap|More workers: measured queue pressure|Multi-agent roles: proven quality benefit|Multi-region: agreed RTO / RPO|Kubernetes: existing platform requirement', 'neutral')], [
    edge('demo', 'pilot', [(505, 275), (580, 275)]), edge('pilot', 'scale', [(1020, 275), (1095, 275)]),
    edge('demo', 'proof1', [(285, 350), (285, 465)]), edge('pilot', 'proof2', [(800, 350), (800, 465)]),
    edge('scale', 'proof3', [(1315, 350), (1315, 465)])], notes=[
    'A separate LLM call or a conditional graph branch does not by itself make this an autonomous multi-agent system.',
    'These are proposed acceptance gates. Test counts and a successful live run do not establish commercial quality or ROI.'])

add('production-delivery', 'Release the workflow and prove it can operate',
    'Version the full decision system, evaluate its claims, and exercise recovery before widening access.', 'PROPOSED AWS', [
    node('source', 65, 215, 320, 155, 'Version and review', 'Code, prompts, schema and rubric|Buying rule, models and source policy|Pinned dependencies and IaC|Peer review of changed assumptions', 'neutral'),
    node('checks', 450, 215, 320, 155, 'Build and evaluate', 'Contract and recovery tests|Expert-labeled fit and buyer evals|Unsupported-claim regression gate|Build and scan container image', 'app'),
    node('staging', 835, 215, 320, 155, 'Exercise staging', 'ECR image -> ECS staging|Isolated secrets and database|SAP sandbox and fault injection|German / English evidence cases', 'cloud'),
    node('release', 1220, 215, 320, 155, 'Promote the same artifact', 'Approval against release criteria|Compatible database migrations|Gradual rollout and rollback|Preserve historical assessments', 'data'),
    node('observe', 160, 560, 530, 170, 'Observe actual business outcomes', 'Trace run, job, evidence, model and reviewer IDs|Queue age, attempts, tokens, latency and errors|Sales acceptance and correction feedback|Unsupported buyer claims and unresolved evidence', 'cloud'),
    node('recover', 855, 560, 585, 170, 'Practice recovery and assign owners', 'Restore database and evidence; verify RPO / RTO|Retry duplicate jobs and ambiguous CRM writes|Exercise lost responses and conservative budgets|Model outage, poor prompt, quota and key rotation', 'human')], [
    edge('source', 'checks', [(385, 290), (450, 290)]), edge('checks', 'staging', [(770, 290), (835, 290)]),
    edge('staging', 'release', [(1155, 290), (1220, 290)]),
    edge('release', 'recover', [(1380, 370), (1380, 560)]),
    edge('recover', 'observe', [(855, 645), (690, 645)]),
    edge('observe', 'checks', [(425, 560), (425, 460), (610, 460), (610, 370)], 'Feedback into evaluation', (455, 443))], notes=[
    'Suggested rollout: read-only pilot, reviewed opportunities, SAP sandbox, then approved production delivery.',
    'Quality thresholds, retention, spend, latency and restore targets must be agreed with the teams that operate the service.'])


def render(d):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(d["title"])}</title><desc id="desc">{escape(d["subtitle"])}</desc>',
             '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#8990a4" stroke-width="1.3"/></marker></defs>',
             '<g font-family="Inter, Arial, sans-serif"><rect width="1600" height="900" fill="#faf9fc"/>',
             text(55, 49, 'LEADGEN / TECHNICAL BLUEPRINT', 16, '#7b6d93', 600),
             text(55, 104, d['title'], 39, weight=600), text(55, 139, d['subtitle'], 21, '#697083'),
             text(1260, 49, d['status'], 16, '#567e9d', 600)]
    for x, y, w, h, label, label_x in d['groups']:
        parts += [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="#f3f2f7" stroke="#d7d4e3" stroke-dasharray="7 5"/>', text(label_x, y + 28, label, 15, '#7d788e', 600)]
    for e in d['edges']:
        points = ' '.join(f'{x},{y}' for x, y in e['points'])
        parts.append(f'<polyline points="{points}" fill="none" stroke="#8990a4" stroke-width="2.4" stroke-linejoin="round" marker-end="url(#arrow)"/>')
        if e['label'] and e['at']:
            x, y = e['at']
            parts += [f'<rect x="{x - 5}" y="{y - 18}" width="{len(e["label"]) * 9 + 12}" height="25" rx="4" fill="#faf9fc"/>', text(x, y, e['label'], 17, '#72798d')]
    for n in d['nodes']:
        x, y, w, h = n['x'], n['y'], n['w'], n['h']
        fill, accent = COLORS[n['tone']]
        parts += [f'<g data-node="{n["id"]}" data-x="{x}" data-y="{y}" data-w="{w}" data-h="{h}">',
                  f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{fill}" stroke="{accent}" stroke-opacity=".24"/>',
                  f'<rect x="{x}" y="{y + 17}" width="4" height="{h - 34}" rx="2" fill="{accent}"/>',
                  text(x + 18, y + 35, n['title'], 20, accent, 600)]
        if n['body']:
            parts.append(text(x + 18, y + 64, n['body'], 17, '#525b6e'))
        parts.append('</g>')
    for i, note in enumerate(d['notes']):
        parts.append(text(55, 829 + i * 29, note, 18, '#687084'))
    parts += [text(55, 886, 'TECHNOVA CASE STUDY / FICTIONAL SOFTWARE PRODUCTS / IMPLEMENTED AND PROPOSED DESIGNS ARE LABELED', 12, '#9991a6'), '</g></svg>']
    return ''.join(parts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for d in DIAGRAMS:
        (OUT / f'{d["id"]}.svg').write_text(render(d))
        mmd = ['%% ' + d['status'] + ' / ' + d['title'], 'flowchart LR']
        for n in d['nodes']:
            label = (n['title'] + ('<br/>' + n['body'].replace('|', '<br/>') if n['body'] else '')).replace('"', '&quot;')
            mmd.append(f'    {n["id"]}["{label}"]')
        for e in d['edges']:
            label = '|"' + e['label'] + '"|' if e['label'] else ''
            mmd.append(f'    {e["a"]} -->{label} {e["b"]}')
        (OUT / f'{d["id"]}.mmd').write_text('\n'.join(mmd) + '\n')
    (OUT / 'manifest.json').write_text(json.dumps([{k: d[k] for k in ('id', 'title', 'subtitle', 'status')} for d in DIAGRAMS], indent=2) + '\n')
    print(f'Built {len(DIAGRAMS)} SVG diagrams and equivalent Mermaid sources in {OUT}')


if __name__ == '__main__': main()
