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
- **Round-trip test in CI** — reconstruct source JSON from the tables, assert byte-identical, fail the build otherwise. Passing 12,000/12,000 on the whole partition (T10) and on the committed ~100-report fixture that CI runs. The **per-era** cadence is a scheduled M1 job with a named owner, not a property of the push CI (AD-019)
- Compression measured on a 2025 partition: **175× lossless** (T9, ~3.4–3.7 GB projected). The 338× in L-003 came from a partition the current export no longer contains (L-006) and is history, not a baseline. M0 re-runs it on an **early-era** partition — 2004q1 onward, since openFDA does not start at 2005 — where `openfda` enrichment is expected to be sparser and the ratio worse
- Add the MedDRA exclusion list for reporting artifacts (`Off label use`, `Condition aggravated`, …) before computing anything — see L-004

**Query + one finding** — PLANNED
- DuckDB over the Parquet
- Compute PRR for the top drug–event pairs in the slice
- One chart, one page, published to GitHub Pages

**Exit criteria:** `make all` on a clean machine produces a public URL with a real chart. If this takes more than 24 h, the architecture is wrong — stop and revisit.

---

## M1 — Corpus completo (~44 h)

**Objetivo:** os 20,7M relatos ingeridos, normalizados e se atualizando em agenda sem supervisão.

> Reescrito em 14/08/2026 pela revisão de arquitetura. O M1 anterior descrevia intenções que o M0 já tinha resolvido de outro jeito — ver AD-017 a AD-022. As ~8 h a mais são o custo de fechar isso.

### Features

**Alvo de armazenamento remoto** — PLANEJADA · *primeira tarefa, antes da crawler* (AD-018)
- Confirmar AD-012 (Hugging Face Datasets favorito, R2 segundo, B2 terceiro) e escrever a decisão
- Uma crawler que escreve em disco local e depois migra é reescrita, não configuração — por isso vem antes

**Era, medida a partir do manifesto** — PLANEJADA (AD-017)
- Uma **era** é um intervalo contíguo de buckets com o mesmo conjunto de caminhos de campo, descoberto pela passagem 1 e gravado em `schema/<era>.json`
- Não é uma década escolhida no papel: uma fronteira escrita à mão seria mais uma constante medida numa partição e aplicada a 2004–2025, que é o erro de L-006
- T19 é o protótipo manual disso, feito uma vez à mão antes de virar mecanismo

**Crawler retomável, uma era por vez** — PLANEJADA (AD-018)
- As 1.767 partições, com checkpoint e reinício no meio da rodada
- Respeitar a educação com o openFDA; a vazão medida foi ~11,6 MB/s, ~2,7 h de transferência pura
- **Os zips de uma era ficam em disco entre a passagem 1 e a passagem 2, e são descartados ao fechar a era.** A passagem 1 precisa varrer todas as partições da era antes que a passagem 2 escreva qualquer uma; a alternativa é baixar tudo duas vezes (~5,4 h)
- **Medir o tamanho da maior era pelo manifesto antes de rodar** — é o pico de disco do milestone e hoje ninguém sabe qual é

**Drift que registra e põe de quarentena** — PLANEJADA (AD-017)
- Campo que o schema da era não tem → registra o evento, põe a partição de quarentena, segue
- Não escreve, não alarga o schema sozinho, não derruba o crawl. `UnknownField` continua sendo o gatilho; muda quem o pega
- Os eventos de drift e a fila de quarentena viram artefato público de qualidade, não remendo escondido

**Round trip por era, em agenda** — PLANEJADA (AD-019)
- Uma partição por era, em job agendado, separado do CI de push — que continua no fixture de ~100 relatos
- A página diz **quais eras foram verificadas e quando**. Sem isso "byte-identical" tem alcance presumido em vez de declarado
- É o job mais caro do projeto: `Tables.load` segura uma partição inteira em dicts Python (266 MB para 4,62 MB de Parquet, T10). Sequencial, dentro do teto de 500 MB por partição

**Refresh agendado** — PLANEJADA
- Cron no GitHub Actions; incremental — só partições novas ou alteradas
- O `download.json` do openFDA carrega uma data de export; ela é o sinal de mudança
- Reparticionamento não é mudança de conteúdo: um id que some do manifesto é evento registrado, não erro (L-006)

**Métricas de qualidade** — PLANEJADA
- Contagens de linha, taxas de nulo, eventos de drift, fila de quarentena, `repeated_report_ids`, atraso de frescor — calculadas a cada rodada, guardadas como série temporal
- `metrics.json` por partição já tem o formato; M1 empilha

**Medir a query da G1** — PLANEJADA (AD-021)
- Contagem de pares medicamento-evento distintos sobre o corpus inteiro, com a lista de exclusão aplicada, e o número publicado seja ele qual for
- Depende de `prr._directory` ganhar um caminho multi-partição: hoje ele recusa mais de uma partição, e a recusa é o que impede a medida de existir
- O `<5 s` da G1 é expectativa prévia até essa medição, não critério

**Revisar a lista de exclusão** — PLANEJADA
- Como o próprio cabeçalho dela promete: foi curada contra uma partição e é um piso, não uma enumeração

**Critérios de saída:** o corpus completo se reconstrói sem supervisão; as métricas de qualidade são consultáveis ao longo do tempo; a fila de quarentena e as eras verificadas pelo round trip estão publicadas; e a query da G1 tem um número medido.

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
