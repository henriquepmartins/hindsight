# State

**Last Updated:** 2026-08-21
**Current Work:** M0 — Walking Skeleton. T1–T12 done: repo initialized, dependencies pinned, Makefile skeleton, partition resolver, pinned resumable downloader, streaming report iterator, openfda dimension writer, record splitter, schema inference + Parquet sink, round-trip reconstructor, round-trip test, MedDRA exclusion list. **AD-013 is decided** — five tables, and a null `seq` on `report_duplicate` means the source carried a bare object. **The round trip closes and is now defended: 12,000 / 12,000 byte-identical, plus 13 tests over a committed 100-report fixture that CI can run without the partition.** Phase 3, the core of M0, is finished, and T12 curated 187 exclusion terms that clear the top of the ranking — what surfaces underneath is infliximab → sepsis, a real anti-TNF warning. **T12 also found the trap T13 walks into: one report carries 2,321 drug rows, and the naive join inflates the pair counts 2.2× (L-009).** T13 is written: PRR and χ² over a 2×2 of **distinct reports**, Evans as the screening criterion (AD-014), 0.13 s over the partition. **Its eye-check failed, and the failure is the milestone's finding — the top of the table is nine near-duplicate reports of one Canadian patient on ~90 drugs, and neither `drugcharacterization` nor Evans removes it (L-010).** T13 is committed. **T14 is done and it enlarged the finding (L-011): the nine duplicate reports are not a cluster to route around — 125 reports of 12,000, 1.04%, supply 66.4% of the whole pair table.** Three notebooks record the analyses that actually ran, `reports/m0.qmd` publishes that in 370 words and one chart, and `hindsight analyze --csv` writes the committed table the page reads. **T15 is done too** — `_quarto.yml` + `index.qmd`, light theme with no toggle, per-milestone navbar, the disclaimer in every footer, and `make site` regenerating the CSV before rendering so a stale page takes deliberate effort. **T16 is done** — CI green in 30 s, and its first run immediately caught the one dependency rule this milestone had just written down being broken (L-012). **T17 está commitado** (`ci: publish site to GitHub Pages`); falta confirmar a URL viva.

**Uma revisão de arquitetura em 14/08 fechou o M1 no papel antes de T19 fechar o M0** — AD-017 a AD-022. Quatro dos seis achados eram a mesma coisa: uma promessa do PROJECT/ROADMAP que o M0 resolveu de um jeito deliberadamente estreito e correto, e que nenhum milestone assumia de volta na largura prometida. Dois já foram implementados e verificados: **`repeated_report_ids` no `metrics.json` com o round trip recusando o id ambíguo** (AD-020, medido 0 de 12.000) e a **guarda de procedência da página no CI** (AD-022). O `make test` deixou de ser um stub que saía 1, então `make all` roda de ponta a ponta pela primeira vez. Suíte em **202 testes, 1,6 s**.

**T17, T18 e T19 fecharam em 14/08 e o M0 está completo.** O site está no ar e público. `make all` num clone limpo leva **47,4 s** com pico de **324,5 MB**, e o CSV que ele escreve é byte-idêntico ao versionado — a página é verificável, não confiável. O row group fica em 2.000, agora com os três pontos medidos.

**A M1 foi decomposta em 16/08/2026** — `.specs/features/m1-corpus-completo/` com spec (24 requisitos), design e 29 tasks em cinco fases. Três coisas saíram da decomposição e não estavam em lugar nenhum. Primeira: **o ROADMAP da M1 se referencia em círculo** — era é descoberta pela passagem 1, mas a passagem 1 é escopada por era; o pico de disco é o tamanho da maior era, e as eras não são conhecidas antes de medir. O design resolve com três fases sobre o corpus (varredura → mapa de eras → colheita) em vez de duas passagens sobre uma era, e o preço é honesto: o corpus é transferido duas vezes, ~5,4 h, que é exatamente o custo que AD-018 rejeitou. Segunda: **o drift não tem quando acontecer na colheita inicial** — se a varredura leu todas as partições da era, o schema congelado contém todo campo que a era tem, e `UnknownField` só pode disparar no refresh. AD-017 não diz isso. Terceira, e é a que abre **B-006**: a `dim_openfda` é deduplicada por partição.

**T19 é a que mudou o projeto.** A partição mais antiga do export comprime 78,8× e mesmo assim sai *menor* que a de 2025, então a projeção de corpus desce para 1,7–3,6 GB. E ela carrega **6 `safetyreportid` repetidos em 12.000** — o que abriu **B-004**, hoje fechado pela AD-025. *(Contra o export de 17/08 são 3, e a caracterização dos pares mudou: ver AD-025.)*

**Uma revisão de arquitetura independente da decomposição da M1 rodou em 18/08 e pediu mudanças** — 9 bloqueantes e 7 importantes. Três dos bloqueantes são o mesmo defeito: número propagado entre documentos sem ninguém reabrir o dado. `patient.drug: null` não existe (o caminho com 1.560 ocorrências é `patient.drug[].drugtreatmentdurationunit`), as chaves da `dim_openfda` nunca foram locais, e `receiver` não mudou de tipo entre eras — é sempre-nulo em 2004 e o sentinela do `schema` o escreve como `"string"`, o que faz a regra de fronteira de era fechar era por ruído. **A decomposição não deve ser implementada como está**, e as quatro tasks de decisão (T1, T3, T7, T8) precisam remedir antes de escrever seus ADs.

**Duas coisas foram consertadas em 18/08, na ordem que a revisão pediu.** Primeira: **o arnês do round trip** tinha a partição de 2025 fixa no arquivo de teste, então o Verify que iterava as duas eras rodava 2025 duas vezes, e artefato ausente virava `pytest.skip` — o portão do milestone não podia falhar. Agora é parametrizado por partição, o nome do caso carrega o id, e artefato faltando é falha. Consequência registrada em **B-007**: `make all` fica vermelho até a T4. Segunda: **o repin**. O openFDA reescreveu as duas partições fixadas em oito dias (**L-014**), os bytes de 10/08 não existem mais, e `ensure_local` nunca comparava o pin com o export publicado — rodava feliz sobre bytes velhos. `StalePin` e `--repin` fecham o mecanismo (**AD-027**); as duas partições foram reingeridas contra o export de 17/08 e **quase todo número do M0 mudou** (**L-015**).

**A T1 fechou em 18/08 — AD-025 escrita, B-004 resolvido.** A junção das cinco tabelas passa a ser `ordinal`, posicional dentro da partição, e `safetyreportid` vira atributo. A remedição derrubou a caracterização que L-013 tinha dado aos pares repetidos, e de quebra encontrou o 2×2 da PRR contando `DISTINCT safetyreportid` — 11.997 e não 12.000 em 2004. **T2** implementa.

**Próxima ação:** decidir se `reports/m0.qmd` é reescrito contra o export novo. O topo da tabela deixou de ser absurdo — é `HYDRALAZINE` → vasculite ANCA-positiva, uma associação real — e a seção que se chama "aritmeticamente certo e clinicamente absurdo" perdeu o exemplo. Isso continua em aberto, e é editorial.

**A T2 fechou em 21/08** — `ordinal` nas cinco tabelas, PR #9. Dois desvios do Verify registrados na tasks.md: `repetidos` deu 3 e não 6 (o número do spec era do export de 10/08), e a suíte segue vermelha em 2004 na precondição de null explícito, que é B-005/B-007 e era esperado. **A T3 fechou no mesmo dia** — AD-026 decide B-005 por marcadores de forma da fonte; `_without_nulls` deixa de existir na T4, que é a próxima task de implementação e quem devolve o `make all` ao verde.

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

> As seis decisões abaixo saíram de uma revisão de arquitetura em 14/08/2026, feita antes de T19 fechar o M0. Todas tratam da mesma assimetria: o M0 está especificado no nível de contrato e o M1 estava no nível de intenção. São em português porque a regra de idioma mudou em 14/08; as seções acima ficam como estão até a passada de tradução.

### AD-017: Era é medida, e drift põe a partição de quarentena em vez de derrubar o crawl (2026-08-14)

**Decisão:** uma **era** é um intervalo contíguo de buckets com o mesmo conjunto de caminhos de campo, descoberto pela passagem 1 e gravado em `schema/<era>.json` — não uma década escolhida no papel. E quando uma partição carrega um campo que o schema da era não tem, o pipeline **registra o evento de drift, põe a partição de quarentena e segue**. Não escreve, não alarga o schema sozinho, não para o crawl.

**Razão:** o ROADMAP prometia "detect and record every drift event rather than crashing on it" e o mecanismo implementado faz o oposto — `enforce` levanta `UnknownField` e `_observe` levanta `SchemaConflict`. Está certo em M0, onde um humano está olhando. Contra a restrição "o pipeline deve rodar sem supervisão a partir de M1", um campo novo em qualquer uma das 1.767 partições para tudo até alguém re-inferir à mão.

