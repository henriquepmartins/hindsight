# M0 — Walking Skeleton Tasks

**Spec:** [`spec.md`](spec.md) · **Design:** [`design.md`](design.md)
**Status:** Approved — ready to execute
**Budget:** ~24 h. 19 tasks. If you cross 30 h, stop and revisit the architecture (ROADMAP exit criteria).

---

## How these tasks are executed

Every task carries a **Verify** block — the command that proves it is done. Most also carry a **Concept** line: the thing that task exists to teach me. That is the reason M0 is budgeted at 24 h and not 6.

One task per sitting. Don't batch them — the review is where the learning lands.

---

## Execution plan

```
Phase 1 — Foundation (sequential, ~3 h)
  T1 → T2 → T3

Phase 2 — Acquisition (~4 h)
  T2 ──→ T4 ──→ T5 ──→ T6

Phase 3 — Normalization (~8 h)  ← the core of M0
  T6 ──→ T7 ─┐
             ├──→ T9 ──→ T10 ──→ T11
  T6 ──→ T8 ─┘

Phase 4 — Analysis (~4 h)
  T12 [P, unblocked from T2 onward]
  T9, T12 ──→ T13 ──→ T14

Phase 5 — Publish (~3 h)
  T14 ──→ T15 ──→ T17
  T11 ──→ T16
  everything ──→ T18

Phase 6 — Era check (~2 h)
  T18 ──→ T19
```

**Only real parallelism:** T12 (exclusion list) is pure data curation and can be done in any gap — waiting on a download, low-energy evening. Everything else is a chain, which is correct for a walking skeleton.

---

## Phase 1 — Foundation

### T1: Initialize repo and Python project

**What:** Git repo, `pyproject.toml` (uv, Python 3.12), directory skeleton, `.gitignore` with `data/`.
**Where:** repo root
**Depends on:** None · **Requirement:** M0-01

**Done when:**
- [ ] `git init` done, first commit exists
- [ ] Layout matches design.md, empty packages have `__init__.py`
- [ ] `data/` is gitignored; `schema/`, `reference/`, `tests/fixtures/` are not

**Verify:** `git status --short` is clean after `mkdir -p data/raw && touch data/raw/x` — the file must not appear.

**Commit:** `chore: initialize project structure`

---

### T2: Pin and install dependencies

**What:** Add `duckdb`, `pyarrow`, `ijson`, `httpx`, `pytest`; lock; verify imports. Closes **B-003**.
**Where:** `pyproject.toml`, `uv.lock`
**Depends on:** T1 · **Requirement:** M0-01, M0-02

Note: `polars` is deliberately left out (design.md). Add it when a transform needs a dataframe.

**Done when:**
- [ ] `uv sync` succeeds from a clean checkout
- [ ] `uv.lock` is committed
- [ ] `uv run python -c "import duckdb, pyarrow, ijson, httpx"` exits 0

**Verify:** clone into a temp dir, `uv sync`, run the import line. Must pass with no network beyond the package index.

**Commit:** `chore: pin dependencies`

---

### T3: Makefile skeleton

**What:** `make` targets — `install`, `ingest`, `test`, `analyze`, `site`, `all`, `clean`. Targets call the CLI; several are stubs until later tasks fill them.
**Where:** `Makefile`
**Depends on:** T2 · **Requirement:** M0-17

**Done when:**
- [ ] `make` with no args prints the target list
- [ ] Every target exists and either works or exits with "not implemented yet" — never a confusing shell error
- [ ] `.PHONY` declared correctly

**Verify:** `make` then `make test` → clear message, not a stack trace.

**Commit:** `chore: add Makefile skeleton`

---

## Phase 2 — Acquisition

### T4: Partition manifest resolver

**What:** `resolve(partition_id) -> Partition` — fetch `api.fda.gov/download.json`, walk to `results.drug.event`, return the matching partition's URL, export date, and size.
**Where:** `src/hindsight/manifest.py`
**Depends on:** T2 · **Requirement:** M0-03

**Concept:** *Talking to an API you don't control.* The response is a deeply nested dict whose shape you must discover, not assume. You'll practice exploring an unknown JSON structure at the REPL before writing the accessor — and writing the accessor so it **fails loudly** if the shape changes, instead of returning `None` three call frames from where the problem is.

