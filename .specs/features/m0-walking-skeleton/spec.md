# M0 — Walking Skeleton Specification

**Milestone:** M0 (ROADMAP.md)
**Budget:** ~24 h @ 6 h/week ≈ 4 weeks
**Status:** Approved — ready to execute

---

## Problem Statement

Every layer of the Hindsight pipeline currently exists only on paper. The reconnaissance spike proved that one partition *can* be normalized losslessly, but it did so in a 57-line throwaway script that loads 1.2 GB into memory, hardcodes its input path, and lives in `.specs/`. Nothing is installable, testable, scheduled, or published.

M0 pushes 12,000 reports through every layer of the real architecture and puts one chart on a public URL. Nothing is scaled and nothing is complete — but every link in the chain is proven to exist, and the parts that were guesses become measurements.

## Goals

- [ ] One openFDA partition traverses ingest → normalize → Parquet → DuckDB → chart → public page
- [ ] The round-trip integrity test runs in CI and fails the build on any mismatch
- [ ] `make all` reproduces the whole chain on a clean machine in under 15 minutes
- [ ] Peak RSS during ingestion stays under 500 MB — proving the streaming design, not just claiming it

## Out of Scope

| Excluded | Reason |
|---|---|
| Remote object storage (R2 / HF / B2) | Cloud accounts on the critical path of a walking skeleton. Local `data/` is enough to prove the chain. Deferred to M1 — AD-008 |
| More than 2 partitions | Scale is M1. M0 uses one 2025 partition + one 2005-era partition for the drift check |
| Entity resolution, deduplication | M2. PRR in M0 runs on raw `medicinalproduct` strings and the numbers are labeled provisional |
| Bayesian shrinkage, ROR, confidence intervals | M3. M0 computes plain PRR only |
| Any backtest or point-in-time logic | M4 |
| Scheduled/incremental refresh | M1 |
| Postgres | No mart needs serving yet |
| Interactive charts | AD-004. Static render only |

---

## User Stories

### P1: Reproducible environment ⭐ MVP

**User Story:** As the developer, I want a pinned, installable Python project so that the pipeline runs identically on my laptop and in CI.

**Why P1:** B-003 blocks task 1 of everything else. Nothing can be verified until this exists.

**Acceptance Criteria:**

1. WHEN `uv sync` runs on a clean checkout THEN the system SHALL install all dependencies from a committed lockfile
2. WHEN `python -c "import duckdb, polars, pyarrow"` runs THEN the system SHALL exit 0
3. WHEN the same command runs in GitHub Actions THEN the system SHALL resolve identical versions

**Independent Test:** Fresh clone into a temp dir, `uv sync`, imports succeed.

---

### P2 → P1: Partition acquisition ⭐ MVP

**User Story:** As the pipeline, I want to resolve and fetch a named openFDA partition so that ingestion starts from a pinned, verifiable source rather than a file someone downloaded by hand.

**Why P1:** The pinning principle (AD-008) is load-bearing for the whole reproducibility claim. If M0 starts from a manual download, the claim is false from day one.

**Acceptance Criteria:**

1. WHEN the manifest fetcher runs THEN the system SHALL read `api.fda.gov/download.json` and produce the list of `drug/event` partition URLs with the export date
2. WHEN a partition is requested by id (e.g. `2025q1/0001-of-0028`) THEN the system SHALL download it, compute its SHA-256, and record `{id, url, export_date, sha256, bytes}` in `data/manifest/`
3. WHEN the same partition is requested again and the local file matches the recorded SHA-256 THEN the system SHALL skip the download
4. WHEN the download is interrupted THEN the system SHALL NOT leave a truncated file that a later run treats as complete
5. WHEN the recorded SHA-256 does not match the downloaded bytes THEN the system SHALL fail loudly rather than proceed

**Independent Test:** Run twice; second run reports "cached", network transfer is zero.

---

### P1: Streaming normalization ⭐ MVP

