import React from 'react';
import {Heading,Icon,Badge} from './ui';
import './blueprint.css';

const diagrams=[
 ['current-architecture','The laptop architecture','FastAPI, two executors, three graphs and local persistence.','Implemented','app'],
 ['current-workflow','The implemented workflow','Evidence, rubric assessment, score calculation and optional buyer qualification.','Implemented','app'],
 ['langgraph-detail','Research graph: node by node','Eight exact nodes, the scope interrupt, model calls and checkpoint retries.','Implemented','app'],
 ['buyer-workflow','Buyer graph: the bounded branch','Four exact nodes, one targeted search, evidence gates and an independent budget.','Implemented','app'],
 ['qualification-graph','Qualification graph: the human decision','Two exact nodes, interrupt/resume and the persisted decision transaction.','Implemented','app'],
 ['rag-evidence','RAG, assessment and scoring','Follow a source capture through validation, rubric judgment and code-calculated points.','Implemented','app'],
 ['human-review','Human review and resume','Saved human decisions today; authorized and versioned resume in production.','Demo to production','human'],
 ['production-architecture','The AWS architecture','Managed services, durable dispatch and explicit network boundaries.','Proposed AWS','cloud'],
 ['production-workflow','The production workflow','Versioned jobs, optional buyer qualification, human review and CRM delivery.','Proposed AWS','cloud'],
 ['evolution','The path to production','Operating controls, quality gates and conditional multi-agent evolution.','Delivery decisions','cloud'],
 ['production-delivery','Deployment and operations','Release gates, evidence evaluation, monitoring, rollback and recovery.','Proposed AWS','cloud'],
];
export function Blueprint({navigate}){
 const selected=diagrams.find(d=>location.pathname===`/blueprint/${d[0]}`);
 const index=selected?diagrams.indexOf(selected):-1;
 return <>
  <Heading eyebrow="SYSTEM REFERENCE" title={selected?selected[1]:'Architecture, from demo to production.'}>
   {selected?selected[2]:'Explore the running services, exact workflow nodes and proposed cloud design.'}
  </Heading>
  <div className="blueprint-actions">
  </div>
  {selected?<>
   <div className="blueprint-detail-head"><button className="back-link" onClick={()=>navigate('/blueprint')}><Icon name="back" size={15}/>All diagrams</button><Badge tone={selected[4]==='app'?'green':'neutral'}>{selected[3]}</Badge><a href={`/diagrams/${selected[0]}.svg`} target="_blank" rel="noreferrer">Open full size<Icon name="external" size={14}/></a><a href={`/diagrams/${selected[0]}.svg`} download>SVG<Icon name="download" size={14}/></a><a href={`/diagrams/${selected[0]}.mmd`} download>Mermaid source<Icon name="code" size={14}/></a></div>
   <div className="blueprint-canvas"><img src={`/diagrams/${selected[0]}.svg`} alt={`${selected[1]}. ${selected[2]}`}/></div>
   <div className="blueprint-pagination"><button className="button" disabled={index===0} onClick={()=>navigate(`/blueprint/${diagrams[index-1][0]}`)}><Icon name="back" size={16}/>Previous</button><span>{index+1} / {diagrams.length}</span><button className="button" disabled={index===diagrams.length-1} onClick={()=>navigate(`/blueprint/${diagrams[index+1][0]}`)}>Next<Icon name="arrow" size={16}/></button></div>
  </>:<>
   <div className="blueprint-context"><div><span>01 / THE RUNNING SYSTEM</span><strong>Services and evidence.</strong><p>Trace the local application, model calls, source validation and persisted records.</p></div><div><span>02 / INSIDE LANGGRAPH</span><strong>Three graphs, fourteen nodes.</strong><p>Inspect research, buyer qualification and human review with their exact branches and checkpoints.</p></div><div><span>03 / PRODUCTION DESIGN</span><strong>Durable cloud operation.</strong><p>See the proposed AWS services, identity controls, release gates and recovery design.</p></div></div>
   <div className="blueprint-grid">{diagrams.map(([id,title,description,status,tone])=><button className="blueprint-card" key={id} onClick={()=>navigate(`/blueprint/${id}`)}><div className="blueprint-preview"><img src={`/diagrams/${id}.svg`} alt="" loading="lazy"/></div><div className="blueprint-card-copy"><Badge tone={tone==='app'?'green':'neutral'}>{status}</Badge><h2>{title}<Icon name="arrow" size={18}/></h2><p>{description}</p></div></button>)}</div>
   <div className="quiet-note"><Icon name="info" size={16}/><span>AWS designs are proposed; no cloud resources have been deployed.</span></div>
  </>}
 </>
}
