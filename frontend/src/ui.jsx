import React from 'react';

const paths = {
  discover: <><circle cx="12" cy="12" r="9"/><path d="m16 8-2.5 5.5L8 16l2.5-5.5L16 8Z"/></>,
  arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
  back: <path d="m14 6-6 6 6 6"/>,
  down: <path d="m6 9 6 6 6-6"/>,
  up: <path d="m6 15 6-6 6 6"/>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
  pipeline: <><rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="11" rx="1.5"/><rect x="17" y="4" width="4" height="7" rx="1.5"/></>,
  book: <><path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15"/></>,
  graph: <><rect x="8" y="2" width="8" height="5" rx="1"/><rect x="2" y="17" width="7" height="5" rx="1"/><rect x="15" y="17" width="7" height="5" rx="1"/><path d="M12 7v5H5.5v5M12 12h6.5v5"/></>,
  play: <path d="m9 5 11 7-11 7V5Z"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  external: <><path d="M14 3h7v7m0-7L10 14M10 3H4v17h17v-6"/></>,
  file: <><path d="M14 2H5v20h14V7l-5-5ZM14 2v6h5M8 12h8m-8 4h6"/></>,
  shield: <><path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z"/><path d="m8 12 3 3 5-6"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M19 10a7 7 0 0 0-12-5L4 8m16 8-3 3a7 7 0 0 1-12-5"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  plus: <path d="M12 5v14M5 12h14"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-11v1"/></>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-13h-8l1-7Z"/>,
  factory: <path d="M2 20V8l6 4V8l6 4V4h8v16H2Z"/>,
  layers: <><path d="m12 3 10 5-10 5L2 8l10-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></>,
  target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
  people: <><circle cx="9" cy="7" r="3"/><path d="M3 21v-4a6 6 0 0 1 12 0v4M16 4a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v3"/></>,
  filter: <><path d="M4 6h16M7 12h10m-7 6h4"/></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/></>,
  code: <><path d="m7 7-5 5 5 5m10-10 5 5-5 5M14 3l-4 18"/></>,
};
export function Icon({name, size=20, ...props}) {return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name] || paths.layers}</svg>}
export function Button({children,kind='',className='',icon, ...props}) {return <button className={`button ${kind} ${className}`} {...props}>{icon && <Icon name={icon} size={17}/>} {children}</button>}
export function Badge({children,tone='neutral',dot=false}) {return <span className={`badge ${tone}`}>{dot && <i/>}{children}</span>}
export function Empty({icon='discover',title,children,action}) {return <div className="empty"><span className="empty-icon"><Icon name={icon} size={28}/></span><h3>{title}</h3><p>{children}</p>{action}</div>}
export function Heading({eyebrow,title,children,action}) {return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{children && <p>{children}</p>}</div>{action}</div>}
export function CompanyMark({name='',size=''}) {return <span className={`company-mark ${size}`} style={{'--mark-hue':String([...name].reduce((a,c)=>a+c.charCodeAt(0),0)%280)}}>{name.replace(/[^a-zA-Z ]/g,'').split(' ').filter(Boolean).slice(0,2).map(x=>x[0]).join('')}</span>}
export function ErrorNotice({error}) {return error ? <div className="notice danger" role="alert"><Icon name="info"/>{error}</div>:null}
export function Modal({title,children,onClose}) {
  const ref=React.useRef(null);
  React.useEffect(()=>{const previous=document.activeElement; const dialog=ref.current; dialog.showModal();return ()=>{dialog.close();previous?.focus?.()}},[]);
  return <dialog ref={ref} className="modal" onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}><div className="modal-head"><h2>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><Icon name="close"/></button></div>{children}</dialog>;
}
export const pretty = text => String(text ?? '').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
export const when = value => value ? new Date(value).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : 'Not recorded';
export async function api(path, options={}) {
  const r=await fetch(`/api${path}`,{headers:{'Content-Type':'application/json'},...options});
  if(!r.ok){let d;try{d=await r.json()}catch{};throw new Error(typeof d?.detail==='string'?d.detail:`Request failed (${r.status}). Please try again.`)}
  return r.json();
}
export const post=(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)});
