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
- `load_export() -> Export` added as the primary entry point; `resolve` is now a one-partition convenience over it. Measured: the manifest is 590 KB and lists all 1,767 partitions, so resolving per id would cost M1 ~1 GB of redundant transfer. The real reason is L-006 though — partitions resolved minutes apart can carry two different `export_date`s, and an `Export` makes one date per run structural instead of a rule someone has to remember.
- Covered by `tests/test_manifest.py` — 21 cases, no network, 0.03 s. The Verify block below needs the live endpoint, so CI (T16) could not otherwise reach the failure paths M1 depends on.

**Verify:**
```bash
uv run pytest tests/test_manifest.py -q     # 21 passed, no network
uv run python -c "
from hindsight.manifest import resolve, load_export
print(resolve('2025q1/0001-of-0028'))
e = load_export()
print(len(e.partitions), e.export_date, sum(p.records for p in e.partitions.values()))"
```
Expected: a `Partition` with a real URL and an export date matching STATE.md's verified fact (2026-08-10 or later), then `1767 2026-08-10 20692690` — the corpus-level facts, re-derived in one fetch.

**Commit:** `feat(manifest): resolve openFDA partitions from download.json`

---

### T5: Pinned, resumable downloader

**What:** `ensure_local(partition) -> Path` — download to a `.part` file, verify SHA-256, atomically rename, write `data/manifest/<id>.json` with `{id, url, export_date, sha256, bytes}`. Skip if the local file already matches.
**Where:** `src/hindsight/fetch.py`
**Depends on:** T4 · **Requirement:** M0-04

**Concept:** *Atomicity and idempotence.* A download that gets interrupted must not leave something a later run mistakes for complete — this is why you write to `.part` and rename only after verification (rename is atomic on POSIX; a partial write is not). Idempotence is what makes the whole pipeline safe to re-run, which is the property M1's crawler is built on.

**Done when:**
- [x] First run downloads and writes the manifest entry
- [x] Second run detects the SHA-256 match and transfers zero bytes
- [x] `Ctrl-C` mid-download leaves only a `.part`; the next run does not treat it as complete
- [x] Mismatched SHA-256 raises and deletes the bad file

**Deviations from the original criteria, and why:**
- **A CLI was needed to satisfy this task's own Verify block.** `uv run hindsight fetch` did not exist — T3's Makefile was written against a CLI nobody had built. Added `src/hindsight/cli.py` and a `[project.scripts]` entry. One command; `ingest` lands in T9.
- **Resume is HTTP Range, but only against an existing pin.** Without a pin the first download *defines* it, so a leftover `.part` from an older export would be spliced in with nothing to catch it. With a pin, a bad prefix is caught by the SHA-256 and discarded. Measured: resuming from a real 60 MB prefix finished in 7.8 s vs 14.1 s cold, same digest.
- **A mismatch after resuming names both causes.** The first version blamed openFDA for rewriting the partition, which is wrong when the local prefix was the corrupt half. Asserting one cause out of two is exactly the confident wrong answer this project is built to avoid.
- **`size_mb` is MiB, not MB.** Measured: 162,319,793 bytes against a stated `154.80`. That closes the ambiguity T4 flagged as "worth 5%". The name is openFDA's; `Partition.size_mb` now says so and stays advisory.

**Verify:**
```bash
uv run pytest tests/test_fetch.py -q            # 11 passed, no network
time uv run hindsight fetch 2025q1/0001-of-0028   # 14.1 s, 162,319,793 bytes
time uv run hindsight fetch 2025q1/0001-of-0028   # 1.1 s, prints "cached"
```
The cached run is 1.1 s rather than the "< 1 s" first written here, and the reason matters: ~1.0 s of it is `resolve()` re-fetching the 590 KB manifest. Hashing 155 MB is the cheap part. `load_export()` is what fixes this when M1 fetches in bulk.

**Commit:** `feat(fetch): pinned resumable partition download`

---

### T6: Streaming report iterator ⭐

**What:** `iter_reports(zip_path) -> Iterator[dict]` — open the zip member as a stream, yield each object under `results` one at a time. Never extract to disk. Never materialize the array.
**Where:** `src/hindsight/stream.py`
**Depends on:** T5 · **Requirement:** M0-05, M0-11

**Concept:** *Generators and bounded memory* — the single most important Python concept in this project. A generator turns "load 1.2 GB, then loop" into "hold one 100 KB record at a time," and it is the difference between a pipeline that handles 1,767 partitions and one that doesn't. You'll also meet `zipfile.ZipFile.open()`, which decompresses lazily as you read — so the zip is never unpacked to disk at all. This is the task where `pip install more-ram` stops being the answer.

**Watch for:** `ijson.items(f, 'results.item')` is the incantation — `'results.item'` means "each element of the results array," not a field called `item`.

**Done when:**
- [x] Yields exactly `Partition.records` dicts — read the count from the manifest, do not hardcode 12,000 (L-006)
- [x] Nothing is extracted to disk (check `data/` before and after)
- [x] Peak RSS stays under 500 MB across a full pass
- [x] Works as a generator — `next(iter_reports(p))` returns immediately, without reading the whole file