Era, como conceito, tinha o problema oposto: aparecia no design (schema por era), no PROJECT (round trip por era) e no T19, e não estava definido em lugar nenhum. Definir por medição é o único critério que o próprio detector de drift consegue verificar — uma fronteira escrita à mão seria mais uma constante medida numa partição e aplicada a 2004–2025, que é o erro de L-006.

**Trade-off:** o corpus passa a ter buracos declarados em vez de estar sempre completo, e a fila de quarentena é trabalho de operador que precisa aparecer em algum lugar. Contra isso: um buraco declarado é publicável, e "publique as falhas com o mesmo destaque que os acertos" é padrão nº 2 do projeto.

**Alternativas rejeitadas:**
- *Alargar o schema da era automaticamente e registrar.* Mais barato e mantém o corpus completo. Escreve partições contra um schema que mudou sem revisão, que é exatamente o "alargar em silêncio" que a mensagem de erro de `_observe` recusa.
- *Continuar quebrando.* Honesto, e incompatível com um cron. Um crawl de 1.767 partições que morre na partição 900 por um campo novo perde as 867 restantes por um evento que o design já esperava.

**Impacto:** os eventos de drift viram o artefato de qualidade de dados que M1 já prometia, e a fila de quarentena vira uma linha da página que se autoavalia. `UnknownField` continua sendo o gatilho — muda quem o pega e o que faz com ele, não o detector.

### AD-018: Em escopo de era, as duas passagens retêm os zips da era; o alvo remoto é decidido antes da crawler (2026-08-14)

**Decisão:** o M1 processa **uma era por vez** e retém os zips daquela era em disco entre a passagem 1 e a passagem 2, descartando ao fechar a era. E o alvo de armazenamento remoto (AD-012) é **decidido e escrito antes** da tarefa da crawler, não depois.

**Razão:** AD-011 precificou as duas passagens como "~40 linhas e uma segunda leitura do zip, cacheada depois". É verdade por partição e falso por era: a passagem 1 precisa varrer **todas** as partições da era antes que a passagem 2 escreva **qualquer** uma. Junto com a regra "stream → transform → discard: os 111 GB nunca estão todos em disco", sobravam duas saídas e nenhuma estava escrita — baixar cada partição duas vezes (~5,4 h de transferência contra as 2,7 h medidas) ou reter bytes. Reter por era limita o pico ao maior bucket em vez do corpus, e mantém a transferência no número medido.

A ordem da crawler contra o armazenamento é o mesmo tipo de dívida: uma crawler que escreve em disco local e depois migra para o remoto é reescrita, não configuração.

**Trade-off:** o pico de disco deixa de ser ~1,5 GB por partição e passa a ser o tamanho da maior era. É um número que ninguém mediu ainda — o M1 mede antes de rodar, a partir do manifesto, que já traz o tamanho de cada partição.

**Impacto:** o M1 ganha um limite de disco explícito no lugar de uma suposição, e a decisão de AD-012 sai de "revisitar em M1" para "primeira tarefa de M1".

### AD-019: O round trip por era ganha dono, e a página diz quais eras foram verificadas (2026-08-14)

**Decisão:** o teste de round trip por era vira uma feature de M1 rodando **em agenda, uma partição por era**, separada do CI de push. O CI de push continua no fixture de ~100 relatos. A página publica quais eras foram verificadas e quando.

**Razão:** `PROJECT.md` §Scope promete "a round-trip integrity test in CI, run per era". `spec.md` P1 AC5 restringe o CI ao fixture, que é a decisão certa para o push — 22 s de download por commit não se paga. E M1–M5 nunca voltavam ao assunto, então a prova central do projeto encolhia em silêncio: de M1 em diante "lossless" seria testado sobre 100 relatos de um export, enquanto o corpus cresce para 91 buckets com forma comprovadamente dependente da era (L-007, L-006).

Um item de escopo v1 sem milestone dono não é escopo, é intenção.

**Trade-off:** o job agendado baixa uma partição por era, e `Tables.load` segura uma partição inteira em dicts Python (266 MB para 4,62 MB de Parquet, T10). É sequencial e cabe no teto de 500 MB por partição, mas é o job mais caro do projeto.

**Impacto:** "byte-identical" passa a ter alcance declarado em vez de alcance presumido. É a diferença entre a afirmação do README ser verdadeira e ser verdadeira sobre o fixture.

### AD-020: `safetyreportid` repetido é contado, e o round trip recusa o id ambíguo (2026-08-14) — IMPLEMENTADO

**Decisão:** `write_partition` conta ids repetidos e grava `repeated_report_ids` no `metrics.json`, mantendo as duas linhas. `Tables.from_rows` levanta `BrokenTables` quando um id aparece duas vezes em `report`.

**Razão:** `spec.md` §Edge Cases já mandava "record the count and keep both" e nada contava. Pior: `Tables.from_rows` chaveava os relatos por `safetyreportid` num dict, então um id repetido descartava uma linha em silêncio, enquanto `_by_report` fundia as linhas de medicamento dos dois relatos numa lista só. O round trip é a única prova de que "lossless" é verdade, e estava chaveado num campo cuja unicidade nunca foi checada — em um projeto cuja premissa de M2 inteira é que o FAERS tem duplicatas.

As duas metades são deliberadamente diferentes. A ingestão **conta e mantém**, porque dedupe é M2 e jogar fora na escrita seria decidir M2 na ingestão. A reconstrução **recusa**, porque com dois relatos sob o mesmo id não existe informação sobre qual array pertence a qual — e uma reconstrução que chuta isso passaria no teste sem ser o inverso da escrita, que é a forma de falha de L-008.

**Trade-off:** um set de ids por partição na escrita, limitado a 12.000 entradas, e uma partição com ids repetidos passa a ser não-reconstruível até M2 existir. É o comportamento correto: ela já era não-reconstruível, só que em silêncio.

**Impacto:** medido na partição de 2025 — **0 ids repetidos em 12.000**. A suposição valia; agora ela é verificada por partição, e M1 descobre onde ela deixa de valer em vez de herdar o número.

### AD-021: O "<5 s" da G1 vira uma query nomeada, medida em M1 (2026-08-14)

**Decisão:** a medida de sucesso da G1 passa a nomear a query — contagem de pares medicamento-evento distintos sobre o corpus inteiro, com a lista de exclusão aplicada — e o alvo passa a ser **medido em M1 sobre as partições já ingeridas**, com o número publicado seja ele qual for. O `<5 s` deixa de ser critério e vira expectativa prévia até haver medição.

**Razão:** "uma única query DuckDB sobre o corpus completo retorna em <5s num laptop" não dizia qual query, e a única medição existente é 0,13 s sobre 12.000 relatos — 1/1.767 do corpus. Pior, o caminho que a testaria está fechado por construção: `_directory` levanta `PrrError` quando há mais de uma partição ingerida, porque o PRR é reportado por partição. O particionamento year/quarter também não ajuda: a query da G1 é um `GROUP BY` de corpus inteiro sobre ~178M linhas de medicamento contra ~75M de reação, sem poda de partição.

É a meta que justifica a arquitetura de armazenamento para o leitor, e era a única das quatro sem nenhum dado por trás. L-002 existe exatamente sobre isso.

**Trade-off:** o número medido pode ser ruim, e aí a G1 muda ou a arquitetura de consulta muda. Descobrir isso em M1 custa uma tarde; descobrir em M5 custa o argumento.

**Impacto:** M1 ganha uma tarefa de medição, e `prr._directory` ganha um caminho multi-partição — hoje ele recusa, e a recusa é o que impede a medida de existir.

### AD-022: A procedência da página publicada é checada no CI (2026-08-14) — IMPLEMENTADO

**Decisão:** o cabeçalho de `reports/data/prr_top.csv` — `partition`, `export_date`, `min_count` — é lido por `export.provenance()` e conferido contra o pin versionado em `data/manifest/` e o `schema/` da partição, em testes que rodam no CI de push.

**Razão:** T17 declarou o custo com honestidade — a página lê um CSV versionado e nunca toca `data/parquet/`, então ela pode discordar do pipeline e nada falha. A mitigação era a procedência no cabeçalho, que só ajuda quem abre o arquivo. `make site` regenera antes de renderizar; o workflow de publish só roda `quarto render`; o CI não olhava o CSV.

Em M0 — um gráfico, um CSV, tudo commitado junto — o risco é pequeno. O refresh agendado de M1 muda a natureza dele: os números passam a mudar sozinhos e a página não.

**Trade-off:** o CI não pode regenerar o CSV, porque `data/parquet/` é gitignored e baixar a partição a cada push é o que AC5 do P1 recusou. Então a checagem é de procedência, não de valor: ela pega uma partição sem pin e uma data de export que não bate, e **não** pega um CSV gerado com a lista de exclusão antiga sobre a partição certa. Isso fica com o job agendado de AD-019.

**Impacto:** L-012 outra vez, na forma geral — uma restrição que o ambiente não impõe é uma restrição já violada em algum lugar que ninguém olhou. Verificado hoje: o CSV commitado reproduz byte-idêntico a partir do Parquet local, então isso é uma guarda ausente e não uma divergência viva.

