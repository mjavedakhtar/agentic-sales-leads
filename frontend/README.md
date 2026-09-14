# LeadGen Frontend

This directory contains the user interface for the AI Lead Generation Platform. Built with React and Vite, it delivers a high-performance, real-time workspace for technical sales teams, featuring evidence-backed qualification, human-in-the-loop review, and interactive graph traceability.

## Visual Interface Overview

### 1. Market Discovery & Research Plays
Start an evidence-led research run with live Gemini web search or captured market replays.
![Market Discovery](screenshots/01-discover-page.png)

### 2. Opportunity Shortlist & Fit Scoring
View prioritized leads with quantitative 100-point commercial fit scores and evidence coverage indicators.
![Opportunity Shortlist](screenshots/02-research-shortlist.png)

### 3. Transparent Lead Assessment & Audit Trail
Inspect exact quotes, source links, confidence ratings, open qualification gaps, and software technical gate checks.
![Lead Assessment](screenshots/03-lead-scoring-drawer.png)

### 4. Technical Product Knowledge & BM25 Retrieval
Explore product specifications with verified page-level citations from technical datasheets.
![Product Knowledge](screenshots/04-product-knowledge.png)

### 5. LangGraph Engineering & Workflow Visualizer
Interactive step-by-step state inspection of graph checkpoints, human review gates, and deterministic scoring logic.
![Engineering Visualizer](screenshots/05-engineering-architecture.png)

### 6. Purchasing Authority & Buyer Qualification
Separate technical suitability from commercial purchasing responsibility.
![Buyer Qualification](screenshots/06-buyer-qualification.png)

### 7. Sales Pipeline & Kanban Workspace
Track approved opportunities across qualification stages with full decision logs and export capabilities.
![Sales Pipeline](screenshots/07-sales-pipeline.png)

---

## Development

```bash
# Install dependencies
npm install

# Start development server with HMR
npm run dev

# Build production bundle (output to dist/)
npm run build
```

When running full-stack, the FastAPI backend serves the production bundle built in `dist/` directly from `http://localhost:8040`.