**Done when:**
- [x] Returns a `Partition` dataclass: `id`, `url`, `export_date`, `size_mb`, `records`
- [x] Unknown partition id raises a named exception with the id in the message, and lists what the bucket actually contains
- [x] An unexpected response shape raises rather than returning `None`

**Deviations from the original criteria, and why:**
- `size_bytes: int` → `size_mb: float`. The manifest reports `"size_mb": "154.80"` — a string, two decimals, approximate. Naming a derived value `size_bytes` would imply a precision the source does not have, and would force a silent MB-vs-MiB choice worth 5%. T5 records the true byte count from the download.
- `records: int` added. Free from the manifest, and it removes a hardcoded assumption: not every partition holds 12,000 reports (`2025q1/0028-of-0028` holds 3,230).
- `export_date` is a `datetime.date`, not a string. M1 orders exports to detect change, and `"2026-8-9" > "2026-08-10"` as strings.
- The partition id is derived from the download URL, since the manifest carries no id of its own. The pattern must not require `YYYYqN` — openFDA publishes a non-quarter `all_other/` bucket (L-006).

**Verify:**
```bash
uv run python -c "from hindsight.manifest import resolve; print(resolve('2025q1/0001-of-0028'))"
```
Expected: a `Partition` with a real URL and an export date matching STATE.md's verified fact (2026-08-10 or later).

**Commit:** `feat(manifest): resolve openFDA partitions from download.json`

---

### T5: Pinned, resumable downloader

**What:** `ensure_local(partition) -> Path` — download to a `.part` file, verify SHA-256, atomically rename, write `data/manifest/<id>.json` with `{id, url, export_date, sha256, bytes}`. Skip if the local file already matches.
**Where:** `src/hindsight/fetch.py`
**Depends on:** T4 · **Requirement:** M0-04

**Concept:** *Atomicity and idempotence.* A download that gets interrupted must not leave something a later run mistakes for complete — this is why you write to `.part` and rename only after verification (rename is atomic on POSIX; a partial write is not). Idempotence is what makes the whole pipeline safe to re-run, which is the property M1's crawler is built on.

**Done when:**
- [ ] First run downloads and writes the manifest entry
- [ ] Second run detects the SHA-256 match and transfers zero bytes
- [ ] `Ctrl-C` mid-download leaves only a `.part`; the next run does not treat it as complete
- [ ] Mismatched SHA-256 raises and deletes the bad file

**Verify:**
```bash
time uv run hindsight fetch 2025q1/0001-of-0028   # ~22 s, per STATE.md's 11.6 MB/s
time uv run hindsight fetch 2025q1/0001-of-0028   # < 1 s, prints "cached"
```

**Commit:** `feat(fetch): pinned resumable partition download`

---

### T6: Streaming report iterator ⭐

**What:** `iter_reports(zip_path) -> Iterator[dict]` — open the zip member as a stream, yield each object under `results` one at a time. Never extract to disk. Never materialize the array.
**Where:** `src/hindsight/stream.py`
**Depends on:** T5 · **Requirement:** M0-05, M0-11

**Concept:** *Generators and bounded memory* — the single most important Python concept in this project. A generator turns "load 1.2 GB, then loop" into "hold one 100 KB record at a time," and it is the difference between a pipeline that handles 1,767 partitions and one that doesn't. You'll also meet `zipfile.ZipFile.open()`, which decompresses lazily as you read — so the zip is never unpacked to disk at all. This is the task where `pip install more-ram` stops being the answer.

**Watch for:** `ijson.items(f, 'results.item')` is the incantation — `'results.item'` means "each element of the results array," not a field called `item`.

**Done when:**
- [ ] Yields exactly `Partition.records` dicts — read the count from the manifest, do not hardcode 12,000 (L-006)
- [ ] Nothing is extracted to disk (check `data/` before and after)
- [ ] Peak RSS stays under 500 MB across a full pass
- [ ] Works as a generator — `next(iter_reports(p))` returns immediately, without reading the whole file

**Verify:**
```bash
/usr/bin/time -l uv run python -c "
from hindsight.stream import iter_reports
print(sum(1 for _ in iter_reports('data/raw/2025q1-0001-of-0028.zip')))
" 2>&1 | grep -E "12000|maximum resident"
```
Expected: `12000`, and maximum resident set size well under 500 MB (design.md predicts < 200 MB).