**User Story:** As the pipeline, I want to convert one partition into fact and dimension Parquet without ever holding the full JSON in memory.

**Why P1:** This is the core engineering claim of the project. The spike proved the *transformation*; it did not prove the *streaming*. At 1,767 partitions, a design that needs 1.2 GB of RAM per partition is a design that cannot scale.

**Acceptance Criteria:**

1. WHEN a partition zip is processed THEN the system SHALL yield reports one at a time from inside the zip without extracting it to disk
2. WHEN normalization completes THEN the system SHALL emit four tables: `report`, `report_drug`, `report_reaction`, `dim_openfda`
3. WHEN a drug entry carries an `openfda` block THEN the system SHALL replace it with a SHA-1 content-hash key and store the block once in `dim_openfda`
4. WHEN a drug entry carries `openfda: {}` THEN the system SHALL preserve the distinction from an absent `openfda` — an empty dict is a key, not a null (L-005)
5. WHEN any field appears in the source THEN the system SHALL retain it — no hardcoded keep-list, ever (L-005)
6. WHEN Parquet is written THEN the system SHALL use ZSTD level 9 and partition by year/quarter
7. WHEN the process runs THEN peak RSS SHALL stay below 500 MB

**Independent Test:** Process the 2025q1 partition, observe 4 Parquet files and a memory ceiling well under the 1.2 GB input.

---

### P1: Round-trip integrity test ⭐ MVP

**User Story:** As a skeptical reader, I want proof that the derived corpus is byte-identical to the source so that "lossless" is a test result and not an adjective.

**Why P1:** This test already found two real bugs before any pipeline existed (L-005). It is the single highest-value artifact in M0.

**Acceptance Criteria:**

1. WHEN the round-trip test runs THEN the system SHALL reconstruct the original nested JSON from the four tables and compare it to source, report by report
2. WHEN all reports match THEN the test SHALL pass and print the count compared
3. WHEN any report differs THEN the test SHALL fail and name the differing keys and the `safetyreportid`
4. WHEN the test runs in CI on push THEN the build SHALL fail on mismatch
5. WHEN the test runs THEN it SHALL use a committed fixture of ~100 reports, not the full 246 MB partition — CI must not depend on a 22-second download

**Independent Test:** Corrupt one field in the normalizer, watch CI go red, revert.

---

### P1: One finding ⭐ MVP

**User Story:** As a visitor, I want to see one real disproportionality result computed from the corpus so that the pipeline demonstrably produces analysis, not just files.

**Why P1:** A pipeline that ends at Parquet proves plumbing. The chart is what makes it a data project.

**Acceptance Criteria:**

1. WHEN the analysis runs THEN the system SHALL build a 2×2 contingency table per drug–event pair over the partition
2. WHEN PRR is computed THEN the system SHALL exclude MedDRA reporting artifacts (`Off label use`, `Condition aggravated`, `Intentional product use issue`, …) from a versioned, committed exclusion list (L-004)
3. WHEN results are displayed THEN the system SHALL show the top pairs by PRR with their raw counts alongside
4. WHEN any result is displayed THEN the page SHALL state that it derives from a single partition, has no entity resolution, and makes no causal claim
5. WHEN a pair has fewer than 3 reports THEN the system SHALL exclude it from the chart — with the threshold stated on the page

**Independent Test:** Open the notebook, see the chart, see the caveats.

---

### P1: Public page ⭐ MVP

**User Story:** As a hiring manager, I want a URL I can open so that the project is evaluable without cloning anything.

**Acceptance Criteria:**

