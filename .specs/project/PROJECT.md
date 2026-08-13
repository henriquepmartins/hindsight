# Hindsight

**Vision:** Rebuild the FDA's drug-safety early-warning system from public data, then rewind time to test whether it would have caught real safety warnings before the FDA issued them.
**For:** Hiring managers evaluating data engineering / data science / ML candidates — and, secondarily, anyone who wants an open, queryable version of FAERS.
**Solves:** 20.7M adverse-event reports sit in a public archive that is effectively unusable — 111 GB of denormalized JSON, drug names spelled dozens of ways, duplicate reports, and a file format that has changed repeatedly since 2004. Nobody can ask it questions. This project makes it answerable, and then answers one.

## Goals

- **G1 — Make the corpus usable.** All 20.7M reports (2004–present) normalized into a queryable columnar store under 5 GB, refreshed automatically, with documented data-quality metrics. Success: a single DuckDB query over the full corpus returns in <5s on a laptop.
- **G2 — Detect signals.** Implement the disproportionality methods regulators actually use (PRR, ROR, Bayesian shrinkage) over every drug–event pair. Success: reproduce at least 3 well-documented drug–event associations from the literature within published effect-size ranges.
- **G3 — Prove it works (the headline).** For a held-out set of real FDA safety label changes, measure how early the system would have flagged the signal using only data available at that time. Success: a published lead-time distribution with honest confidence intervals — **including the misses**.
- **G4 — Ship a public artifact.** A cleaned, versioned Parquet dataset + a generated report site. Success: both public, both reproducible from a single command.

## Tech Stack

**Core:**

- Language: Python 3.12
- Lake: Parquet (partitioned by year/quarter), Cloudflare R2 (10 GB free tier)
- Engine: DuckDB (analytics over Parquet)
- Serving: PostgreSQL (curated marts only — Neon/Supabase free tier)
- Orchestration: GitHub Actions (scheduled crawl + rebuild)
- Report: Quarto or Evidence.dev → GitHub Pages

**Key dependencies:** `duckdb`, `pyarrow`, `ijson` (incremental JSON — required by the streaming design), `httpx`, `polars`, `scipy` / `statsmodels`, `lifelines` (time-to-onset)

**Explicitly NOT used:** no Next.js/React frontend, no LangChain/LLM layer, no deep learning. Each was considered and rejected — see AD-004, AD-005, AD-006 in STATE.md.

## Scope

**v1 includes:**

- Incremental ingestion of the full openFDA `drug/event` corpus (2004q3 → present)
- Lossless normalization of the `openfda` enrichment block into a content-hashed dimension table (removes ~93% of the bytes; verified byte-identical on round-trip — see L-005)
- A round-trip integrity test in CI, run per era, that fails the build if the derived corpus differs from source
- Drug-name entity resolution (`medicinalproduct` / `activesubstance` → canonical substance)
- Report deduplication (FAERS contains known duplicates and superseding versions)
- Disproportionality signal detection: PRR, ROR, and a Bayesian shrinkage estimator
- Time-to-onset analysis for signals with usable start/event dates
- **The Hindsight backtest**: point-in-time signal reconstruction vs. known FDA label changes
- A generated report site including a self-grading data-quality page
- Public Parquet dataset release

**Explicitly out of scope:**

- Causal claims. Disproportionality measures reporting patterns, not causation. Every output says so.
- Clinical or prescribing recommendations of any kind.
- Real-time/streaming ingestion (openFDA refreshes in batches; streaming would be theater).
- The FAERS quarterly ASCII files as primary source (see AD-002).
- Non-drug FAERS domains (devices, foods).

## Constraints

- **Time:** 6 h/week, sustained. Every design decision is judged against this first.
- **Cost:** R$ 0 — hard limit. This is why storage architecture is a first-class concern, not an afterthought.
- **Language:** All artifacts in English.
- **Continuity:** The pipeline must run unattended on a schedule from Milestone 1 onward.
- **Integrity:** The project must be able to prove its own claims. Any finding that cannot be validated against an external source is downgraded to exploratory.