---

### AD-025: a junção entre as cinco tabelas é uma chave substituta posicional, e `safetyreportid` vira atributo (2026-08-18)

> Numerada 025 porque é a proposta que o design da M1 já reservava com esse número. As 023, 024 e 026 continuam vazias, à espera das T3, T8 e T7.

**Remedido contra o export de 2026-08-17 antes de decidir**, porque todo número de B-004 e L-013 vinha de bytes que não existem mais (L-014). O que mudou não é só a contagem:

| | export 10/08 | export 17/08 |
|---|---|---|
| ids repetidos em `2004q1/0001-of-0005` | 6 de 12.000 | **3 de 11.997 distintos** |
| documentos envolvidos | 12 | **6** |
| ids repetidos em `2025q1/0001-of-0028` | 0 | **0** |
| `transmissiondate` ausente | — | **0 de 24.000, nas duas partições** |
| `(safetyreportid, transmissiondate)` repetidos | — | **0 nas duas partições** |

**E a caracterização dos pares estava errada.** L-013 disse que "cada par difere em `transmissiondate` e em mais um campo — `companynumb` num caso, `primarysource` noutro" e concluiu "duas submissões distintas debaixo de um id só". No export corrente, **os três pares diferem em `transmissiondate`, e dois deles não diferem em mais nada**. O terceiro, `4305706-0`, difere em **3 campos de 4.890**, e os outros dois são a mesma lista de reações com um termo MedDRA recodificado — `TUMOUR HAEMORRHAGE` virou `TONGUE HAEMORRHAGE` entre 29/11/2004 e 07/01/2005, e a lista é ordenada, então o termo mudou de posição junto.

Isso não são dois documentos sem relação. É **um caso e seu follow-up** — que é exatamente o que o FAERS produz, e o que uma reanálise ponto-no-tempo existe para enxergar.

**Decisão:** `report` ganha `ordinal` (int, a posição do relato dentro da partição, atribuída por `enumerate` na passagem 2). `ordinal` é a chave de junção das cinco tabelas; as filhas passam a chavear em `(ordinal, seq)`. **`safetyreportid` permanece como coluna do `report`, nunca descartado** — é o identificador público do relato e o round trip precisa dele. Globalmente um relato é `(partição, ordinal)`, e a partição já está no caminho hive do Parquet.

**Razão:** a chave de junção de cinco tabelas sobre 20,7 milhões de relatos não pode depender de uma medição. `ordinal` não colide por construção, em nenhuma era, sem que ninguém precise conferir. Esta é a segunda vez que o projeto escolhe uma chave: a primeira foi `safetyreportid`, escolhida com a evidência de uma partição de 2025, e custou este bloqueador.

**Alternativa rejeitada — a chave natural `(safetyreportid, transmissiondate)`.** Ela é sedutora agora, e é a mesma sedução de antes com outro nome: única em 2 partições de 1.767. Se colidir na partição 900, a correção é migrar cinco tabelas no meio da colheita. E ela é larga — duas colunas, uma delas string, replicadas em quatro tabelas filhas.

**Alternativa rejeitada — deduplicar na ingestão.** Agora com razão melhor do que a de B-004: o par `4305706-0` difere num termo MedDRA. Colapsar os dois documentos descarta a revisão, que é precisamente o que a M4 existe para observar.

**Alternativa rejeitada — round trip só onde os ids são únicos.** Zero código, e publica um buraco exatamente onde a fonte é mais suja, que é onde a prova mais vale.

**Trade-off, dito por inteiro:** `ordinal` não carrega informação nenhuma. **Não é estável entre exports** (L-006), e L-014 acabou de provar que os exports rotacionam em dias reescrevendo conteúdo. Uma inserção a montante desloca todos os ordinais depois dela. **Portanto a M4 não pode usar `ordinal` como identidade durável** — um sinal datado por ordinal é um sinal datado por número de linha, e ele muda sem que o caso mude.

**O que preenche esse buraco, e sai de graça:** a varredura da M1 lê as 1.767 partições antes de a colheita escrever um byte. Ela conta as colisões de `(safetyreportid, transmissiondate)` sobre o corpus inteiro — um contador numa passagem que já vai acontecer. Se o par for único sobre 20,7 milhões de relatos, a M2 e a M4 ganham uma identidade derivada de conteúdo, que sobrevive a um re-export porque é recomputável a partir dele. Se colidir, aprendemos isso antes de virar migração. **Nos dois casos a chave de junção não muda** — é essa separação que torna a decisão barata: junção por construção, identidade por medição.

**Impacto:**
- **T2** implementa: `normalize.split`, as três tabelas filhas, `roundtrip.Tables` e `reconstruct`, e os schemas congelados das duas partições já ingeridas.
- **`analysis/prr.py` conta errado hoje, e a decisão conserta.** O 2×2 é montado com `count(DISTINCT safetyreportid)` (L-009). Em `2004q1/0001-of-0005` isso dá **11.997 e não 12.000** — os três pares colapsam em silêncio, e o denominador de toda razão da partição fica 3 relatos curto. São 0,025% e não muda conclusão nenhuma; o que importa é que ninguém tinha visto, e que numa partição mais suja o mesmo mecanismo erra mais.
- **`repeated_report_ids` do `metrics.json` fica.** Deixa de ser o sintoma de um bloqueador e passa a ser uma medida de qualidade da fonte por partição — que é o que a M2 vai querer ler.
- **Uma pendência para a T2, não medida:** os buckets `YYYYqN` gravam `year=/quarter=/part=` e o bucket `all_other` grava `bucket=/part=` (`write.partition_dir`). A tupla que qualifica o `ordinal` globalmente não tem a mesma forma nas duas. Nenhuma partição `all_other` foi ingerida ainda, então isto está escrito como consequência de desenho e não como medição.

**Fecha B-004.**

---

### AD-026: marcadores de forma da fonte, e a remoção de nulls deixa de existir (2026-08-21)

> Numerada 026 porque é a que o design da M1 reservava para a T3. Decidida contra os números da remedição de 20/08/2026, que já são do export de 17/08 — a revisão de arquitetura exigiu remedir antes de escrever o AD, e a medição está feita.

**Decisão:** cada uma das quatro tabelas de fato ganha uma coluna `source_shape` (`list<string>`) — a lista dos campos daquela linha que chegaram **explicitamente nulos** ou como **array vazio**. O marcador guarda o caminho pontilhado dentro do objeto que a linha representa: `receiver` no `report`, `drugtreatmentdurationunit` na linha de medicamento, `pt_patientdeath.patientdeathdate` para o null dentro do struct — sem ele o marcador não alcança 2 dos 5 caminhos de null de 2004. A reconstrução lê a coluna e reemite `null`, `[]`, ou omite a chave, conforme o marcador diga. Com isso `_without_nulls` **deixa de existir** dos dois lados da comparação — não passa a ser justificado melhor, sai do código — e a comparação do round trip compara os documentos crus.

**Razão:** L-008 provou que remover nulls dos dois lados só é um inverso se a fonte nunca carregar null explícito, e disse em letras que a medição de 2025 não transfere. Não transferiu: em `2004q1/0001-of-0005` são **12.000 de 12.000 relatos** com pelo menos um null explícito, em cinco caminhos — `receiver` 12.000 · `primarysource` 3.150 · `drug[].drugtreatmentdurationunit` 1.560 · `patientdeath.patientdeathdate` e `...dateformat` 1.027 cada. O round trip da era antiga hoje não prova nada: os 11.988 "idênticos" só concordam depois que a remoção apaga a diferença dos dois lados, que é exatamente a comparação autocertificante que L-008 mandou desconfiar. A informação que falta já chega ao `split` — o parser materializa `"receiver": null` como chave presente com valor `None`, e é a escrita que a descarta, porque Parquet não tem ausência. O marcador preserva o que o parser viu em vez de deixar a comparação inventar.

Só um dos cinco caminhos mistura ausente com null (`drugtreatmentdurationunit`: ausente 40.780 · null 1.560 · valor 1.284). Nos outros quatro o null do Parquet já é inequívoco. O mecanismo cobre os cinco do mesmo jeito porque distinguir por caminho seria uma regra medida numa partição e aplicada a 2004–2025 — o erro de L-006 outra vez.

**O mesmo mecanismo fecha o todo de L-007.** Array vazio indistinguível de campo ausente era um buraco sem instância conhecida, com 1.767 partições pela frente para produzir uma. Zero child rows não dizia se a fonte tinha `[]` ou não tinha o campo; agora diz, porque o marcador registra o `[]`. Continua sem ocorrência medida nas duas partições — o que fecha é o mecanismo, não um número.

**O que o marcador não cobre, de propósito:** `openfda: {}` (502 vezes em 2004, 476 em 2025) já é distinto de `openfda` ausente pela chave da dimensão — chave nula é ausente, chave que hasheia `{}` é o bloco vazio, e é isso que consertou o L-005. Nenhum marcador para objeto vazio; duplicar a distinção em dois mecanismos seria duas formas de mentir em vez de uma forma de dizer.

