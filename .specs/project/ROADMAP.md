# Roadmap

**Current Milestone:** M0 — Walking Skeleton
**Status:** Planning

**Budget:** 6 h/week. Each milestone below is sized in hours, not dates. ~24 h/month.

> **Sequencing rule:** M0 proves the whole chain end-to-end on a tiny slice *before* anything is scaled. The full crawl (M1) runs unattended in the background while later milestones are built. Never block on a crawl.

---

## M0 — Walking Skeleton (~24 h)

**Goal:** One partition of FAERS goes all the way through every layer and produces one chart on a public page. Nothing is scaled, nothing is complete, but every link in the chain is proven to exist.

### Features

**Ingest slice** — PLANNED
- Download a single openFDA partition (~246 MB zip → 1.2 GB JSON, 12,000 reports)
- Stream-parse without ever holding the full file in memory
- Pin the partition (URL + export date + SHA-256) in a manifest rather than archiving it — see AD-008. Local `data/raw/` is a cache, not the raw layer

**Normalize slice** — PLANNED
- Split into fact tables (`report`, `report_drug`, `report_reaction`) + dimension (`openfda`, keyed by content hash)
- Write partitioned Parquet
- **Round-trip test in CI** — reconstruct source JSON from the tables, assert byte-identical, fail the build otherwise. Already passing 12,000/12,000 in the spike (L-005); it must stay passing on one partition per era
- Compression already proven on a 2025 partition (338× lossless, ~3.4 GB projected — see L-003). M0 re-runs it on a **2005-era** partition, where `openfda` enrichment is expected to be sparser and the ratio worse
- Add the MedDRA exclusion list for reporting artifacts (`Off label use`, `Condition aggravated`, …) before computing anything — see L-004

**Query + one finding** — PLANNED
- DuckDB over the Parquet
- Compute PRR for the top drug–event pairs in the slice
- One chart, one page, published to GitHub Pages

**Exit criteria:** `make all` on a clean machine produces a public URL with a real chart. If this takes more than 24 h, the architecture is wrong — stop and revisit.

---

## M1 — Full Corpus (~36 h)

**Goal:** All 20.7M reports ingested, normalized, and refreshing on a schedule without supervision.

### Features

**Resumable crawler** — PLANNED
- All 1,767 partitions, checkpointed and restartable mid-run
- Respect openFDA politeness; measured throughput was ~11.6 MB/s, so ~2.7 h of pure transfer
- Stream → transform → discard: the 111 GB is never all on disk at once

**Schema drift handling** — PLANNED
- FAERS field layouts have changed since 2004; detect and record every drift event rather than crashing on it
- Drift events become a published data-quality artifact, not a hidden hack

**Scheduled refresh** — PLANNED
- GitHub Actions cron; incremental — only new/changed partitions
- openFDA `download.json` carries an export date; use it as the change signal

**Data-quality metrics** — PLANNED
- Row counts, null rates, drift events, freshness lag — computed every run, stored as a time series

**Exit criteria:** the full corpus rebuilds unattended, and the quality metrics are queryable over time.

---

## M2 — Cleaning & Entity Resolution (~30 h)

**Goal:** Turn "Tylenol / TYLENOL / paracetamol / APAP / Tylenlo" into one drug. This is the milestone that decides whether any downstream number means anything.

### Features

**Drug entity resolution** — PLANNED
- Canonicalize `medicinalproduct` + `activesubstance` against the `openfda` dimension (UNII / RxCUI where present)
- Fall back to normalized string matching for the long tail with no enrichment
- **Publish a measured accuracy rate on a hand-labeled sample** — an unmeasured resolver is worthless

**Report deduplication** — PLANNED
- FAERS carries explicit `duplicate` / `reportduplicate` fields and `safetyreportversion` — use them first
- Then near-duplicate detection on (drug set, reaction set, date, demographics)
- Record how many were removed and why

**Exit criteria:** a documented, measured resolution and dedup rate. Not "it looks better" — a number.

---

## M3 — Signal Detection (~30 h)

**Goal:** Every drug–event pair scored with the methods regulators actually use.

### Features

**Disproportionality engine** — PLANNED
- 2×2 contingency counts for every drug–event pair
- PRR and ROR with confidence intervals
- A Bayesian shrinkage estimator so rare pairs with 2 reports don't outrank real signals

**Reproduce known associations** — PLANNED
- Validate against ≥3 well-documented drug–event pairs from the literature (G2)
- A method that cannot reproduce known results is not ready to claim new ones

**Time-to-onset** — PLANNED
- Weibull fits on drug-start → reaction-onset intervals where dates permit
- Honest reporting of how few reports actually carry usable dates

---

## M4 — The Hindsight Backtest (~30 h)

**Goal:** The headline. Would this system have flagged real safety warnings before they were issued?

### Features

**Ground-truth set** — PLANNED
- **Primary:** FDA SrLC database, filtered to `section=BW` (Boxed Warning) — dated safety *changes*, 2016→present. Export mechanism still unsolved (B-002); 2 h budgeted in M3 to crack it
- **Fallback (verified working):** openFDA `drug/label` — 33,056 labels carrying `boxed_warning`, each with an `effective_time`. Sufficient to run M4 on its own
- FAERS starts 2004 vs. ground truth from 2016 → a 12-year lookback before the first evaluable event, which is close to ideal for a lead-time study

**Point-in-time reconstruction** — PLANNED
- For each ground-truth event, recompute signals using **only** reports received before that date
- No leakage: this is the entire scientific content of the project and the one thing worth being paranoid about

**Lead-time analysis** — PLANNED
- Distribution of how early (or late, or never) each signal crossed threshold
- **Publish the misses and the false positives with equal prominence as the hits**

---

## M5 — Public Artifacts (~18 h)

**Goal:** Ship the two things a stranger can actually use.

### Features

**Dataset release** — PLANNED
- Versioned Parquet on R2 + a data dictionary + a DOI via Zenodo
- One-command reproduction from raw source

**Report site** — PLANNED
- Quarto/Evidence → GitHub Pages, rebuilt by the pipeline
- Pages: the finding · methods · limitations · **self-grading data quality** · the misses
- Limitations page written *before* the results page

**README as trailer** — PLANNED
- The one-sentence pitch, the headline number, the honest caveats, links to everything

---

## Future Considerations

- Drug–drug interaction signals (pairs of drugs, not single drugs)
- Demographic subgroup analysis (the "older women" question)
- Comparison against EU EudraVigilance for cross-registry corroboration
- Recurrent-event modeling of repeat reporters
