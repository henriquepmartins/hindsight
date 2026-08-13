# State

**Last Updated:** 2026-08-13
**Current Work:** M0 — Walking Skeleton. T1–T5 done: repo initialized, dependencies pinned, Makefile skeleton, partition resolver, pinned resumable downloader. Next action: **T6** (streaming report iterator).

---

## Recent Decisions

### AD-001: Domain — FDA FAERS adverse events (2026-08-11)

**Decision:** Build a FAERS signal-detection platform. Chosen over five alternatives: ClinicalTrials.gov outcome switching, EU public-procurement cartel screening, ENTSO-E grid data, OpenSky flight tracking, and package-registry supply chain.
**Reason:** It was the only candidate that scored top marks on *both* "the data is genuinely messy" and "you can check whether you're right." The rewind-against-known-warnings backtest gives the project an external ground truth, which almost no portfolio project has.
**Trade-off:** The filthiest data of the six — expect a large share of total effort spent on cleaning (M2). Also refreshes in batches, not continuously.
**Impact:** Entity resolution and deduplication are load-bearing milestones, not chores. If M2 is done badly, M3 and M4 produce confident nonsense.

### AD-002: Source — openFDA JSON, not FAERS quarterly ASCII (2026-08-11)

**Decision:** Primary source is `download.open.fda.gov/drug/event/` (1,767 partitions, 111 GB zipped).
**Reason:** Measured 11.6 MB/s from openFDA's S3 vs. a stalled download from `fis.fda.gov` (13 MB in 180 s before timing out). openFDA is also structured, documented, and carries the `openfda` enrichment block for entity resolution.
**Trade-off:** openFDA is a derived product; the ASCII files are the true primary source. Some FAERS fields may be absent or reshaped.
**Impact:** Verify field coverage in M0. If a needed field is missing, the ASCII files become a supplementary source, not a replacement.

### AD-003: Storage — Parquet on R2 + DuckDB, Postgres for marts only (2026-08-11)

**Decision:** Raw/staged layers as partitioned Parquet on Cloudflare R2 (10 GB free), queried by DuckDB. Only small curated marts go to Postgres.
**Reason:** 111 GB cannot fit any free hosted Postgres (~0.5 GB). Free tiers force the columnar design — which is the correct modern architecture anyway.
**Trade-off:** No always-on SQL server over the full corpus; heavy queries run locally or in CI.
**Impact:** Makes the R$0 constraint an architectural asset rather than a limitation to apologize for.

### AD-004: No web frontend (2026-08-11)

**Decision:** Static generated report site (Quarto/Evidence → GitHub Pages). No Next.js/React app.
**Reason:** In the deleted portfolio, a hand-built frontend was ~40% of the hours for ~0% of the data signal. At 6 h/week that trade is fatal.
**Trade-off:** No interactive filtering UI.
**Impact:** Saves ~50 h. The report becomes a pipeline build artifact, which strengthens the engineering narrative.

### AD-005: No LLM layer (2026-08-11)

**Decision:** No LangChain / text-to-SQL / chat interface.
**Reason:** Text-to-SQL over your own database is the most-cloned project of the last two years and is mostly plumbing.
**Trade-off:** Gives up the "AI" buzzword on the surface.
**Impact:** None on the goals. Statistical rigor is the differentiator here.

### AD-006: No deep learning (2026-08-11)

**Decision:** Bayesian shrinkage + classical survival methods. No neural networks.
**Reason:** On tabular epidemiological data, DL underperforms and signals inexperience. Deliberately *not* using it — and benchmarking to show why — is the stronger move.
**Trade-off:** None material.
**Impact:** Frees effort for the backtest, which is where the actual value is.

### AD-007: Walking skeleton before scale (2026-08-11)

**Decision:** M0 pushes 12,000 reports through every layer before anything is scaled.
**Reason:** Three weeks of crawling with nothing to show is how 6 h/week projects die in month three.
**Trade-off:** Some M0 code gets rewritten at scale.
**Impact:** Something publishable exists by week 4; the full crawl then runs in the background.

### AD-008: No cloud storage in M0; pin, don't hoard (2026-08-13)

