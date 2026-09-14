import React from 'react';
import {Icon} from './ui';

export const isRubricV2=lead=>lead?.scoring_version==='llm-rubric-v2';
export const scoreFloor=lead=>Number.isFinite(lead?.score)?lead.score:0;
export const scoreCeiling=lead=>Number.isFinite(lead?.score_upper)?lead.score_upper:scoreFloor(lead);
export const policyLabel=(lead,mode)=>isRubricV2(lead)?lead.scoring_policy?.label||'Demo rubric v2':mode==='replay'?'Captured policy v1':'Legacy policy v1';
export const evidenceAnchor=e=>`evidence-${e.id||e.fact_id}`;
export const coverageDescription=lead=>lead.coverage_description||(isRubricV2(lead)?'Share of scoring criteria with an accepted rating supported by a quotation from a fetched public page. Commercial judgments remain inferences.':'Historical coverage counts criteria marked observed under policy v1. It is not the share of evidence cards with sources.');

export function FitValue({lead,denominator=true}){
  const unassessed=isRubricV2(lead)&&lead.score_status==='unassessed';
  const range=isRubricV2(lead)&&scoreCeiling(lead)>scoreFloor(lead);
  return <>{unassessed?<span className="fit-unassessed">Not assessed</span>:<>{scoreFloor(lead)}{range&&`-${scoreCeiling(lead)}`}{denominator&&<small>/100</small>}</>}</>;
}

export function ScoreTrack({lead}){
  const lower=Math.max(0,Math.min(100,scoreFloor(lead)));
  const upper=Math.max(lower,Math.min(100,scoreCeiling(lead)));
  return <span className="score-track" aria-hidden="true"><i style={{width:`${lower}%`}}/>{isRubricV2(lead)&&upper>lower&&<i className="score-unknown" style={{left:`${lower}%`,width:`${upper-lower}%`}}/>}</span>;
}

export function PolicyNotice({leads=[],mode}){
  if(!leads.length||leads.every(isRubricV2))return null;
  return <div className="policy-notice"><Icon name="info" size={16}/><p>{mode==='replay'?'Captured research retains its original policy v1 scores.':'These saved assessments retain their original policy v1 scores and evidence coverage.'} Start a new live assessment to use the current rubric. Existing decisions stay with their original assessment.</p></div>;
}

export function ScorePanel({lead,mode,onEvidence}){
  const v2=isRubricV2(lead);
  const criteria=lead.criteria||[];
  const assessed=lead.assessed_criteria??criteria.filter(c=>c.score!==null&&c.score!==undefined).length;
  const count=lead.criterion_count||criteria.length||4;
  const completeness=lead.assessment_completeness??Math.round(assessed/count*100);
  return <section className={`panel fit-panel ${v2?'rubric-v2':''}`}>
    <div className="panel-heading split"><h2>Why this lead ranks</h2><Icon name="target" size={19}/></div>
    <div className="big-fit"><strong><FitValue lead={lead}/></strong><span>Commercial fit<small>{policyLabel(lead,mode)}</small></span></div>
    {v2&&<div className={`score-explanation ${lead.score_status==='complete'?'complete':''}`}><strong>{lead.score_status==='unassessed'?'Open range: 0-100/100':lead.score_status==='provisional'?'Provisional score range':'All four criteria assessed'}</strong><p>{lead.score_explanation||'The score adds rubric points from assessed criteria. Unknown criteria keep their possible points open until more evidence is available.'}</p>{lead.score_status!=='complete'&&<p>The range shows points still open because of missing evidence. It is not a statistical confidence interval.</p>}</div>}
    {!v2&&<PolicyNotice leads={[lead]} mode={mode}/>}
    <div className="criteria-list">{criteria.map(c=>{
      const unknown=v2&&(c.status==='unknown'||c.score===null||c.score===undefined);
      const linked=(lead.evidence||[]).filter(e=>(c.fact_ids||[]).includes(e.fact_id||e.id));
      return <div className={`criterion ${unknown?'criterion-unknown':''}`} key={c.key}>
        <div><strong>{v2&&c.key==='size'?'Workload scale':c.label}</strong><span>{unknown?<span className="unknown-points">Unknown</span>:<>{c.score}<small>/{c.max}</small></>}</span></div>
        <div className="criterion-meter" aria-hidden="true">{!unknown&&<i style={{width:`${Math.max(0,Math.min(100,(Number(c.score)||0)/(Number(c.max)||1)*100))}%`}}/>}</div>
        {v2&&<div className="criterion-calculation">{unknown?`${c.max} possible points remain open`:`Rubric rating ${c.rating}/5 × ${c.max} = ${c.score} points`}</div>}
        <p>{c.reason}</p>
        {v2&&c.rubric_anchor&&<details className="rubric-detail"><summary>How this rating is defined<Icon name="down" size={12}/></summary><p>{c.rubric_anchor}</p></details>}
        {v2&&linked.length>0&&<div className="criterion-sources"><span>Supporting evidence</span>{linked.map(e=><a key={e.fact_id||e.id} href={`#${evidenceAnchor(e)}`} onClick={event=>{if(onEvidence){event.preventDefault();onEvidence(e)}}}><Icon name="file" size={12}/>{e.fact_id||e.id}</a>)}</div>}
        {v2&&!unknown&&<p className="criterion-basis">{c.evidence_basis==='fetched'?'Judgment supported by fetched-page evidence.':c.evidence_basis==='mixed'?'Judgment uses fetched pages and search summaries.':c.evidence_basis==='summary'?'Judgment uses search summaries; fetched-page support is missing.':'Evidence support still needs confirmation.'}</p>}
        {v2&&c.gaps?.length>0&&<details className="rubric-detail"><summary>{c.gaps.length} qualification {c.gaps.length===1?'question':'questions'}<Icon name="down" size={12}/></summary><ul>{c.gaps.map((gap,i)=><li key={i}>{typeof gap==='string'?gap:gap.question||gap.detail}</li>)}</ul></details>}
      </div>;
    })}</div>
    <div className="evidence-separation"><div><Icon name="shield" size={16}/><strong>Evidence coverage</strong><b>{lead.coverage??0}%</b></div><p>{coverageDescription(lead)}</p>{v2&&<div className="assessment-completeness"><span>Assessment completeness</span><strong>{assessed}/{count} criteria · {completeness}%</strong></div>}</div>
    {v2&&<p className="rubric-policy-note">Demo weights: 20 / 40 / 20 / 20. The LLM judges each criterion; code applies the weights. Sales calibration is still needed.</p>}
  </section>;
}
