# State

**Last Updated:** 2026-08-13
**Current Work:** M0 — Walking Skeleton. T1–T12 done: repo initialized, dependencies pinned, Makefile skeleton, partition resolver, pinned resumable downloader, streaming report iterator, openfda dimension writer, record splitter, schema inference + Parquet sink, round-trip reconstructor, round-trip test, MedDRA exclusion list. **AD-013 is decided** — five tables, and a null `seq` on `report_duplicate` means the source carried a bare object. **The round trip closes and is now defended: 12,000 / 12,000 byte-identical, plus 13 tests over a committed 100-report fixture that CI can run without the partition.** Phase 3, the core of M0, is finished, and T12 curated 187 exclusion terms that clear the top of the ranking — what surfaces underneath is infliximab → sepsis, a real anti-TNF warning. **T12 also found the trap T13 walks into: one report carries 2,321 drug rows, and the naive join inflates the pair counts 2.2× (L-009).** T13 is written: PRR and χ² over a 2×2 of **distinct reports**, Evans as the screening criterion (AD-014), 0.13 s over the partition. **Its eye-check failed, and the failure is the milestone's finding — the top of the table is nine near-duplicate reports of one Canadian patient on ~90 drugs, and neither `drugcharacterization` nor Evans removes it (L-010).** T13 is committed. Next action: **T14**, reshaped by **AD-015 and AD-016** — three numbered notebooks recording the analyses that actually ran, plus one ~350-word report at `reports/m0.qmd` that publishes the duplicate cluster as M0's result rather than the ranking.

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

### AD-013: `reportduplicate` becomes a fifth table (2026-08-13) — ACCEPTED

**Decision:** `reportduplicate` leaves the report row and becomes `report_duplicate(safetyreportid, seq, duplicatenumb, duplicatesource)`. A `seq` of `NULL` records that the source carried a bare object rather than an array. Five tables, not four.

**Reason:** it is not a single nested object, which is what design.md assumed when it listed `reportduplicate` among the structs. It arrives **both** ways — 1,857 bare objects and 1,096 arrays in one partition (L-007) — and Arrow holds one type per column, so the four-table model has no column that can hold it. It is a repeated child, exactly like `drug` and `reaction`, and those already get a table with a `seq`.

**Trade-off:** the round trip has one more table to reassemble, and `seq IS NULL` is a contract T10 has to honour rather than infer. Against that, `duplicatenumb` is the field M2's deduplication joins on, so a table is where it wants to be anyway — a repeated child kept in a column is something every later query has to unnest first.

**Alternatives rejected:**
- *Promote every bare object to a one-element list.* Cheapest, and it silently rewrites the source's shape. The round trip would then only be identical after an undeclared normalization, which is precisely the claim this project is not willing to soften.
- *Declare "one row means it was an object" and store no marker.* Reproduces this partition exactly, because openFDA never emits an array of one — measured. It rests on a rule nobody guarantees, over a corpus spanning 2004–2025 of which one export has been read.
- *Two columns, a struct and a list.* Lossless, and it publishes the source's XML-to-JSON artifact as permanent schema, with every M2 query having to read both.

**Impact:** implemented in T9, decided 2026-08-13, and only then written into the specs — `design.md` §Data contracts and `spec.md` P1 §2 now say five tables. The order matters more than the edit: the two lines sat wrong for a whole task rather than being quietly corrected to match code that already ran, which is the difference between an acceptance criterion and a transcript of the implementation.

The null `seq` is now stated in design.md as a contract rather than left as a property of the code. T10 reads that null to decide whether to rebuild an object or a list, so a reader who does not know the rule cannot check the round-trip claim — and an unverifiable lossless claim is the one thing this project cannot ship. T10 and T11 are unblocked.

### AD-014: PRR ships with the Evans criterion, and with the fact that it is not enough (2026-08-13)

**Decision:** `top_pairs` returns χ² beside PRR and flags a pair as a signal on **Evans et al. 2001** — PRR ≥ 2 **and** χ² ≥ 4 **and** a ≥ 3, all three. χ² uses Yates' continuity correction. `signals_only` narrows the table to flagged pairs; the default returns everything, ranked by PRR.