**Decision:** M0 writes Parquet to local `data/`. The reproducibility guarantee comes from committed `manifest/` (partition id, URL, export date, SHA-256) + `schema/`, not from archiving raw bytes. Remote object storage moves to M1.
**Reason:** Two problems solved at once. First, a cloud account on the critical path of a walking skeleton is how week 1 becomes week 3. Second, ROADMAP M0 previously said "archive the raw zip to R2 (raw layer is immutable)" while the README committed to "reproducibility by pinning, not by hoarding" — the 111 GB never fits in a 10 GB free tier, and pinning makes hoarding unnecessary.
**Trade-off:** No remote copy until M1. If openFDA rewrites a partition in place, the SHA-256 mismatch detects it but cannot recover the original.
**Impact:** M0 has zero external accounts. AD-003's R2 choice is reopened — see AD-012.

### AD-009: Quarto for the report site (2026-08-13)

**Decision:** Quarto, rendering Jupyter notebooks, → GitHub Pages. Evidence.dev rejected.
**Reason:** Python-native — the notebook runs the DuckDB query and renders the chart in the same process. Evidence would add a Node toolchain and a second language for a site with one chart in it. Closes the open todo.
**Trade-off:** Weaker interactive charting than Evidence.
**Impact:** Notebooks become build artifacts, which means they must run top-to-bottom on a clean kernel.

### AD-010: Every task ships with an executable Verify block (2026-08-13)

**Decision:** Tasks are cut small enough to finish in one sitting, and each one carries a **Verify** block: a concrete command with an expected result, run before the task is called done. A task without a runnable check is not a task.
**Reason:** "Done" is otherwise a feeling. The verify block is also what makes a spec falsifiable — T4's block is what surfaced that openFDA had re-chunked 2025q1 (L-006), a full milestone before T9 would have tripped over it.
**Trade-off:** More up-front work per task, and a longer tasks.md. M0 is budgeted at 24 h partly because of this.
**Impact:** Task granularity is tighter than it would otherwise be, so each task stays reviewable in one sitting.

### AD-011: Explicit schema, never inferred from a sample (2026-08-13)

**Decision:** Two-pass ingestion. Pass 1 computes the union of every field across **all** records into a `pyarrow.Schema` written to `schema/<partition>.json`; pass 2 writes Parquet against that frozen schema. Rejected: streaming to NDJSON and letting DuckDB infer types on the way to Parquet.
**Reason:** Every bug in L-005 came from one habit — deriving a schema from a sample. DuckDB's `read_json_auto` samples rows by default; a flag forces a full scan, but a design where losing a field means forgetting a keyword argument invites the same bug back. Two passes make the failure mode structural instead of optional.
**Trade-off:** ~40 extra lines and a second read of the zip (a few seconds, cached after first run).
**Impact:** The schema file is exactly what M1's drift detection needs — drift becomes a diff between two committed files rather than a mechanism invented later. T19 prototypes it by hand.

### AD-012: Remote storage front-runner is Hugging Face Datasets (2026-08-13, provisional)

**Decision:** When M1 needs remote storage, evaluate Hugging Face Datasets first, R2 second, B2 third. Not final — revisit at M1.
**Reason:** The corpus is public by design and ~3.4 GB. HF gives free public-repo storage, DuckDB reads `hf://datasets/…/**/*.parquet` natively, and it doubles as M5's public dataset release — one account covers the lake and the artifact. R2's free tier is 10 GB with zero egress but wants a card on file; B2 is 10 GB with egress free to 3× storage.
**Trade-off:** HF is git+LFS, not an S3 API. A scheduled incremental pipeline means many commits, and history needs occasional squashing. HF public storage is "best-effort" and conditioned on the dataset being genuinely reusable.
**Impact:** Partially supersedes AD-003's R2 choice for the lake layer. AD-003's core reasoning — columnar not Postgres — is unaffected.

---

## Active Blockers

### ~~B-001: Parquet compression ratio is estimated, not measured~~ — RESOLVED 2026-08-11

**Resolution:** Measured end-to-end on a real partition. **1.2 GB JSON → 3.55 MB Parquet (338×).** Full-corpus projection: **~3.4 GB.** See L-003. Storage is no longer a constraint on this project.

> A lossy column-pruned variant reached 1.41 MB/partition (852×, ~2.4 GB projected). **That variant is rejected** — it drops fields M2 depends on (L-005). If you see 852× or 2.4 GB anywhere, it is the superseded number.

### B-002: Ground truth for the backtest — DOWNGRADED 2026-08-11, not eliminated

**Discovered:** 2026-08-11
**Impact:** M4 is the headline milestone and depends on a dated list of real FDA safety actions. Was the project's biggest risk. Now bounded.