**Commit:** `feat(stream): incremental report iterator over zipped JSON`

---

## Phase 3 — Normalization *(the core)*

### T7: openfda dimension writer

**What:** Content-hash function + first-sight dimension writer. `key(block) -> str` returns `sha1(json.dumps(block, sort_keys=True))[:16]`; the writer holds a `set` of seen keys and emits each block once.
**Where:** `src/hindsight/normalize.py`
**Depends on:** T6 · **Requirement:** M0-06

**Concept:** *Content-addressed deduplication.* Instead of choosing a key and hoping it's unique, you let the content define its own identity — the same idea Git uses for every object it stores. `sort_keys=True` is load-bearing: without it, two identical blocks with different key order hash differently and your dimension silently doubles.

**⚠️ The trap that already bit once:** `k = key(o) if o else None` is **wrong**. An empty dict `{}` is falsy, so `openfda: {}` gets treated as absent — this produced exactly 492 mismatches in the spike (L-005). The correct test is `if o is not None`. Write it the wrong way first, watch T11 fail, then fix it. That failure is worth more than the correct line.

**Done when:**
- [ ] `key()` is stable across runs and across key ordering
- [ ] Empty dict produces a key, absent field produces `None`
- [ ] Each distinct block is written once; a `set` of hashes is the only state retained
- [ ] Asserts no hash collision — two different blocks mapping to one key raises

**Verify:**
```bash
uv run python -c "
from hindsight.normalize import key
assert key({'a':[1],'b':[2]}) == key({'b':[2],'a':[1]})   # order-independent
assert key({}) is not None                                 # empty dict is real
print('ok')"
```

**Commit:** `feat(normalize): content-hashed openfda dimension`

---

### T8: Record splitter

**What:** `split(report) -> RowSet` — one report dict becomes one report row (with `pt_`-prefixed patient fields), N drug rows, M reaction rows. **Every field is kept. No keep-list, ever.**
**Where:** `src/hindsight/normalize.py`
**Depends on:** T6 · **Requirement:** M0-07

**Concept:** *Denormalized JSON → relational rows*, which is the core move of the entire project. The `seq` column exists because JSON arrays are ordered and SQL tables are not — without it the round trip cannot restore original order. The `pt_` prefix exists so reconstruction is mechanical rather than a lookup table.

**⚠️ The other trap from L-005:** do not build the column list by inspecting one record. Iterate `report.items()`. If you find yourself typing a list of field names, stop — that's the bug that dropped `companynumb` from 89.6% of reports.

**Done when:**
- [ ] Report with no `patient.drug` yields the report row and zero drug rows (not a skipped report)
- [ ] `seq` is the original array index
- [ ] Round-tripping keys by hand on one report loses nothing
- [ ] No literal field-name list appears anywhere in the function

**Verify:**
```bash
uv run python -c "
from hindsight.stream import iter_reports
from hindsight.normalize import split
r = next(iter_reports('data/raw/2025q1-0001-of-0028.zip'))
rs = split(r)
src = set(r) | {'pt_'+k for k in (r.get('patient') or {}) if k not in ('drug','reaction')}
assert set(rs.report) >= src - {'patient'}, src - set(rs.report)
print('no fields lost')"
```

**Commit:** `feat(normalize): split reports into fact rows`

---

### T9: Schema inference + Parquet sink ⭐

**What:** Pass 1 — `schema.infer(reports)` unifies types across **all 12,000** records into four `pyarrow.Schema`s, saved to `schema/<partition>.json`. Pass 2 — `ParquetSink` writes row groups against the frozen schema with ZSTD-9. Also emits `metrics.json`.
**Where:** `src/hindsight/schema.py`, `src/hindsight/write.py`
**Depends on:** T7, T8 · **Requirement:** M0-08, M0-19

**Concept:** *Explicit schema over inferred schema.* This is the design's central choice (design.md). Arrow requires one schema for the whole file; JSON gives you 12,000 records that disagree. Pass 1 computes the union and writes it down as a reviewable artifact; pass 2 can then fail loudly on anything unexpected instead of silently widening to string or dropping a column. You'll also meet `ParquetWriter.write_table()` — writing in row groups is what keeps memory flat regardless of file size.