**Deviations from the original criteria, and why:**
- **`use_float=True` on `ijson.items`.** ijson yields `decimal.Decimal` for JSON numbers by default, and T7's `json.dumps` content hash cannot serialize one. Measured: all 19,648,458 scalars in this partition are strings, so it changes nothing today — it is there for the 2005-era partition in T19, where the guarantee that matters is "whatever `json.load` would have returned."
- **An absent or empty `results` array raises instead of yielding zero reports.** Silently streaming nothing is the failure mode where openFDA renames a key, all 1,767 partitions ingest cleanly, and the corpus is empty. Checked rather than assumed: no partition in the 2026-08-10 export reports zero records — the smallest, `2024q4/0029-of-0029`, holds 324 — so the guard cannot fire on real data.
- **The count is not checked inside `iter_reports`.** The signature takes a path, not a `Partition`; comparing against `Partition.records` belongs to T9's ingest, which is where a mismatch can be acted on. Verified externally here instead (output below).
- **CRC-32 verification came free.** `ZipFile.open()` checks the member's CRC on the read that reaches EOF, so a full pass over a rotted archive raises rather than ending the stream early. Pinned by a test that flips a byte inside a stored member.
- Covered by `tests/test_stream.py` — 13 cases, no network, 0.02 s.

**Verify:**
```bash
/usr/bin/time -l uv run python -c "
from hindsight.stream import iter_reports
print(sum(1 for _ in iter_reports('data/raw/2025q1-0001-of-0028.zip')))
" 2>&1 | grep -E "12000|maximum resident"
```
Measured: `12000`, peak RSS **47.7 MB**, full pass in **2.1 s** — a quarter of design.md's < 200 MB prediction, a tenth of the spec ceiling. The first report arrives in **2.8 ms**, which is the generator property stated as a number rather than asserted.

```bash
uv run pytest tests/test_stream.py -q          # 13 passed, no network, 0.02 s
uv run python -c "
from hindsight.manifest import resolve
from hindsight.stream import iter_reports
p = resolve('2025q1/0001-of-0028')
n = sum(1 for _ in iter_reports('data/raw/2025q1-0001-of-0028.zip'))
print(p.records, n, n == p.records)"   # 12000 12000 True
```

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
- [x] `key()` is stable across runs and across key ordering
- [x] Empty dict produces a key, absent field produces `None`
- [x] Each distinct block is written once; a `set` of hashes is the only state retained
- [x] Asserts no hash collision — two different blocks mapping to one key raises

**Deviations from the original criteria, and why:**
- **The last two criteria contradict each other.** A `set` of truncated hashes cannot detect a collision — deciding whether two blocks that share a key are the same block requires something the set threw away. Resolved by keeping `key -> full 40-char digest`: a collision is a key hit whose full digests differ. Blocks themselves are still never retained. Measured on this partition: 2,251 distinct blocks, ~90 KB of digests against ~30 MB for the blocks.
- **The writer is `OpenfdaDimension.add(block) -> (key, row | None)`.** An absent block returns `(None, None)`, so T9's write loop needs no `is not None` branch of its own. That makes the L-005 trap structurally impossible at the call site rather than a rule repeated at each one. `add` also returns the key, so the block is hashed once per drug row and not twice.
- **`usedforsecurity=False` on the sha1.** This is a content address, not a security hash. Same digest, and it keeps the pipeline working on a FIPS-restricted interpreter.
- **The `if o` bug was not committed first.** The task asks for it to be written wrong, watched fail at T11, then fixed. Under the current working agreement that just plants a known bug in the history. `test_the_falsy_test_is_the_bug_this_rule_exists_for` puts both expressions side by side instead — same evidence, nothing broken in git.
- Covered by `tests/test_normalize.py` — 15 cases, no network, 0.02 s. The digest of a known block is pinned as a literal, so changing the separators, the sort, or the encoding fails there rather than silently re-keying every row ever written.

**Verify:**
```bash
uv run python -c "
from hindsight.normalize import key
assert key({'a':[1],'b':[2]}) == key({'b':[2],'a':[1]})   # order-independent
assert key({}) is not None                                 # empty dict is real
print('ok')"
```

Then over the real partition, which is where the numbers come from:

```
drug rows           71,990
openfda absent      11,128  -> openfda_key is None
openfda empty {}       507  -> a real key, the L-005 507
blocks emitted       2,251  == len(dimension)
dedup ratio           27.0x
peak RSS             51 MB  (streaming + dimension)
```

The 2,251 settles the 2,537-vs-1,491 contradiction STATE.md had parked for M0-11. Neither recorded value was right.

**Commit:** `feat(normalize): content-hashed openfda dimension`

---

### T8: Record splitter

**What:** `split(report) -> RowSet` — one report dict becomes one report row (with `pt_`-prefixed patient fields), N drug rows, M reaction rows. **Every field is kept. No keep-list, ever.**
**Where:** `src/hindsight/normalize.py`
**Depends on:** T6 · **Requirement:** M0-07

**Concept:** *Denormalized JSON → relational rows*, which is the core move of the entire project. The `seq` column exists because JSON arrays are ordered and SQL tables are not — without it the round trip cannot restore original order. The `pt_` prefix exists so reconstruction is mechanical rather than a lookup table.

**⚠️ The other trap from L-005:** do not build the column list by inspecting one record. Iterate `report.items()`. If you find yourself typing a list of field names, stop — that's the bug that dropped `companynumb` from 89.6% of reports.

**Done when:**
- [x] Report with no `patient.drug` yields the report row and zero drug rows (not a skipped report)
- [x] `seq` is the original array index
- [x] Round-tripping keys by hand on one report loses nothing
- [x] No literal field-name list appears anywhere in the function

