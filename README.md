# Automated B2B Client Reporting & Query Engine

A production-grade natural language query engine that bridges the gap between non-technical business users and a relational database. Ask a business question in plain English, get back validated SQL, raw data, and a clean business summary. Powered by **Gemini 2.5 Flash** and built with **FastAPI**.

---

## How It Works

Every request runs through a strict three-phase pipeline:

```
         User Prompt 
             │
             ▼
┌─────────────────────────────┐
│  Phase 1 — SQL Generation   │  Gemini 2.5 Flash (temp=0.0)
│  Natural language → SELECT  │  Schema-grounded, deterministic
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  Phase 2 — Guardrail Check  │  Blocks DROP, DELETE, UPDATE,
│  + Database Execution       │  INSERT, ALTER, TRUNCATE + 15 more
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  Phase 3 — Summarisation    │  Gemini 2.5 Flash (temp=0.3)
│  Raw rows → Business prose  │  Plain-English analyst summary
└─────────────────────────────┘
```

---

## Features

- **Natural language to SQL** — Gemini converts any business question into a valid SQLite `SELECT` statement
- **Security guardrails** — 20 blocked keywords, comment stripping, markdown fence removal, and strict `SELECT`/`WITH` enforcement before any SQL touches the database
- **Business summaries** — raw query results are translated into readable, structured English with proper formatting
- **Interactive UI** — clean enterprise-style frontend with a collapsible schema explorer, suggested questions dropdown, syntax-highlighted SQL viewer, and dynamic results table
- **Auto-seeded database** — 12 realistic B2B clients, 144 usage log entries, and 37 invoices seeded on first startup — no setup required
- **Zero build step** — frontend is plain HTML/CSS/JS served directly by FastAPI

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI |
| AI model | Gemini 2.5 Flash (`google-genai`) |
| Database | SQLite via SQLAlchemy ORM |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Templating | Jinja2 |
| Server | Uvicorn |

---

## Project Structure

```
.
├── main.py              # FastAPI app, Gemini orchestration, API routes
├── database.py          # SQLAlchemy models, schema context, seed data
├── guardrails.py        # SQL validation and security layer
├── requirements.txt     # Pinned Python dependencies
├── .env                 # Your secrets (gitignored)
├── .env.example         # Environment variable template
├── templates/
│   └── index.html       # Single-page frontend UI
└── static/
    ├── style.css        # Full design system stylesheet
    └── app.js           # Frontend logic, dropdown, table renderer
```

---

## Database Schema

```
clients
  ├── id              INTEGER  PK
  ├── company_name    TEXT
  ├── tier            TEXT     -- Enterprise | Mid-Market | SMB
  ├── industry        TEXT
  └── country         TEXT

subscriptions
  ├── id              INTEGER  PK
  ├── client_id       INTEGER  FK → clients.id
  ├── plan_name       TEXT     -- Starter | Growth | Professional | Enterprise
  ├── monthly_price   REAL
  └── status          TEXT     -- Active | Paused | Churned

usage_logs
  ├── id              INTEGER  PK
  ├── client_id       INTEGER  FK → clients.id
  ├── api_calls_made  INTEGER
  ├── storage_used_gb REAL
  └── log_date        DATE

invoices
  ├── id              INTEGER  PK
  ├── client_id       INTEGER  FK → clients.id
  ├── amount_due      REAL
  ├── payment_status  TEXT     -- Paid | Unpaid
  └── due_date        DATE
```

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-username/b2b-query-engine.git
cd b2b-query-engine
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key

```bash
cp .env.example .env
```

Open `.env` and replace the placeholder with your real key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

Get a free API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

### 5. Start the server

```bash
uvicorn main:app --reload
```

The database is seeded automatically on first startup. Open **http://localhost:8000** in your browser.

---

## API Reference

### `POST /api/query`

Accepts a natural language business question and returns SQL, raw results, and a business summary.

**Request**
```json
{
  "prompt": "Which Enterprise clients have unpaid invoices?"
}
```

**Response**
```json
{
  "question": "Which Enterprise clients have unpaid invoices?",
  "generated_sql": "SELECT c.company_name, i.amount_due, i.due_date ...",
  "raw_results": [
    { "company_name": "Apex Dynamics", "amount_due": 5243.10, "due_date": "2026-05-01" }
  ],
  "summary": "Two Enterprise clients currently have outstanding invoices..."
}
```

**Error responses**

| Status | Cause |
|---|---|
| `400` | SQL failed guardrail validation (destructive keyword or non-SELECT) |
| `422` | Prompt too short (< 5 characters) or too long (> 1000 characters) |
| `502` | Gemini API error or timeout |
| `500` | Database execution error |

---

### `GET /health`

Liveness probe for monitoring and load balancers.

```json
{ "status": "ok", "model": "gemini-2.5-flash" }
```

---

### `GET /docs`

Interactive Swagger UI for exploring and testing the API directly in the browser.

---

## Example Queries

| Question | What it demonstrates |
|---|---|
| Which Enterprise clients have unpaid invoices? | JOIN across 3 tables + status filter |
| List all churned clients and their subscription plan. | Multi-table JOIN + enum filter |
| Show total API calls per client in the last 30 days. | Aggregation + date arithmetic |
| Which 3 clients have the highest monthly price? | ORDER BY + LIMIT |
| How many clients do we have per country? | GROUP BY aggregation |
| Which client used the most storage on average this month? | AVG + date filter + ORDER BY |

---

## Security

The guardrail layer inspects every Gemini-generated SQL string before execution:

- Strips markdown code fences (` ```sql `) the model may emit
- Removes `--` line comments and `/* */` block comments to prevent keyword smuggling
- Blocks 20 destructive/mutating keywords: `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `REPLACE`, `CREATE`, `ATTACH`, `DETACH`, `PRAGMA`, `VACUUM`, `REINDEX`, `GRANT`, `REVOKE`, `EXEC`, `EXECUTE`, `CALL`, `MERGE`, `LOAD`
- Enforces that the statement opens with `SELECT` or `WITH` (for CTEs)
- All violations return `HTTP 400` with a specific user-facing error message

---

## License

MIT