**Type unification rules:** everything is `string` unless proven otherwise; `openfda` fields are `list<string>`; nested single objects (`pt_summary`, `primarysource`, `sender`, `receiver`, `reportduplicate`) are **structs**, not flattened and not JSON-stringified (design.md).

**Done when:**
- [ ] `schema/2025q1-0001.json` is committed and human-readable
- [ ] Four Parquet files exist, ZSTD-9, under `data/parquet/year=2025/quarter=1/`
- [ ] Report row count equals the manifest's `records` for this partition — read it from `Partition.records`, do not hardcode 12,000 (the last partition of a quarter is a remainder; `2025q1/0028-of-0028` holds 3,230)
- [ ] Drug and reaction row counts are **recorded**, not asserted. L-003's 103,187 / 57,664 came from a partition that no longer exists (L-006) — they are prior expectations. Write the measured numbers into STATE.md
- [ ] A record with a field absent from the schema raises, never silently drops
- [ ] Compression ratio measured and compared against L-003's 338×. An order-of-magnitude gap means something is wrong; a modest gap is just a different partition
- [ ] `metrics.json` carries row counts and non-null rates for `drugstartdate`, UNII, `companynumb`

**Verify:**
```bash
uv run hindsight ingest 2025q1/0001-of-0028
du -sh data/parquet/                                    # ≈ 3.5 MB
uv run python -c "
import duckdb
for t in ['report','report_drug','report_reaction','dim_openfda']:
    print(t, duckdb.sql(f\"SELECT count(*) FROM 'data/parquet/**/{t}.parquet'\").fetchone()[0])"
```
Expected: `12000 / 103187 / 57664 / <n>`. **Record that `<n>`** — it settles the 2,537-vs-1,491 contradiction flagged in STATE.md L-003.

**Commit:** `feat(write): explicit-schema Parquet sink`

---

### T10: Round-trip reconstructor ⭐

**What:** `reconstruct(tables, report_id) -> dict` — rebuild the original nested JSON from the four tables: strip `pt_` back into `patient`, re-nest drugs and reactions in `seq` order, rejoin `openfda` from the dimension.
**Where:** `src/hindsight/roundtrip.py`
**Depends on:** T9 · **Requirement:** M0-09