**Reason:** PRR alone is not a screening rule anywhere in the literature, and shipping the ratio without the criterion it is always quoted with invites the reader to treat a high ratio as a finding. The three conditions cover each other: PRR alone flags every rare pair, χ² alone flags every common one, and the minimum count keeps arithmetic off two reports.

**Trade-off:** it is more than T13's spec lists, and it borders M3. It is not shrinkage — no prior, no borrowing across pairs — so AD-006 and M3's scope are untouched.

**Impact, and the part that matters:** **it does not clean this partition.** 24,299 of 28,540 pairs pass, and every implausible pair at the top clears it comfortably — χ² is large *because* the expected count is 0.015 (L-010). The criterion is shipped with that measurement attached rather than as a quality gate it cannot be. A reader who sees `signal = yes` on nail fungus and buprenorphine should conclude the input is wrong, not that the threshold is.

### AD-015: matplotlib + seaborn, in a `viz` group the pipeline does not depend on (2026-08-14)

**Decision:** charts are matplotlib with seaborn's `darkgrid` theme, declared in a `viz` dependency group rather than in `dependencies`. Plotly, Recharts and matplotlib-alone were considered and rejected.

**Reason:** the same argument that chose Quarto in AD-009 — the notebook runs the DuckDB query and draws the chart in one process, and matplotlib is the only candidate native to that process. Recharts is React, which AD-004 already excluded and which would reintroduce the Node toolchain AD-009 rejected Evidence.dev to avoid. Plotly renders under Quarto but embeds ~3 MB of JavaScript per page to buy interactivity nothing on this site needs, and its tooltips are unreadable in the print-and-greyscale test the palette rule below is held to. matplotlib alone would work — `darkgrid` is five lines of `rcParams` — but seaborn ships calibrated palettes, and palette selection is the part most likely to be got wrong by someone reasoning from first principles about colour.

**Trade-off:** four packages the pipeline never imports (matplotlib, seaborn, jupyter, ipykernel). Keeping them in a group rather than in `dependencies` is what stops CI from paying for them: T16 runs `pytest` and touches no chart, so only the render workflow installs the group.

**Impact:** `uv sync` no longer installs everything by default. The Makefile and both workflows have to say which groups they want, which is a one-line cost that also makes the split legible.

### AD-016: notebooks and the report are different artifacts with different rules (2026-08-14)

**Decision:** a milestone produces **three or more numbered notebooks** in `notebooks/`, one per analysis that actually happened, and **one report** in `reports/<milestone>.qmd` that is the site page. The notebooks keep their outputs, stay in the repo, and are never rendered to the site. The report is held to a hard word budget and a fixed set of rules:

- **~350 words of prose**, allocated 40 (problem and objective) · 90 (data) · 100 (analysis) · 120 (result). Fewer words, never fewer ideas.
- **Headings assert something.** "The top of the table is one patient counted nine times", not "Results". A reader skims headings before deciding to read the body, so a heading spent on a template label is the most valuable line on the page wasted.
- **Limitations close the analysis section**, immediately before the result.
- **One chart.** Colour encodes exactly one variable, and the palette is Okabe-Ito — `#0072B2` for the body of the data, `#D55E00` for the accent, `#3C3C3C` for text. Those two hues sit at roughly 40% and 48% grey, so colour alone fails in greyscale: the accent carries opacity and marker size as well, and the difference survives as density rather than hue.
- **Plotting code lives in the document, not in a module.** Calculation lives in a module with tests. The plotting is the only code in this project whose audience is the site's reader rather than the repo's reviewer, so it is written to be read: no helper function, no loop, no branch.

**Reason:** the two artifacts have different readers and the same file cannot serve both. A notebook is a record — verbose, with the outputs attached, read by someone who already decided to look. The report is read by someone deciding whether to look at all, and every rule above is a defence of that reader's attention.

The narrative arc — problem, objective, data, model, optimisation, analysis, result — runs **across milestones, not inside each document**. M0 is the data-assembly-and-first-analysis chapter and has no model, because AD-007 put the modelling in M3. This is what stops each milestone's page from being the same template filled in five times, and it is why M0's report does not manufacture a modelling section it has nothing to put in.

**Trade-off:** the word budget will hurt. The round trip alone has more to say than 90 words, and the honest 12,000-word version of this page would be read by nobody.

