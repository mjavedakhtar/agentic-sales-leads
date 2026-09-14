import React, {useState, useEffect, useCallback} from 'react';
import {Icon, Button, Badge, ErrorNotice, api} from './ui';
import {Discover, Research} from './Research';
import {Assessment, Pipeline} from './Workspace';
import {Knowledge, Engineering} from './Engineering';
import {Blueprint} from './Blueprint';
import {Buyers} from './Buyers';

export default function App(){
  const [path,setPath]=useState(location.pathname);
  const [data,setData]=useState(null);
  const [error,setError]=useState('');
  const [toast,setToast]=useState('');
  const [menu,setMenu]=useState(false);
  const refresh=useCallback(()=>api('/bootstrap').then(setData).catch(e=>setError(e.message)),[]);
  useEffect(()=>{refresh();const fn=()=>{setPath(location.pathname);setMenu(false)};window.addEventListener('popstate',fn);return()=>window.removeEventListener('popstate',fn)},[refresh]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),4500);return()=>clearTimeout(t)},[toast]);
  const navigate=useCallback((url)=>{if(location.pathname!==url)history.pushState({},'',url);setPath(url);setMenu(false);window.scrollTo({top:0,behavior:'instant'})},[]);
  const notify=useCallback(message=>setToast(message),[]);
  const buyerRoute=path==='/buyers/example'||/^\/research\/[^/]+\/buyers\/?$/.test(path);
  const section=buyerRoute?'Buyer comparison':path.startsWith('/research')?'Research':path.startsWith('/leads')?'Lead assessment':path==='/pipeline'?'Pipeline':path==='/knowledge'?'Product knowledge':path.startsWith('/blueprint')?'Technical blueprint':path==='/engineering'?'Engineering':'Discover';
  const runRoute=path.startsWith('/research/') || path.startsWith('/leads/');
  const currentRun=runRoute?data?.runs.find(run=>run.id===path.split('/')[2]):null;
  const modeLabel=path==='/buyers/example'?'Illustrative comparison':currentRun?(currentRun.mode==='live'?'Live web research':'Captured replay'):runRoute?'Research session':data?.capabilities?.live?.configured?'Live research available':'Captured research';
  const modeTone=currentRun?(currentRun.mode==='live'?'live':'replay'):data?.capabilities?.live?.configured?'live':'replay';
  useEffect(()=>{document.title=`${section} | LeadGenPlatform`},[section]);
  const props={data,navigate,refresh,notify};
  const links=[['discover','Discover','/'],['pipeline','Pipeline','/pipeline'],['book','Product knowledge','/knowledge']];
  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className={`sidebar ${menu?'open':''}`}>
      <a href="/" className="brand" onClick={e=>{e.preventDefault();navigate('/')}}><span className="brand-icon"><i/><i/><i/></span><div><strong>leadgen<span>®</span></strong><small>BY TechNova</small></div></a>
      <div className="workspace-label"><span className="workspace-avatar">C</span><div>Commercial workspace<small>Materials & solutions</small></div><Icon name="down" size={14}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{links.map(([icon,label,url])=><a key={url} href={url} aria-current={(path===url || url==='/'&&(section==='Research'||section==='Lead assessment'||section==='Buyer comparison'))?'page':undefined} className={(path===url || url==='/'&&(section==='Research'||section==='Lead assessment'||section==='Buyer comparison'))?'active':''} onClick={e=>{e.preventDefault();navigate(url)}}><Icon name={icon}/>{label}{url==='/pipeline'&&data?.stats?.pipeline>0&&<span className="nav-count">{data.stats.pipeline}</span>}</a>)}</nav>
      <div className="nav-label second">UNDER THE HOOD</div>
      <nav aria-label="Technical navigation"><a href="/engineering" className={path==='/engineering'?'active':''} onClick={e=>{e.preventDefault();navigate('/engineering')}}><Icon name="graph"/>Engineering<Icon name="code" size={15}/></a><a href="/blueprint" className={path.startsWith('/blueprint')?'active':''} onClick={e=>{e.preventDefault();navigate('/blueprint')}}><Icon name="layers"/>Technical blueprint</a></nav>
      <div className="sidebar-bottom"><div className="user-profile"><span>JA</span><div>Javed Akhtar<small>Commercial workspace</small></div><i className="online-dot"/></div></div>
    </aside>
    {menu && <div className="menu-overlay" onClick={()=>setMenu(false)}/>}
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="mobile-menu icon-button" aria-label="Toggle navigation" onClick={()=>setMenu(!menu)}><Icon name="filter"/></button><span>Workspace</span><span className="slash">/</span><strong>{section}</strong></div><div className="topbar-right"><span className={`mode-indicator ${modeTone}`}><i/>{modeLabel}</span><span className="avatar-small">JA</span></div></header>
      <main id="main" className={`main-content page-${section.toLowerCase().replaceAll(' ','-')}`}>
        <ErrorNotice error={error}/>
        {!data&&!error?<div className="loading-state"><span className="spinner"/>Opening your workspace...</div>:!data?<div className="empty"><h2>Let’s reconnect your workspace</h2><p>The local API is unavailable. Start the app with ./start.sh, then retry.</p><Button onClick={()=>{setError('');refresh()}}>Retry connection</Button></div>:buyerRoute?<Buyers {...props} id={path.split('/')[2]} example={path==='/buyers/example'}/>:path.startsWith('/research/')?<Research {...props} id={path.split('/')[2]}/>:path.startsWith('/leads/')?<Assessment {...props} runId={path.split('/')[2]} leadId={path.split('/')[3]}/>:path==='/pipeline'?<Pipeline {...props}/>:path==='/knowledge'?<Knowledge {...props}/>:path.startsWith('/blueprint')?<Blueprint {...props}/>:path==='/engineering'?<Engineering {...props}/>:<Discover {...props}/>}
      </main><footer className="app-footer"><span>LeadGenPlatform by TechNova</span><span>Fictional products · Public-source evidence · Human decisions</span></footer>
    </div>
    {toast&&<div className="toast" role="status"><span><Icon name="check" size={16}/></span>{toast}<button className="icon-button" aria-label="Dismiss notification" onClick={()=>setToast('')}><Icon name="close" size={15}/></button></div>}
  </div>
}