**Trade-off:** uma coluna nova em quatro tabelas, escrita por `split` iterando o registro — nenhum nome de campo hardcoded, que é o não-negociável do projeto. Em 2004 o valor típico é `["receiver"]` e dicionariza para quase nada; o Parquet já cresceu 2,78 → 3,14 MB com o `ordinal` da AD-025 e o marcador pesa menos que ele. Contra isso: a largura das tabelas entra na conta de colisão de nome (`source_shape` entra nos nomes reservados de `_pin_pipeline_columns`, ao lado de `ordinal`) e a reconstrução ganha um ramo por caso — `null`, `[]`, ausente — que só existe para servir a prova. É preço da afirmação central do projeto, não de uma feature.

**Alternativas rejeitadas, com o custo de cada uma:**

- *Uma máscara por campo anulável, nas cinco tabelas.* Exato, e caro de um jeito que não é bytes: as quatro tabelas de fato somam **49 colunas em 2004 e 73 em 2025** (contadas nos schemas congelados), então são dezenas de máscaras booleanas quase todas falsas, presentes em todo schema diff, toda comparação entre eras e toda query que lista colunas. E a lista de "campos que merecem máscara" teria de vir de algum lugar — derivá-la à mão é a keep-list que L-005 baniu, e derivá-la por medição a torna mais uma constante de export.
- *Declarar o null explícito como normalização anunciada.* Barato hoje, e o custo é a afirmação: "byte-identical" passaria a significar "idêntico depois de descartar nulls explícitos" — o que, em 2004, é descartar um valor real em 12.000 de 12.000 relatos, incluindo `primarysource`, que carrega a qualificação do reportante e pesa sinal na M3. É também a "identidade após normalização não declarada" que a AD-013 recusou para `reportduplicate`; aceitá-la aqui seria recusar a forma do erro num caso e comprá-la no outro.
- *Escopo declarado: o round trip prova só as eras sem null explícito.* Zero código, e o custo é o portão: a T6 exige as duas eras verdes antes da Fase 3, então a colheita não começa — e, começando, publicaria uma prova cujo alcance medido até hoje é uma partição de 2025. É a alternativa que a AD-025 recusou na mesma posição ("publica um buraco exatamente onde a fonte é mais suja"), com o agravante de que aqui o buraco é a era inteira.

**Impacto:** a T4 implementa — `split` grava o marcador, `reconstruct` reemite conforme ele, `_without_nulls` sai dos dois lados, `test_the_source_carries_no_explicit_nulls` é **removido** (se ele ainda fizer falta, o AC4 de P1 §"Ausente, nulo e vazio" não foi cumprido), e um teste novo defende cada um dos três casos. As duas partições são reingeridas e o Verify da T4 espera 12.000 linhas com `source_shape` não vazio em 2004 — os mesmos 12.000 relatos que a remedição mediu, agora reconstruídos em vez de recusados. Fecha B-007 junto: `make all` volta ao verde quando a comparação crua passar na era antiga.

**Fecha B-005.**

---

### AD-027: pin obsoleto é recusado por nome, e mover de export é um ato explícito (2026-08-18) — IMPLEMENTADO

> Numerada 027 de propósito: 023 a 026 estão reservadas para as quatro tasks de decisão da M1 (`.specs/features/m1-corpus-completo/design.md`), que ainda não foram escritas aqui.

**Decisão:** `fetch.ensure_local` compara o `export_date` do pin gravado com o `export_date` que o `resolve()` acabou de ler do manifesto vivo. Divergiu, levanta `StalePin` e não faz nada. Mover a partição para o export corrente exige `--repin`, que existe em `hindsight fetch` e em `hindsight ingest`, apaga o zip cacheado, baixa limpo sem retomada, grava o pin novo e implica `--reinfer`.

**Razão:** o guarda que existia comparava o zip em cache contra o **pin**, nunca contra o export publicado. Os dois batiam, então `hindsight ingest` rodava feliz sobre bytes de uma semana antes e nada falhava onde alguém olhava. É a forma exata de L-012, e a revisão de arquitetura da M1 a encontrou como o achado mais caro dela.

**Trade-off:** uma partição parada num export antigo passa a exigir uma flag para andar, e a flag carrega uma consequência que nenhum comando consegue executar por você — remedir. `--repin` implica `--reinfer` porque o schema congelado descreve os bytes antigos, mas ele não sabe reescrever um número que mora numa frase do relatório.

**Alternativa rejeitada:** *repinar sozinho quando o export muda.* Silencioso na direção oposta: o corpus andaria de export sem ninguém decidir, e todo número medido viraria falso sem aviso.

**Impacto:** fecha o achado 1 da revisão no nível do mecanismo. **Não fecha no nível do plano** — a M1 leva semanas e o export rotaciona em dias, então falta a regra de que um export novo invalida o mapa de eras em vez de continuá-lo. Isso é decisão da Fase 2 da M1 e ainda não está escrita.

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

### ~~B-005: a normalização que faz o round trip passar não é um inverso na era antiga~~ — RESOLVIDO 2026-08-21

**Resolução:** fechado pela **AD-026**. As quatro tabelas de fato ganham `source_shape`, a lista dos campos que chegaram explicitamente nulos ou como array vazio, com caminho pontilhado dentro da linha. A reconstrução reemite `null` e `[]` onde o marcador diga, `_without_nulls` deixa de existir dos dois lados e a comparação vira crua. O mesmo mecanismo fecha o todo de L-007 — array vazio indistinguível de ausente passa a ser registrado, mesmo sem instância conhecida. A **T4** da M1 implementa; até lá o round trip continua recusando 2004 na precondição, que é o estado vermelho declarado em **B-007**.

**Descoberto:** revisão do PR da T19, ao perguntar quanto da era antiga a recusa por id estava jogando fora. A resposta expôs um problema maior que o id.

**O fato, remedido em 20/08/2026** contra o export de 17/08, caminhando recursivamente todo valor dos 24.000 relatos das duas partições: em `2004q1/0001-of-0005`, **12.000 de 12.000 relatos carregam pelo menos um null explícito**, e o conjunto inteiro de caminhos que produzem isso são cinco.

| caminho | ausente | null | valor |
|---|---|---|---|
| `receiver` | 0 | **12.000** | 0 |
| `primarysource` | 0 | 3.150 | 8.850 |
| `patient.drug[].drugtreatmentdurationunit` | 40.780 | 1.560 | 1.284 |
| `patient.patientdeath.patientdeathdate` | | 1.027 | |
| `patient.patientdeath.patientdeathdateformat` | | 1.027 | |

Em `2025q1/0001-of-0028` são **zero**, o que confirma L-008 sobre a era nova.

**Três números desta entrada estavam errados.** `patient.drug: null` **não existe**; o caminho é `patient.drug[].drugtreatmentdurationunit` e são 1.560 linhas de 43.624, não 1.375 relatos. `primarysource` são 3.150 e não 3.165. `patient.patientdeath.*` são 1.027 em cada um de dois campos, não 1.139.

**Dois fatos que a varredura anterior não podia ver, porque era rasa.** Os nulls de `patientdeath` estão **dentro de um struct**, então distinguir ausente de nulo exige caminho pontilhado e não nome de campo raso. E **`patient.drug[].openfda: {}` ocorre nas duas eras**, 502 vezes em 2004 e 476 em 2025, que é exatamente o caso de L-005 e a razão da regra `if o is not None`. Ele fecha hoje porque a linha da dimensão existe e a remoção de nulls varre as 18 colunas nulas antes da comparação. Tirar essa remoção sem pôr um marcador no lugar **quebraria o round trip de 2025, que hoje está verde**.

**Só um dos cinco caminhos mistura ausente com null**, o `drugtreatmentdurationunit`. Nos outros quatro o null do Parquet já é inequívoco. São 2 partições de 1.767, e a varredura da Fase 2 mede o resto.

**Por que isso é pior que B-004.** L-008 é a lição de que remover nulls dos dois lados antes de comparar só é o inverso do que o Parquet fez **se a fonte nunca carregar um null explícito** — caso contrário a remoção apaga um valor real dos dois lados, os dois passam a concordar, e o teste construído para pegar perda silenciosa vira o mecanismo que a esconde. L-008 mediu **0 nulls explícitos** e concluiu que a comparação significava o que dizia. Aquela medição era de 2025, e L-008 já dizia em letras que ela não transfere.

Ela não transferiu. Medido agora com o guarda por relatório em vigor: dos 12.000, **12 são recusados por id ambíguo e 11.988 reconstroem idênticos — depois de remover os nulls dos dois lados.** Esse 11.988 **não é prova de nada**: é exatamente a comparação autocertificante que L-008 descreve. A leitura correta não é "99,9% da era antiga é comprovadamente lossless", é "não sabemos, e o número que parece dizer que sabemos é o número que L-008 mandou desconfiar".