**Concept:** *Inverse functions as proof.* If `split` is lossless then `reconstruct ∘ split = identity`, and that is checkable rather than assertable. This is the intellectual core of the project — the reason the README can claim 338× compression without hedging. Port the logic from [`spike-flatten.py:21-51`](../../project/spike-flatten.py#L21-L51), but as reviewable code with names longer than two characters.

**Watch for:** the spike's `sn()` helper strips `None` values before comparing, because absent-vs-null is a distinction JSON round-tripping introduces. Understand *why* that's legitimate normalization and not cheating — then keep it, and document it in a comment.

**Done when:**
- [ ] `reconstruct` returns a dict equal to the source for a hand-picked report
- [ ] Drug and reaction order matches the source exactly
- [ ] A report with `openfda: {}` reconstructs to `{}`, not a missing key
- [ ] Works from Parquet, not from the in-memory rows

**Verify:** one report by hand, compared with `json.dumps(..., sort_keys=True)`. T11 makes it 12,000.

**Commit:** `feat(roundtrip): reconstruct source JSON from normalized tables`

---

### T11: Round-trip test ⭐

**What:** A pytest that runs `split` → `reconstruct` over a committed ~100-report fixture and asserts byte-identical. Names the failing `safetyreportid` and differing keys on failure.
**Where:** `tests/test_roundtrip.py`, `tests/fixtures/sample_100.json`
**Depends on:** T10 · **Requirement:** M0-10

**Concept:** *Fixtures and the CI contract.* The full partition is 246 MB — CI cannot download it on every push. A committed fixture makes the test fast, hermetic, and deterministic. Choosing the fixture is the real skill: 100 random reports won't cover the edge cases, so deliberately include reports with `openfda: {}`, with no drugs, and with `patient.summary` present.

**Done when:**
- [ ] `pytest` passes on the fixture
- [ ] A separate slow-marked test does all 12,000 locally and reports `12000/12000`
- [ ] Failure output names the `safetyreportid` and the differing keys — not just `assert False`
- [ ] Deliberately breaking T7's empty-dict rule makes it fail, and the message points at the cause

**Verify:**
```bash
uv run pytest tests/test_roundtrip.py -v          # fast, fixture
uv run pytest -m slow                             # full partition, 12000/12000
```
Then break `if o is not None` → `if o`, re-run, confirm it goes red. Revert.

**Commit:** `test: round-trip integrity over committed fixture`

---

## Phase 4 — Analysis

### T12: MedDRA exclusion list [P]

**What:** A committed CSV of MedDRA terms that are reporting artifacts rather than adverse reactions, each with a `reason`. Seed from L-004: `Off label use`, `Condition aggravated`, `Intentional product use issue`, plus what the data shows.
**Where:** `reference/excluded_terms.csv`
**Depends on:** T2 (do it any time after) · **Requirement:** M0-12

**Concept:** *Domain judgment as a versioned artifact.* This list changes results, so it belongs in git with a reason per row and not inline in a query. Someone will disagree with a term someday; a CSV makes that a pull request instead of an argument.

**Done when:**
- [ ] CSV with `term,reason` and the three terms from L-004
- [ ] Every row's reason says why it's an artifact, not just "noise"
- [ ] A header comment states the list is provisional and reviewed each milestone

**Verify:** open it and read the reasons. If a reason doesn't convince you, it won't convince a reader.

**Commit:** `feat(reference): MedDRA reporting-artifact exclusion list`

---

### T13: PRR query

**What:** DuckDB SQL building a 2×2 contingency table per drug–event pair and computing PRR, with the exclusion list applied and a minimum count of 3.
**Where:** `src/hindsight/analysis/prr.py`
**Depends on:** T9, T12 · **Requirement:** M0-13

**Concept:** *Disproportionality analysis* — the actual statistics regulators use, and the piece of domain knowledge that makes this a pharmacovigilance project rather than a JSON-flattening exercise. PRR = (a/(a+b)) / (c/(c+d)) over the 2×2 of drug-present/absent × event-present/absent. Expressing that in SQL means computing four marginals from one table, which is a genuinely good window-function exercise.

**Done when:**
- [ ] Returns drug, event, a, b, c, d, PRR — **raw counts alongside the ratio, always**
- [ ] Excluded terms are gone from the output
- [ ] Pairs with a < 3 are filtered, threshold as a named parameter
- [ ] Runs in under 5 s (STATE.md measured 0.048 s for the join+group-by, so this has room)
- [ ] Top results are sanity-checked by eye — an implausible #1 usually means the marginals are wrong

**Verify:**
```bash
uv run python -c "from hindsight.analysis.prr import top_pairs; print(top_pairs(limit=20))"
```
Expected: no `Off label use`, every row with counts, PRR descending.

**Commit:** `feat(analysis): PRR over drug-event contingency tables`

---

### T14: Analysis notebook

**What:** A Jupyter notebook that reads the Parquet with DuckDB, runs T13, and produces one chart. Limitations text **above** the chart.
**Where:** `notebooks/m0_finding.ipynb`
**Depends on:** T13 · **Requirement:** M0-14

**Concept:** *The notebook as a rendered artifact, not a scratchpad.* It has to run top-to-bottom on a clean kernel, because Quarto executes it in CI. Any hidden state that only exists because you ran cells out of order will fail the build — which is the discipline that separates a notebook you can publish from one you can only demo.

**Done when:**
- [ ] Restart-and-run-all works from a clean kernel
- [ ] One chart, readable, axes labeled, with the counts visible
- [ ] Limitations appear before the result: one partition · no entity resolution · no causal claim · min count 3
- [ ] No absolute paths

**Verify:** Restart kernel → Run All → no errors. Then `git stash` any uncommitted state and re-run.

**Commit:** `feat(notebook): M0 finding with limitations`

---

## Phase 5 — Publish

### T15: Quarto site

**What:** `_quarto.yml` rendering the notebook to `_site/`, with the project title and the standing disclaimer in the footer.
**Where:** `_quarto.yml`, `index.qmd`
**Depends on:** T14 · **Requirement:** M0-15

**Done when:**
- [ ] `quarto render` produces `_site/index.html` with the chart
- [ ] The not-medical-advice disclaimer is in the footer of every page
- [ ] `_site/` is gitignored

**Verify:** `quarto render && open _site/index.html`

**Commit:** `feat(site): Quarto rendering`

---

### T16: CI workflow

**What:** GitHub Actions on push/PR — `uv sync`, `pytest` (fixture only, no download).
**Where:** `.github/workflows/ci.yml`
**Depends on:** T11 · **Requirement:** M0-02, M0-10

**Done when:**
- [ ] Green on push
- [ ] Under 2 min
- [ ] No network beyond the package index
- [ ] Breaking the normalizer turns it red

**Verify:** push a deliberately broken branch, confirm red, delete it.

**Commit:** `ci: round-trip test on push`

---

### T17: Publish workflow

**What:** GitHub Actions rendering Quarto and deploying `_site/` to Pages on push to `main`.
**Where:** `.github/workflows/publish.yml`
**Depends on:** T15 · **Requirement:** M0-16

Note: the workflow renders a notebook that reads `data/parquet/`, which is gitignored. **Commit the small aggregated PRR result** (a few KB CSV) as the notebook's input, rather than the corpus. The pipeline produces it; the site consumes it. Keeps CI hermetic and the repo small.

**Done when:**
- [ ] Pages URL is live and public
- [ ] Rebuilds on push to `main`
- [ ] Works in a private window

**Verify:** open the URL on your phone.

**Commit:** `ci: publish site to GitHub Pages`

---

### T18: `make all` on a clean machine

**What:** Wire every target so one command goes from empty checkout to rendered site. Measure and record peak RSS and wall time.
**Where:** `Makefile`, `README.md`
**Depends on:** T1–T17 · **Requirement:** M0-11, M0-17

**Concept:** *Reproducibility is a claim you test, not one you make.* Your machine has state — a cached download, an env var, a package you installed and forgot. A clean clone in a fresh directory is the only honest check, and it is where most "works on my machine" projects quietly fail.

**Done when:**
- [ ] Fresh clone in a temp dir + `make all` → rendered site, no manual steps
- [ ] Under 15 min end to end
- [ ] Peak RSS recorded and under 500 MB
- [ ] README updated with real measured numbers

**Verify:**
```bash
cd $(mktemp -d) && git clone <repo> h && cd h && /usr/bin/time -l make all
```

**Commit:** `chore: make all reproduces the full chain`

---

## Phase 6 — Era check

### T19: 2005-era partition

**What:** Run the same pipeline against an early partition. Record compression ratio, row counts, and every field present in 2025 but absent in 2005.
**Where:** `schema/<2005-partition>.json`, STATE.md
**Depends on:** T18 · **Requirement:** M0-18

**Concept:** *Schema drift, discovered rather than assumed.* Every storage number in this project comes from one 2025 partition. FAERS field layouts have changed since 2004, so this is where you find out whether M1's sizing is real. Diffing two committed schema files **is** the drift detector — you're prototyping M1's mechanism by hand, once, before automating it.

**Done when:**
- [ ] A 2005-era partition ingests without crashing
- [ ] Its compression ratio is measured and compared to 338×
- [ ] The schema diff against 2025 is recorded as a field-level list
- [ ] A new Lesson (L-006) is written into STATE.md with real numbers
- [ ] If the ratio is dramatically worse, the full-corpus projection is revised **before** M1 starts

**Verify:**
```bash
uv run hindsight ingest 2005q1/...
diff <(jq -S 'keys' schema/2005*.json) <(jq -S 'keys' schema/2025*.json)
```

**Commit:** `feat: era drift check on 2005 partition`

---

## Granularity check

| Task | Scope | Verdict |
|---|---|---|
| T1–T3 | config files | ✅ |
| T4, T5, T6 | one function each | ✅ |
| T7, T8 | one function each, same file, cohesive | ✅ |
| T9 | two modules, one contract | ⚠️ largest task at ~3 h — split into T9a schema / T9b sink if it stalls |
| T10, T11 | one function, one test | ✅ |
| T12–T14 | one artifact each | ✅ |
| T15–T17 | one config each | ✅ |
| T18, T19 | verification, not construction | ✅ |

**T9 is the one to watch.** If pass 1 fights you for more than 90 minutes, split it and commit the schema inference on its own.

---

## Definition of done for M0

All 19 tasks committed, CI green, a public URL with a chart, and these four numbers measured rather than projected:
distinct `openfda` blocks (T9) · peak RSS (T18) · 2005 compression ratio (T19) · 2005↔2025 schema diff (T19).
