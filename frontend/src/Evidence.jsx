import React from 'react';
import {Badge,Icon,pretty} from './ui';
import {evidenceAnchor} from './scoring';

function sourceUrl(value){
  if(typeof value!=='string')return null;
  if(value.startsWith('/api/documents/'))return value;
  try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null}catch{return null}
}

export function EvidenceRecord({record:e,index,active}){
  const challenged=['contradicted','insufficient'].includes(e.support_status);
  const label=challenged?pretty(e.support_status):e.provenance==='observed'?'Source-backed':pretty(e.provenance);
  const href=sourceUrl(e.url);
  const entity=typeof e.entity==='string'?e.entity:null;
  const quantity=e.quantitative||e.quantity;
  const language={de:'German',en:'English','de-DE':'German','en-GB':'English','en-US':'English'}[e.language]||e.language;
  const dimensions=e.dimensions||(e.dimension?[e.dimension]:[]);
  const labels={size:'Workload scale',application:'Technical fit',sector:'Automation maturity',position:'Platform ownership'};
  return <article className={`evidence-row ${active?'highlighted':''} ${challenged?'evidence-challenged':''}`} id={evidenceAnchor(e)} tabIndex={-1}>
    <div className="evidence-number">{String(index+1).padStart(2,'0')}</div>
    <div className="evidence-content">
      <div className="evidence-row-top"><Badge tone={challenged?'amber':e.provenance==='observed'?'green':e.provenance==='inferred'?'amber':'neutral'}>{label}</Badge><span>{pretty(e.source_type)}</span>{e.fact_id&&<span className="fact-reference">{e.fact_id}</span>}</div>
      <h3>{e.claim}</h3>
      {e.quote&&<blockquote>{e.quote}</blockquote>}
      {(entity||e.entity_scope||e.language||e.as_of)&&<dl className="evidence-context">{entity&&<div><dt>Entity</dt><dd>{entity}</dd></div>}{e.entity_scope&&<div><dt>Scope</dt><dd>{pretty(e.entity_scope)}</dd></div>}{e.language&&<div><dt>Source language</dt><dd>{language}</dd></div>}{e.as_of&&<div><dt>As of</dt><dd>{e.as_of}</dd></div>}</dl>}
      {quantity&&Number.isFinite(quantity.value)&&<div className="parsed-quantity"><span>Parsed quantity</span><strong>{quantity.approximate?'Approx. ':''}{quantity.value.toLocaleString('en-GB',{maximumFractionDigits:4})} {quantity.unit}</strong><small>Original expression: {quantity.value_text}</small></div>}
      {e.support_reason&&<p className="evidence-support"><strong>Support review:</strong> {e.support_reason}</p>}
      {dimensions.length>0&&<div className="evidence-dimensions">{dimensions.map(d=><span key={d}>{labels[d]||pretty(d)}</span>)}</div>}
      <div className="source-line">{href?<a href={href} target="_blank" rel="noreferrer"><Icon name="external" size={13}/>{e.title||(href.startsWith('/')?'Original document':new URL(href).hostname)}</a>:<span>{e.title||'No supporting public source'}</span>}{e.captured_at&&<span>Captured {new Date(e.captured_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</span>}</div>
    </div>
  </article>;
}
