# Hindsight

**Could we have known sooner?**

When a drug hurts someone — a rash, a heart attack, a death — a report gets filed with the FDA. Twenty million of them sit in a public archive. Sometimes, years later, the FDA issues a safety warning about that drug.

This project asks the obvious question nobody has systematically answered: **was the warning already visible in the reports, and how long before?**

---

## What this is

An end-to-end pipeline that ingests the complete FDA Adverse Event Reporting System (FAERS), cleans it into something queryable, runs the disproportionality statistics that drug regulators actually use, and then — the part that matters — **rewinds time**.

For each real safety warning the FDA has issued, the system recomputes its signals using *only* the reports that existed before that date, and measures how early it would have raised a flag. The misses and the false alarms get published with the same prominence as the hits.

That backtest is the whole point. It is the difference between "I built a thing" and "I built a thing, and here is the evidence it works."

> **This is not medical advice, and it makes no causal claims.** Disproportionality analysis measures *reporting patterns*, not causation. A signal means "this combination appears more often than expected in a voluntary reporting database" — nothing more.

---

## Status

🚧 **Day 0.** Nothing is built yet. What exists is a specification and a completed reconnaissance of the data.

| Milestone | What it delivers | Status |
|---|---|---|
| **M0** Walking skeleton | One partition through every layer → one public chart | ⬜ Not started |
| **M1** Full corpus | All 20.7M reports, refreshing unattended | ⬜ Planned |
| **M2** Cleaning & entity resolution | "Tylenol" and "paracetamol" become one drug | ⬜ Planned |
| **M3** Signal detection | PRR / ROR / Bayesian shrinkage over every drug–event pair | ⬜ Planned |
| **M4** The Hindsight backtest | Lead-time vs. real FDA warnings | ⬜ Planned |
| **M5** Public artifacts | Open dataset + report site | ⬜ Planned |

Full plan in [`.specs/project/ROADMAP.md`](.specs/project/ROADMAP.md). Decisions and open risks in [`.specs/project/STATE.md`](.specs/project/STATE.md).

---

## What the data actually looks like

Measured directly on 2026-08-11, not estimated:

| | |
|---|---|
| Reports in the archive | **20,692,690** |
| Bulk export | 1,767 files, **111 GB** compressed |
| Reports in one file | 12,000 — in **1.2 GB** of JSON |
| Per report | ~100 KB, ~8.6 drugs |
| Download throughput | 11.6 MB/s |

That ~100 KB per report is absurd for what is essentially a list of drugs and symptoms — so I measured where it goes.

**92.7% of the entire archive is one lookup block, copied into every drug row.** The `openfda` enrichment field — brand names, NDC codes, pharmacologic classes, UNII identifiers — accounts for 641 MB of a 692 MB payload, repeated across 103,187 drug rows per file.

So I pulled it out into a dimension table and measured the result on a real partition:

| stage | size |
|---|---|
| source zip | 246 MB |
| raw JSON | 1,200 MB |
| after normalization (NDJSON) | 65.5 MB |
| **Parquet, ZSTD-9** | **3.55 MB** |

**338× smaller than the JSON, 69× smaller than the compressed source — and provably lossless.**

Not "lossless" as an assertion. The spike reconstructs the original nested JSON back out of the normalized tables and compares it to the source record by record: **12,000 of 12,000 byte-identical, zero mismatches.**

That test earned its keep immediately. It caught an earlier version silently dropping `patient.summary` (present on 49% of reports) and `reportduplicate` — the latter being a field this project's own deduplication step depends on. It then caught a subtler one: an empty `openfda: {}` object being treated as an absent field, erasing the difference between *"we checked and found nothing"* and *"we never looked."* 550 drug entries, across exactly 492 reports. A compression number without a round-trip test is a guess.

**The full 20.7M-report corpus projects to ~3.4 GB**, and peak disk during ingestion is ~1.5 GB, since partitions are streamed and discarded one at a time. The 111 GB is something the pipeline *passes through* — never something it stores.

*(Measured on one 2025 partition; early years will compress differently. Reproduce with [`spike-flatten.py`](.specs/project/spike-flatten.py) — it runs the normalization and the round-trip test together.)*

---

## Architecture

```
openFDA S3  ──▶  raw zips (immutable, archived on fetch)
                      │
                      ▼
              stream-parse ──▶ normalize ──▶ Parquet on R2
                                   │          (partitioned by year/quarter)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
              DuckDB (analytics)           Postgres (small marts)
                    │                             │
                    ▼                             ▼
        signal detection · backtest        generated report site
```

**Principles:**

- **Reproducibility by pinning, not by hoarding.** Archiving all 111 GB of raw source is impossible on free tiers, so the pipeline pins the openFDA export date and partition manifest instead, and any partition can be re-fetched byte-identically from an official, stable, public source. The round-trip test is what guarantees the derived corpus matches it.
- **Never hold 111 GB.** Stream → transform → discard, one partition at a time.
- **Free tiers force the right design.** No hosted Postgres can hold this, so the corpus is columnar — which is the correct architecture regardless.
- **Point-in-time or it doesn't count.** The backtest must never see a byte of data that didn't exist on the date being simulated. Preventing leakage is the entire scientific content of the project.

**Stack:** Python 3.12 · DuckDB · Polars · Parquet on Cloudflare R2 · PostgreSQL · GitHub Actions · Quarto → GitHub Pages

**Deliberately not used:** no React frontend, no LLM layer, no deep learning. Each was considered and rejected for stated reasons — see AD-004 through AD-006 in [`STATE.md`](.specs/project/STATE.md).

---

## The standard this is held to

1. **Reproduce before you discover.** The methods must first recover at least three drug–event associations already established in the literature. A method that can't reproduce known results has no business claiming new ones.
2. **Publish the misses.** Lead-time results include the warnings the system would have missed entirely, and the false alarms it would have raised.
3. **Measure the cleaning.** Entity resolution and deduplication ship with accuracy rates on a hand-labeled sample — not "it looks better."
4. **The system grades itself.** A public page tracks data freshness, row counts, null rates, and every schema-drift event caught.
5. **Limitations page written first.** Before the results page.

---

## Prior art and honest positioning

Signal detection in FAERS is a real, mature discipline — the FDA, EMA, and Uppsala Monitoring Centre all do it, and the statistical methods used here come from that literature rather than being invented for this project. openFDA already makes the data queryable, and academic studies have analyzed FAERS extensively.

What doesn't exist publicly, as far as I can find: **a reproducible, open, end-to-end pipeline that rebuilds the corpus from raw source and then measures its own historical lead time against real regulatory action.** That gap is what this builds.

If someone has already done this, I want to know — open an issue.

---

## License

Code: MIT. Derived dataset: CC BY 4.0. Source data is US public domain (openFDA).