**Deviations from the original criteria, and why:**
- **`split(report, dimension)`, not `split(report)`.** design.md gives this module one job — hiding the openfda hashing rule and the empty-dict trap — and first-sight dedup is state that spans the whole partition, so a per-report pure function can compute a key but cannot decide whether the block has been emitted. The alternative, returning the raw block for T9 to dedup, puts the L-005 test back at the call site that T7 deliberately took it out of. The dimension is a required argument rather than a default, because a fresh one per call would emit every block 32× and still look correct.
- **`RowSet` has four fields, not three.** `openfda` holds the blocks this report was the first to carry — empty for all but 2,251 of the 12,000. T9 then writes four tables from one object instead of maintaining a fifth stream of its own.
- **A source field that collides with a column raises.** Not in the original criteria, and the reason it is now: `{**columns, **fields}` resolves a duplicate by keeping the last value silently, so a drug field named `seq` would overwrite the array position the round trip is rebuilt from. Checked rather than assumed — none of the 27 top-level names start with `pt_`, and no drug or reaction field is named `safetyreportid`, `seq`, or `openfda_key`. The guard cannot fire on the current export; it fires on the export where openFDA adds a field, which is the whole point. The message names the table and the colliding field and **not** the report: a clash is openFDA changing its schema, so it hits every report at once and which one arrived first carries no information. The first draft threaded a formatted `report 'x' drug[3]` string into all four call sites, which meant building ~117,000 strings per partition for a message that never prints — measured at 1.299 s against 1.209 s for the same work, ~7% of `split`'s runtime and ~2.6 min across 1,767 partitions.
- **A missing `safetyreportid` raises.** It is the only join key back to a report's child rows. Measured: 12,000 of 12,000 present, all distinct.
- **`patient` and the two arrays are type-checked.** `enumerate` accepts a string and yields one character per position, so `drug: "ASPIRIN"` would otherwise become rows that look valid until T11 runs. The array check is technically redundant — a non-list is caught one line later by the per-entry check — but it is kept for the message: `'drug' should be an array` names the problem, `'drug'[0] should be an object` sends the reader at partition 900 to the wrong place.
- **The four field names in the module are table boundaries, not a keep-list.** `patient`, `drug`, `reaction`, `openfda` are named because each becomes a table of its own. Every other field travels by iteration, whatever it is called. Pinned by a test that invents a field name and asserts it arrives.
- **Reaction rows are 44,916**, not L-003's 57,664 — that figure came from the partition that no longer exists (L-006). Drug rows are 71,990, matching T7.
- Covered by `tests/test_normalize.py` — now 34 cases, no network, 0.01 s. Each new test was checked by mutation rather than by having been written first: eight ways of breaking the splitter were applied one at a time (keep-list, falsy openfda test, `seq` as a counter, silent overwrite, tolerated missing id, unchecked array, inline block, arrays leaking into the report row) and every one turned the suite red.

**Verify:**
```bash
uv run pytest tests/test_normalize.py -q     # 34 passed, no network
uv run python -c "
from hindsight.stream import iter_reports
from hindsight.normalize import split, OpenfdaDimension
r = next(iter_reports('data/raw/2025q1-0001-of-0028.zip'))
rs = split(r, OpenfdaDimension())
src = set(r) | {'pt_'+k for k in (r.get('patient') or {}) if k not in ('drug','reaction')}
assert set(rs.report) >= src - {'patient'}, src - set(rs.report)
print('no fields lost')"
```

One report proves too little for a rule this project has already been bitten by, so the same check ran over all 12,000, comparing every source key at every level against the row it should have landed in:

```
reports            12,000   manifest says 12,000   match True
drug rows          71,990
reaction rows      44,916
dim_openfda rows    2,251   == len(dimension)
openfda absent     11,128   -> openfda_key is None
openfda empty {}      507   -> a real key
reports losing a field   0
report columns  32   (26 top-level + 6 pt_)
drug columns    29   (26 source + safetyreportid, seq, openfda_key)
reaction columns 5   (3 source + safetyreportid, seq)
peak RSS      65 MiB   wall 4.8 s
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
- [x] `schema/2025q1-0001-of-0028.json` is committed and human-readable — 162 lines, one line per column
- [x] Parquet files exist, ZSTD-9, under `data/parquet/year=2025/quarter=1/part=0001-of-0028/` — **five, not four** (AD-013)
- [x] Report row count equals the manifest's `records` for this partition — read it from `Partition.records`, do not hardcode 12,000 (the last partition of a quarter is a remainder; `2025q1/0028-of-0028` holds 3,230)
- [x] Drug and reaction row counts are **recorded**, not asserted — 71,990 and 44,916, in STATE.md
- [x] A record with a field absent from the schema raises, never silently drops
- [x] Compression ratio measured and compared against L-003's 338× — **175×**, gap accounted for in L-003's note
- [x] `metrics.json` carries row counts and non-null rates for `drugstartdate`, UNII, `companynumb`

**Deviations from the original criteria, and why:**

- **⚠️ Five tables, not four — `reportduplicate` became `report_duplicate` (AD-013, needs a decision).** Pass 1 failed three seconds into the first partition: the field is an object in 1,857 reports and an array in 1,096, and Arrow holds one type per column. design.md had it listed among the nested single objects. It is a repeated child, and it never arrives as an array of length 1 — the XML-to-JSON fingerprint (L-007). A `NULL` `seq` records the bare-object shape so T10 can put it back as an object. `design.md` §Data contracts and `spec.md` P1 §2 still say four tables and are **left untouched**: an acceptance criterion does not get rewritten to match code that already runs. The AD is where the decision goes.
- **The schema file is `2025q1-0001-of-0028.json`, not `2025q1-0001.json`.** Same stem rule as the pin, so `data/manifest/2025q1-0001-of-0028.json` and `schema/2025q1-0001-of-0028.json` name the same partition the same way. Dropping `-of-0028` would also merge two partitions that re-chunking made different (L-006).
- **A `part=` level under the quarter.** Every partition writes a file called `report.parquet`; without it the 28 partitions of 2025q1 overwrite each other and leave a corpus that looks complete. Costs nothing at M0's one partition, and DuckDB's `**` glob reads it unchanged.
- **`metrics.py` is a module design.md's table does not list.** It is P3's artifact and M1 grows it into a quality time series; putting it in `write.py` would make that module about two things. Flagged rather than assumed.
- **Coverage is measured by querying the Parquet, not by counting during the write.** A counter measures the loop; a query measures the artifact, and the artifact is what the claim is about. It also means the row counts in `metrics.json` are an independent check on `Written.rows` rather than a copy of it.
- **The columns the pipeline writes itself are not inferred.** `safetyreportid`, `seq`, `openfda_key` have declared types, and observation has to agree or it raises. Without this, a partition whose duplicates all arrived as bare objects has a null `seq` on every row, and inference resolves it to `string` there and `int64` in the next partition — a column type that depends on which partition you read, which is the drift the schema file exists to detect.
- **A type conflict raises; it does not record a drift event.** spec.md's edge case asks for a recorded drift event, and M0 has nowhere to record one — drift detection is M1, and its input is the diff between two of these schema files. Raising is the loud version of the same rule. The one conflict in the corpus was found this way and is now a table.
- **`int64` and `double` are not widened into each other.** Every schema bug this project has had came from a quiet resolution. No FAERS scalar is a number today (19,648,458 measured, all strings), so a conflict here is news.
- **A struct that is empty in every record raises.** Parquet cannot write a struct with no child fields — measured, `ArrowNotImplementedError`. The convenient answer is to drop the column, which is a data-loss decision that inference does not get to make.
- **`--reinfer` exists.** Pass 1 is skipped when the schema file is present, because the file *is* the schema — recomputing it silently would make the committed artifact decorative. The flag is how you deliberately re-derive it.
- **Three small additions to modules T5–T8 wrote:** `Partition.stem` (the pin and the schema file name the partition by one rule, not two), `RowSet.by_table()` plus the table-name constants (the names were already inline in `normalize.py`; now every module reads them from one place), and `stream.json_bytes()` (the compression ratio's denominator, read from the zip's central directory rather than by decompressing).
- Covered by `tests/test_schema.py` and `tests/test_write.py` — **130 cases total, no network, 0.3 s.** Checked by mutation rather than by assertion count: nine ways of breaking the two modules were applied one at a time (skip `enforce`, never flush mid-loop, keep the `.part` file on failure, stop pinning `seq`, let a null set the type, leave `reportduplicate` in the report row, give the bare object `seq=0`, unsorted field names, drop the final flush). Eight turned the suite red immediately. **The ninth did not:** disabling the mid-loop flush wrote identical output in one row group — the whole flat-memory property, silently gone. `test_a_partition_leaves_in_batches_rather_than_all_at_the_end` was added for it, and it is the one test here that would have caught nothing about correctness and everything about the design.

**Verify:**
```bash
uv run hindsight ingest 2025q1/0001-of-0028 --reinfer
uv run python -c "
import duckdb
for t in ['report','report_drug','report_reaction','report_duplicate','dim_openfda']:
    print(t, duckdb.sql(f\"SELECT count(*) FROM 'data/parquet/**/{t}.parquet'\").fetchone()[0])"
```

```
cached 2025q1/0001-of-0028 (162,319,793 bytes)
pass 1: inferring the schema from every record
schema schema/2025q1-0001-of-0028.json (inferred)
pass 2: writing parquet against the frozen schema
metrics data/parquet/year=2025/quarter=1/part=0001-of-0028/metrics.json
partition          2025q1/0001-of-0028 (export 2026-08-10)
report                 12,000
report_drug            71,990
report_reaction        44,916
report_duplicate        7,872
dim_openfda             2,251
distinct openfda        2,251
parquet                  4.62 MB   175.0x vs json   35.2x vs zip
companynumb             87.6%
drugstartdate           22.5%
unii                    82.9%
        9.55 real         7.97 user         0.23 sys
           175374336  maximum resident set size

report 12000 · report_drug 71990 · report_reaction 44916 · report_duplicate 7872 · dim_openfda 2251
```

Second run, against the committed schema rather than re-inferring it: **5.2 s**, pass 1 skipped, identical output. `report_duplicate`'s 7,872 is 1,857 bare objects plus 6,015 array entries — the same split the recon pass counted before any of this was written, which is what says the table did not invent or lose a row.

**Commit:** `feat(write): explicit-schema Parquet sink`

---

### T10: Round-trip reconstructor ⭐

**What:** `reconstruct(tables, report_id) -> dict` — rebuild the original nested JSON from the five tables: strip `pt_` back into `patient`, re-nest drugs and reactions in `seq` order, rejoin `openfda` from the dimension, and put `reportduplicate` back in the shape its null `seq` records (AD-013).
**Where:** `src/hindsight/roundtrip.py`
**Depends on:** T9 · **Requirement:** M0-09

**Concept:** *Inverse functions as proof.* If `split` is lossless then `reconstruct ∘ split = identity`, and that is checkable rather than assertable. This is the intellectual core of the project — the reason the README can claim 338× compression without hedging. Port the logic from [`spike-flatten.py:21-51`](../../project/spike-flatten.py#L21-L51), but as reviewable code with names longer than two characters.

**Watch for:** the spike's `sn()` helper strips `None` values before comparing, because absent-vs-null is a distinction JSON round-tripping introduces. Understand *why* that's legitimate normalization and not cheating — then keep it, and document it in a comment.

**Done when:**
- [x] `reconstruct` returns a dict equal to the source for a hand-picked report
- [x] Drug and reaction order matches the source exactly
- [x] A report with `openfda: {}` reconstructs to `{}`, not a missing key
- [x] A `report_duplicate` row with `seq IS NULL` reconstructs to an object; rows with `seq` 0..N reconstruct to an array in that order (AD-013, added when the decision was taken)
- [x] Works from Parquet, not from the in-memory rows

**Deviations from the original criteria, and why:**

- **`tables` needed a type, so `Tables` is one.** design.md gives the signature `reconstruct(tables, report_id)` without saying what `tables` is. It is `Tables`, with two constructors: `load(directory)` reads the five Parquet files, `from_rows(by_table)` indexes rows already in memory. Both exist because T11 needs both — the fixture test has no Parquet to read and the slow test must read the artifact rather than the rows — and putting the indexing rules in one place is what stops the two paths from testing subtly different things.
- **Child rows are grouped by `safetyreportid` once, at load.** Scanning per report is 12,000 passes over 71,990 drug rows. Not a micro-optimization: it is the difference between 7.4 s and something quadratic in a number M1 multiplies by 1,767.
- **The null-stripping normalization is measured rather than justified.** The task asks to keep the spike's `sn()` and document why it is legitimate. Documenting it is not enough — it is legitimate only if the source never carries an explicit JSON null, and if it ever did, the strip would erase a real value and turn a genuine mismatch into a pass. That is the failure where the test built to catch data loss is the thing hiding it. **Measured: 0 explicit nulls across all 12,000 reports.** T11 should assert this per partition rather than inherit it, because it is a property of an export, not of the format.
- **`_ordered` raises on a gap in `seq` instead of sorting what it has.** `sorted` returns four entries for an array that had five and looks entirely correct doing it.
- **`_duplicates` raises when one report has both a null `seq` and numbered rows.** The source wrote `reportduplicate` one way; a table recording both is corrupt, not ambiguous, and guessing which to believe is how the AD-013 contract would quietly stop meaning anything.
- **No tests in this task.** T11 is the test, per the granularity table — the one place in M0 where the function and its test are deliberately separate tasks. The verification below is a throwaway script, not a committed artifact.
- **The empty-array hole is documented in the module, not fixed.** `"drug": []` produces zero child rows, indistinguishable from an absent `drug`, and this module rebuilds the absent version. No array in the export is empty (L-007), so it is a hole with no known instance. It stays on STATE.md's todo list as M1's to close.

**Verify:**

The task asks for one report by hand. One report proves too little for a rule this project has been bitten by twice, so it ran on one specimen of every shape the module makes a decision about, then on all 12,000:

```
loaded from data/parquet/year=2025/quarter=1/part=0001-of-0028
  reports         12,000      duplicate grps   2,953      dim_openfda   2,251

scanned 12,000 source reports
explicit JSON nulls in the source: 0

PASS  first report in the partition                    24737707
PASS  a drug with openfda: {} (the L-005 case)         24737707
PASS  a drug with no openfda at all                    24737707
PASS  2+ drugs, so order is falsifiable                24737707
PASS  reportduplicate as a bare object (seq NULL)      24744701
PASS  reportduplicate as an array (seq 0..N)           24821689

specimens compared: 6   failures: 0
openfda: {} survives as {} at drug positions [3] (not a missing key)
bare-object duplicate rebuilt as dict
array duplicate rebuilt as list of 2
```

```
RSS before load             41.9 MB
RSS after Tables.load      308.5 MB   (0.17 s)

reports compared          12,000
byte-identical            12,000
MISMATCHES                     0

round-trip wall              7.4 s
RSS peak                   354.7 MB   (ceiling 500)
```

The 2,953 duplicate groups are 1,857 bare objects plus 1,096 arrays — the split L-007 counted before this module existed, which is what says the reconstruction is reading the contract rather than reproducing its own assumption.

**⚠️ The RSS is the finding here, and it is not comfortable.** `Tables.load` costs **266 MB** for a partition that is 4.62 MB on disk — the tables are read into Python dicts, and a dict is roughly 60× its Parquet. The 500 MB ceiling holds today with ~30% headroom, and the headroom is thinner than it looks: no partition in the export exceeds 12,000 records (checked, 1,676 of 1,767 hold exactly that), but bytes range up to 217 MB against this partition's 162 MB, and the dead partition of L-003 carried 43% more drug rows per report than this one. A partition at that density lands near 450 MB. Nothing to fix in T10 — `reconstruct` itself is flat, and the cost is entirely `Tables.load` holding a partition to answer 12,000 lookups. **T11 owns the decision**, and it has a cheap out: the fixture test never loads a partition, and the slow test could stream reports in `safetyreportid` order instead of indexing them all. Recorded rather than absorbed.

**Commit:** `feat(roundtrip): reconstruct source JSON from normalized tables`

---

### T11: Round-trip test ⭐

**What:** A pytest that runs `split` → `reconstruct` over a committed ~100-report fixture and asserts byte-identical. Names the failing `safetyreportid` and differing keys on failure.
**Where:** `tests/test_roundtrip.py`, `tests/fixtures/sample_100.json`
**Depends on:** T10 · **Requirement:** M0-10

**Concept:** *Fixtures and the CI contract.* The full partition is 246 MB — CI cannot download it on every push. A committed fixture makes the test fast, hermetic, and deterministic. Choosing the fixture is the real skill: 100 random reports won't cover the edge cases, so deliberately include reports with `openfda: {}`, with no drugs, and with `patient.summary` present.

**Done when:**
- [x] `pytest` passes on the fixture
- [x] A separate slow-marked test does all 12,000 locally and reports `12000/12000`
- [x] Failure output names the `safetyreportid` and the differing keys — not just `assert False`
- [x] Deliberately breaking T7's empty-dict rule makes it fail, and the message points at the cause

**Deviations from the original criteria, and why:**

- **The comparison is one-sided: the source is never normalized.** The spike stripped nulls from *both* documents before comparing, and the task asked to keep that helper and document why it is legitimate. Keeping it as-is was the wrong answer. Any normalization applied to both sides of an equality can only ever make it pass, so the round trip would have been partly proving itself. Since the source carries zero explicit nulls — measured, T10 — stripping it is a no-op, and the comparison can be against the **raw source**. What was a shared normalization is now `test_the_source_carries_no_explicit_nulls`, a precondition that goes red on the export where it stops holding, instead of a helper that quietly keeps the test green there. This is L-008 and it is the main thing that changed in this task.
- **The fixture cannot contain a report with no drugs, because none exists.** The criterion asks to deliberately include one. Measured over all 12,000: **0 reports without drugs, 0 without reactions, 0 with an empty array anywhere.** L-007 saw this from the other side. The shape is covered by T8's unit tests on synthetic reports, which is where it belongs — inventing a report for the fixture would make the fixture a thing this project wrote rather than a thing openFDA sent.
- **`sample_100.json` is committed raw, not gzipped.** 4,564 KB looked too big until it was measured: git zlib-compresses blobs, so the repo carries **1,370 KB** either way. Gzipping would have saved nothing and cost the ability to read the file. The 4× ratio is low for JSON because most of the bytes are `openfda` NDC and SPL identifiers, which genuinely do not repeat.
- **The fixture's recipe is a test, not a comment.** `test_the_fixture_covers_the_shapes_it_was_chosen_for` asserts the counts. A fixture regenerated against a 2005 partition could pass every round-trip assertion while covering none of the cases that ever broke this project, and the failure would look like success.
- **Both paths are tested, not one.** In-memory rows prove `reconstruct` inverts `split`; a real Parquet round trip through `tmp_path` proves nothing was lost between them. Only the second one can catch a schema that drops a column, which is L-005 with better paperwork. 100 reports make it cheap enough for CI.
- **The L-005 bug is simulated in the tables as a standing test**, on top of the manual break the Verify block asks for. A one-time manual check that nobody repeats is not a regression test.
- **`pyproject.toml` gains `[tool.pytest.ini_options]`.** `-m slow` needed the marker registered, and `addopts = "-m 'not slow'"` makes the bare `pytest` the run CI can afford. Not in the task's file list; without it the task's own Verify block emits a warning and the default run reaches for a 155 MB partition.
- **The slow test re-asserts "zero explicit nulls" per report rather than inheriting T10's number.** It is a property of an export, not of the format, and one export of 91 buckets has been read. It costs 23.6 s against T10's 7.4 s for the same reconstruction — that gap *is* the price of not inheriting, paid once per local run.
- **Three guard tests beyond the criteria** — a `seq` gap, a duplicate recorded as both shapes at once, a drug pointing at a missing block. Each is a `BrokenTables` path T10 wrote and nothing exercised.
- **`Tables.load` stays as-is for the slow test.** T10 left the memory question here. Measured: **373 MB peak against the 500 MB ceiling**, and streaming in `safetyreportid` order would trade that headroom for a sort nothing currently needs. Revisit at M1 if a denser partition gets close; the fixture path never loads a partition at all, so CI is unaffected either way.

**Verify:**

```
$ uv run pytest tests/test_roundtrip.py -v
collected 14 items / 1 deselected / 13 selected

test_the_source_carries_no_explicit_nulls PASSED
test_the_fixture_covers_the_shapes_it_was_chosen_for PASSED
test_the_fixture_needs_no_network_and_no_partition PASSED
test_every_fixture_report_rebuilds_identically PASSED
test_drug_order_survives PASSED
test_an_empty_openfda_comes_back_as_an_empty_object PASSED
test_the_two_duplicate_shapes_come_back_as_they_arrived PASSED
test_the_fixture_rebuilds_from_parquet PASSED
test_collapsing_empty_openfda_into_absent_is_caught PASSED
test_an_unknown_report_id_says_so PASSED
test_a_gap_in_seq_is_not_quietly_shortened PASSED
test_a_duplicate_that_is_both_shapes_at_once_raises PASSED
test_a_drug_pointing_at_a_missing_block_raises PASSED

13 passed, 1 deselected in 0.71s

$ uv run pytest -q                      # the whole suite, no network, no partition
143 passed, 1 deselected in 0.69s

$ uv run pytest -m slow -q -s
12,000/12,000 byte-identical
1 passed, 143 deselected in 23.58s
       23.71 real   372,948,992 maximum resident set size
```

Then the break the task asks for — `if block is None` → `if not block` in `OpenfdaDimension.add`:

```
8 failed, 135 passed, 1 deselected in 0.54s

FAILED tests/test_normalize.py::test_every_distinct_block_is_emitted
FAILED tests/test_normalize.py::test_a_truncation_collision_raises_rather_than_merging
FAILED tests/test_normalize.py::test_an_absent_block_keys_to_none_and_an_empty_one_does_not
FAILED tests/test_roundtrip.py::test_every_fixture_report_rebuilds_identically
FAILED tests/test_roundtrip.py::test_drug_order_survives
FAILED tests/test_roundtrip.py::test_an_empty_openfda_comes_back_as_an_empty_object
FAILED tests/test_roundtrip.py::test_the_fixture_rebuilds_from_parquet
FAILED tests/test_roundtrip.py::test_collapsing_empty_openfda_into_absent_is_caught
```

The message is the criterion, so here it is in full:

```
AssertionError: safetyreportid 24737707: 1 field(s) differ
    patient.drug[3].openfda: only in source ({})
```

It names the report, the exact path into it, and the value that vanished. Reverted, and the suite is green again.

**One test was fixed by this exercise.** `test_collapsing_empty_openfda_into_absent_is_caught` originally died with a bare `StopIteration` under the break — with the bug live no empty block reaches the dimension, so the `next(...)` looking for one found nothing and reported the symptom as a crash in the test. That is the same "not just `assert False`" failure the criterion is about, one level up. It now says:

```
AssertionError: the fixture's `openfda: {}` never reached dim_openfda. If
`OpenfdaDimension.add` is testing the block for truthiness instead of
`is not None`, that IS the L-005 bug and this is the test saying so.
```

**Commit:** `test: round-trip integrity over committed fixture`

---

## Phase 4 — Analysis

### T12: MedDRA exclusion list [P]

**What:** A committed CSV of MedDRA terms that are reporting artifacts rather than adverse reactions, each with a `reason`. Seed from L-004: `Off label use`, `Condition aggravated`, `Intentional product use issue`, plus what the data shows.
**Where:** `reference/excluded_terms.csv`
**Depends on:** T2 (do it any time after) · **Requirement:** M0-12

**Concept:** *Domain judgment as a versioned artifact.* This list changes results, so it belongs in git with a reason per row and not inline in a query. Someone will disagree with a term someday; a CSV makes that a pull request instead of an argument.

**Done when:**
- [x] CSV with `term,reason` and the three terms from L-004
- [x] Every row's reason says why it's an artifact, not just "noise"
- [x] A header comment states the list is provisional and reviewed each milestone

**Deviations from the original criteria, and why:**
- **187 terms, not the three seeds.** The three from L-004 are a floor, and the header says so: the list is provisional, reviewed at the start of every milestone, and expected to grow. Measured bite: **6,900 of 44,916 reaction rows — 15.4%** of the partition.
- **The header states the membership rule, not just the disclaimer.** A term is excluded only if it records something other than a bodily response in the patient — how the product was used, supplied or labelled, whether it worked, that an exposure happened, or that nothing did. **Ambiguity keeps the term**, because a term wrongly excluded is invisible and a term wrongly kept shows up at the top of the PRR table where it can be argued with.
- **Procedure and concomitant-therapy terms are deferred in the header rather than left out quietly.** `Chemotherapy`, `Radiotherapy`, `Oxygen therapy` sit in the reaction field and are not bodily responses either, but enumerating them by hand loses — they need the MedDRA hierarchy, and openFDA ships the preferred term only.
- **The header is prose behind `#`, which makes the list's own failure mode silent.** DuckDB returns zero rows without `comment='#'` and raises nothing. Recorded here as T13's to make loud, and it did — see `excluded_terms` below.
- **Checked by ranking with and without it.** `Off label use` and `Product use in unapproved indication` leave the top; infliximab → sepsis and streptococcal infection surface underneath, which is a real anti-TNF boxed warning. That check is also what found L-009.

**Verify:** open it and read the reasons. If a reason doesn't convince you, it won't convince a reader.

**Commit:** `feat(reference): MedDRA reporting-artifact exclusion list`

---

### T13: PRR query

**What:** DuckDB SQL building a 2×2 contingency table per drug–event pair and computing PRR, with the exclusion list applied and a minimum count of 3.
**Where:** `src/hindsight/analysis/prr.py`
**Depends on:** T9, T12 · **Requirement:** M0-13

**Concept:** *Disproportionality analysis* — the actual statistics regulators use, and the piece of domain knowledge that makes this a pharmacovigilance project rather than a JSON-flattening exercise. PRR = (a/(a+b)) / (c/(c+d)) over the 2×2 of drug-present/absent × event-present/absent. Expressing that in SQL means computing four marginals from one table, which is a genuinely good window-function exercise.

**Done when:**
- [x] Returns drug, event, a, b, c, d, PRR — **raw counts alongside the ratio, always**
- [x] Excluded terms are gone from the output
- [x] Pairs with a < 3 are filtered, threshold as a named parameter
- [x] Runs in under 5 s — **0.13 s** over the whole partition
- [x] Top results are sanity-checked by eye — **and the check failed. That failure is M0's finding (L-010).**

**Deviations from the original criteria, and why:**

- **⚠️ The eye-check failed, and the marginals were right.** The criterion says an implausible #1 usually means the marginals are wrong. The #1 is `DESOGESTREL\ETHINYL ESTRADIOL × X-ray abnormal` at PRR 9,596, then nail fungus on a buprenorphine patch, an injectable gold salt and a C1-esterase inhibitor. `BUTRANS × Onychomycosis` recomputed by hand gives a=9, b=9, c=1, d=11,981 — summing to exactly 12,000, and the module agrees to the digit. The query is right and the answer is nonsense, which is the harder version of this failure. It traces to **nine near-duplicate reports of one Canadian patient on 66–96 drugs, filed by six manufacturers** (L-010). Neither `drugcharacterization` nor the screening criterion removes it — both measured before either was believed. **M2 is the fix, and T14 publishes the cluster rather than the ranking.**
- **The cells count distinct reports, not joined rows.** design.md sketches `report_drug JOIN report_reaction USING (safetyreportid)` and labels itself "shape only". That shape ranks verbose reporters: one report carries 2,321 drug rows, and the naive join inflates the partition 2.2× — 882,585 rows against 405,230 distinct triples, 2.1% of it from that one report (L-009). `SELECT DISTINCT` on both sides is the whole reason this file is not two lines.
- **χ² and the Evans criterion ship with the ratio (AD-014).** More than the task lists. PRR alone is not a screening rule anywhere in the literature, and shipping the ratio without the criterion it is always quoted with invites a reader to treat a high ratio as a finding. Yates' correction, floored at zero. Not shrinkage — no prior, no borrowing across pairs — so AD-006 and M3's scope are untouched. **It is shipped with the measurement that it does not work here:** 24,299 of 28,540 pairs pass, 85%, and every implausible pair at the top clears it comfortably.
- **An empty exclusion list raises.** STATE parked this as T13's to own, and it is the one failure in this file that is invisible downstream: without `comment='#'` DuckDB returns zero rows and no error, the query still runs, still returns a full table, and the only symptom is `Off label use` back at the top of a chart nobody re-reads. Two tests pin it, one of them reading the real CSV without the flag.
- **A pair with an undefined PRR sorts last rather than being dropped.** 91 of 28,540 have c = 0 — every report carrying the event also carries the drug. The counts still describe them, and `signal` is `False` rather than `True`: Evans has nothing to say about a zero denominator, and treating it as a pass would put the least-evidenced pairs at the top of a flagged list.
- **Reports whose only reaction was excluded keep their place in `d`.** They are real reports that happened not to record a codeable event. Dropping them would quietly shrink the population the ratio is taken against — pinned by `test_an_excluded_event_still_leaves_its_report_in_the_corpus`.
- **The partition is discovered from disk, not spelled into the source.** A hardcoded id here is L-006's stale pin waiting to happen. Two ingested partitions is an error rather than a choice, because after T19 the second one is a 2005-era file and averaging two eras into one table answers a question nobody asked.
- **A CLI subcommand and a live `make analyze`,** because the Makefile target was a stub pointing at this task. The banner under the table prints the caveats — partition size, threshold, no entity resolution, no dedup, not causation — rather than leaving them to the reader.
- Covered by `tests/test_prr.py` — **24 cases, no network, no partition, 0.51 s.** PRR and χ² are each checked against arithmetic worked independently of the SQL, and `test_the_cells_partition_the_corpus` asserts a+b+c+d equals the report count, which is what caught the join inflation.

**Verify:**
```
$ uv run pytest tests/test_prr.py -q
24 passed in 0.51s

$ uv run hindsight analyze --limit 10
drug                           event                       a     b    c       d       PRR      chi2  signal
DESOGESTREL\ETHINYL ESTRADIOL  X-ray abnormal              4     1    1  11,994   9,596.0   5,877.9  yes
DESOGESTREL\ETHINYL ESTRADIOL  General symptom             3     2    1  11,994   7,197.0   3,747.8  yes
DESOGESTREL\ETHINYL ESTRADIOL  Pustular psoriasis          3     2    1  11,994   7,197.0   3,747.8  yes
MYOCHRYSINE                    Onychomadesis               8     6    1  11,985   6,849.1   5,352.4  yes
BUTRANS                        Onychomycosis               9     9    1  11,981   5,991.0   4,810.9  yes
GOLD SODIUM THIOMALATE         Onychomycosis               9     9    1  11,981   5,991.0   4,810.9  yes
BERINERT                       Onychomycosis               9    11    1  11,979   5,391.0   4,328.8  yes
BUTRANS                        Onychomadesis               8    10    1  11,981   5,325.3   4,161.0  yes
NADOLOL                        Proctitis                   3     4    1  11,992   5,139.9   2,676.0  yes
NADOLOL                        Vaginal flatulence          3     4    1  11,992   5,139.9   2,676.0  yes

12,000 reports · min 3 co-reports · signal = Evans (PRR>=2, chi2>=4, a>=3) · raw
medicinalproduct strings, no entity resolution and no deduplication (M2) ·
disproportionate reporting is not causation

0.195 total
```

No excluded term appears, every row carries its 2×2, PRR descends, and the whole partition takes 0.13 s of query time against a 5 s budget. **Every one of those ten rows is the duplicate cluster.** That is the acceptance criterion doing its job — it asked for the table to be read by eye, and reading it is what turned M0's deliverable from a ranking into a finding.

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