**What was verified today:**

- **openFDA `drug/label` works and is the safe fallback.** 261,646 labels, `last_updated` 2026-08-11, **33,056 carry a `boxed_warning`**, and every record has an `effective_time` date. That is drug → serious safety warning → date, fully machine-readable, available right now. Confirmed by direct API call.
- **FDA SrLC database exists and is the better source.** Public, covers **January 2016 → present**, and — critically — is indexed by *section changed*, including **`BW` = Boxed Warning**, plus Contraindications, Warnings & Precautions, Adverse Reactions, Drug Interactions. That is precisely the ground-truth shape M4 needs. Search form found at `accessdata.fda.gov/scripts/cder/safetylabelingchanges/` with `date_range_from` / `date_range_to` / `section` parameters.

**Open sub-problem:** SrLC is a session-based ColdFusion app. POSTing the search form returns a 302 into a session-rendered page, and naive cookie-jar replay returned the unfiltered index. FDA documentation states the data can be downloaded — that mechanism has **not** been located (~15 min spent, time-boxed).

**Workaround:** openFDA `drug/label` boxed warnings alone are sufficient to run M4. SrLC would make it sharper (dated *changes* rather than current state), not possible-vs-impossible.

**Resolution:** Budget 2 h in M3 to either find the SrLC export or drive the form properly. If both fail, M4 runs on openFDA boxed warnings + a hand-curated set of 20–30 landmark cases, with the coverage limitation stated plainly in the report.

**Consequence for M4 scope:** SrLC starting in 2016 is not a real constraint — FAERS runs from 2004, giving a 12-year lookback before the first evaluable event. That is close to the ideal shape for a lead-time study.

### ~~B-003: `pyarrow` / `duckdb` not installed locally~~ — RESOLVED 2026-08-13

**Resolution:** Closed by **T2**. Pinned in `uv.lock` and verified from a clean clone with `uv sync --frozen`: Python 3.12.12 · duckdb 1.5.5 · pyarrow 25.0.1 · ijson 3.5.1 · httpx 0.28.1 · pytest 9.1.1 (dev group). `polars` deliberately omitted (design.md).

---

## Lessons Learned

### L-001: The 111 GB is 93% one repeated lookup block

**Context:** Sizing the corpus for a R$0 budget. openFDA reports 1,767 partitions totaling 111 GB zipped, which looked disqualifying.
**Problem:** One partition holds only 12,000 reports in 1.2 GB of JSON — ~100 KB per report, which made no sense for what is essentially a list of drugs and symptoms.
**Solution:** Measured it directly: the `openfda` enrichment block (brand names, NDC codes, pharm classes, UNII, SPL ids) accounts for **641 MB of a 692 MB** payload — 92.7%. It is a lookup table that has been denormalized into all 103,187 drug rows per partition.
**Prevents:** Rejecting the project on storage grounds, and the much worse error of loading it as-is. Normalizing this into a dimension table is both the thing that makes R$0 possible **and** the most concrete data-engineering result the project has: a ~2 TB raw dataset reduced to single-digit GB with zero information loss.

### L-005: "Lossless" is a claim that must be tested, and the test found two real bugs

**Context:** After reporting an 852× reduction, the obvious challenge came back: *are we losing data?*
**Problem:** The first spike **was** lossy — not from compression, but because it selected columns from a hardcoded keep-list built by inspecting `results[0]`. That sample missed `companynumb` (89.6% of reports), `patient.summary` (49.1%), and dropped `reportduplicate` and `primarysource` — the first is required by M2's dedup feature and the second carries reporter qualification (physician vs. consumer), which weights signal strength.
**Solution:** Rewrote it to keep **every** field, deduplicating `openfda` by SHA-1 content hash rather than by a chosen key. Then wrote a round-trip test: reconstruct the original nested JSON from the normalized tables and compare, report by report.

Round 1: **6,108 / 12,000 mismatched.** Round 2 after fixing reconstruction: **492 mismatched.** Those 492 traced to a one-character class of bug — `k = hash(o) if o else None` treats an empty dict `openfda: {}` as absent, erasing the distinction between *"we checked and found no enrichment"* and *"the field wasn't there."* 550 drug entries across exactly 492 reports. Fixed with `if o is not None`.

Round 3: **12,000 / 12,000 byte-identical. Zero mismatches.**

