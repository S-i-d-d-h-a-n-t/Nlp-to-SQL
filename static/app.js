/**
 * app.js
 * ------
 * Frontend logic for the B2B Client Reporting & Query Engine.
 *
 * Responsibilities:
 *  - Handle form submission and call POST /api/query
 *  - Animate the three-phase loading pipeline (SQL Gen → Guardrail → Summary)
 *  - Render the business summary, syntax-highlighted SQL, and dynamic results table
 *  - Populate suggested query chips from the sidebar
 *  - Check /health on load and reflect API status in the sidebar footer
 */

"use strict";

// ─── DOM References ────────────────────────────────────────────────────────────
const promptInput   = document.getElementById("prompt-input");
const runBtn        = document.getElementById("run-btn");
const loadingBar    = document.getElementById("loading-bar");
const loadingSteps  = document.getElementById("loading-steps");
const errorBanner   = document.getElementById("error-banner");
const errorMsg      = document.getElementById("error-msg");
const resultsArea   = document.getElementById("results-area");
const summaryCard   = document.getElementById("summary-card");
const summaryText   = document.getElementById("summary-text");
const summaryQuestion = document.getElementById("summary-question");
const sqlCard       = document.getElementById("sql-card");
const sqlPre        = document.getElementById("sql-pre");
const tableCard     = document.getElementById("table-card");
const tableWrapper  = document.getElementById("table-wrapper");
const rowCountBadge = document.getElementById("row-count");
const copyBtn       = document.getElementById("copy-btn");
const statusDot     = document.getElementById("status-dot");
const statusText    = document.getElementById("status-text");

// Step pill elements
const stepPills = {
  sql:      document.getElementById("step-sql"),
  guard:    document.getElementById("step-guard"),
  exec:     document.getElementById("step-exec"),
  summary:  document.getElementById("step-summary"),
};

// ─── Suggested Queries ─────────────────────────────────────────────────────────
const SUGGESTED_QUERIES = [
  { icon: "💰", text: "Which Enterprise clients have unpaid invoices?" },
  { icon: "📉", text: "List all churned clients and their last subscription plan." },
  { icon: "📊", text: "Show total API calls per client in the last 30 days." },
  { icon: "🏆", text: "Which 3 clients have the highest monthly subscription price?" },
  { icon: "⚠️",  text: "Show clients with Paused subscriptions and their outstanding invoice amounts." },
  { icon: "🌍", text: "How many clients do we have per country?" },
  { icon: "💾", text: "Which client used the most storage on average this month?" },
  { icon: "📋", text: "Show all invoices due in the last 7 days and their payment status." },
];

// ─── Schema Explorer (collapsible tables) ─────────────────────────────────────
function initSchemaExplorer() {
  document.querySelectorAll(".schema-table-header").forEach(header => {
    const colList = header.nextElementSibling; // .schema-column-list
    const icon    = header.querySelector(".schema-collapse-icon");

    header.addEventListener("click", () => {
      const isExpanded = header.getAttribute("aria-expanded") === "true";

      if (isExpanded) {
        colList.classList.add("collapsed");
        header.setAttribute("aria-expanded", "false");
        icon.textContent = "+";
      } else {
        colList.classList.remove("collapsed");
        header.setAttribute("aria-expanded", "true");
        icon.textContent = "−";
      }
    });
  });
}

// ─── Suggested Questions Dropdown ─────────────────────────────────────────────
const suggestionsToggle = document.getElementById("suggestions-toggle");
const suggestionsPanel  = document.getElementById("suggestions-panel");

function buildSuggestions() {
  // Header row
  const header = document.createElement("div");
  header.className = "suggestions-panel-header";
  header.textContent = "Click a question to load it";
  suggestionsPanel.appendChild(header);

  // One button per query
  SUGGESTED_QUERIES.forEach(({ icon, text }) => {
    const btn = document.createElement("button");
    btn.className = "suggestion-item";
    btn.setAttribute("role", "option");
    btn.innerHTML = `<span class="suggestion-icon">${icon}</span><span class="suggestion-text">${text}</span>`;
    btn.addEventListener("click", () => {
      promptInput.value = text;
      // Trigger auto-resize
      promptInput.style.height = "auto";
      promptInput.style.height = Math.min(promptInput.scrollHeight, 160) + "px";
      closeDropdown();
      promptInput.focus();
    });
    suggestionsPanel.appendChild(btn);
  });
}

function openDropdown() {
  suggestionsPanel.classList.add("open");
  suggestionsToggle.setAttribute("aria-expanded", "true");
}

function closeDropdown() {
  suggestionsPanel.classList.remove("open");
  suggestionsToggle.setAttribute("aria-expanded", "false");
}