1. WHEN the pipeline finishes THEN Quarto SHALL render the analysis notebook to static HTML
2. WHEN a push to `main` succeeds THEN GitHub Actions SHALL publish the rendered site to GitHub Pages
3. WHEN the site is published THEN it SHALL carry the limitations text before the result — not after (project standard #5)

**Independent Test:** Open the Pages URL in a private window.

---

### P2: Era drift check

**User Story:** As the architect, I want the same pipeline run against a 2005-era partition so that the compression and coverage numbers are known to hold across the corpus, not just in 2025.

**Why P2:** The whole storage projection rests on one 2025 partition (STATE.md caveat). If 2005 behaves differently, M1's sizing is wrong — better to learn that now than after a 2.7-hour crawl. Not P1 because the chain is already proven without it.

**Acceptance Criteria:**

1. WHEN a 2005-era partition is processed THEN the system SHALL report its compression ratio and per-table row counts
2. WHEN fields present in 2025 are absent in 2005 THEN the system SHALL record the difference rather than crash
3. WHEN the run completes THEN the measured ratios SHALL be written into STATE.md as a new Lesson

**Independent Test:** Two rows in a comparison table, one per era.

---

### P3: Data-quality snapshot

**User Story:** As the project, I want null rates and row counts emitted as a machine-readable artifact so that M1's quality time series has a schema to grow into.

**Acceptance Criteria:**

1. WHEN normalization completes THEN the system SHALL write `metrics.json` with row counts per table and non-null rates for `drugstartdate`, UNII, and `companynumb`

---

## Edge Cases

- WHEN a partition contains a report with no `patient.drug` array THEN the system SHALL emit the report row with zero drug rows, not skip the report
- WHEN two different `openfda` blocks hash to the same key THEN the system SHALL fail loudly (SHA-1 truncated to 16 hex chars — collision is implausible but silent corruption is unacceptable)
- WHEN a field contains a value whose JSON type differs between reports THEN the system SHALL record a drift event rather than coerce silently
- WHEN `safetyreportid` is duplicated within a partition THEN the system SHALL record the count and keep both — dedup is M2's job, not M0's
- WHEN the openFDA export date changes mid-run THEN the manifest SHALL record the date actually used

---

## Requirement Traceability

| ID | Story | Task | Status |
|---|---|---|---|
| M0-01 | Reproducible environment | T1, T2 | Pending |
| M0-02 | Environment reproduces in CI | T2, T16 | Pending |
| M0-03 | Partition manifest resolution | T4 | Pending |
| M0-04 | Pinned, checksummed download with resume | T5 | Pending |
| M0-05 | Streaming read from inside the zip | T6 | Pending |
| M0-06 | `openfda` dimension by content hash, empty-dict safe | T7 | Pending |
| M0-07 | Fact-table splitting, no keep-list | T8 | Pending |
| M0-08 | Parquet write, ZSTD-9, partitioned | T9 | Pending |
| M0-09 | Round-trip reconstruction | T10 | Pending |
| M0-10 | Round-trip test green in CI on a fixture | T11, T16 | Pending |
| M0-11 | Memory ceiling proven < 500 MB | T6, T18 | Pending |
| M0-12 | MedDRA exclusion list, versioned | T12 | Pending |
| M0-13 | PRR over 2×2 contingency tables | T13 | Pending |
| M0-14 | Chart + caveats in a notebook | T14 | Pending |
| M0-15 | Quarto render | T15 | Pending |
| M0-16 | Published to GitHub Pages | T17 | Pending |
| M0-17 | `make all` on a clean machine | T3, T18 | Pending |
| M0-18 | Era drift check (P2) | T19 | Pending |
| M0-19 | `metrics.json` snapshot (P3) | T9 | Pending |

**Coverage:** 19 requirements, 19 mapped to tasks, 0 unmapped ✅

---

## Success Criteria

- [ ] A public URL shows a chart derived from real FAERS data, with limitations stated above it
- [ ] `make all` on a clean machine produces that site in < 15 min
- [ ] CI is green, and goes red when the normalizer is deliberately broken
- [ ] Peak RSS during ingestion measured and recorded, < 500 MB
- [ ] The 2005-era compression ratio is a measured number in STATE.md, not a projection
- [ ] The distinct-`openfda` count contradiction in L-003 is resolved with a real measurement

**Failure criterion:** if M0 exceeds 24 h, stop and revisit the architecture (ROADMAP exit criteria). Do not push through.