**Alternatives rejected:**
- *One notebook per milestone, doing everything* — the format cannot hold both readers, and it is the layout the Cookiecutter convention exists to move away from.
- *Notebooks numbered to match the arc, inventing the ones that did not happen* — it has the shape of an exploration workflow without the content. M0's exploration happened in T4–T13, in modules with tests, and the three notebooks are the three analyses that genuinely ran.
- *Rendering the notebooks to the site alongside the report* — three raw notebooks beside the page would compete with it for the attention it needs undivided, and would put a 155 MB partition on CI's critical path.

**Impact:** design.md's tree changes, T14 splits into notebooks plus a report, T15 fixes the site to a light theme (seaborn's `darkgrid` panel is `#EAEAF2` and needs a light page around it) with per-milestone navigation from the start, and T17 renders the report from a committed CSV rather than from `data/parquet/`. M1 onward inherits all of it without relitigating.

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

> ✅ **Resolved by T7, closed by T9:** the distinct-`openfda` count is **2,251** for `2025q1/0001-of-0028`, measured by running `OpenfdaDimension` over all 12,000 reports. Neither recorded value was right (2,537 above, 1,491 originally here), which is what the missing spike output already implied. The partition holds 71,990 drug rows and 44,916 reaction rows against L-003's 103,187 / 57,664 — a different partition, not a regression.
>
> **The 338× does not reproduce either: T9 measures 175×** (4.62 MB, ZSTD-9, lossless). Not an order of magnitude, so nothing here says the pipeline is wrong, and the gap is now accounted for rather than waved at. Row-group size explains ~12% of it (4.06 MB in one group, 199×) and `dim_openfda` is 55% of what remains — 2.53 MB for 2,251 blocks, which are lists of brand names, NDC codes and SPL ids that dictionary-encode badly because they genuinely do not repeat. The rest is the dead partition: it held 43% more drug rows and 1.2 GB of JSON against this one's 807 MB, so its ratio was taken on a different, denser file. **Publish 175×, not 338×.** The corpus projection barely moves, because the two halves scale differently: the fact tables are 2.09 MB of the 4.62 and scale linearly (~3.7 GB over 1,767 partitions), while `dim_openfda` converges — the same products recur in every quarter, so it is a fixed cost paid once, not 2.53 MB × 1,767. L-003's ~3.4 GB is still the right order of magnitude. One partition has been measured; T19 is the second.

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

### L-007: openFDA serializes a repeated child two different ways, and only one field does it

**Context:** T9's pass 1 unifies the type of every field over all 12,000 records. It failed on the first partition, three seconds in.

**Problem:** `report.reportduplicate` is an object in 1,857 reports and an array in 1,096. Arrow holds one type per column, so there is no schema that can hold both — and design.md had listed the field among the nested single objects, alongside `primarysource` and `sender`.

**Solution:** measured the whole surface before deciding anything. Over the partition: **120 distinct field paths, exactly one with more than one JSON type.** The shape is not random — `reportduplicate` is an array only when there are 2+ entries, and **never once an array of length 1** across all 1,096. That is the signature of an XML-to-JSON conversion: FAERS is ICH E2B XML, a repeated element that occurs once has no array to be in, and the converter emits a bare object. So the field is a repeated child that looks like a struct, and it becomes a table (AD-013).

Two more facts fell out of the same pass: `patient.drug` and `patient.reaction` are present, as arrays, in **12,000 of 12,000** reports, and **no array anywhere in the partition is empty**. An empty array would be indistinguishable from an absent field under the current model, since both produce zero child rows — a real hole, and one nothing in this export can trigger. T11 is where it would surface.

**Prevents:** a schema conflict at partition 900 of a 1,767-partition crawl, and the two shortcuts that were available here. Promoting the bare object to a one-element list would have cost nothing today and made "byte-identical" mean "identical after a normalization we did not mention". Deriving the shape from the row count would have worked on every partition of this export and on no partition anyone has checked.

### L-008: The normalization that makes the round trip pass is the one place it could lie

**Context:** T10 rebuilds a report from Parquet and compares it to the source. Parquet has no absent column — a report with no `companynumb` comes back as `{"companynumb": None}` where the source had no such key — so both sides are stripped of nulls before comparing. The spike did this too, in a helper called `sn()`, and the task asked to keep it and document why it is legitimate.