**O caminho de perda é concreto**, não teórico, e não é o que estava escrito aqui. `report.receiver` chega como `null` explícito nos 12.000 relatos, `write_partition` grava a coluna inteira nula, e `reconstruct` passa por `_without_nulls`, que apaga a chave. A fonte tinha `"receiver": null`, o rebuild não tem `receiver`. Só a remoção de nulls dos dois lados faz os dois parecerem iguais. Vale igual para `primarysource` em 3.150 relatos e para os dois campos de `patientdeath` em 1.027.

**Por que não vazou:** `test_the_whole_partition_rebuilds_from_parquet` afirma a precondição por relatório antes de comparar (T11, que foi o que L-008 comprou). Em 2004 ela falha no primeiro relato. O teste **recusa** em vez de mentir, que é o desenho funcionando. Mas o resultado prático é que o round trip não tem nada a dizer sobre a era antiga.

**A decisão que falta, e que nenhuma task contém:** o round trip precisa distinguir *ausente* de *explicitamente nulo*. As opções não são equivalentes:
- *Marcar presença por campo* — resolve de verdade e custa uma coluna de máscara ou um sentinela por campo anulável, em cinco tabelas.
- *Declarar o null explícito como normalização anunciada* — barato, e é exatamente a "identidade após uma normalização não declarada" que AD-013 recusou em outro contexto.
- *Escopo declarado: o round trip prova as eras sem null explícito, e a página diz quais são* — zero código, e publica o buraco onde a fonte é mais suja.

**Resolver antes de:** M1 ligar o job por era de AD-019, junto com B-004. Este é o que decide se ele tem o que provar; B-004 decide de quantos relatórios.

### B-006: a `dim_openfda` é deduplicada por partição, então ela multiplica em vez de convergir — ABERTO 2026-08-16

> **Remedido em 18/08/2026 após o repin (L-015): 872 de 1.197, 72,8%, projeção ~3,60 GB.** As três afirmações que sustentam o bloqueador continuam de pé — a chave já é global, só a escrita é por partição, e a dimensão sozinha come a maior parte do orçamento da G1. A revisão de arquitetura da M1 acrescentou duas coisas que esta entrada não tem: a razão que a AD-024 usa para rejeitar a compactação posterior é falsa (não existem chaves locais), e uma dimensão global em memória custa ~10 KB por bloco, o que a torna incompatível com o teto de 500 MB e com o round trip. Ver os achados 2, 3 e 4 da revisão.
>
> **Remedido de novo em 20/08/2026, medindo os bytes da partição em vez de projetar a partir dos fatos:** `dim_openfda` é **64% dos bytes** da partição de 2004 (1,91 MB de 3,00 MB) e **59%** da de 2025 (2,46 MB de 4,17 MB). A média de 2,19 MB × 1.767 dá **~3,9 GB**, não 3,60. E a união das duas partições é **2.442** blocos contra soma ingênua de 3.314: 26,3% de economia entre as duas partições mais distantes que o corpus tem.

**Descoberto:** decomposição da M1, ao dimensionar o corpus com a dimensão contada e não só os fatos.

**O fato:** a chave da dimensão já é global por construção — 16 dígitos do SHA-1 do bloco em JSON canônico, então dois blocos idênticos em partições diferentes geram a mesma chave. **Só a escrita é por partição:** `write_partition` cria uma `OpenfdaDimension` nova a cada chamada e cada diretório recebe seu próprio `dim_openfda.parquet`. A ARCHITECTURE já dizia isso em letras — "a deduplicação é interna à partição, não de corpus" — sem que ninguém tivesse multiplicado o número por 1.767.

**A medição, sobre as duas partições ingeridas** (números do export de 10/08; contra o de 17/08 são 1.197, 2.117, interseção **872** e união **2.442**)**:** 2004 tem 1.128 blocos, 2025 tem 2.251, a interseção é **866** e a união **2.513**. Ou seja **76,8% da dimensão de 2004 é redundante contra uma partição 21 anos depois** — e essas são as duas partições mais distantes que o corpus tem. Entre partições adjacentes a sobreposição só pode ser maior.

**O que custa:** ~2,19 MB por partição × 1.767 ≈ **3,9 GB só de dimensão** (medido em 20/08; a primeira estimativa dizia 3,7 GB), contra a projeção de 1,7–3,6 GB de fatos de L-013. Total 5,6–7,5 GB. **A G1 promete `< 5 GB` e não sobrevive a isso.** L-003 dizia que a dimensão "converge em vez de multiplicar, porque os mesmos medicamentos recorrem em toda partição" — a afirmação está certa sobre o *conteúdo* e errada sobre o *código*, que nunca a implementou.

**O que ajuda:** `dim_openfda` tem as **mesmas 19 colunas em 2004 e em 2025**, conferido nos dois schemas versionados. É a única das cinco tabelas cuja forma não depende da era, o que torna uma dimensão única sobre o corpus segura por schema.

**A decisão que falta:** dimensão global, por era, ou por partição com mais espaço. A proposta do design da M1 é AD-024, global, com a colheita mantendo em memória só o conjunto de chaves já vistas — e quantas chaves o corpus tem é a incógnita que dimensiona esse `set`, medida na varredura antes de a colheita começar.

**Resolver antes de:** a colheita da M1. Uma colheita de 1.767 partições escrita contra uma dimensão por partição não é uma colheita a corrigir depois, é uma colheita a refazer. Task **T8** da M1.

### ~~B-004: `safetyreportid` não identifica um relato na era antiga~~ — RESOLVIDO 2026-08-18

**Resolução:** fechado pela **AD-025**. A junção entre as cinco tabelas passa a ser `ordinal`, a posição do relato dentro da partição, que não colide por construção em nenhuma era. `safetyreportid` permanece como coluna do `report` — vira atributo, e a colisão vira dado da M2 em vez de obstáculo. A **T2** da M1 implementa; até lá o código continua chaveando em `safetyreportid` e `reconstruct` continua recusando o id ambíguo pelo nome (AD-020).

**Remedido antes de decidir, e a caracterização mudou.** Contra o export de 2026-08-17 são **3 ids repetidos em 12.000**, não 6, e os pares **não são "duas submissões distintas" como L-013 afirmou**: os três diferem em `transmissiondate`, dois deles não diferem em mais nada, e o terceiro difere em 3 campos de 4.890 — um termo MedDRA recodificado numa lista ordenada. É um caso e seu follow-up. Ver AD-025 para a tabela completa e para a chave natural `(safetyreportid, transmissiondate)`, que é única nas duas partições e mesmo assim foi rejeitada como chave de junção.

**O que ficou aberto de propósito:** `ordinal` não é estável entre exports (L-006), então a identidade durável de que a M4 precisa não é ele. A varredura da M1 mede as colisões de `(safetyreportid, transmissiondate)` sobre o corpus para responder isso, e é um contador numa passagem que já vai acontecer.

**O que este bloqueador não resolvia e continua sem resolver:** o round trip na era antiga. Isso é **B-005**, e é maior — B-004 custava 6 documentos em 12.000; B-005 custa os 12.000.

### B-007: `make all` reprova enquanto a B-005 estiver aberta — ABERTO 2026-08-18, por decisão

**Descoberto:** ao consertar o arnês do round trip, que tinha a partição de 2025 fixa no arquivo de teste e por isso rodava a mesma era duas vezes quando o Verify pedia duas (achado 5 da revisão de arquitetura da M1).

**O fato:** com o arnês parametrizado, `make all` descobre as partições ingeridas e testa todas. Em `2004q1/0001-of-0005` o round trip para no primeiro relato, na precondição de null explícito — `report.receiver` é null nos 12.000 relatos da partição. **Uma verde, uma vermelha.** O arnês antigo dizia duas verdes rodando 2025 duas vezes.

**Isto não é regressão.** É a B-005 aparecendo pela primeira vez num comando que alguém roda. O teste recusa em vez de mentir, que é o desenho funcionando (T11).

**A decisão, tomada em 18/08:** deixar vermelho. As alternativas eram `make all` passar `PARTITION` explicitamente — o que reintroduz de forma declarada o "o default esconde 2004" que o achado 5 acabou de abrir — e marcar 2004 como `xfail`, que fica verde hoje e vira mentira na direção oposta no dia em que a T4 consertar e ninguém tirar a marca. Vermelho é a única em que o que aparece na tela e o estado do projeto são a mesma coisa. É o padrão nº 2 do README aplicado ao próprio build.

**Consequência para a página:** a afirmação de que `make all` reproduz a cadeia inteira num clone limpo passa a ter escopo — ela vale para a era de 2025 e não para o corpus. Precisa aparecer assim onde estiver escrita.

