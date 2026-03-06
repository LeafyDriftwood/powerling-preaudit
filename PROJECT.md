# Powerling Pre-Audit System

## Goal

Automate the Powerling pre-audit report - a deliverable Powerling sends to prospective clients that analyzes their website across multiple digital pillars and benchmarks them against their competitors.

The manual workflow currently is:
1. Account manager gathers the client URL and competitor URLs
2. Uses SEMrush manually for SEO/health data
3. Feeds everything into a custom GPT via ChatGPT.com
4. Validates the output manually
5. Exports to PDF and delivers to the client

The goal is to fully automate this: submit a URL → get a structured, professional-quality report as output.

---

## Audit Structure (Pillars)

The audit covers four pillars. Each pillar produces:
- An intro sentence
- Key findings intro paragraph
- 5-7 key finding bullets
- Impact paragraph
- 5 recommendations
- Expected ROI paragraph
- Benchmark table (client vs. 3 competitors)

### Pillar 1: Globalization
Assesses how well the website serves an international audience.
- Language Coverage Rate (LCR) = (Available Languages / Required Languages) × 100
- LCR is computed deterministically from gathered data - not AI-guessed
- Language selector type, hreflang tags, translation quality, traffic by country

### Pillar 2: Website Health *(NOT YET IMPLEMENTED)*
Intended to assess technical SEO, site speed, and crawlability.
- Currently a placeholder: `"Google PageSpeed / SEO diagnostic integration pending."`
- Planned: Google PageSpeed Insights API, SEMrush API (or equivalent), Core Web Vitals

### Pillar 3: Accessibility & Compliance
- WCAG issues, accessibility statement, cookie consent, privacy policy, ToS, sitemap
- GDPR and ADA compliance indicators
- Accessibility lawsuits from public record
- Primary region detected to assess regulatory exposure

### Pillar 4: Online Reputation
- Social media presence with follower counts (LinkedIn, X, Instagram, Facebook, YouTube)
- Review scores and counts: Trustpilot, Google Reviews, Glassdoor, G2/Capterra
- CEO approval rating (Glassdoor)
- Recent news (past 12 months), controversies, overall sentiment

### Competitive Landscape
- One cross-pillar comparison table: client vs. 3 competitors, 4 pillar rows
- Two-sentence intro paragraph

### Conclusion
- Positives, negatives, top 5 cross-pillar recommendations, combined ROI

---

## Tech Stack

### Backend
- **FastAPI** - REST API server
- **SQLite + SQLAlchemy** - Job persistence (status tracking, result storage)
- **OpenAI Python SDK** - All AI calls
  - `gpt-4o-search-preview` (Chat Completions) - web search/data gathering
  - `gpt-4o` (Chat Completions) - report generation (no search)
- **python-dotenv** - Environment variable loading
- `OPENAI_API_KEY` stored in `backend/.env`

### Frontend
- **Next.js 16 App Router** (TypeScript)
- **Tailwind CSS**
- **react-hot-toast** - Toast notifications

### Project Layout
```
powerling-preaudit/
├── backend/
│   ├── .env                  # OPENAI_API_KEY
│   ├── audit_jobs.db         # SQLite DB (auto-created, gitignored)
│   └── app/
│       ├── __init__.py       # (may need to create if import issues)
│       ├── audit.py          # Full pipeline logic
│       └── main.py           # FastAPI app, DB models, endpoints
└── frontend/
    └── app/
        ├── layout.tsx
        ├── page.tsx                      # Submission form
        └── audits/
            └── [job_id]/
                └── page.tsx             # Job status polling page
```

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/audits` | Submit a new audit job |
| GET | `/audits/{job_id}` | Poll job status and metadata |
| GET | `/audits/{job_id}/result` | Get the full completed report (JSON) |

### POST /audits request body
```json
{
  "url": "https://client.com",
  "company_name": "Acme Corp",
  "competitor_1": "https://competitor1.com",
  "competitor_2": "https://competitor2.com",
  "competitor_3": "https://competitor3.com"
}
```

### Job Status Flow
```
pending → processing → completed
                    ↘ error
```

---

## Pipeline (audit.py)

The pipeline runs as a **FastAPI BackgroundTask** after job creation. It is fully sequential (no concurrency) to support stateful conversations.

```
Phase 1: gather_all_client_data(url, company_name)
  └── Stateful 3-turn conversation with gpt-4o-search-preview
        Turn 1 → Globalization data (languages, LCR, traffic)
        Turn 2 → Accessibility & Compliance (model has Turn 1 context)
        Turn 3 → Online Reputation (model has Turn 1+2 context)

Phase 2: For each competitor URL:
  └── gather_competitor_benchmark_data(comp_url)
        One call per competitor, gpt-4o-search-preview
        Covers all benchmark dimensions in one shot