**Problem:** documenting it is not enough, and the reason is uncomfortable. Stripping nulls is an inverse of what Parquet did **only if the source never carries an explicit JSON null.** If it ever does, the strip erases a real value on both sides, the two sides agree, and the test passes. That is not a small bug: it is the test built to catch silent data loss becoming the mechanism that hides it — and it would hide it behind a `12000/12000` that reads exactly like a proof.

Every other check in this pipeline can be wrong and something downstream notices. This one is load-bearing for the project's central claim, and it is self-certifying.

**Solution:** measure the condition instead of asserting it. Walked every value at every depth of all 12,000 reports: **0 explicit nulls.** So the normalization is an inverse here, provably, and the comparison means what it says.

The measurement does not transfer. Whether an export carries explicit nulls is a property of that export, not of Parquet or of JSON, and one export of 91 buckets has been read. T11 asserts it per partition rather than inheriting T10's number, which costs one pass and turns an inherited assumption into a check that travels with the corpus.

**Prevents:** a round-trip test that is green because it compares two documents after deleting the difference. Also the general shape of it, which is worth more than the instance: any normalization applied to *both* sides of an equality test can only ever make it pass, so the justification has to be measured on the data and not argued from the format.

### L-009: One report can carry 2,321 drug rows, and a naive join turns that into the ranking

**Context:** T12 checked the exclusion list the only way that means anything — ranking the top drug–event pairs with the list applied and without it. The list worked: `Off label use` and `Product use in unapproved indication` left the top, and infliximab → sepsis and streptococcal infection surfaced underneath, which is a real anti-TNF boxed warning and a good omen for M4.

**Problem:** the pair counts were bigger than the terms that fed them. `INFLIXIMAB × Sepsis` counted 862, and `Sepsis` appears on 74 reports in the entire partition. A count cannot exceed its own inputs, so either the ranking was wrong or the normalization was.

**Solution:** measured, then checked the measurement against the source rather than against the Parquet. Report `24942430` lists **2,321 drug entries against 8 reactions** — 862 of them `INFLIXIMAB`, and only 212 distinct drug objects among all 2,321. Confirmed by re-reading the report out of the source zip: it is real data, an aggregate literature report, not a bug in T8's splitter. The byte-identical round trip already implied that — a splitter that invented rows would have reconstructed 862 entries where the source had one — but the claim was worth spending one query on rather than inferring.

Over the partition the naive join produces **882,585 rows against 405,230 distinct `(report, drug, event)` triples — 2.2× inflation**, and **2.1% of every joined row in the partition comes from that single report.** 40 reports of 12,000 carry more than 100 drug rows.

**What this costs T13.** design.md sketches the analysis as `FROM report_drug d JOIN report_reaction r USING (safetyreportid)` and labels itself "shape only; you write the real one in T13" — this is the part that has to change. A 2×2 built by counting joined rows ranks products by how many times a reporter repeated the product name inside one report, not by how often a drug and an event occur together. **The cells count distinct `safetyreportid`.** The inflation does not cancel out of the ratio either: it is concentrated on whichever drugs happen to appear in aggregate reports, so it moves the numerator and the denominator by different factors.

**Prevents:** a headline PRR table that is a ranking of verbose reporters. At 1,767 partitions the 0.33% of reports carrying more than 100 drug rows projects to roughly **69,000 such reports** across 20.7M — far too many to treat as outliers to notice later, and they are exactly the reports M2's deduplication will also have to survive.

### L-010: The top of the PRR table is one patient, counted nine times

**Context:** T13's acceptance criterion says to read the top of the table by eye, because "an implausible #1 usually means the marginals are wrong". The #1 was `DESOGESTREL\ETHINYL ESTRADIOL × X-ray abnormal` at PRR 9,596, followed by `Onychomycosis` — nail fungus — on a buprenorphine patch, an injectable gold salt and a C1-esterase inhibitor. Nothing about that is pharmacology.

**Problem:** the marginals were not wrong. Recomputing `BUTRANS × Onychomycosis` by hand gives a=9, b=9, c=1, d=11,981, summing to exactly 12,000, and the module agrees to the digit. The query is right and the answer is still nonsense, which is the harder version of this failure.

