"""
main.py
-------
FastAPI application entry point for the Automated B2B Client Reporting & Query Engine.

Three-phase request pipeline
-----------------------------
  Phase 1 — SQL Generation
    User's natural language prompt + SCHEMA_CONTEXT → Gemini (temperature=0.0)
    → deterministic, raw SQLite SELECT statement.

  Phase 2 — Guardrail + Execution
    Generated SQL → guardrails.validate_sql() → SQLAlchemy execution
    → list of raw result rows.

  Phase 3 — Business Summarisation
    Raw rows + original question → Gemini (temperature=0.3)
    → clean, client-facing English summary.

Environment
-----------
  Set GEMINI_API_KEY in a .env file or as a shell environment variable.
  The google-genai SDK picks it up automatically via genai.Client().
"""

import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
from google.genai import types
from google.genai._api_client import HttpOptions
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SCHEMA_CONTEXT, get_db, seed_database
from guardrails import validate_sql

# ---------------------------------------------------------------------------
# Environment & Gemini client initialisation
# ---------------------------------------------------------------------------

load_dotenv()  # Load GEMINI_API_KEY from .env if present

# Resolve and validate the API key at import time so the server fails fast
# with a clear message rather than a cryptic SDK error at request time.
_API_KEY = os.getenv("GEMINI_API_KEY")
if not _API_KEY:
    raise EnvironmentError(
        "GEMINI_API_KEY is not set. "
        "Add it to a .env file or export it as an environment variable."
    )

# Pass the key explicitly — avoids SDK ambiguity between Google AI and Vertex AI.
# 45 s timeout: generous for a single-turn request, prevents indefinite worker blocks.
# Note: HttpOptions.timeout is in milliseconds.
client = genai.Client(
    api_key=_API_KEY,
    http_options=HttpOptions(timeout=45_000),
)

MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Application lifespan — seed DB on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed the SQLite database with mock data before accepting requests."""
    seed_database()
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Automated B2B Client Reporting & Query Engine",
    description=(
        "Bridges natural language business questions and a relational database. "
        "Powered by Gemini 2.5 Flash."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Static files & templates ──
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Payload accepted by the POST /api/query endpoint."""

    prompt: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Natural language business question to answer from the database.",
        examples=["Which Enterprise clients have unpaid invoices this month?"],
    )


class QueryResponse(BaseModel):
    """Structured response returned by the POST /api/query endpoint."""

    question: str = Field(..., description="The original user question.")
    generated_sql: str = Field(..., description="The SQL query produced by Gemini.")
    raw_results: list[dict[str, Any]] = Field(
        ..., description="Raw rows returned by the database."
    )
    summary: str = Field(
        ..., description="Business-friendly summary produced by Gemini."
    )


# ---------------------------------------------------------------------------
# System instructions for each Gemini call
# ---------------------------------------------------------------------------

_SQL_SYSTEM_INSTRUCTION = f"""
You are an expert SQLite query generator for a B2B SaaS analytics platform.

Your ONLY job is to convert a natural language business question into a single,
valid, read-only SQLite SELECT statement.

Rules you MUST follow:
1. Return ONLY the raw SQL query — no explanations, no markdown, no code fences.
2. The query MUST start with SELECT.
3. Never use DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, or any mutating keyword.
4. Use only the tables and columns defined in the schema below.
5. Prefer explicit column aliases (AS) for clarity in results.
6. Use standard SQLite date functions for any date arithmetic.
7. If the question cannot be answered from the schema, return exactly:
   SELECT 'Question cannot be answered from the available schema.' AS message;

DATABASE SCHEMA:
{SCHEMA_CONTEXT}
""".strip()

_SUMMARY_SYSTEM_INSTRUCTION = """
You are a fluent B2B Data Analyst presenting findings to a non-technical business audience.

Your job is to translate raw database query results into a concise, professional
English summary that directly answers the user's original question.

Rules:
1. Write in clear, plain business English — no SQL, no technical jargon.
2. Highlight key numbers, trends, or anomalies that are relevant to the question.
3. Keep the summary focused and under 200 words unless the data genuinely requires more.
4. If the result set is empty, say so clearly and suggest a possible reason.
5. Do not invent data that is not present in the results.
""".strip()


