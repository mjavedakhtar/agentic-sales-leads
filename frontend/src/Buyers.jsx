import React,{useEffect,useState} from 'react';
import {Icon,Button,Badge,Heading,Empty,CompanyMark,ErrorNotice,api,post,pretty,when} from './ui';
import {FitValue,policyLabel} from './scoring';
import './buyers.css';

const STATUS={
  supported_buyer:{label:'Software buyer supported',tone:'green'},
  user_or_specifier:{label:'Platform user / specifier',tone:'purple'},
  turnkey_buyer:{label:'Turnkey solution buyer',tone:'neutral'},
  unclear:{label:'Buying responsibility unclear',tone:'amber'},
};
const ROLES=[['platform_use','Deploys the software'],['specification','Specifies the platform architecture'],['procurement','Purchases commercial licenses'],['turnkey_delivery','Purchases turnkey SI solutions'],['customer_mandated','Uses customer-mandated software']];
const STAGES={assess_existing:'Assessing the stored evidence',targeted_research:'Researching missing purchasing evidence',assess_followup:'Assessing the new evidence',complete:'Comparison ready'};
const isBuyer=c=>c.buyer_status==='supported_buyer'&&c.eligible;
const purchasingUnknown=c=>c.roles?.procurement?.status?c.roles.procurement.status==='unknown':c.buyer_status==='unclear';
const matchesFilter=(candidate,key)=>key==='all'||(key==='supported_buyer'?isBuyer(candidate):key==='unclear'?purchasingUnknown(candidate):candidate.buyer_status===key);
const safeUrl=value=>{try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null}catch{return null}};
const evidenceKey=e=>[e.phase,e.source_id,e.url,e.quote].join('|');
const domId=value=>String(value).replace(/[^a-zA-Z0-9_-]/g,'-');
const asText=value=>typeof value==='string'?value:value?.question||value?.detail||value?.reason||'';

export function BuyerCheckLaunch({run,data,navigate}){
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const configured=Boolean(data.capabilities?.live?.configured);
  async function start(){setBusy(true);setError('');try{await post(`/runs/${run.id}/buyer-check`,{});navigate(`/research/${run.id}/buyers`)}catch(e){setError(e.message)}finally{setBusy(false)}}
  return <><section className="buyer-entry" aria-label="Buying responsibility check"><span className="icon-tile"><Icon name="shield"/></span><div className="buyer-entry-copy"><h3>Who actually buys the software?</h3><p>Check purchasing responsibility separately from commercial fit.</p><small>{configured?'Checks stored evidence, then makes at most one targeted public search for missing evidence.':'Live research is unavailable. The illustrative comparison is ready to explore.'}</small></div><div className="buyer-entry-actions"><Button kind="secondary" onClick={start} disabled={busy||!configured||!run.leads?.length}>{busy?<span className="spinner"/>:<Icon name="shield" size={16}/>}Check buying responsibility</Button><button className="text-button" onClick={()=>navigate('/buyers/example')}>Preview the comparison<Icon name="arrow" size={13}/></button></div></section><div className="buyer-entry-error"><ErrorNotice error={error}/></div></>;
}

