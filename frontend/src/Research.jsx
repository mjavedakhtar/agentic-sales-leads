import React,{useState,useEffect} from 'react';
import {Icon,Button,Badge,Heading,Empty,CompanyMark,ErrorNotice,pretty,when,api,post} from './ui';
import {FitValue,ScoreTrack,PolicyNotice,isRubricV2,scoreFloor,policyLabel,coverageDescription} from './scoring';
import {BuyerCheckLaunch} from './Buyers';

const playDesigns=[{icon:'factory',type:'AUTOMOTIVE',title:'Find the next assembly opportunity',desc:'Automotive assembly plants with a potential need for predictive maintenance.',tone:'lilac'},{icon:'bolt',type:'ELECTRONICS',title:'Automate quality assurance',desc:'Robotics and electronics manufacturers where anomaly detection matters.',tone:'peach'},{icon:'layers',type:'INDUSTRIAL EDGE',title:'Look beyond the usual accounts',desc:'Industrial manufacturers needing high-frequency sensor ingestion and telemetry.',tone:'mint'}];

export function Discover({data,navigate,refresh}){
  const [query,setQuery]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const configured=Boolean(data.capabilities?.live?.configured);
  const [mode,setMode]=useState(()=>{try{const saved=localStorage.getItem('leadgen.researchMode');if(saved==='replay'||saved==='live'&&configured)return saved}catch{}return data.default_mode || (configured?'live':'replay')});
  const [productId,setProductId]=useState(data.products?.[0]?.id || 'CS-AI');
  const live=mode==='live';
  useEffect(()=>{try{localStorage.setItem('leadgen.researchMode',mode)}catch{}},[mode]);
  async function start(scenario){
    setError('');setBusy(true);
    if(scenario){setQuery(scenario.query);setProductId(scenario.product_id)}
    try{
      const payload={mode,query:scenario?.query || query};
      if(live)payload.product_id=scenario?.product_id || productId;
      if(scenario)payload.scenario_id=scenario.id;
      const run=await post('/runs',payload);refresh();navigate(`/research/${run.id}`);
    }catch(e){setError(e.message)}finally{setBusy(false)}
  }
  return <>
    <div className="discover-intro"><div><div className="eyebrow"><span className="tiny-line"/>A CLEARER VIEW OF YOUR NEXT OPPORTUNITY</div><h1>Great software.<br/>Better connections<span className="purple">.</span></h1><p>Find the right companies. Understand the fit.<br/>Move forward with evidence.</p></div><LeadGenPlatformArt/></div>
    <section className="research-composer panel" aria-label="Start a research brief">
      <div className="composer-heading"><span className="icon-tile small"><Icon name="discover"/></span><h2>What market would you like to explore?</h2><Badge tone="purple">Evidence-led research</Badge></div>
      <div className="research-options">
        <div className="research-mode-group" role="group" aria-label="Research mode">
          <button type="button" aria-pressed={live} disabled={busy||!configured} onClick={()=>{setMode('live');setError('')}}><Icon name="search" size={16}/><span>Live web research</span>{configured&&<i/>}</button>
          <button type="button" aria-pressed={!live} disabled={busy} onClick={()=>{setMode('replay');setError('')}}><Icon name="file" size={16}/><span>Captured replay</span></button>
        </div>
        {live&&<label className="research-product"><span>TARGET PRODUCT</span><select aria-label="Target product" value={productId} onChange={e=>setProductId(e.target.value)} disabled={busy}>{(data.products || []).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
      </div>
      <p className="research-mode-description" id="research-mode-description">{live?'Gemini searches the public web for your market and grounds recommendations in sources. You confirm the scope first.':configured?'Replay saved company research for one of the three markets below. No new web search or model calls.':'Captured research is available. Configure a Gemini API key on the server to enable live web research.'}</p>
      <form onSubmit={e=>{e.preventDefault();start()}}>
        <textarea aria-label="Research brief" aria-describedby="research-mode-description" value={query} onChange={e=>setQuery(e.target.value)} placeholder={live?'Find automotive assembly plant manufacturers in Germany, or explore another market...':'Find German automotive assembly plants for CloudScale AI predictive maintenance.'} maxLength={1200} rows={2} required disabled={busy}/>
        <div className="composer-bottom"><span><Icon name="shield" size={15}/>{live?'Public sources. Every recommendation has a trail.':'Saved sources. Scope, ranking and decisions run now.'}</span><Button kind="primary" type="submit" disabled={busy||!query.trim()||live&&!configured}>{busy?<><span className="spinner"/>Preparing brief</>:<>Create research brief<Icon name="arrow" size={17}/></>}</Button></div>
      </form>
      {busy&&<p className="brief-preparing" role="status">{live?'Gemini is interpreting your request. This can take around 20 seconds.':'Preparing the captured scope for your confirmation.'}</p>}
      <ErrorNotice error={error}/>
    </section>
    <div className="section-heading"><div><h2>Start with a research play</h2><p>{live?'Three starting points. Live research follows the brief you confirm.':'Three focused markets, grounded in the supplied product sheets.'}</p></div><span className="subtle">{live?'Live search in your selected market':'3 captured research scenarios'}</span></div>
    <div className="play-grid">{data.scenarios.map((scenario,i)=>{const design=playDesigns[i%3];return <button className={`play-card ${design.tone}`} key={scenario.id} onClick={()=>start(scenario)} disabled={busy}><div className="play-top"><span className="play-icon"><Icon name={design.icon} size={23}/></span><span>{design.type}</span><Icon name="arrow" size={18}/></div><h3>{design.title}</h3><p>{design.desc}</p><div className="play-footer"><span>{scenario.product_id?.includes('NT')||scenario.product_id?.includes('nova')?'DataStream Pro':'CloudScale AI'}</span><span>{scenario.geography || 'Germany'}</span></div></button>})}</div>
    <section className="recent-section"><div className="section-heading"><div><h2>Your research desk</h2><p>Return to a shortlist and pick up where you left off.</p></div><Badge>{data.runs.length} {data.runs.length===1?'brief':'briefs'}</Badge></div>{data.runs.length?<div className="panel recent-list">{data.runs.slice(0,5).map(run=><button key={run.id} onClick={()=>navigate(`/research/${run.id}`)}><span className="recent-icon"><Icon name={run.mode==='live'?'search':'file'}/></span><div><strong>{run.title}</strong><small>{run.mode==='live'?'Live web research':'Captured replay'} · {when(run.created_at)} · {run.lead_count} leads</small></div><RunStatus run={run}/><Icon name="arrow" size={17}/></button>)}</div>:<div className="desk-empty"><span className="recent-icon"><Icon name="file"/></span><div><strong>A fresh start for your next opportunity.</strong><p>Your research briefs and shortlists will appear here.</p></div></div>}</section>
    <div className="quiet-note"><Icon name="info" size={15}/><span>{live?'Research uses Gemini with Google Search. Product specifications are fictional case-study software solutions. Human qualification remains the next step.':'Captured replay uses saved public research for three markets. Scope confirmation, product retrieval, ranking and decisions run locally.'}</span></div>
  </>
}
function LeadGenPlatformArt(){return <div className="leadgen-art" aria-hidden="true"><div className="orbital orbit-one"/><div className="orbital orbit-two"/><div className="orbital orbit-three"/><div className="orbital-center"><div className="molecule"><i/><i/><i/><i/></div></div><span className="orbit-dot dot-one"/><span className="orbit-dot dot-two"/><span className="orbit-dot dot-three"/><div className="floating-chip chip-one"><span className="check-tile"><Icon name="check" size={13}/></span>Application fit</div><div className="floating-chip chip-two"><span className="purple"><Icon name="file" size={15}/></span>Evidence connected</div><div className="floating-chip chip-three"><span className="amber-dot"/>Human judgment</div></div>}

export function Research({id,data,navigate,refresh}){
  const [run,setRun]=useState(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [filter,setFilter]=useState('all');const [search,setSearch]=useState('');const [sort,setSort]=useState('score');
  useEffect(()=>{
    let active=true;setRun(null);setError('');setFilter('all');setSearch('');
    api(`/runs/${id}`).then(next=>{if(active)setRun(next)}).catch(e=>{if(active)setError(e.message)});
    return()=>{active=false};
  },[id]);
  useEffect(()=>{
    if(run?.status!=='researching')return;
    let active=true;let timer;
    async function poll(){
      try{
        const next=await api(`/runs/${id}`);
        if(!active)return;
        setRun(next);setError('');
        if(next.status!=='researching'){refresh();return}
      }catch(e){
        if(!active)return;
        if(/not found|404/i.test(e.message)){setError('This research run is no longer available. Return to your research desk.');return}
        setError('Connection interrupted. Reconnecting to your saved research run...');
      }
      if(active)timer=setTimeout(poll,1500);
    }
    timer=setTimeout(poll,1500);
    return()=>{active=false;clearTimeout(timer)};
  },[id,run?.status,refresh]);
  async function confirm(){setBusy(true);setError('');try{const next=await post(`/runs/${id}/scope`,{confirmed:true});setRun(next);refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  async function retry(){setBusy(true);setError('');try{const next=await post(`/runs/${id}/retry`,{});setRun(next);refresh()}catch(e){setError(e.message)}finally{setBusy(false)}}
  async function fallback(scenario){setBusy(true);setError('');try{const next=await post('/runs',{mode:'replay',scenario_id:scenario.id,query:scenario.query,product_id:scenario.product_id});refresh();navigate(`/research/${next.id}`)}catch(e){setError(e.message)}finally{setBusy(false)}}
  function chooseCaptured(){try{localStorage.setItem('leadgen.researchMode','replay')}catch{}navigate('/')}
  if(!run)return <><ErrorNotice error={error}/><div className="loading-state">{!error&&<><span className="spinner"/>Loading research brief...</>}</div></>;
  const live=run.mode==='live';
  const capturedScenario=data.scenarios.find(s=>s.id===run.scenario_id);
  const leads=run.leads.filter(l=>(filter==='all'||filter==='review'&&(!l.review||l.review.decision==='needs_research')||filter==='approved'&&l.review?.decision==='approve'||filter==='blocked'&&l.gate.status==='blocked')&&`${l.name} ${l.application} ${l.sector}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>(Number(a.gate.status==='blocked')-Number(b.gate.status==='blocked'))||(sort==='coverage'?(b.coverage??0)-(a.coverage??0):sort==='name'?a.name.localeCompare(b.name):scoreFloor(b)-scoreFloor(a)||(b.assessed_criteria??4)-(a.assessed_criteria??4)));
  return <>
    <button className="back-link" onClick={()=>navigate('/')}><Icon name="back" size={15}/>All research</button>
    <Heading eyebrow={live?'LIVE RESEARCH BRIEF':'CAPTURED RESEARCH BRIEF'} title={run.scope.product_name || run.title} action={<RunStatus run={run}/>}>{run.query}</Heading>
    <ErrorNotice error={error}/>
    {run.status==='researching'?<ResearchProgress run={run} navigate={navigate}/>:run.status==='failed'?<section className="panel research-failure">
      <span className="icon-tile"><Icon name="refresh" size={24}/></span><div className="eyebrow">{live?'LIVE RESEARCH PAUSED':'RESEARCH PAUSED'}</div><h2>Research could not finish.</h2><p>Your brief is saved. {live?'Retry the live run, or start a separate captured brief.':'Return to your research desk to start another brief.'}</p>
      <ErrorNotice error={run.error || 'The research service could not complete this run. Please try again.'}/>
      <div className="research-recovery-actions">{live&&<Button kind="primary" onClick={retry} disabled={busy||!data.capabilities?.live?.configured}>{busy?<span className="spinner"/>:<Icon name="refresh" size={16}/>}Retry live research</Button>}{live&&capturedScenario?<Button onClick={()=>fallback(capturedScenario)} disabled={busy}>Start captured fallback<Icon name="arrow" size={16}/></Button>:<Button onClick={live?chooseCaptured:()=>navigate('/')} disabled={busy}>{live?'Choose a captured research play':'Back to research'}</Button>}</div>
      {live&&capturedScenario&&<p className="recovery-scope">Captured fallback uses the saved scope: {capturedScenario.title}. You will confirm it before research begins.</p>}
      <button className="text-button" onClick={()=>navigate('/engineering')}>Inspect the recorded workflow<Icon name="arrow" size={14}/></button>
    </section>:run.status==='awaiting_scope'?<>
      <div className="scope-layout"><section className="panel scope-panel"><div className="panel-heading"><span className="icon-tile"><Icon name="target"/></span><div><h2>A clear brief makes better leads.</h2><p>Confirm the scope before research begins.</p></div></div><div className="scope-grid"><Scope label="TARGET PRODUCT" value={run.scope.product_name}/><Scope label="GEOGRAPHY" value={run.scope.geography}/><Scope label="APPLICATION" value={run.scope.application}/><Scope label="SUPPLY CHAIN" value={(run.scope.positions||[]).map(pretty).join(', ')}/>{run.scope.sectors?.length>0&&<Scope label="SECTORS" value={run.scope.sectors}/>}</div>{run.scope.additional_constraints?.length>0&&<div className="scope-additional"><h3 className="small-title">Additional requirements</h3><ul>{run.scope.additional_constraints.map((constraint,i)=><li key={i}>{constraint}</li>)}</ul></div>}<div className="section-rule"/><h3 className="small-title">What makes a good lead?</h3><div className="scope-criteria">{run.scope.criteria.map(c=><div key={c.key}><span>{c.label}</span><div className="mini-meter"><i style={{width:`${c.weight}%`}}/></div><strong>{c.weight}%</strong></div>)}</div><div className="notice lavender"><Icon name="info" size={18}/><div><strong>Bounded research, explicit assumptions</strong>{(run.scope.limitations||[]).map((l,i)=><p key={i}>{l}</p>)}<p>Unknown information stays unknown. A fit score is a prioritization aid, not proof of buying intent.</p></div></div><div className="scope-actions"><Button onClick={()=>navigate('/')} kind="ghost">Edit brief</Button><Button kind="primary" onClick={confirm} disabled={busy}>{busy?<><span className="spinner"/>Researching...</>:<>Confirm & research<Icon name="arrow" size={17}/></>}</Button></div></section>
      <aside className="research-explainer"><div className="eyebrow">FROM BRIEF TO SHORTLIST</div><h2>A little structure.<br/>A lot more leadgen.</h2>{[['book','Read the product','Retrieve applications and technical limits from the supplied spec sheet.'],['search','Connect the evidence',live?'Search the public web, then extract claims with original quotations and source references.':'Use captured company research and label the strength of each claim.'],['filter','Prioritize the fit',live?'Use an LLM to assess an explicit rubric; code calculates points and technical gates.':'Check technical constraints and retain the captured scoring policy.'],['people','Keep you in control','You decide which opportunities enter the sales pipeline.']].map(([icon,title,desc])=><div className="explain-step" key={title}><span><Icon name={icon} size={19}/></span><div><h3>{title}</h3><p>{desc}</p></div></div>)}<div className="checkpoint-note"><Icon name="shield" size={17}/>Your scope decision is checkpointed.</div></aside></div>
    </>:<>
      <div className="run-context"><Badge tone={live?'green':'neutral'}>{live?'Live web research':'Captured replay'}</Badge><Badge>{run.scope.geography}</Badge><Badge>{run.scope.product_name}</Badge><span><Icon name="clock" size={14}/>Created {when(run.created_at)}</span><button className="text-button" onClick={()=>navigate('/engineering')}>Inspect workflow<Icon name="arrow" size={14}/></button></div>
      <div className="stats-grid"><Stat label="COMPANIES RESEARCHED" value={run.leads.filter(l=>!l.synthetic).length} detail={live?'From this live web research run':'From captured public sources'} icon="people"/><Stat label="READY FOR ASSESSMENT" value={run.leads.filter(l=>l.gate.status!=='blocked'&&!l.review).length} detail="Your judgment is the next step" icon="target"/><Stat label="APPROVED FOR PIPELINE" value={run.leads.filter(l=>l.review?.decision==='approve').length} detail="Human decisions, recorded" icon="check"/></div>
      {live&&<SearchProvenance run={run}/>}
      <div className="section-heading"><div><h2>Your opportunity shortlist</h2><p>Commercial fit and evidence coverage, shown separately.</p></div><span className="policy-tag"><Icon name="filter" size={14}/>{run.leads.some(isRubricV2)&&run.leads.some(l=>!isRubricV2(l))?'Mixed policy versions':policyLabel(run.leads[0],run.mode)}</span></div>
      <BuyerCheckLaunch run={run} data={data} navigate={navigate}/>
      <PolicyNotice leads={run.leads} mode={run.mode}/>
      <section className="panel shortlist"><div className="table-toolbar"><label className="search-input"><Icon name="search" size={17}/><input aria-label="Search shortlist" placeholder="Find a company..." value={search} onChange={e=>setSearch(e.target.value)}/></label><div><select aria-label="Filter leads" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All leads</option><option value="review">Needs assessment</option><option value="approved">Approved</option><option value="blocked">Technically blocked</option></select><select aria-label="Sort leads" value={sort} onChange={e=>setSort(e.target.value)}><option value="score">Highest supported points first</option><option value="coverage">Best evidence first</option><option value="name">Company A-Z</option></select></div></div>
      <div className="table-scroll"><table><thead><tr><th>COMPANY / APPLICATION</th><th>COMMERCIAL FIT</th><th>EVIDENCE</th><th>ASSESSMENT</th><th><span className="sr-only">Action</span></th></tr></thead><tbody>{leads.map(lead=><tr key={lead.id}><td><button className="company-cell" onClick={()=>navigate(`/leads/${id}/${lead.id}`)}><CompanyMark name={lead.name}/><div><strong>{lead.name}</strong><span>{lead.application||pretty(lead.sector)}</span></div></button></td><td><div className="score-cell"><strong><FitValue lead={lead}/></strong><ScoreTrack lead={lead}/></div>{isRubricV2(lead)&&<small className="table-subtext">{lead.score_status==='unassessed'?'Open range: 0-100/100':lead.score_status==='provisional'?'Provisional range':'All criteria assessed'}</small>}</td><td><div className="coverage-cell" title={coverageDescription(lead)}><span className="coverage-dots" aria-hidden="true">{(isRubricV2(lead)?[0,1,2,3]:[0,1,2,3,4]).map(n=><i key={n} className={lead.coverage>n*(isRubricV2(lead)?25:20)?'filled':''}/>)}</span><strong>{lead.coverage??0}%</strong></div><small className="table-subtext">{isRubricV2(lead)?'Fetched-page support':'Legacy coverage'}</small>{isRubricV2(lead)&&<small className="table-subtext">{lead.assessed_criteria??0}/{lead.criterion_count||4} criteria assessed</small>}</td><td><LeadStatus lead={lead}/><small className="table-subtext">{lead.gaps.length?`${lead.gaps.length} open questions`:'Review evidence'}</small></td><td><button className="assess-link" onClick={()=>navigate(`/leads/${id}/${lead.id}`)}>Assess<Icon name="arrow" size={16}/></button></td></tr>)}</tbody></table></div>{!leads.length&&(live&&!run.leads.length?<Empty icon="search" title="No supported leads found" action={<Button kind="secondary" onClick={()=>navigate('/')}>Create another brief<Icon name="arrow" size={16}/></Button>}>This search did not return companies with enough usable public evidence. Try a narrower application or geography, then create a new brief.</Empty>:<Empty icon="search" title="No leads match this view">Try another company name or change the filter.</Empty>)}<div className="table-foot"><span>{leads.length} of {run.leads.length} assessments</span><span><Icon name="shield" size={14}/>A technical mismatch cannot be approved.</span></div></section>
      <div className="insight-strip"><span className="icon-tile"><Icon name="info"/></span><div><strong>Fit is a hypothesis. Evidence tells you what to ask next.</strong><p>A high score does not establish technical qualification, buying responsibility or software licensing demand. Open an assessment to see the gaps.</p></div></div>
    </>}
  </>
}
function RunStatus({run}){
  const statuses={awaiting_scope:['amber','Confirm scope'],researching:['purple','Researching'],completed:['green','Ready to review'],failed:['red','Needs attention']};
  const [tone,label]=statuses[run.status] || ['neutral',pretty(run.status)];
  return <Badge tone={tone} dot>{label}</Badge>;
}
function ResearchProgress({run,navigate}){
  const trace=run.trace || [];
  const stages={confirm_scope:'Confirming the research scope',retrieve_product:'Reading the product specifications',discover_candidates:'Searching public company sources',extract_evidence:'Extracting and checking source evidence',assess_fit:'Assessing fit against the product rubric',calculate_scores:'Calculating points and open score ranges',technical_gate:'Checking technical constraints',rank_candidates:'Prioritizing the opportunities'};
  const current=stages[run.current_node] || trace.at(-1)?.label || 'Starting your research';
  return <section className="panel research-progress" aria-busy="true">
    <div className="research-progress-header"><span className="research-progress-icon"><Icon name="search" size={26}/><span className="spinner"/></span><div><div className="eyebrow">{run.mode==='live'?'LIVE WEB RESEARCH':'CAPTURED RESEARCH'}</div><h2>Building a shortlist with evidence.</h2><p>{run.mode==='live'?'Public research, evidence extraction and rubric assessment run in sequence. We will show the shortlist when these checks are ready.':'Retrieving product context, attaching saved evidence and checking the fit.'}</p></div></div>
    <div className="research-current-stage" role="status"><span className="spinner"/><div><span>CURRENT ACTIVITY</span><strong>{current}</strong></div><Badge tone="purple">In progress</Badge></div>
    <div className="research-progress-body"><div><h3 className="small-title">Recorded activity</h3><div className="research-activity-list">{trace.slice(-5).map((event,i)=><div key={`${event.node}-${event.at}-${i}`}><span><Icon name={['running','started'].includes(event.status)?'clock':['waiting','interrupted'].includes(event.status)?'people':event.status==='failed'?'info':'check'} size={14}/></span><div><strong>{event.label || pretty(event.node)}</strong><p>{event.detail}</p><small>{when(event.at)}</small></div></div>)}</div></div><aside><Icon name="shield" size={23}/><h3>You keep the final say.</h3><p>We collect public evidence and identify open questions. Every opportunity still needs your assessment.</p><p>Your run continues on the server if you leave this page.</p><button className="text-button" onClick={()=>navigate('/engineering')}>Inspect workflow<Icon name="arrow" size={14}/></button></aside></div>
    <div className="research-progress-foot"><span>Updates reflect recorded workflow activity.</span><span>{run.usage?.model_calls || 0} model calls · {run.usage?.search_calls || 0} search calls recorded</span></div>
  </section>;
}
function safeSourceUrl(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null}catch{return null}}
function SearchProvenance({run}){
  const usage=run.usage || {};
  const sources=(run.sources || []).filter(source=>safeSourceUrl(source.url || source.uri));
  const queries=run.search_queries || [];
  const currentRubric=run.workflow_version==='controlled-assessment-v2'||run.leads?.some(isRubricV2);
  const capturedCount=sources.filter(source=>source.source_type==='live_public_page').length;
  const entry=typeof run.search_entry_point==='string'?run.search_entry_point:run.search_entry_point?.rendered_content || run.search_entry_point?.renderedContent;
  return <div className="search-provenance">
    {currentRubric&&sources.length>0&&<div className={`source-capture-summary ${capturedCount?'':'summary-only'}`}><Icon name={capturedCount?'file':'info'} size={16}/><p>{capturedCount?<><strong>{capturedCount} of {sources.length} public sources captured.</strong> {capturedCount<sources.length?'Other sources may be represented only by search summaries. Evidence coverage counts accepted criterion support from quoted pages.':'Evidence coverage counts accepted criterion support from these quoted pages.'}</>:<><strong>Original pages could not be captured.</strong> This assessment relies on search summaries; inspect the source links before outreach.</>}</p></div>}
    {entry&&<iframe className="google-search-suggestions" title="Google Search suggestions for this research" srcDoc={entry} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer"/>}
    <details className="research-source-details"><summary><span><Icon name="search" size={16}/>Search activity and sources</span><span>{sources.length} sources · {usage.model_calls || 0} model calls<Icon name="down" size={14}/></span></summary><div className="research-source-content"><p>{usage.search_calls || 0} search calls · {Number(usage.total_tokens || 0).toLocaleString()} tokens recorded. Source references support the research; technical suitability and buying intent remain to be qualified.</p>{queries.length>0&&<div className="research-query-list">{queries.map((query,i)=><span key={i}>{query}</span>)}</div>}{sources.length>0&&<ul>{sources.map((source,i)=><li key={source.url || source.uri || i}><a href={safeSourceUrl(source.url || source.uri)} target="_blank" rel="noreferrer">{source.title || source.url || source.uri}<Icon name="external" size={13}/></a></li>)}</ul>}</div></details>
  </div>;
}
function Scope({label,value}){return <div className="scope-field"><span>{label}</span><strong>{Array.isArray(value)?value.join(', '):value}</strong></div>}
export function Stat({label,value,detail,icon}){return <div className="stat-card"><div><span>{label}</span><Icon name={icon} size={18}/></div><strong>{value}</strong><p>{detail}</p></div>}
export function LeadStatus({lead}){return lead.gate.status==='blocked'?<Badge tone="red">Technical mismatch</Badge>:lead.review?.decision==='approve'?<Badge tone="green" dot>Approved</Badge>:lead.review?.decision==='reject'?<Badge tone="red">Not pursuing</Badge>:lead.review?.decision==='needs_research'?<Badge tone="amber">Research requested</Badge>:<Badge tone="amber">Needs assessment</Badge>}
