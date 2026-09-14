# Open-Source AI Lead Generation Platform

An advanced, standalone AI-powered lead generation platform built by Javed Akhtar. 

This platform evaluates market briefs against technical product specifications to automatically discover, score, and verify potential leads using live web research and LLMs. It focuses on turning fragmented market data into grounded, evidence-backed opportunities for technical sales teams.

## Core Features

- **Automated Web Research**: Discovers and cross-references potential leads using real-time search.
- **Evidence-Backed Assessments**: Each lead is evaluated against structured product technical specifications (e.g., latency thresholds, compliance grades).
- **Human-in-the-Loop Qualification**: Generates rich briefings that allow a human to easily review evidence and accept or reject the lead.
- **Trust Boundaries & Security**: Strict separation between public evidence (untrusted) and internal product data (trusted).
- **Traceability**: Decisions are tied directly to cited, addressable chunks of information from public domains.

## Quick Start

### 1. Prerequisites
- Python 3.10+
- Node.js 18+ (for the frontend UI)
- Gemini API key

### 2. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt # Or use your preferred package manager (e.g., uv)

cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 4. Running the Platform
From the project root:
```bash
./start.sh
```
This will boot up the FastAPI backend and serve the application locally. Navigate to `http://localhost:8040` to explore the workspace.

## Architecture

The system uses [LangGraph](https://python.langchain.com/v0.1/docs/langgraph/) to orchestrate research tasks and qualification loops. State is persisted in a local SQLite database (`leadgen.db`), allowing research to be paused for human review and resumed cleanly. 

The primary components include:
1. **Engine**: The core graph execution environment for discovering and extracting evidence.
2. **BuyerEngine**: An optional graph for determining procurement roles.
3. **Store**: Local SQLite checkpoints and business state.
4. **React Application**: A front-end interface built with Vite, utilizing polling for real-time state updates.

## Extending the Platform

This project includes fictional sample products (e.g., `CloudScale AI` and `DataStream Pro`) in `backend/data/products.json`. To use this for your own use-case, simply replace the product definitions and inject your own PDFs or product spec sheets into the knowledge pipeline.

## License

MIT License. Feel free to fork and build upon this platform for your own lead generation initiatives.