Phase 3: build_facts_pack(...)
  └── Merges all gathered data
  └── Computes LCR deterministically for client and each competitor

Phase 4: Sequential generation with gpt-4o
  ├── generate_pillar1(facts)
  ├── generate_pillar3(facts)
  ├── generate_pillar4(facts)
  ├── generate_competitive_landscape(facts, pillar_summaries)
  └── generate_conclusion(facts, pillar_summaries)

Return: structured dict with facts + all pillar content
```

### Key Design Decisions
- **Unified Chat Completions API** throughout (no Responses API)
- **gpt-4o-search-preview** for all web-search tasks - this is the correct model for real-time web access via Chat Completions
- **gpt-4o** for generation - cheaper and faster since no search needed
- **Stateful conversation** for client data so later turns benefit from context (e.g., Turn 3 "Online Reputation" already knows the company region from Turn 2)
- **_parse_json() helper** strips markdown fences from model output before JSON parsing
- **LCR computed deterministically** from the gathered available/required language lists - never AI-estimated
- **Competitor facts gathered first** so generation calls are pure writing tasks with no hallucinated benchmarks
- **response_format={"type": "json_object"}** on all generation calls for reliable output

---

## Running the App

### Backend
```bash
cd backend
pip install fastapi uvicorn sqlalchemy openai python-dotenv
uvicorn app.main:app --reload
# Runs on http://localhost:8000
```

**Important:** If you change the DB schema (add columns to AuditJob), delete `audit_jobs.db` first:
```bash
rm backend/audit_jobs.db
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

---

## Current State (as of Feb 2026)

### What works
- [x] Form submission (company name, URL, 3 competitor URLs)
- [x] Job creation and persistence in SQLite
- [x] Background pipeline execution (pending → processing → completed/error)
- [x] Status polling page (polls every 2 seconds, stops on terminal state)
- [x] Full audit pipeline for Pillars 1, 3, 4
- [x] Competitor data gathering
- [x] Competitive landscape and conclusion generation
- [x] Result storage in DB
- [x] Result retrieval endpoint (`GET /audits/{job_id}/result`)

### What's missing / not yet done
- [ ] **Results display page** - the frontend has no page to render the completed JSON report. When status = "completed", the user should be redirected to a rich report view. Currently `GET /audits/{job_id}/result` returns raw JSON with no frontend.
- [ ] **Pillar 2 (Website Health)** - placeholder only. Needs Google PageSpeed Insights API integration and SEO diagnostics.
- [ ] **PDF generation** - the final deliverable is a PDF. WeasyPrint or pdfkit planned.
- [ ] **HTML report template** - before PDF, need a well-designed HTML template (probably React-to-PDF or a Jinja2 template server-side).
- [ ] **requirements.txt / pyproject.toml** - backend has no dependency manifest.
- [ ] **Error handling on frontend** - status page shows error status but no "try again" flow.
- [ ] **Auth / multi-tenancy** - all jobs are public by job ID. No user accounts or access control.

---

## What's Next (Priority Order)

1. **Results display page** (`/audits/[job_id]/result` route in Next.js)
   - Fetch `GET /audits/{job_id}/result` when status is "completed"
   - Render each pillar with its intro, findings, impact, recommendations, ROI, benchmark table
   - Render competitive landscape table
   - Render conclusion

2. **Auto-redirect to results** - when the status page detects `completed`, redirect to the results page automatically.

3. **Pillar 2 (Website Health)** - integrate Google PageSpeed Insights API (free, no auth needed for basic use). Pull Core Web Vitals, performance score, SEO score.

4. **PDF export** - add a "Download as PDF" button on the results page. Options: browser `window.print()` with print CSS, WeasyPrint (server-side), or a headless Chrome PDF render.

5. **requirements.txt** - pin all backend dependencies.

---

## Known Issues & Gotchas

- **DB schema changes**: SQLAlchemy's `create_all` won't ALTER existing tables. Must `rm audit_jobs.db` after any model change.
- **`__init__.py`**: If the relative import `from .audit import run_audit` breaks, create an empty `backend/app/__init__.py`.
- **gpt-4o-search-preview**: This model does not support `response_format={"type": "json_object"}`. JSON output is enforced via prompt instructions + `_parse_json()` helper. Only use `response_format` on `gpt-4o` calls.
- **LCR non-determinism**: The `required_languages` list is gathered via web search (AI-estimated for the client's market). This is inherently approximate - the LCR formula is deterministic but the input list is AI-inferred.
- **Competitor `company_name`**: The competitor benchmark data includes a `company_name` field that the model fills in from its search. This may differ slightly from what the user expects. Consider passing the competitor company name from the user alongside the URL.
- **3 competitors hardcoded**: The DB schema and API both assume exactly 3 competitors. The pipeline logic uses `for comp_url in competitors` (flexible), but the DB model has `competitor_1/2/3` columns.