function toggleDropdown() {
  const isOpen = suggestionsPanel.classList.contains("open");
  isOpen ? closeDropdown() : openDropdown();
}

// Toggle on button click
suggestionsToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleDropdown();
});

// Close when clicking anywhere outside the dropdown
document.addEventListener("click", (e) => {
  if (!suggestionsToggle.contains(e.target) && !suggestionsPanel.contains(e.target)) {
    closeDropdown();
  }
});

// Close on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDropdown();
});

// ─── Health Check ──────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch("/health");
    if (res.ok) {
      const data = await res.json();
      statusDot.classList.remove("offline");
      statusText.textContent = `API online · ${data.model}`;
    } else {
      throw new Error("non-200");
    }
  } catch {
    statusDot.classList.add("offline");
    statusText.textContent = "API offline";
  }
}

// ─── Loading State Helpers ─────────────────────────────────────────────────────
function setStep(active) {
  Object.entries(stepPills).forEach(([key, el]) => {
    el.classList.remove("active", "done");
    const keys = Object.keys(stepPills);
    const activeIdx = keys.indexOf(active);
    const thisIdx   = keys.indexOf(key);
    if (thisIdx < activeIdx)  el.classList.add("done");
    if (thisIdx === activeIdx) el.classList.add("active");
  });
}

function markAllDone() {
  Object.values(stepPills).forEach(el => {
    el.classList.remove("active");
    el.classList.add("done");
  });
}

function showLoading() {
  loadingBar.classList.add("active");
  loadingSteps.classList.add("active");
  errorBanner.classList.remove("active");
  hideResults();
  runBtn.disabled = true;
  runBtn.innerHTML = `<span>⏳</span> Running…`;
  setStep("sql");
}

function hideLoading() {
  loadingBar.classList.remove("active");
  runBtn.disabled = false;
  runBtn.innerHTML = `<span>▶</span> Run Query`;
}

function hideResults() {
  summaryCard.classList.remove("active");
  sqlCard.classList.remove("active");
  tableCard.classList.remove("active");
}

function showError(message) {
  errorBanner.classList.add("active");
  errorMsg.textContent = message;
  loadingSteps.classList.remove("active");
}

// ─── Lightweight Markdown Renderer (summary only) ─────────────────────────────
// Handles the subset Gemini uses: bold, bullet lists, numbered lists, line breaks.
// No external library needed.
function renderMarkdown(text) {
  // Escape HTML to prevent injection
  let s = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Bold: **text** or __text__
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");

  // Italic: *text* or _text_ (single, not already consumed by bold)
  s = s.replace(/\*([^*\n]+?)\*/g, "<em>$1</em>");
  s = s.replace(/_([^_\n]+?)_/g, "<em>$1</em>");

  // Process line by line for lists and paragraphs
  const lines = s.split("\n");
  const out = [];
  let inUl = false;
  let inOl = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Unordered list item: lines starting with "* " or "- "
    if (/^[\*\-]\s+/.test(line)) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${line.replace(/^[\*\-]\s+/, "")}</li>`);
      continue;
    }

    // Ordered list item: lines starting with "1. " "2. " etc.
    if (/^\d+\.\s+/.test(line)) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${line.replace(/^\d+\.\s+/, "")}</li>`);
      continue;
    }

    // Close any open list before a non-list line
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }

    // Blank line → paragraph break
    if (line.trim() === "") {
      out.push("<br>");
      continue;
    }

    out.push(`<span>${line}</span><br>`);
  }

  // Close any trailing open list
  if (inUl) out.push("</ul>");
  if (inOl) out.push("</ol>");

  return out.join("\n");
}

// ─── SQL Syntax Highlighter ────────────────────────────────────────────────────
const SQL_KEYWORDS = [
  "SELECT","FROM","WHERE","JOIN","LEFT","RIGHT","INNER","OUTER","FULL","CROSS",
  "ON","AS","AND","OR","NOT","IN","IS","NULL","LIKE","BETWEEN","EXISTS",
  "GROUP","BY","ORDER","HAVING","LIMIT","OFFSET","DISTINCT","UNION","ALL",
  "CASE","WHEN","THEN","ELSE","END","WITH","OVER","PARTITION","ROWS","RANGE",
  "ASC","DESC","COUNT","SUM","AVG","MIN","MAX","COALESCE","CAST","DATE",
  "STRFTIME","JULIANDAY","SUBSTR","UPPER","LOWER","TRIM","ROUND","ABS",
];