**Prevents:** shipping a corpus that silently differs from the source. A compression ratio means nothing without a round-trip test, and *sampling one record to infer a schema is not schema inference* — it is a guess that happens to typecheck. The round-trip test belongs in CI from M0 onward, running on one partition per era.

### L-003: The whole corpus fits in ~3.4 GB, and the pipeline never needs more than ~1.5 GB of disk

**Context:** 111 GB of source data vs. a laptop with 50 GB free.
**Problem:** The project looked disk-bound.
**Solution:** Ran the spike ([`spike-flatten.py`](spike-flatten.py)) on one real partition: strip `openfda` into a shared dimension, flatten to three fact tables, write Parquet with ZSTD-9.

| stage | size |
|---|---|
| source zip | 246 MB |
| raw JSON | 1,200 MB |
| NDJSON after normalization | 65.5 MB |
| **Parquet (ZSTD-9), lossless** | **3.55 MB** |

**338× smaller than the JSON, 69× smaller than the zip — with every field retained** (see L-005 for the proof). Breakdown for 12,000 reports: report 0.49 MB · drug 1.19 MB (103,187 rows) · reaction 0.21 MB (57,664 rows) · openfda dimension 1.66 MB (2,537 distinct blocks).

**Projected full corpus: ~3.4 GB.** Facts scale linearly (~3.2 GB); the `openfda` dimension does **not** — the same drugs recur in every partition, so it converges rather than multiplying. A lossy column-pruned variant reached 1.41 MB/partition (~2.4 GB), but the ~1 GB saved is not worth the fields lost.

Compression is this extreme because nearly every column is low-cardinality and dictionary-encodes to almost nothing: only 4,721 distinct MedDRA terms across 57,664 reactions, dates repeat heavily within a quarter, and the `openfda` block (92.7% of bytes) collapses from 103,187 inline copies to a few thousand dimension rows.

> ⚠️ **Unresolved:** the distinct-`openfda` count was recorded twice with different values (2,537 above vs. 1,491 originally here). The spike output was not saved, so neither is trustworthy. **M0-11 re-measures it** and this note gets replaced with the number. Everything else in L-003 was recorded once and stands.

**Verified not to be silent data loss:** row counts match the source exactly (12,000 / 103,187), all 21+15+5 columns survive, and a join+group-by across the full partition returns 322,185 distinct drug–event pairs in **0.048s**.

**Prevents:** designing around a storage problem that does not exist. Peak transient disk during ingestion is ~1.5 GB (zip + unzipped JSON), and streaming directly from the zip would cut that to ~250 MB.

### L-004: Two field-coverage facts that constrain later milestones

**Context:** Measured non-null rates while validating the spike.
**Problem:** Two numbers change milestone scope and were about to be assumed rather than checked.
**Solution:**
- **`drugstartdate` is present on only 20.5% of drug rows.** M3's time-to-onset analysis can therefore only ever run on a fifth of the data. This must be stated openly in the report, not buried.
- **UNII is present on 83.3% of drug rows.** So ~17% of drugs have no canonical identifier and need string-based resolution — that fraction *is* M2's actual workload, now quantified.
- Top drug–event pairs are dominated by `Off label use`, `Condition aggravated`, `Intentional product use issue` — these are **reporting artifacts, not adverse reactions.** A MedDRA term exclusion list is required before any signal detection, or the results will be nonsense.

**Prevents:** promising a time-to-onset analysis that the data cannot support, under-scoping entity resolution, and publishing "signals" that are just reporting categories.

### L-006: openFDA re-chunks quarters between exports — a pinned URL can vanish, not just change

**Context:** T4 resolves a partition id against `api.fda.gov/download.json`. The id used throughout these specs — `2025q1/0001-of-0034` — came from the reconnaissance spike on 2026-08-11.

**Problem:** It does not resolve. In the export dated 2026-08-10, **2025q1 contains 28 partitions, not 34**, and no partition anywhere in the manifest exceeds 217 MB — so the spike's `246 MB zip → 12,000 reports → 103,187 drug rows → 3.55 MB Parquet` was measured on a file that today's manifest does not contain.

**Solution:** Two things, neither of which is "pick a new id and move on."

1. `resolve()` fails loudly on a stale id and reports what the bucket actually holds — `'2025q1' has 28 partitions (0001-of-0028 .. 0028-of-0028)` — because the common cause of a miss is re-chunking, not a typo.
2. The per-partition numbers in L-003 are demoted from acceptance criteria to **prior expectations**. T9 re-measures and records; it does not assert equality against a vanished file.