**Resolver:** T4 da M1, que é quem distingue ausente de explicitamente nulo. Fecha junto com B-005.

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
>
> ✅ **T19 mediu a segunda, e ela desce a projeção.** `2004q1/0001-of-0005` comprime **78,8×** — muito pior que 175× — e mesmo assim sai **menor em bytes**: 2,78 MB contra 4,62 MB, com os mesmos 12.000 relatos. A razão caiu porque a fonte é menos redundante, não porque o pipeline é pior. Só os fatos projetam **1,7 GB (densidade 2004) a 3,6 GB (densidade 2025)** sobre 20.692.690 relatos, com 23% do corpus anterior a 2015. **A razão a citar depende da era; o número de corpus a citar é a faixa.** Ver L-013.

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

> **Corrigido em 20/08/2026:** arrays vazios continuam sem ocorrência, mas **objetos vazios têm**. `patient.drug[].openfda: {}` aparece 502 vezes em 2004 e 476 em 2025. Ele não cai no buraco descrito acima porque a linha da dimensão existe e a chave é que decide se `openfda` é reemitido — ver B-005.

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

**Solution:** followed the pairs back to the reports. **Ten** reports carry `Onychomycosis` — this lesson first said nine, and its own 2×2 already contradicted it, since a = 9 plus c = 1 is ten reports carrying the event. The tenth names three drugs and is an ordinary report; the **nine** that make the cluster each list **66–96 distinct drugs**. All nine are Canadian, all `serious=1`, eight of the nine record a patient age of 40, and they were received between January and March 2025. They were filed by **six different manufacturers** — Purdue, JNJ, Sandoz, Biocon, BEH. Two share the identical `companynumb` `CA-SANDOZ-SDZ2024CA107730` **and an identical ten-term reaction list**: the same case, filed twice. Across all nine, 19 drugs are common to every report and the pairwise drug-list Jaccard runs 0.38 / 0.48 median / 0.91. They carry 41 `report_duplicate` entries between them.

So it is one patient — or a very small number — on a long medication list, reported independently by every manufacturer whose product was on that list. Every drug in the list gets a=9 against every event in it. That is the entire top of the table.

**Two fixes that look obvious and are not:**

- **Restrict to suspect drugs.** `drugcharacterization` distinguishes suspect (42,665 rows), concomitant (28,554) and interacting (771), and disproportionality is conventionally run on suspect drugs only. It does nothing here: in these nine reports **every one of the ~90 drugs is marked suspect**. Measured before it was believed, which is the only reason it did not get shipped as a fix.
- **Apply the screening criterion.** Evans (AD-014) keeps **24,299 of 28,540 pairs — 85%** — and every pair named above clears it comfortably. χ² is *large* precisely because the expected count is 0.015, so PRR and χ² agree enthusiastically about the same bad input. A threshold cannot tell a duplicate from a signal; both statistics are functions of a, and a is what is wrong.

**Prevents:** publishing a signal table as a finding. It also converts AD-001's claim — that entity resolution and deduplication are load-bearing milestones rather than chores — from an assertion into a measurement, which is what M0 is for. At 1,767 partitions this is not one bad cluster to route around: 40 reports per 12,000 carry more than 100 drug rows (L-009), roughly 69,000 across the corpus, and each one manufactures pairs across its whole medication list. **M2 is the fix, and until M2 exists every number in this table is provisional in the strong sense — not "approximate", but "attributable to the wrong drug".**

### L-011: 1% of the reports manufacture two thirds of the pair table

**Context:** T13 found nine near-duplicate reports at the top of the ranking (L-010) and left them looking like a bad cluster to route around. T14 had to decide what the M0 page publishes, which meant answering a question T13 never asked: how much of the table is like that?

**Problem:** "the top ten rows are contaminated" is an anecdote. A page built on it invites the reader to assume rows eleven onward are fine.

**Solution:** measured the whole table against a rule rather than against those nine ids. A report's *breadth* is how many distinct drugs it names; a pair's **crowding** is the median breadth of the reports behind its `a`. Both are computed from the data, and the cut is the partition's own 99th percentile rather than a constant — a number written into the source would be measured on one partition of one export and then applied to a corpus spanning 2004–2025, which is the mistake L-006 is about.

The distribution has the gap that makes the cut usable: **median report names 2 distinct drugs, the 99th percentile names 27, the widest names 121.** The L-010 cluster names 66–96, so nothing sits on the line arguing about which side it belongs on.

Then the number that changed the milestone's deliverable: **125 reports of 12,000 — 1.04% — supply the evidence for 18,946 of the 28,540 pairs. 66.4%.** Evans flags 24,299 pairs and 18,055 of those are crowded. Of the top 100 by PRR, 85 are.

**Solution, the second half.** Removing the crowded pairs is not a fix, and the module says so rather than implying otherwise: a patient on 90 drugs who has an adverse reaction is a real patient, and separating that from a repeated case needs entity resolution, which is M2. But the ranking underneath is worth looking at — the highest-PRR pairs from ordinary reports include **risperidone → gynaecomastia**, a documented prolactin effect. One pair is not a finding. It is the first evidence that the method works once the input is clean.

**Prevents:** publishing a ranking as a result, and the weaker version of the same error — publishing "the top is contaminated" without saying how far down the contamination goes. It also converts AD-001's claim that deduplication is load-bearing from a measurement about nine reports into one about two thirds of the table.

### L-012: The dependency rule was already broken when the check for it was written

**Context:** AD-015 puts the chart stack in a `viz` group so CI never installs it, and T16 added a step asserting `import matplotlib` fails.

**Problem:** it went red on the first run — but not on matplotlib. `tests/test_export.py` imported **pandas**, which arrives as seaborn's dependency and therefore lives in `viz` too. The suite had been passing locally for one reason only: the chart stack was synced on the machine that wrote it. The separation existed in `pyproject.toml` and nowhere else.

**Solution:** the tests read the CSV with the standard library's `csv` instead. Not by widening the group — these tests assert what the *file* contains, and a reader that types the columns for you is testing the reader, so the stdlib is the more honest instrument anyway.

**Prevents:** a dependency boundary that is documentation. The general shape is worth more than the instance: **a constraint the environment does not enforce is a constraint that is already violated somewhere you have not looked**, and the interval between writing AD-015 and CI catching this was one task. It also says something about the local environment — `uv sync --group viz` makes the developer's machine strictly more permissive than CI, so anything CI must reject has to be checked there rather than here.

### L-013: A era antiga é mais barata, e é a única que o round trip não consegue provar

**Contexto:** T19 rodou o pipeline contra `2004q1/0001-of-0005` — a partição mais antiga do export — para descobrir se os números de armazenamento de M1 valem fora de 2025. Todo número deste projeto vinha de uma partição de 2025.

**Problema:** a razão de compressão despencou de **175× para 78,8×**, que era exatamente o cenário que a task mandava tratar como "revise a projeção antes de M1". Só que a leitura óbvia está errada.

**Solução — a razão piorou e o tamanho melhorou.** A partição de 2004 sai com **2,78 MB de Parquet contra os 4,62 MB da de 2025**, com o mesmo número de relatos. A razão caiu porque a *fonte* é menos redundante, não porque o pipeline é pior: 219 MB de JSON contra 807 MB, `openfda` presente em muito menos linhas (1.128 blocos distintos contra 2.251), 36.324 linhas de medicamento contra 71.990. Comprimir 175× um arquivo inchado e 78,8× um arquivo enxuto pode dar o arquivo enxuto menor, e deu.

Então a projeção de corpus **desce**, não sobe:

| | 2004q1/0001-of-0005 | 2025q1/0001-of-0028 |
|---|---|---|
| JSON da fonte | 219,2 MB | 807,5 MB |
| Parquet | **2,78 MB** | 4,62 MB |
| Razão | 78,8× | 175× |
| Fatos por relato | **83 B** | 174 B |
| `dim_openfda` como fatia da saída | **63%** (1,74 MB) | 55% (2,47 MB) |

Sobre 20.692.690 relatos, só os fatos projetam **1,7 GB na densidade de 2004 e 3,6 GB na de 2025**, e 23% do corpus é anterior a 2015. O `< 5 GB` da G1 sobrevive com folga. L-003 pode parar de ser um número com asterisco.

**Depois vem a parte que muda o design.** A partição carrega **6 `safetyreportid` repetidos em 12.000** — 11.994 distintos. *(Export de 10/08. Contra o de 17/08 são 3, com 11.997 distintos — L-015 e AD-025.)* A guarda de AD-020 disparou na primeira exposição real que teve, e o 0-de-12.000 de 2025 era mesmo propriedade de um export e não do corpus.

Os seis pares **não são o mesmo relato duas vezes.** Conferidos contra o zip da fonte, cada par difere em `transmissiondate` e em mais um campo — `companynumb` (`163-20785-04030148` contra `163-20784-04030148`) num caso, `primarysource` ausente contra presente noutro. São duas submissões distintas debaixo de um id só.

> ⚠️ **Este parágrafo não sobreviveu ao repin.** Contra o export de 17/08 são três pares, não seis; os três diferem em `transmissiondate` e dois não diferem em mais nada; e o terceiro difere em 3 campos de 4.890, com um termo MedDRA recodificado. "Duas submissões distintas" era leitura de um export; a leitura que se sustenta é **um caso e seu follow-up**. Ver AD-025.