**Solution:** followed the pairs back to the reports. Nine reports carry `Onychomycosis`, and each of them lists **66–96 distinct drugs**. All nine are Canadian, all `serious=1`, eight of the nine record a patient age of 40, and they were received between January and March 2025. They were filed by **six different manufacturers** — Purdue, JNJ, Sandoz, Biocon, BEH. Two share the identical `companynumb` `CA-SANDOZ-SDZ2024CA107730` **and an identical ten-term reaction list**: the same case, filed twice. Across all nine, 19 drugs are common to every report and the pairwise drug-list Jaccard runs 0.38 / 0.48 median / 0.91. They carry 41 `report_duplicate` entries between them.

So it is one patient — or a very small number — on a long medication list, reported independently by every manufacturer whose product was on that list. Every drug in the list gets a=9 against every event in it. That is the entire top of the table.

**Two fixes that look obvious and are not:**

- **Restrict to suspect drugs.** `drugcharacterization` distinguishes suspect (42,665 rows), concomitant (28,554) and interacting (771), and disproportionality is conventionally run on suspect drugs only. It does nothing here: in these nine reports **every one of the ~90 drugs is marked suspect**. Measured before it was believed, which is the only reason it did not get shipped as a fix.
- **Apply the screening criterion.** Evans (AD-014) keeps **24,299 of 28,540 pairs — 85%** — and every pair named above clears it comfortably. χ² is *large* precisely because the expected count is 0.015, so PRR and χ² agree enthusiastically about the same bad input. A threshold cannot tell a duplicate from a signal; both statistics are functions of a, and a is what is wrong.