export function Buyers({id,example=false,data,navigate}){
  const [run,setRun]=useState(null);const [check,setCheck]=useState(null);const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [phase,setPhase]=useState('initial');const [filter,setFilter]=useState('all');
  const configured=Boolean(data.capabilities?.live?.configured);
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setCheck(null);setRun(null);setPhase('initial');setFilter('all');
    const request=example?api('/buyer-checks/example').then(next=>({next})):Promise.all([api(`/runs/${id}`),api(`/runs/${id}/buyer-check`)]).then(([record,next])=>({record,next}));
    request.then(({record,next})=>{if(active){setRun(record||null);setCheck(next);setLoading(false)}}).catch(e=>{if(active){setError(e.message);setLoading(false)}});
    return()=>{active=false};
  },[id,example]);
  useEffect(()=>{
    if(example||check?.status!=='running')return;
    let active=true;let timer;
    async function poll(){try{const next=await api(`/runs/${id}/buyer-check`);if(!active)return;setCheck(next);setError('');if(next?.status!=='running')return}catch(e){if(!active)return;setError('Connection interrupted. Reconnecting to the saved buying-responsibility check...')}if(active)timer=setTimeout(poll,1500)}
    timer=setTimeout(poll,1500);return()=>{active=false;clearTimeout(timer)};
  },[id,example,check?.status]);
  async function start(retry=false){setBusy(true);setError('');try{const next=await post(`/runs/${id}/buyer-check${retry?'/retry':''}`,{});setCheck(next)}catch(e){setError(e.message)}finally{setBusy(false)}}
  if(loading)return <div className="loading-state"><span className="spinner"/>Opening the buyer comparison...</div>;
  if(!run&&!check)return <><button className="back-link" onClick={()=>navigate('/')}><Icon name="back" size={15}/>All research</button><ErrorNotice error={error}/></>;
  const illustrative=example||check?.mode==='illustrative';
  const scope=check?.baseline?.scope||run?.scope||{};
  const initial=check?.initial_candidates||[];const final=check?.candidates||[];
  const initialReady=initial.length>0;const completed=check?.status==='completed';
  const finalReady=completed&&final.length>0;
  const shownPhase=phase==='final'&&finalReady?'final':'initial';
  const candidates=shownPhase==='final'?final:initial;
  const visible=candidates.filter(c=>matchesFilter(c,filter));
  const initialBuyers=initial.filter(isBuyer).length;const finalBuyers=final.filter(isBuyer).length;
  const originalCount=check?.baseline?.lead_count??run?.leads?.length??initial.filter(c=>c.origin!=='followup').length;
  const filters=[['all','All companies'],['supported_buyer','Supported software buyers'],['user_or_specifier','Users / specifiers'],['turnkey_buyer','Turnkey solution buyers'],['unclear','Unclear']];
  const counts=Object.fromEntries(filters.map(([key])=>[key,candidates.filter(c=>matchesFilter(c,key)).length]));
  const entry=check?.followup?.search_entry_point;const searchHtml=typeof entry==='string'?entry:entry?.rendered_content||entry?.renderedContent;
  return <div className="buyer-page">
    <button className="back-link" onClick={()=>navigate(illustrative?'/':`/research/${id}`)}><Icon name="back" size={15}/>{illustrative?'All research':'Back to original shortlist'}</button>
    <Heading eyebrow="BUYING RESPONSIBILITY" title="Relevant company. Actual software buyer?" action={<Badge tone={illustrative?'amber':completed?'green':check?.status==='failed'?'red':'purple'}>{illustrative?'Illustrative example':completed?'Comparison saved':check?.status==='failed'?'Check paused':check?'Checking evidence':'Ready to check'}</Badge>}>Separate application fit from purchasing responsibility. See what the same evidence supports, then what a targeted follow-up adds.</Heading>
    {illustrative&&<div className="buyer-illustrative" role="note"><Icon name="info" size={20}/><div><strong>Fictional companies and illustrative evidence</strong><p>This saved example demonstrates the qualification rule. It does not describe real prospects or results from a live web search. No model calls are made.</p></div></div>}
    <div className="buyer-context">{scope.product_name&&<Badge>{scope.product_name}</Badge>}{scope.geography&&<Badge>{scope.geography}</Badge>}<Badge tone="purple">Separate buyer qualification</Badge>{check?.updated_at&&<span>{illustrative?'Example':'Saved'} · {when(check.updated_at)}</span>}</div>
    <ErrorNotice error={error}/>
    {!check&&<section className="panel buyer-setup"><div className="buyer-setup-head"><span className="icon-tile"><Icon name="shield"/></span><div><h2>A focused second look at your shortlist.</h2><p>An enterprise may deploy a platform, specify its architecture, license it, or inherit it from a parent organization. This check looks for evidence of each responsibility.</p></div></div><div className="buyer-setup-steps">{[['01','Assess the existing evidence','Apply the purchasing rule to the same companies and saved sources.'],['02','Close one evidence gap','Make at most one targeted public search pass where purchasing responsibility is unresolved.'],['03','Compare and review','Keep the original commercial fit alongside a separate buyer finding and its evidence.']].map(([n,title,desc])=><div key={n}><span>{n}</span><strong>{title}</strong><p>{desc}</p></div>)}</div><div className="buyer-setup-actions"><Button kind="primary" onClick={()=>start()} disabled={busy||!configured||!run?.leads?.length}>{busy?<span className="spinner"/>:<Icon name="shield" size={16}/>}Check buying responsibility</Button><Button onClick={()=>navigate('/buyers/example')}>Preview illustrative comparison<Icon name="arrow" size={15}/></Button></div><p className="buyer-setup-foot">{configured?'This action uses live model calls and may perform a targeted public search.':'Live research is unavailable. Configure the research provider to check this shortlist, or explore the illustrative comparison.'}</p></section>}
    {check?.status==='running'&&<section className="panel buyer-progress" aria-live="polite"><div className="buyer-progress-head"><span className="spinner"/><div><strong>{STAGES[check.current_node]||'Checking buying responsibility'}</strong><p>Assess existing evidence → bounded research → reassess → human review.</p></div><Badge tone="purple">In progress</Badge></div><p>You can return to this page while the check continues. Existing scores and sales decisions remain attached to the original assessment.</p></section>}
    {check?.status==='failed'&&<section className="panel buyer-progress"><div className="buyer-progress-head"><Icon name="info"/><div><strong>The buyer check could not finish.</strong><p>Completed stages are saved. Any findings below are from the stages that finished.</p></div></div><ErrorNotice error={check.error||'The research service could not complete this check.'}/><Button kind="secondary" onClick={()=>start(true)} disabled={busy||!configured||check.can_retry===false}>{busy?<span className="spinner"/>:<Icon name="refresh" size={15}/>}Retry buyer check</Button>{check.can_retry===false&&<p>This check cannot make further research or assessment calls within its recorded budget. Review the saved findings and open questions.</p>}</section>}
    {initialReady&&<>
      <div className="buyer-summary"><div><span>ORIGINAL SHORTLIST</span><Icon name="people" size={19}/><strong>{originalCount}</strong><p>Companies prioritized for commercial fit.</p></div><div><span>BUYERS FROM STORED EVIDENCE</span><Icon name="file" size={19}/><strong>{initialBuyers}</strong><p>Same companies and evidence, with the purchasing rule applied.</p></div><div><span>BUYERS AFTER FOLLOW-UP</span><Icon name="shield" size={19}/><strong>{completed?finalBuyers:'…'}</strong><p>{completed?(check.followup?.performed?(illustrative?'Illustrates one targeted follow-up search.':'After one targeted public search pass.'):'No additional public search was needed.'):'The final comparison is still pending.'}</p></div></div>
      <div className="buyer-controls"><div><h2>What changes when purchasing matters?</h2><p>Original commercial fit stays visible beside the buyer finding.</p></div><div className="buyer-stage-switch" role="group" aria-label="Evidence used for buyer comparison"><button aria-pressed={shownPhase==='initial'} onClick={()=>{setPhase('initial');setFilter('all')}}>Stored evidence only</button><button aria-pressed={shownPhase==='final'} disabled={!finalReady} onClick={()=>{setPhase('final');setFilter('all')}}>After follow-up</button></div></div>
      <div className="buyer-stage-note"><Icon name="info" size={15}/><span>{shownPhase==='initial'?'This view applies the buyer qualification rule to the original saved evidence. It isolates the effect of the rule before any additional research.':check.followup?.performed?'This view includes evidence from the bounded follow-up. Newly discovered companies are labelled and have no original commercial score.':'The stored evidence was sufficient to complete this check. No new public search was performed.'}</span></div>
      <div className="buyer-filters" role="group" aria-label="Filter buying responsibility">{filters.map(([key,label])=><button key={key} aria-pressed={filter===key} title={key==='unclear'?'Purchasing responsibility is unknown. These companies may also be platform users or architects.':undefined} onClick={()=>setFilter(key)}>{label}<span>{counts[key]}</span></button>)}</div>
      <div className="buyer-comparison-labels" aria-hidden="true"><span>ORIGINAL COMMERCIAL SHORTLIST</span><span>{shownPhase==='initial'?'BUYER RULE + STORED EVIDENCE':'BUYER RULE + FOLLOW-UP EVIDENCE'}</span></div>
      <div className="buyer-results">{visible.map(candidate=><BuyerCard key={`${shownPhase}-${candidate.id}`} candidate={candidate} initial={initial.find(c=>c.id===candidate.id)} phase={shownPhase} originalLead={run?.leads?.find(l=>l.id===candidate.id)} runId={id} illustrative={illustrative} navigate={navigate}/>)}</div>
      {!visible.length&&<Empty icon="shield" title={filter==='supported_buyer'?'No supported software buyer in this view.':'No companies match this filter.'}>{filter==='supported_buyer'?'The available evidence does not establish purchasing responsibility. Relevant prospects can still be reviewed for a research or influence opportunity.':'Choose another responsibility to explore the findings.'}</Empty>}
      <div className="buyer-boundary"><Icon name="people" size={18}/><span>Public evidence can support responsibility for purchasing enterprise software. It does not establish current buying intent, available budget, or a named decision maker. Human qualification remains the next step.</span></div>
    </>}
    {completed&&!initialReady&&<Empty icon="search" title="No companies available for comparison.">Return to the research desk and create a shortlist before checking buying responsibility.</Empty>}
    {searchHtml&&<iframe className="google-search-suggestions" title="Google Search suggestions for the buyer follow-up" srcDoc={searchHtml} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer"/>}
    {check&&<BuyerTrace check={check}/>}
  </div>;
}

