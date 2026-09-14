# Evidence artifacts

`companies.json` contains 11 curated research records from the existing interview captures. The original captures were created on 13 Sep 2026. This application makes no network or model calls to refresh them.

Each company record contains the exact selected excerpt, original capture timestamp, original seed filename and SHA-256 of the original saved HTML. `source_capture.page_text` retains the saved source text for local verification. HTML entities are decoded and em dash punctuation is normalized to a standard hyphen. Source statements remain company self-descriptions, not independent verification.

Application suitability is an authored research hypothesis. Imported model `quality` flags are not used. Original search snippets are not silently promoted to observed company facts. Geography explicitly marked as research scope is not supported by the excerpt itself. Schröder + Heidler has an additional self-reported structured-metadata headcount of at least 115 employees. This is not annual polymer demand.

`products.json` contains page-addressable chunks extracted with pypdf from the two provided fictional product PDFs. `documents/` contains unchanged copies of those PDFs. Product facts, compliance and commercial volume ranges are fictional case-study data, unrelated to any real product.

The V-0 housing request is an authored synthetic policy example in `backend/domain.py`. It is not attributed to any real company. Its commercial score remains the sum of its four criterion contributions, while the independent hard technical gate excludes it from prioritized eligible leads and prevents approval.

`scripts/prepare_data.py` reproducibly builds these artifacts from the local interview materials. Runtime uses only files in this folder; it does not import or execute sibling application code.

Runtime databases are created on launch. `leadgen.db` holds runs, review decisions, pipeline records, customer notes and evaluation results. `leadgen.db.checkpoints` holds actual LangGraph checkpoints. Both must be preserved for full restart continuity. Tests use isolated temporary databases.

Captured replay requests use a bounded rule parser. Ordinary paraphrases are accepted only when the product, application and geography map to one captured scope. Unsupported qualifiers, markets, size filters, technical constraints and negations are rejected rather than silently discarded. Live mode uses Gemini to interpret an open brief for either supplied product and preserves restrictions for search and assessment. Both modes require human scope confirmation.