**Prevents:** publishing a signal table as a finding. It also converts AD-001's claim — that entity resolution and deduplication are load-bearing milestones rather than chores — from an assertion into a measurement, which is what M0 is for. At 1,767 partitions this is not one bad cluster to route around: 40 reports per 12,000 carry more than 100 drug rows (L-009), roughly 69,000 across the corpus, and each one manufactures pairs across its whole medication list. **M2 is the fix, and until M2 exists every number in this table is provisional in the strong sense — not "approximate", but "attributable to the wrong drug".**

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
| Uncompressed partition JSON | 807,482,752 B — **not the 1.2 GB** design.md assumed. Zip ratio 4.98× | T6, `ZipFile.infolist()` |
| Reports per partition, re-measured | 12,000, on a partition that still exists | T6, streamed and counted against `Partition.records` |
| Peak RSS, full streaming pass | **47.7 MB** (ceiling 500 MB, design.md predicted < 200 MB) | T6, `/usr/bin/time -l` |
| Full-partition parse time | 2.1 s for 12,000 reports; first report in 2.8 ms | T6, same run |
| Every FAERS scalar is a string | 19,648,458 scalars in the partition, zero non-`str` | T6, walked every value |
| Smallest partition in the export | 324 records (`2024q4/0029-of-0029`); none report zero | T6, manifest, all 1,767 |
| Distinct `openfda` blocks | **2,251** in one partition, settling 2,537-vs-1,491 | T7, `OpenfdaDimension` over 12,000 reports |
| `openfda` dedup ratio | 27.0× — 60,862 blocks on drug rows collapse to 2,251 | T7, same run |
| Drug rows per partition, re-measured | 71,990 (L-003's 103,187 came from the dead partition) | T7, same run |
| `openfda: {}` present but empty | **507 drug rows** — absent is 11,128, and they are not the same | T7, same run |
| Reaction rows per partition | **44,916** — L-003's 57,664 came from the dead partition | T8, `split` over all 12,000 |
| Fields lost by `split` | **0** of 12,000 reports, compared key by key at every level | T8, same run |
| Report row width | 32 columns — 26 top-level (27 less `patient`) + 6 `pt_` | T8, same run |
| Top-level names starting `pt_` | **none** of 27, so the prefix collides with nothing today | T8, same run |
| **Parquet, whole partition, ZSTD-9** | **4,615,236 B (4.62 MB)** across 5 files | T9, `hindsight ingest` |
| **Compression vs raw JSON** | **175×** (807,482,752 → 4,615,236) | T9, same run |
| Compression vs source zip | 35.2× (162,319,793 → 4,615,236) | T9, same run |
| `dim_openfda` share of the output | **2.53 MB of 4.62 MB — 55%**, from 2,251 rows | T9, per-file sizes |
| Row-group size is worth ~12% | 12,000 reports/group → 4.06 MB (199×) vs 2,000/group → 4.62 MB (175×) | T9, same rows written twice |
| `report_duplicate` rows | **7,872** = 1,857 bare objects + 6,015 array entries | T9, `split` over all 12,000 |
| Field paths with more than one JSON type | **1 of 120** — `reportduplicate` only (L-007) | T9, typed every value |
| `patient.drug` / `patient.reaction` present | 12,000 of 12,000, always arrays, **never empty** | T9, same pass |
| Report row width | **31 columns** — 32 less `reportduplicate`, now its own table | T9, schema file |
| `companynumb` coverage | **87.6%** of reports (L-004's 89.6% came from the dead partition) | T9, `metrics.json` |
| `drugstartdate` coverage | **22.5%** of drug rows (L-004 said 20.5%) | T9, same file |
| UNII coverage | **82.9%** of drug rows, by join (L-004 said 83.3%) | T9, same file |
| Peak RSS, both passes + metrics | **175 MB** against a 500 MB ceiling | T9, `/usr/bin/time -l` |
| Wall time, one partition | **9.5 s** cold, **5.2 s** against the committed schema | T9, same run |
| **Round trip, whole partition** | **12,000 / 12,000 byte-identical**, rebuilt from Parquet | T10, `reconstruct` vs the source zip |
| Explicit JSON nulls in the source | **0** across all 12,000 reports | T10, walked every value at every depth |
| Round-trip wall time | **7.4 s** for 12,000 reports, 0.17 s of it loading the tables | T10, same run |
| `Tables.load` memory | **266 MB** for a 4.62 MB Parquet partition — peak 354.7 MB of a 500 MB ceiling | T10, `ru_maxrss` before and after |
| Max records in any partition | **12,000**; 1,676 of 1,767 hold exactly that, none more | T10, manifest, all 1,767 |
| `report_duplicate` groups | **2,953** reports = 1,857 bare objects + 1,096 arrays | T10, matches L-007's recon count |
| Reports with **no drugs** | **0** of 12,000 — also 0 with no reactions, 0 with an empty array anywhere | T11, every report tested for each shape |
| Fixture cost in the repo | 4,564 KB on disk, **1,370 KB stored** — git zlib-compresses blobs, so gzipping it saves nothing | T11, `git hash-object` then the loose object's size |
| Fast suite | **143 tests, 0.69 s**, no network, no partition on disk | T11, `uv run pytest -q` |
| Slow suite, whole partition | 12,000/12,000 byte-identical, **23.6 s**, peak RSS **373 MB** of 500 | T11, `uv run pytest -m slow` |
| Cost of re-asserting the null precondition | 23.6 s vs T10's 7.4 s for the same reconstruction | T11, the difference is `explicit_nulls` per report (L-008) |
| Distinct MedDRA terms in the partition | **4,281** across 44,916 reaction rows | T12, `report_reaction.parquet` |
| Exclusion list size and bite | **187 terms, 6,900 of 44,916 reaction rows — 15.4%** | T12, list joined against the partition |
| MedDRA versions inside one partition | **two** — 27.1 on 44,792 rows, 28.0 on 124 | T12, `reactionmeddraversionpt` |
| Top term once the list is applied | `Fatigue` (581), then Diarrhoea, Nausea, Headache — `Death` 8th | T12, before/after ranking |
| Max drug rows in a single report | **2,321** (report `24942430`), 862 of them the same `medicinalproduct`, 212 distinct drug objects | T12, verified against the source zip (L-009) |
| Reports with more than 100 drug rows | **40 of 12,000** — 0.33%, ~69,000 projected over the corpus | T12, same run |
| Naive drug × reaction join | **882,585 rows vs 405,230 distinct triples — 2.2×**, 2.1% of it one report | T12, same run (L-009) |
| Drug–event pairs at min 3 co-reports | **28,540**, of which 91 have an undefined PRR (c = 0) | T13, `top_pairs` |
| Pairs clearing Evans | **24,299 of 28,540 — 85%.** The criterion barely filters | T13, same run (AD-014) |
| `BUTRANS × Onychomycosis` | a=9 b=9 c=1 d=11,981 · PRR 5,991 · χ² 4,811 · flagged | T13, recomputed by hand and by query, agreeing |
| `drugcharacterization` split | suspect 42,665 · concomitant 28,554 · interacting 771 rows | T13, `report_drug.parquet` |
| The nine duplicate reports | 66–96 drugs each, **all marked suspect**, 6 manufacturers, 2 sharing a `companynumb` and a reaction list | T13, source zip and Parquet (L-010) |
| Their pairwise drug-list overlap | Jaccard **0.38 min · 0.48 median · 0.91 max**, 19 drugs common to all nine | T13, same run |
| PRR wall time, whole partition | **0.13 s** against a 5 s budget | T13, spec Verify block |

> ⚠️ Caveat, hardened by **L-006**: per-partition figures come from one partition, `2025q1/drug-event-0001-of-0034` — **which no longer exists.** The 2026-08-10 export chunks 2025q1 into 28 files, not 34. These figures are prior expectations, not reproducible measurements. **T6 through T9 have since re-measured every one of them** against `2025q1/0001-of-0028`: reports 12,000 (matches), drug rows 71,990 and reaction rows 44,916 (both lower), compression 175× rather than 338×. Where the two disagree, the T6–T9 row is the measurement and the spike row is history. The corpus-level rows above (1,767 partitions, 111 GiB, 20,692,690 records) were re-verified against the manifest on 2026-08-13 and hold exactly.

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
- [ ] **Schedule AD-006's benchmark in M3.** The AD's case for skipping deep learning rests on "deliberately not using it *and benchmarking to show why*", and the benchmark was never put on the roadmap — which leaves the stronger half of the argument unevidenced. Gradient boosting against the shrinkage estimator, on the same pairs, publishing the result either way
- [x] ~~Choose Quarto vs. Evidence.dev~~ — Quarto, AD-009
- [ ] Confirm remote storage target at M1 start (AD-012 — HF Datasets front-runner)
- [x] ~~Record the distinct-`openfda` count during T9~~ — 2,251, and L-003's numbers are now annotated rather than trusted
- [x] ~~**Decide AD-013** (`reportduplicate` as a fifth table)~~ — accepted 2026-08-13. Five tables, `seq IS NULL` is the bare-object marker, specs updated to match
- [ ] Empty arrays are indistinguishable from absent fields (L-007). **T11 re-measured: 0 empty arrays anywhere, and 0 reports without drugs or without reactions**, so the hole still has no known instance. Decide before M1 crawls 1,767 partitions — the reconstruction currently rebuilds the absent version
- [ ] Row-group size: 2,000 costs ~12% of the output size (T9). T18 owns the trade against peak RSS
- [x] ~~**`Tables.load` holds a whole partition in Python dicts** — 266 MB for 4.62 MB of Parquet (T10)~~ — T11 kept it. Measured 373 MB peak against the 500 MB ceiling; streaming in `safetyreportid` order would trade that headroom for a sort nothing needs. CI never loads a partition. **Revisit at M1** if a denser partition gets close
- [x] ~~T11 must assert "zero explicit nulls" per partition rather than inherit T10's measurement (L-008)~~ — done, and it is what makes the round-trip comparison one-sided
- [ ] Add `ijson` to PROJECT.md's key dependencies — required by the streaming design, currently missing
- [ ] **Review the exclusion list at the start of M1**, as its own header promises. It was curated against one partition and is a floor, not an enumeration
- [ ] Procedure and concomitant-therapy terms (`Chemotherapy`, `Radiotherapy`, `Oxygen therapy`) sit in the reaction field and are not bodily responses either. Enumerating them by hand loses; they need the MedDRA hierarchy, which openFDA does not ship — the export carries the preferred term only. Deferred, and stated in the list's header rather than left out quietly
- [x] ~~The exclusion list's `#` header requires `comment='#'` on read. Without it DuckDB returns **zero rows silently** and nothing is excluded — T13 owns making that failure loud~~ — done. `excluded_terms` raises on an empty read and the message names the cause; two tests pin it, one reading the real CSV without the flag
- [ ] Spec traceability table still reads `Pending` for M0-01 … M0-12, all of which are done. Refresh it in one pass rather than a row per task

---