**What this costs AD-008.** The "pin, don't hoard" guarantee assumed the worst case was openFDA *rewriting a partition in place*, which a SHA-256 mismatch detects. Re-chunking is worse: the URL 404s and the bytes are gone, so a pin can become unresolvable rather than merely stale. Corpus-level reproducibility survives — 1,767 partitions, 111.0 GiB, and the per-partition record counts still sum to exactly 20,692,690 — but **partition-level reproducibility across exports does not.** The manifest must therefore pin the `export_date` alongside the URL, and any claim of byte-identical re-fetch is only valid *within* a single export.

**Also corrected:** design.md's open question said openFDA starts at 2004q3. It starts at **2004q1** — 91 buckets, including a non-quarter `all_other/` bucket of 4 partitions for reports that could not be dated. A partition-id pattern requiring `YYYYqN` silently drops those four.

**Prevents:** building M1's crawler on the assumption that a partition URL is a stable identity, and publishing a compression ratio traceable to a file nobody can fetch again.

### L-002: Always measure before believing a size number

**Context:** Two sizing assumptions were wrong on inspection — the FAERS ASCII files (assumed fast, actually stalled) and the JSON corpus (assumed dense, actually 93% redundant).
**Problem:** Both would have propagated into the architecture unchallenged.
**Solution:** Probe the actual endpoints and measure the actual bytes before writing the design.
**Prevents:** An architecture built on plausible-sounding numbers nobody checked.

---

## Verified Facts (as of 2026-08-11)

| Fact | Value | How verified |
|---|---|---|
| Total reports | 20,692,690 | `api.fda.gov/drug/event.json` meta |
| openFDA last updated | 2026-07-30 | same |
| Bulk export date | 2026-08-10 | `api.fda.gov/download.json` |
| Partitions | 1,767 files, 111 GB zipped | download manifest, summed |
| Reports per partition | 12,000 | parsed one partition |
| Drug rows per partition | 103,187 | same (~8.6 drugs/report) |
| `openfda` block share | 92.7% of JSON bytes | measured on one partition |
| openFDA throughput | 11.6 MB/s (246 MB in 22 s) | timed download |
| `fis.fda.gov` throughput | stalled (~13 MB in 180 s) | timed download |
| Size by era | 2015+ = 90.7 GB · 2020+ = 62.5 GB | manifest, grouped by year |
| `2025q1/0001-of-0028` | 162,319,793 bytes, sha256 `efe6edcc60e2…` | T5, downloaded and pinned 2026-08-13 |
| Manifest `size_mb` is **MiB** | 162,319,793 B vs a stated `154.80` | T5, same download |
| openFDA throughput, re-measured | 11.5 MB/s (162 MB in 14.1 s) | T5, `time hindsight fetch` |

> ⚠️ Caveat, hardened by **L-006**: per-partition figures come from one partition, `2025q1/drug-event-0001-of-0034` — **which no longer exists.** The 2026-08-10 export chunks 2025q1 into 28 files, not 34. These figures are prior expectations, not reproducible measurements; T9 re-measures against `2025q1/0001-of-0028`. The corpus-level rows above (1,767 partitions, 111 GiB, 20,692,690 records) were re-verified against the manifest on 2026-08-13 and hold exactly.

---

## Deferred Ideas

- [ ] Drug–drug interaction signals (2-drug contingency tables) — Captured during: scoping
- [ ] Demographic subgroup analysis — Captured during: scoping
- [ ] Cross-check against EU EudraVigilance — Captured during: scoping
- [ ] Recurrent-event modeling of repeat reporters — Captured during: scoping

---

## Todos

- [ ] Verify B-002 ground-truth source before M2 completes — highest-risk unknown
- [ ] Confirm openFDA field coverage vs. FAERS ASCII — **moved to M1** (AD-002). M0 does not need it
- [ ] Decide the Bayesian shrinkage estimator (BCPNN vs. gamma-Poisson) once M3 begins
- [x] ~~Choose Quarto vs. Evidence.dev~~ — Quarto, AD-009
- [ ] Confirm remote storage target at M1 start (AD-012 — HF Datasets front-runner)
- [ ] Record the distinct-`openfda` count during T9 and delete the ⚠️ note in L-003
- [ ] Add `ijson` to PROJECT.md's key dependencies — required by the streaming design, currently missing

---
