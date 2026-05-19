"""
guardrails.py
-------------
Security and validation layer for the Automated B2B Client Reporting & Query Engine.

Responsibilities:
  - Inspect every Gemini-generated SQL string BEFORE it touches the database.
  - Block all destructive or mutating SQL keywords unconditionally.
  - Enforce that the statement is a read-only SELECT query.
  - Strip markdown code-fence artifacts that the model may occasionally emit
    despite being instructed not to.
  - Raise an HTTP 400 Bad Request with a clear, user-facing message on any
    violation so the API consumer always gets actionable feedback.

Design principles:
  - Fail closed: when in doubt, reject.
  - No regex-only reliance for keyword detection — we normalise the SQL string
    (strip comments, collapse whitespace, upper-case) before checking, making
    it much harder to bypass with trivial obfuscation.
"""

import re

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Blocked keyword list
# Any SQL statement containing these tokens is unconditionally rejected.
# ---------------------------------------------------------------------------

_BLOCKED_KEYWORDS: list[str] = [
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "REPLACE",       # SQLite-specific upsert — mutates data
    "CREATE",        # Prevent schema changes
    "ATTACH",        # SQLite ATTACH DATABASE — could open arbitrary files
    "DETACH",
    "PRAGMA",        # SQLite PRAGMA can change DB settings
    "VACUUM",        # Rewrites the DB file
    "REINDEX",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "CALL",
    "MERGE",
    "LOAD",
    "COPY",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_markdown_fences(sql: str) -> str:
    """
    Remove markdown code-fence wrappers that the model may emit despite
    instructions to the contrary.

    Handles patterns like:
      ```sql\\nSELECT ...\\n```
      ```\\nSELECT ...\\n```
    """
    # Remove opening fence (```sql or ```)
    sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql.strip())
    # Remove closing fence
    sql = re.sub(r"\s*```$", "", sql.strip())
    return sql.strip()


def _strip_sql_comments(sql: str) -> str:
    """
    Remove SQL line comments (-- ...) and block comments (/* ... */).
    This prevents keyword smuggling inside comment strings.
    """
    # Block comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Line comments
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _normalise(sql: str) -> str:
    """
    Return an upper-cased, whitespace-collapsed version of the SQL string
    with comments removed — used exclusively for keyword scanning.
    """
    sql = _strip_sql_comments(sql)
    sql = sql.upper()
    sql = re.sub(r"\s+", " ", sql).strip()
    return sql


def _extract_first_token(normalised_sql: str) -> str:
    """Return the first whitespace-delimited token of the normalised SQL."""
    parts = normalised_sql.split()
    return parts[0] if parts else ""


# ---------------------------------------------------------------------------
# Public validation entry point
# ---------------------------------------------------------------------------


def validate_sql(raw_sql: str) -> str:
    """
    Validate and sanitise a Gemini-generated SQL string.

    Steps
    -----
    1. Strip any markdown code-fence wrappers.
    2. Reject empty or whitespace-only strings.
    3. Normalise (strip comments, upper-case, collapse whitespace).
    4. Scan for blocked mutating/destructive keywords.
    5. Enforce that the statement begins with SELECT.

    Parameters
    ----------
    raw_sql : str
        The raw SQL string returned by the Gemini model.

    Returns
    -------
    str
        The cleaned SQL string, safe to execute against the database.

    Raises
    ------
    HTTPException (400)
        If any validation rule is violated.
    """
    # Step 1 — strip markdown artifacts
    cleaned_sql = _strip_markdown_fences(raw_sql)

    # Step 2 — reject empty output
    if not cleaned_sql.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "The model returned an empty query. "
                "Please rephrase your question and try again."
            ),
        )

    # Step 3 — normalise for scanning (do NOT use this for execution)
    normalised = _normalise(cleaned_sql)

    # Step 4 — blocked keyword scan
    # We use word-boundary matching so that e.g. "UPDATED_AT" does not
    # trigger the UPDATE block.
    for keyword in _BLOCKED_KEYWORDS:
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, normalised):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Query rejected: the keyword '{keyword}' is not permitted. "
                    "Only read-only SELECT statements are allowed."
                ),
            )

    # Step 5 — enforce SELECT or WITH (CTE) as the opening statement.
    # Gemini legitimately generates WITH ... AS (SELECT ...) SELECT ... for
    # complex aggregations. We allow WITH only when it is followed by a
    # SELECT inside the CTE body — the blocked-keyword scan above already
    # ensures no mutating statements are present anywhere in the string.
    first_token = _extract_first_token(normalised)
    if first_token not in ("SELECT", "WITH"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Query rejected: statement must begin with SELECT or WITH, "
                f"but got '{first_token}'. "
                "Only read-only SELECT queries are permitted."
            ),
        )

    # Extra guard for WITH: the normalised body must still contain SELECT
    if first_token == "WITH" and "SELECT" not in normalised:
        raise HTTPException(
            status_code=400,
            detail=(
                "Query rejected: WITH clause does not contain a SELECT statement."
            ),
        )

    return cleaned_sql