function highlightSQL(sql) {
  // Escape HTML first
  let s = sql
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Strings (single-quoted)
  s = s.replace(/'([^']*)'/g, `<span class="str">'$1'</span>`);

  // Numbers
  s = s.replace(/\b(\d+\.?\d*)\b/g, `<span class="num">$1</span>`);

  // Keywords (word-boundary, case-insensitive)
  SQL_KEYWORDS.forEach(kw => {
    const re = new RegExp(`\\b(${kw})\\b`, "gi");
    s = s.replace(re, `<span class="kw">$1</span>`);
  });

  // Line comments
  s = s.replace(/(--[^\n]*)/g, `<span class="cmt">$1</span>`);

  return s;
}

// ─── Results Table Builder ─────────────────────────────────────────────────────
const PILL_MAP = {
  "Enterprise": "pill-enterprise",
  "Mid-Market":  "pill-midmarket",
  "SMB":         "pill-smb",
  "Active":      "pill-active",
  "Paused":      "pill-paused",
  "Churned":     "pill-churned",
  "Paid":        "pill-paid",
  "Unpaid":      "pill-unpaid",
};

function cellValue(val) {
  if (val === null || val === undefined) return `<span style="color:var(--neutral-400)">—</span>`;
  const str = String(val);
  if (PILL_MAP[str]) return `<span class="pill ${PILL_MAP[str]}">${str}</span>`;
  // Currency heuristic: column values that look like floats > 10 with no letters
  if (/^\d+\.\d+$/.test(str) && parseFloat(str) > 10) {
    return `$${parseFloat(str).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return str;
}

function buildTable(rows) {
  if (!rows || rows.length === 0) {
    tableWrapper.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <p>No rows returned for this query.</p>
      </div>`;
    rowCountBadge.textContent = "0 rows";
    return;
  }

  const cols = Object.keys(rows[0]);
  const thead = `<thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>`;
  const tbody = `<tbody>${rows.map(row =>
    `<tr>${cols.map(c => `<td>${cellValue(row[c])}</td>`).join("")}</tr>`
  ).join("")}</tbody>`;

  tableWrapper.innerHTML = `<table class="results-table">${thead}${tbody}</table>`;
  rowCountBadge.textContent = `${rows.length} row${rows.length !== 1 ? "s" : ""}`;
}

// ─── Copy SQL Button ───────────────────────────────────────────────────────────
copyBtn.addEventListener("click", () => {
  const sql = sqlPre.textContent;
  navigator.clipboard.writeText(sql).then(() => {
    copyBtn.classList.add("copied");
    copyBtn.innerHTML = `✓ Copied`;
    setTimeout(() => {
      copyBtn.classList.remove("copied");
      copyBtn.innerHTML = `⎘ Copy`;
    }, 2000);
  });
});

// ─── Main Query Handler ────────────────────────────────────────────────────────
async function runQuery() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    promptInput.focus();
    return;
  }

  showLoading();

  // Simulate phase transitions for UX feedback
  // (the real API call is a single round-trip; we animate steps during the wait)
  const stepTimer1 = setTimeout(() => setStep("guard"),   800);
  const stepTimer2 = setTimeout(() => setStep("exec"),   1800);
  const stepTimer3 = setTimeout(() => setStep("summary"), 3000);

  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);
    clearTimeout(stepTimer3);

    const data = await res.json();

    if (!res.ok) {
      // FastAPI error shape: { detail: "..." }
      const msg = data.detail || `Server error (${res.status})`;
      showError(msg);
      hideLoading();
      loadingSteps.classList.remove("active");
      return;
    }

    markAllDone();
    hideLoading();

    // ── Render Summary ──
    summaryQuestion.textContent = `"${data.question}"`;
    summaryText.innerHTML = renderMarkdown(data.summary);
    summaryCard.classList.add("active");

    // ── Render SQL ──
    sqlPre.innerHTML = highlightSQL(data.generated_sql);
    sqlCard.classList.add("active");

    // ── Render Table ──
    buildTable(data.raw_results);
    tableCard.classList.add("active");

    // Scroll results into view
    summaryCard.scrollIntoView({ behavior: "smooth", block: "start" });

  } catch (err) {
    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);
    clearTimeout(stepTimer3);
    showError(`Network error: ${err.message}. Is the server running?`);
    hideLoading();
    loadingSteps.classList.remove("active");
  }
}

// ─── Event Listeners ───────────────────────────────────────────────────────────
runBtn.addEventListener("click", runQuery);

promptInput.addEventListener("keydown", (e) => {
  // Ctrl+Enter or Cmd+Enter submits
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    runQuery();
  }
});

// Auto-resize textarea
promptInput.addEventListener("input", () => {
  promptInput.style.height = "auto";
  promptInput.style.height = Math.min(promptInput.scrollHeight, 160) + "px";
});

// ─── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  buildSuggestions();
  initSchemaExplorer();
  checkHealth();
});