**A consequência é B-004:** `reconstruct` recusa esses 12 relatórios pelo nome, e `design.md` não pode mais chamar `safetyreportid` de PK. O comportamento está correto — recusar é melhor do que reconstruir chutando qual array pertence a qual relato.

> ⚠️ **Esta lição afirmou primeiro que o id repetido era o que impedia o round trip em 2004. Estava incompleta, e a revisão do PR encontrou a metade maior.** A partição carrega **null explícito em 12.000 de 12.000 relatos**, o que quebra a precondição de L-008 e torna a comparação autocertificante. É **B-005**. Os 11.988 que "reconstroem idênticos" só o fazem depois de remover os nulls dos dois lados, que é precisamente a operação que L-008 mandou não confiar. B-004 custa 12 relatórios; B-005 custa a era inteira.

**E a era antiga é onde M2 tem mais trabalho e menos ferramenta.** O diff de schema:

- `report_drug` tem **16 colunas em 2004 contra 29 em 2025**, e entre as 13 ausentes está **`activesubstance`** — que o PROJECT nomeia como entrada da resolução de entidades de M2. Em 2004 ela não existe.
- **UNII cobre 51,9% das linhas de medicamento contra 82,9% em 2025.** A "cauda longa sem identificador canônico" que L-004 quantificou em ~17% é de **48%** na era antiga.
- **`report_duplicate` tem 0 linhas**: o campo não existe em 2004. `duplicatenumb`, que AD-013 identificou como aquilo em que a deduplicação de M2 junta, não está lá — justamente na era em que os ids colidem.
- `report` perde 8 colunas de 2025 e ganha uma que sumiu depois (`pt_patientdeath`); `primarysource`, `receiver` e `sender` são structs de forma diferente.
- Boa notícia isolada: **`drugstartdate` cobre 32,8% contra 22,5% em 2025.** A análise de tempo até o evento de M3 tem *mais* dados na era antiga, não menos.

**Fronteira de era, que é o que AD-017 precisava:** 24 contra 31 colunas em `report`, 16 contra 29 em `report_drug`, três structs de forma diferente. 2004 e 2025 não são a mesma era por nenhum critério, e o diff de campos é evidência utilizável em vez de uma década escolhida no papel.

**Previne:** dimensionar M1 por uma partição de 2025 e descobrir na partição 900 que o identificador não identifica. Também previne o erro mais caro que estava armado: publicar "byte-identical" como propriedade do corpus quando ela é, hoje, propriedade das eras em que ninguém reusou um id.

### L-014: O openFDA reescreve uma partição no lugar em 8 dias, e o pin detecta sem recuperar

**Medido em 18/08/2026**, ao conferir o achado 1 da revisão de arquitetura da M1. O manifesto vivo publicava `export_date: 2026-08-17`; os pins do M0 diziam `2026-08-10`. Um `HEAD` nas duas URLs fixadas:

| partição | pin (10/08) | export de 17/08 | delta |
|---|---|---|---|
| `2004q1/0001-of-0005` | 46.533.953 B | 69.338.863 B | **+49%** |
| `2025q1/0001-of-0028` | 162.319.793 B | 109.378.959 B | **−33%** |

Mesmos ids, mesmas fronteiras — 5 e 28 partições, 12.000 relatos cada. Não foi rechunking, foi **revisão de conteúdo**. Oito dias.

**A AD-008 previu isto por escrito e aceitou:** *"se o openFDA reescrever uma partição in-place, o SHA-256 detecta mas não recupera o original."* O trade-off venceu em oito dias, o que é mais rápido do que "pin, don't hoard" supunha ao ser escrito. Os bytes de 10/08 não existem mais em lugar nenhum, então todo número que o M0 mediu contra eles é irreproduzível — não errado, **irreproduzível**, que para este projeto é pior.

**O que sobreviveu ao repin, e é a parte útil:** os **conjuntos de campos são idênticos** nos dois exports, tabela por tabela. `report` 24↔24 em 2004 e 31↔31 em 2025, e o mesmo nas outras quatro. A forma do dado não se mexeu; só o conteúdo. Isso é evidência direta para a fronteira de era da M1 — uma revisão de export muda contagem e valor, não caminho de campo, então um mapa de eras derivado do export N tem chance real de sobreviver ao N+1. Uma medição, dois exports; não é uma lei.

**O que não sobreviveu:** quase todo número medido. Ver a tabela em L-015.

**A consequência de desenho, que ainda não tem decisão:** a M1 leva semanas a 6 h/semana e o export rotaciona em dias. Varredura, mapa de eras e colheita virão de exports diferentes se ninguém escrever a regra. AD-027 resolveu o mecanismo — mover de export agora é explícito e nomeado. A regra de plano ("export novo invalida o mapa de eras em vez de continuá-lo") é da Fase 2 da M1 e continua não escrita.

**E reabre AD-008 e AD-012 juntas:** guardar os zips crus no alvo remoto teria tornado o pin recuperável. "Pin, don't hoard" foi escolhido quando ninguém tinha visto o openFDA reescrever nada. Agora viu.

### L-015: Cada número do M0 é propriedade de um export, e o repin de 18/08 mudou quase todos

Remedido sobre o export de 2026-08-17, com o pipeline inteiro reingerido. O que mudou, e o que não:

| | export 10/08 | export 17/08 |
|---|---|---|
| **2025** `report_drug` | 71.990 | 51.481 |
| **2025** `report_reaction` | 44.916 | 36.568 |
| **2025** `report_duplicate` | 7.872 | 5.308 |
| **2025** `dim_openfda` | 2.251 | 2.117 |
| **2025** Parquet | 4,62 MB | 4,17 MB |
| **2025** UNII | 82,86% | 82,72% |
| **2004** `report_drug` | 36.324 | 43.624 |
| **2004** `report_reaction` | 39.435 | 42.408 |
| **2004** `dim_openfda` | 1.128 | 1.197 |
| **2004** UNII | 51,88% | 55,4% |
| **2004** ids repetidos (B-004) | **6** | **3** |
| Interseção da dimensão (B-006) | 866 de 1.128 · 76,8% | **872 de 1.197 · 72,8%** |
| União da dimensão (B-006) | 2.513 | **2.442** |
| Projeção de dimensão no corpus | ~3,7 GB | **~3,9 GB**, medida em bytes de partição em 20/08 |
| Largura mediana de um relato | 2 | **1** |
| Corte do percentil 99 | 27 | **22** |
| Relato mais largo | 96 | **176** |
| Relatos acima do corte (L-011) | 125 · 1,04% | **127 · 1,06%** |
| Pares na tabela | 28.540 | **16.436** |
| Pares lotados | 18.946 · 66,4% | **11.247 · 68,4%** |
| Evans mantém | 85% | **87,5%** |

**As conclusões sobrevivem; os números não.** A lotação continua sendo o resultado do M0 e ficou um pouco mais forte — 1,06% dos relatos sustentam 68,4% dos pares, contra 1,04% e 66,4%. A B-006 continua furando a G1. A B-005 continua aberta e o round trip continua fechando em 2025 e recusando 2004.