function BuyerCard({candidate,initial,phase,originalLead,runId,illustrative,navigate}){
  const status=STATUS[candidate.buyer_status]||STATUS.unclear;
  const newCompany=candidate.origin==='followup';
  const scoreLead=originalLead||candidate;
  const scored=!newCompany&&Number.isFinite(scoreLead.score);
  const gateBlocked=candidate.technical_gate_status==='blocked'||candidate.gate?.status==='blocked'||originalLead?.gate?.status==='blocked';
  const evidence=[];const evidenceIds=new Map();
  ROLES.forEach(([key])=>(candidate.roles?.[key]?.evidence||[]).forEach(e=>{const key=evidenceKey(e);if(!evidenceIds.has(key)){const anchor=`buyer-${domId(candidate.id)}-e${evidence.length+1}`;evidenceIds.set(key,anchor);evidence.push({...e,anchor})}}));
  const questions=[candidate.next_search_question,...(candidate.validation_issues||[]).map(asText)].filter(Boolean);
  const changed=phase==='final'&&initial&&initial.buyer_status!==candidate.buyer_status;
  return <article className={`buyer-card ${isBuyer(candidate)?'supported':''}`}>
    <div className="buyer-card-main"><div className="buyer-original"><div className="buyer-company"><CompanyMark name={candidate.name}/><div><h3>{candidate.name}</h3><small>{newCompany?'Found during follow-up':`Original shortlist${candidate.original_rank?` · #${candidate.original_rank}`:''}`}{candidate.domain?` · ${candidate.domain}`:''}</small></div></div>{(originalLead?.application||candidate.application)&&<p>{originalLead?.application||candidate.application}</p>}<div className="buyer-original-score">{scored?<><strong><FitValue lead={scoreLead}/></strong><div><span>Original commercial fit</span><small>{policyLabel(scoreLead)}</small></div></>:<div><span>{newCompany?'No commercial assessment yet':'Commercial score not available'}</span><small>{newCompany?'Discovered while checking the purchasing chain.':'The original record is retained.'}</small></div>}</div>{!newCompany&&!illustrative&&runId&&<button className="text-button" onClick={()=>navigate(`/leads/${runId}/${candidate.id}`)}>Open original assessment<Icon name="arrow" size={13}/></button>}</div><div className="buyer-result"><div className="buyer-result-top"><Badge tone={status.tone}>{status.label}</Badge>{newCompany&&<small>New company</small>}</div><h4>{isBuyer(candidate)?'Purchasing responsibility is supported.':candidate.buyer_status==='turnkey_buyer'?'Buys turnkey systems. Software platform purchasing is separate.':candidate.buyer_status==='user_or_specifier'?(candidate.roles?.procurement?.status==='contradicted'?'Relevant role. Purchasing lies elsewhere.':'Relevant role. Purchasing is still unconfirmed.'):'Keep the purchasing question open.'}</h4><p>{candidate.summary||'The available evidence is insufficient to establish purchasing responsibility for the target software platform.'}</p>{changed&&<div className={`buyer-delta ${isBuyer(candidate)?'':'neutral'}`}><Icon name="arrow" size={13}/>{STATUS[initial.buyer_status]?.label||'Unclear'} → {status.label}</div>}{phase==='final'&&initial&&!changed&&<div className="buyer-delta neutral"><Icon name="file" size={13}/>Buyer finding unchanged</div>}{gateBlocked&&<div className="buyer-blocked"><Icon name="shield" size={13}/>Technical block remains. Purchasing evidence does not override it.</div>}</div></div>
    <details className="buyer-detail"><summary><span><Icon name="file" size={14}/>Responsibilities & supporting evidence <span>({evidence.length})</span></span><Icon name="down" size={15}/></summary><div className="buyer-detail-body"><div className="buyer-role-grid">{ROLES.map(([key,label])=>{const role=candidate.roles?.[key]||{};return <div className="buyer-role" key={key}><div><strong>{label}</strong><Badge tone={role.status==='supported'?'green':role.status==='contradicted'?'amber':'neutral'}>{role.status==='supported'?'Supported':role.status==='contradicted'?'Evidence against':'Unknown'}</Badge></div><p>{role.reason||'No accepted evidence for this responsibility.'}</p>{role.evidence?.length>0&&<div className="buyer-role-evidence">{role.evidence.map((e,i)=><a key={`${evidenceKey(e)}-${i}`} href={`#${evidenceIds.get(evidenceKey(e))}`}>{e.source_id||`Source ${i+1}`}</a>)}</div>}{role.validation_issues?.length>0&&<small>{role.validation_issues.map(asText).filter(Boolean).join(' ')}</small>}</div>})}</div>
      {['initial','followup'].map(group=>{const sources=evidence.filter(e=>group==='followup'?e.phase==='followup':e.phase!=='followup');return sources.length>0&&<section className="buyer-evidence-group" key={group}><h4>{group==='followup'?'Evidence added during follow-up':'Evidence from the original assessment'}</h4>{sources.map(e=>{const href=safeUrl(e.url);return <div className="buyer-evidence-item" key={e.anchor} id={e.anchor}><div><strong>{e.source_id||'Source'} · {e.title||'Supporting evidence'}</strong><Badge tone={group==='followup'?'green':'neutral'}>{group==='followup'?'Added in follow-up':'Stored evidence'}</Badge>{e.source_type==='illustrative'&&<Badge tone="amber">Illustrative</Badge>}</div><blockquote>{e.quote||'No source quotation was retained.'}</blockquote><div className="buyer-evidence-meta">{href?<a href={href} target="_blank" rel="noreferrer">Open source<Icon name="external" size={12}/></a>:<span>{illustrative?'Fictional source excerpt':'No public source link available'}</span>}{e.captured_at&&<span>Captured {when(e.captured_at)}</span>}{e.source_type&&<span>{pretty(e.source_type)}</span>}</div></div>})}</section>})}
      {questions.length>0&&<section className="buyer-open-questions"><h4>What still needs human qualification?</h4><ul>{[...new Set(questions)].map((question,i)=><li key={i}>{question}</li>)}</ul></section>}
    </div></details>
  </article>;
}

function BuyerTrace({check}){
  const events=check.trace||[];const queries=check.followup?.queries||[];const questions=check.followup?.questions||[];
  return <details className="buyer-trace"><summary><span><Icon name="graph" size={16}/>How this check ran</span><Icon name="down" size={15}/></summary><div className="buyer-trace-body">{events.map((event,i)=><div key={i}><Icon name="check" size={14}/><div><strong>{event.title||event.label||STAGES[event.node]||pretty(event.node||event.stage||'Recorded step')}</strong><p>{event.detail||event.message||event.description}</p>{(event.at||event.timestamp||event.created_at)&&<small>{when(event.at||event.timestamp||event.created_at)}</small>}</div></div>)}{questions.length>0&&<div><Icon name="search" size={14}/><div><strong>Targeted research questions</strong>{questions.map((question,i)=><p key={i}>{asText(question)}</p>)}</div></div>}{queries.length>0&&<div><Icon name="search" size={14}/><div><strong>Follow-up search queries</strong>{queries.map((query,i)=><p key={i}>{asText(query)}</p>)}</div></div>}<p className="buyer-trace-meta">{check.mode==='illustrative'?'Illustrative saved example. No model calls or live public search.':`Policy ${check.policy_version||'buyer qualification'} · ${check.followup?.performed?'One targeted public search pass recorded.':'No additional public search recorded.'}`} Existing commercial scores and human decisions remain with the original assessment.</p></div></details>;
}