# ---------------------------------------------------------------------------
# Helper: execute raw SQL safely and return list of dicts
# ---------------------------------------------------------------------------


def _execute_query(sql: str, db: Session) -> list[dict[str, Any]]:
    """
    Execute a validated SQL string against the database.

    Returns
    -------
    list[dict]
        Each row as a column-name → value mapping.

    Raises
    ------
    HTTPException (500)
        On any database execution error.
    """
    try:
        result = db.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return rows
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Database execution error: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Helper: call Gemini with a given system instruction and user message
# ---------------------------------------------------------------------------


def _call_gemini(system_instruction: str, user_message: str, temperature: float) -> str:
    """
    Send a single-turn request to Gemini and return the text response.

    Parameters
    ----------
    system_instruction : str
        Persona and rules for the model in this call.
    user_message : str
        The user-facing content to process.
    temperature : float
        Sampling temperature (0.0 = deterministic, higher = more creative).

    Returns
    -------
    str
        The model's text output, stripped of leading/trailing whitespace.

    Raises
    ------
    HTTPException (502)
        If the Gemini API call fails or returns an empty response.
    """
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
            ),
        )
        output = response.text.strip()
        if not output:
            raise ValueError("Gemini returned an empty response.")
        return output
    except HTTPException:
        raise  # Re-raise our own HTTP exceptions untouched
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API error: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /  — Serve the frontend UI
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_ui(request: Request):
    """Serve the single-page frontend application."""
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# POST /api/query  — main endpoint
# ---------------------------------------------------------------------------


@app.post(
    "/api/query",
    response_model=QueryResponse,
    summary="Natural Language → SQL → Business Summary",
    tags=["Query Engine"],
)
def query_endpoint(
    request: QueryRequest,
    db: Session = Depends(get_db),
) -> QueryResponse:
    """
    Accept a natural language business question and return a structured response
    containing the generated SQL, raw database results, and a plain-English summary.

    ### Pipeline
    1. **SQL Generation** — Gemini converts the prompt to a SQLite SELECT statement.
    2. **Guardrail Validation** — The SQL is inspected for destructive keywords.
    3. **Database Execution** — The validated SQL runs against the SQLite database.
    4. **Business Summarisation** — Gemini translates raw rows into a readable summary.
    """

    # ------------------------------------------------------------------
    # Phase 1: Natural Language → SQL
    # ------------------------------------------------------------------
    sql_prompt = (
        f"Business question: {request.prompt}\n\n"
        "Generate the SQLite SELECT query that answers this question."
    )

    generated_sql = _call_gemini(
        system_instruction=_SQL_SYSTEM_INSTRUCTION,
        user_message=sql_prompt,
        temperature=0.0,
    )

    # ------------------------------------------------------------------
    # Phase 2: Guardrail validation + database execution
    # ------------------------------------------------------------------
    validated_sql = validate_sql(generated_sql)  # Raises HTTP 400 on violation
    raw_results = _execute_query(validated_sql, db)

    # ------------------------------------------------------------------
    # Phase 3: Raw results → Business summary
    # ------------------------------------------------------------------
    summary_prompt = (
        f"Original business question: {request.prompt}\n\n"
        f"SQL query used:\n{validated_sql}\n\n"
        f"Raw database results ({len(raw_results)} rows):\n{raw_results}\n\n"
        "Please provide a clear business summary of these results."
    )

    summary = _call_gemini(
        system_instruction=_SUMMARY_SYSTEM_INSTRUCTION,
        user_message=summary_prompt,
        temperature=0.3,
    )

    return QueryResponse(
        question=request.prompt,
        generated_sql=validated_sql,
        raw_results=raw_results,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# GET /health  — liveness probe
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Ops"], summary="Health check")
def health_check():
    """Simple liveness probe for load balancers and monitoring tools."""
    return {"status": "ok", "model": MODEL}


# ---------------------------------------------------------------------------
# Global exception handler — catch-all for unhandled errors
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Unexpected server error: {exc}"},
    )