**O que não sobreviveu é a manchete.** O topo da tabela não é mais micose de unha num adesivo de buprenorfina. É `HYDRALAZINE HYDROCHLORIDE` → vasculite ANCA-positiva, a = 3, b = 0, c = 1, d = 11.996, com lotação 5 — **não lotado**. E essa associação é real e bem documentada na literatura. A seção do relatório se chama "O ranking está aritmeticamente certo e clinicamente absurdo" e o primeiro exemplo dela deixou de ser absurdo. A prosa de `reports/m0.qmd` está desatualizada em número e em tese, e reescrevê-la é decisão editorial, não conserto de pipeline.

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
| Distinct drugs per report | median **2** · 99th percentile **27** · widest **121** | T14, `crowding.breadth` over 12,000 |
| Reports at or above 27 distinct drugs | **125 of 12,000 — 1.04%** | T14, `crowding.wide_reports` |
| **Pairs those 125 reports supply** | **18,946 of 28,540 — 66.4%** | T14, `crowded` column of the exported CSV (L-011) |
| Crowded pairs that Evans flags | **18,055** of the 24,299 flagged | T14, same file |
| Top 100 by PRR that are crowded | **85** · top 500: **432** | T14, same file |
| Reports carrying `Onychomycosis` | **10**, not the nine L-010 said — the tenth names 3 drugs | T14, corrected against the 2×2's own a + c |
| Cluster drug-list overlap, recomputed | Jaccard **0.376 / 0.481 / 0.908** — reproduces L-010 to three digits | T14, `crowding.overlap`, written after the figure was recorded |
| Highest-PRR pair from ordinary reports | `RISPERDAL × Gynaecomastia` — a=5 b=16 c=1, PRR 2,852 | T14, same file |
| Exported CSV | 28,540 rows, 2.58 MB on disk, **773 KB stored** in git | T14, `git cat-file -s` then the loose object |
| M0 report prose | **370 words** against AD-016's ≤400 budget | T14, word count over `reports/m0.qmd` |
| `safetyreportid` repetidos na partição | **0 de 12.000** — a suposição valia e não era checada | Revisão 14/08, `hindsight ingest` re-rodado (AD-020) |
| Ingestão reproduz depois das mudanças | 175× · 2.251 openfda · 71.990 drug · 44.916 reaction · 7.872 duplicate | Revisão 14/08, mesma rodada |
| CSV publicado vs. Parquet local | **byte-idêntico**, 28.540 pares · 18.946 lotados · corte 27,0 | Revisão 14/08, `write_csv` para tmp e `diff` |
| Suíte rápida com as guardas novas | **202 testes, 1,6 s** (eram 191) | Revisão 14/08, `make test` |
| Round trip com a guarda de id repetido | **12.000 / 12.000**, 24,6 s | Revisão 14/08, `pytest -m slow` |
| **Partição mais antiga do export** | `2004q1/0001-of-0005` — 44,4 MB, 12.000 registros, 5 partições no bucket | T19, manifesto |
| **Compressão em 2004** | **78,8×** (219,2 MB → 2,78 MB), contra 175× em 2025 | T19, `hindsight ingest` |
| Parquet de 2004 é **menor** que o de 2025 | 2,78 MB contra 4,62 MB, mesmos 12.000 relatos | T19, mesma rodada |
| Fatos por relato | **83 B** em 2004 · 174 B em 2025 | T19, tamanhos por arquivo |
| Projeção só-fatos do corpus | **1,7 GB .. 3,6 GB** sobre 20.692.690 relatos; 23% do corpus é anterior a 2015 | T19, as duas densidades × manifesto |
| `dim_openfda` como fatia da saída | **63%** em 2004 (1,74 MB, 1.128 blocos) · 55% em 2025 — **export de 10/08; contra o de 17/08 são 64% e 59%**, ver a linha da remedição de 20/08 | T19, mesma rodada |
| Linhas em 2004 | drug **36.324** · reaction **39.435** · duplicate **0** | T19, `metrics.json` |
| **`safetyreportid` repetidos em 2004** | **3 de 12.000** (11.997 distintos). Os três pares diferem em `transmissiondate`; dois não diferem em mais nada. Eram 6 no export de 10/08 | zip da fonte, export de 17/08 (AD-025) |
| **`(safetyreportid, transmissiondate)` repetidos** | **0 em 24.000**, nas duas partições, e `transmissiondate` nunca é nulo | zip da fonte, export de 17/08 (AD-025) |
| Round trip em 2004 | **12 recusados** por id ambíguo · 11.988 idênticos **só após remover nulls dos dois lados** | Revisão do PR da T19 (B-004, B-005) |
| **Nulls explícitos em 2004** | **12.000 de 12.000 relatos**, em **cinco caminhos**: `receiver` 12.000 · `primarysource` 3.150 · `drug[].drugtreatmentdurationunit` 1.560 · `patientdeath.patientdeathdate` e `...dateformat` 1.027 cada. Zero em 2025 | Remedição de 20/08, varredura recursiva das duas partições (B-005) |
| **Só um caminho mistura ausente com null** | `drug[].drugtreatmentdurationunit`: ausente 40.780 · null 1.560 · valor 1.284 | Remedição de 20/08, mesma varredura |
| **`openfda: {}` vazio** | **502** em 2004 · **476** em 2025. Arrays vazios continuam em zero | Remedição de 20/08, mesma varredura |
| **`dim_openfda` em bytes** | **64%** da partição de 2004 (1,91 de 3,00 MB) · **59%** da de 2025 (2,46 de 4,17 MB) · projeção **~3,9 GB** | Remedição de 20/08, tamanhos em disco (B-006) |
| **União da dimensão nas duas partições** | **2.442** contra soma ingênua de 3.314 | Remedição de 20/08, chaves calculadas do zip |
| **Custo de um `set` de chaves de 16 hex** | 91 MB por milhão · 419 MB por 5 milhões, contra o teto de 500 MB | Remedição de 20/08, `sys.getsizeof` |
| Colunas 2004 ↔ 2025 | `report` 24↔31 · `report_drug` 16↔29 · `report_reaction` 3↔5 · `report_duplicate` 2↔4 | T19, diff dos dois schemas versionados |
| `activesubstance` em 2004 | **ausente** — o PROJECT a nomeia como entrada da resolução de entidades de M2 | T19, mesmo diff |
| Cobertura em 2004 | UNII **51,9%** (contra 82,9%) · `drugstartdate` **32,8%** (contra 22,5%) · `companynumb` 89,6% | T19, `metrics.json` |
| Pico de RSS em 2004 | **211 MB** contra o teto de 500 MB; 9,8 s de parede | T19, `/usr/bin/time -l` |
| **`make all` em clone limpo** | **78,1 s**, pico **486,8 MB**, 209 testes, site renderizado | T18 remedido após a revisão incluir os testes lentos no alvo |
| Quem come a memória do `make all` | o round trip, não a ingestão — 219 MB ingerindo contra 486,8 MB no total | T18, as duas medições |
| CSV gerado pelo clone limpo | **byte-idêntico** ao versionado | T18, `diff` |
| Row group contra pico de RSS | 2000 → 219 MB / 4,62 MB · 6000 → 299 MB / 4,23 MB · 12000 → 421 MB / 4,06 MB | T18, três ingestões da mesma partição |

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
- [ ] **Confirmar o alvo de armazenamento remoto como primeira tarefa de M1**, antes da crawler (AD-012, sequenciado por AD-018 — HF Datasets é o favorito)
- [ ] **Medir o tamanho da maior era a partir do manifesto** antes de rodar M1, para o pico de disco de AD-018 ser um número e não uma suposição
- [ ] **Medir a query da G1 sobre várias partições** (AD-021). Depende de `prr._directory` ganhar um caminho multi-partição — hoje ele recusa, e a recusa é o que impede a medida de existir
- [x] ~~Record the distinct-`openfda` count during T9~~ — 2,251, and L-003's numbers are now annotated rather than trusted
- [x] ~~**Decide AD-013** (`reportduplicate` as a fifth table)~~ — accepted 2026-08-13. Five tables, `seq IS NULL` is the bare-object marker, specs updated to match
- [ ] Empty arrays are indistinguishable from absent fields (L-007). **T11 re-measured: 0 empty arrays anywhere, and 0 reports without drugs or without reactions**, so the hole still has no known instance. Decide before M1 crawls 1,767 partitions — the reconstruction currently rebuilds the absent version
- [x] ~~Row-group size: 2,000 costs ~12% of the output size~~ — **T18 mediu os três e manteve 2.000.** 2000 → 219 MB / 4,62 MB · 6000 → 299 MB / 4,23 MB · 12000 → 421 MB / 4,06 MB. A regra de design.md já era "só ajuste se o pico estiver perto do teto", e 219 de 500 não está
- [ ] **`Tables.load` segura uma partição inteira em dicts Python — e a folga acabou.** T11 mantinha com 373 MB de pico contra o teto de 500. Com o round trip dentro do `make all` (revisão da T18), o pico é **486,8 MB: 13 MB de folga.** A condição que este todo marcava para revisitar — "if a denser partition gets close" — aconteceu. Resolver antes de M1, junto com B-004 e B-005, já que os três moram no mesmo job
- [x] ~~T11 must assert "zero explicit nulls" per partition rather than inherit T10's measurement (L-008)~~ — done, and it is what makes the round-trip comparison one-sided
- [x] ~~Add `ijson` to PROJECT.md's key dependencies~~ — o todo estava obsoleto: `ijson` já está na lista de PROJECT.md. Conferido na revisão de 14/08
- [ ] **Review the exclusion list at the start of M1**, as its own header promises. It was curated against one partition and is a floor, not an enumeration
- [ ] Procedure and concomitant-therapy terms (`Chemotherapy`, `Radiotherapy`, `Oxygen therapy`) sit in the reaction field and are not bodily responses either. Enumerating them by hand loses; they need the MedDRA hierarchy, which openFDA does not ship — the export carries the preferred term only. Deferred, and stated in the list's header rather than left out quietly
- [x] ~~The exclusion list's `#` header requires `comment='#'` on read. Without it DuckDB returns **zero rows silently** and nothing is excluded — T13 owns making that failure loud~~ — done. `excluded_terms` raises on an empty read and the message names the cause; two tests pin it, one reading the real CSV without the flag
- [x] ~~Spec traceability table still reads `Pending` for M0-01 … M0-12~~ — atualizada em uma passada na revisão de 14/08
- [ ] **Passada de tradução nos specs.** A regra de idioma mudou em 14/08 e `PROJECT.md`, `ROADMAP.md`, `STATE.md`, `spec.md`, `design.md` e `tasks.md` ainda são majoritariamente ingleses. Conteúdo novo já sai em pt-BR, então os arquivos estão mistos até essa passada acontecer — a seção M1 do ROADMAP foi traduzida por inteiro porque foi reescrita por inteiro

---
