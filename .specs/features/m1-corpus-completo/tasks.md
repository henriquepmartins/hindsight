# M1 — Corpus completo: tasks

**Spec:** [`spec.md`](spec.md) · **Design:** [`design.md`](design.md)
**Status:** Rascunho — revisado em 18/08/2026, **9 bloqueantes abertos**. Não implementar como está; ver o cabeçalho de `.specs/project/STATE.md`
**Orçamento:** ~52 h em 29 tasks. Se passar de 62 h, parar e revisar o ROADMAP.

---

## Como estas tasks são executadas

Toda task carrega um bloco **Verify** — o comando que prova que ela está pronta, rodado e com a
saída real colada, incluindo falhas (AD-010). Uma task por sessão; a revisão é onde o trabalho fecha.

Quatro tasks são **tasks de decisão**: elas não escrevem código, escrevem um AD no STATE. Estão
marcadas com 🔸 e existem porque decidir dentro de uma task de implementação é como o modelo de dados
muda sem revisão.

---

## Plano de execução

```
Fase 0 — Dívida da M0 que bloqueia a colheita (~10 h)
  T1🔸 → T2 ─┐
  T3🔸 → T4 ─┼→ T5 → T6
             │
Fase 1 — Armazenamento, antes da crawler (AD-018) (~7 h)
  T7🔸  [P, independente de tudo]
  T8🔸 → T9 → T10
  T6, T9 ──────────────────────┐
                               │
Fase 2 — Era medida (~8 h)     │
  T11 → T12 → T13 → T14        │
  T12 → T15🔸                  │
                               │
Fase 3 — Crawler e colheita (~13 h)
  T14, T15 → T16 → T17 → T18 → T19 → T20
  T10 ────────────────────────────────┘

Fase 4 — Continuidade e qualidade (~10 h)
  T20 → T21
  T20, T13 → T22
  T20 → T23 → T24

Fase 5 — G1, exclusão, relatório, tradução (~9 h)
  T25 [P, a qualquer momento]
  T20, T13 → T26
  T12 → T27
  T24, T26 → T28
  T29 [P, a qualquer momento]
```

**Paralelismo real:** T7 (alvo remoto) e T25 (lista de exclusão) e T29 (tradução) não dependem de
nada e cabem em qualquer buraco. **T12 e T20 são rodadas longas de máquina**, não de pessoa: horas de
parede, minutos de atenção. Programe as outras tasks ao redor delas.

**A ordem que não pode ser trocada:** a Fase 0 inteira vem antes da Fase 3. Uma colheita de 1.767
partições escrita contra a chave errada não é uma colheita a corrigir, é uma colheita a refazer.

---

## Fase 0 — A dívida da M0 que bloqueia a colheita

### T1: 🔸 Decidir B-004 — a chave que identifica um relato

**O quê:** decidir e escrever como um relato é identificado numa era em que `safetyreportid` não é
único. As três alternativas estão em B-004; a proposta do design é AD-025 (`ordinal`).
**Onde:** `.specs/project/STATE.md`, `.specs/features/m0-walking-skeleton/design.md` (que ainda chama
`safetyreportid` de PK), `ARCHITECTURE.md`
**Depende de:** nada · **Requisito:** M1-01

**Pronta quando:**
- [ ] AD-025 escrito no STATE com decisão, razão, trade-off, alternativas rejeitadas e impacto
- [ ] Está escrito que `ordinal` **não é estável entre exports** (L-006) e que M4 não pode usá-lo como
      identidade durável
- [ ] B-004 marcado como resolvido, com link para o AD
- [ ] `design.md` da M0 e `ARCHITECTURE.md` deixam de afirmar que `safetyreportid` é PK

**Verify:** `grep -rn "safetyreportid" ARCHITECTURE.md .specs/features/m0-walking-skeleton/design.md | grep -i "chave prim\|primary key\|PK"` não retorna nada.

**Commit:** `docs(state): decide B-004 com chave substituta por partição`

---

### T2: A chave substituta nas cinco tabelas

**O quê:** `report` ganha `ordinal`; `report_drug`, `report_reaction` e `report_duplicate` passam a
carregar `ordinal` além de `safetyreportid`. `roundtrip` passa a indexar por `ordinal` e deixa de
recusar id ambíguo.
**Onde:** `src/hindsight/normalize.py`, `write.py`, `schema.py`, `roundtrip.py`, `metrics.py`
**Depende de:** T1 · **Requisito:** M1-01

**Pronta quando:**
- [ ] `normalize.TABLES` declara `ordinal` como coluna que o pipeline escreve, e
      `schema._pin_pipeline_columns` a protege como faz com `safetyreportid`, `seq` e `openfda_key`
- [ ] Um campo da fonte chamado `ordinal` levanta `UnexpectedReportShape`, não sobrescreve
- [ ] `Tables._by_id` some; `reconstruct` não tem mais o caminho de recusa por ambiguidade
- [ ] `metrics.repeated_report_ids` **continua** sendo contado — a chave resolve a reconstrução, não a
      duplicata, que é M2
- [ ] As duas partições são reingeridas e os schemas versionados regravados

**Verify:**
```bash
uv run hindsight ingest 2004q1/0001-of-0005 --reinfer
uv run hindsight ingest 2025q1/0001-of-0028 --reinfer
uv run pytest -q -m "slow or not slow"
uv run python -c "
import json
m = json.load(open('data/parquet/year=2004/quarter=1/part=0001-of-0005/metrics.json'))
print('repetidos:', m['repeated_report_ids'])"
```
Esperado: suíte verde, round trip **12.000/12.000 em 2004 sem nenhum relatório recusado**, e
`repetidos: 6` — o número de L-013 preservado, agora como métrica e não como obstáculo.

**Commit:** `feat(normalize): identifica relato por ordinal dentro da partição`

---

### T3: 🔸 Decidir B-005 — ausente contra explicitamente nulo

**O quê:** decidir como o modelo distingue campo ausente de campo com valor `null` e de array vazio.
As três alternativas estão em B-005; a proposta do design é AD-026 (`source_shape`).
**Onde:** `.specs/project/STATE.md`
**Depende de:** nada · **Requisito:** M1-02

**Pronta quando:**
- [ ] AD-026 escrito no STATE
- [ ] Está escrito que `_without_nulls` **deixa de existir**, e não que passa a ser justificado melhor
- [ ] O todo de L-007 (array vazio indistinguível de ausente) é fechado pelo mesmo AD ou explicitamente
      deixado aberto com a razão
- [ ] B-005 marcado como resolvido

**Verify:** o AD nomeia, para cada alternativa rejeitada, o que ela custa — não só que foi rejeitada.

**Commit:** `docs(state): decide B-005 com marcadores de forma da fonte`

---

### T4: Marcadores de forma, e a comparação deixa de normalizar

**O quê:** as cinco tabelas ganham `source_shape` — lista de campos que chegaram explicitamente nulos
ou como array vazio. `reconstruct` reemite `null` e `[]` onde estavam. `_without_nulls` some dos dois
lados da comparação.
**Onde:** `src/hindsight/normalize.py`, `roundtrip.py`, `schema.py`, `tests/test_roundtrip.py`
**Depende de:** T2, T3 · **Requisito:** M1-02

**Pronta quando:**
- [ ] `split` registra em `source_shape` todo campo cujo valor é `None` e todo array vazio
- [ ] `reconstruct` emite `null`, `[]` ou omite a chave, conforme o marcador
- [ ] A comparação do round trip compara os documentos **crus**, sem remover nada de nenhum lado
- [ ] `test_the_source_carries_no_explicit_nulls` é **removido**, não relaxado — se ele ainda for
      necessário, o AC4 de P1 §"Ausente, nulo e vazio" não foi cumprido
- [ ] Um teste novo defende cada um dos três casos: `null`, `[]`, ausente

**Verify:**
```bash
uv run hindsight ingest 2004q1/0001-of-0005 --reinfer
uv run pytest -q -m "slow or not slow"
uv run python -c "
import duckdb
c = duckdb.connect()
print(c.sql(\"select count(*) from 'data/parquet/year=2004/quarter=1/part=0001-of-0005/report.parquet' where len(source_shape) > 0\").fetchone())"
```
Esperado: **12.000/12.000 em 2004** com a comparação crua, e a contagem acima em 12.000 — os mesmos
12.000 relatos que a revisão da T19 mediu carregando null explícito, agora reconstruídos em vez de
recusados.

**Commit:** `feat(roundtrip): distingue campo ausente de nulo explícito e de array vazio`

---

### T5: Reconstrução em streaming

**O quê:** `Tables.load` deixa de carregar a partição em dicionários. A reconstrução vira um merge
ordenado por `ordinal` sobre os cinco Parquet, montando um relato por vez.
**Onde:** `src/hindsight/roundtrip.py`
**Depende de:** T4 · **Requisito:** M1-03

**Pronta quando:**
- [ ] O pico de RSS do round trip da partição inteira fica **abaixo de 250 MB**
- [ ] `roundtrip` continua importando **apenas** `normalize` — conferido no grafo de imports
- [ ] As guardas de `_ordered` continuam: `seq` fora de `0..n-1` levanta `BrokenTables`, não é
      reordenado em silêncio
- [ ] `make all` volta a ter folga contra o teto de 500 MB, e o novo pico é registrado

**Verify:**
```bash
/usr/bin/time -l uv run pytest -q -m slow 2>&1 | tail -20
grep -n "^from\|^import" src/hindsight/roundtrip.py
```
Esperado: `maximum resident set size` abaixo de 250 MB (era 373 MB em T11), e o único import de
`hindsight` sendo `normalize`.

**Commit:** `perf(roundtrip): reconstrói por merge ordenado em vez de carregar a partição`

---

### T6: O round trip fecha nas duas eras

**O quê:** rodar a prova completa nas duas partições ingeridas e registrar o resultado. É o portão
que abre a Fase 3.
**Onde:** `tests/test_roundtrip.py`, `.specs/project/STATE.md`
**Depende de:** T5 · **Requisito:** M1-04

**Pronta quando:**
- [ ] 12.000/12.000 em `2025q1/0001-of-0028` e em `2004q1/0001-of-0005`
- [ ] Zero relatórios recusados em qualquer uma
- [ ] STATE registra os dois números, o pico de RSS e o tempo de parede
- [ ] A lacuna de evidência da ARCHITECTURE ("a prova cobre 2025 e não 2004") é reescrita para o que
      passou a ser verdade

**Verify:**
```bash
for p in 2004q1/0001-of-0005 2025q1/0001-of-0028; do
  PARTITION=$p /usr/bin/time -l uv run pytest -q -m slow 2>&1 | tail -5
done
```
Esperado: duas suítes verdes. **Se qualquer uma falhar, a Fase 3 não começa** — é o critério de falha
da Fase 0.

**Commit:** `test(roundtrip): prova as duas eras ingeridas ponta a ponta`

---

## Fase 1 — Armazenamento, antes da crawler

### T7: 🔸 Confirmar o alvo de armazenamento remoto

**O quê:** transformar AD-012 (provisória: HF Datasets favorito, R2 segundo, B2 terceiro) numa decisão
escrita. Primeira task da M1 por AD-018 — uma crawler que escreve local e depois migra é reescrita,
não configuração.
**Onde:** `.specs/project/STATE.md`, `PROJECT.md` (§Tech Stack ainda diz R2)
**Depende de:** nada · **Requisito:** M1-05

**Pronta quando:**
- [ ] A decisão está escrita com a conta criada e testada, não escolhida no papel
- [ ] O custo de escrita foi medido: subir ~4 GB no alvo escolhido e cronometrar
- [ ] DuckDB lê do alvo remoto — testado com uma query real, não com a documentação
- [ ] A estratégia de commits está escrita (HF é git+LFS; um commit por era, não por partição)
- [ ] AD-003 (R2) e AD-012 (provisória) são atualizadas ou superseded explicitamente
- [ ] `PROJECT.md` §Tech Stack deixa de dizer "Cloudflare R2" se não for R2

**Verify:**
```bash
uv run python -c "
import duckdb
c = duckdb.connect()
c.sql(\"install httpfs; load httpfs\")
print(c.sql(\"select count(*) from '<url do alvo>/report.parquet'\").fetchone())"
```
Esperado: uma contagem de linhas real vinda do remoto. Falhar aqui é o resultado útil — descobre-se
antes da colheita e não depois.

**Commit:** `docs(state): fixa o alvo de armazenamento remoto`

---

### T8: 🔸 Decidir B-006 — a dimensão `openfda` é global

**O quê:** abrir B-006 no STATE com a medição (866 dos 1.128 blocos de 2004 reaparecem em 2025) e
decidir entre dimensão global, por era, ou por partição.
**Onde:** `.specs/project/STATE.md`
**Depende de:** nada · **Requisito:** M1-06

**Pronta quando:**
- [ ] B-006 escrito com a medição e a projeção: ~2,1 MB × 1.767 ≈ 3,7 GB de dimensão contra 1,7–3,6 GB
      de fatos, e a G1 promete `< 5 GB`
- [ ] AD-024 escrito com a decisão
- [ ] Está registrado que `dim_openfda` tem as **mesmas 19 colunas nas duas eras**, que é o que torna
      uma dimensão única segura por schema
- [ ] O custo em memória do `set` de chaves está nomeado como incógnita que T12 mede

**Verify:** reproduzir a medição da abertura do bloqueador:
```bash
uv run python -c "
import duckdb
a='data/parquet/year=2004/quarter=1/part=0001-of-0005/dim_openfda.parquet'
b='data/parquet/year=2025/quarter=1/part=0001-of-0028/dim_openfda.parquet'
c=duckdb.connect()
print(c.sql(f\"select count(*) from (select openfda_key from '{a}' intersect select openfda_key from '{b}')\").fetchone())"
```
Esperado: `(866,)`.

**Commit:** `docs(state): abre B-006 e decide a dimensão openfda global`

---

### T9: A dimensão global

**O quê:** `dim_openfda` sai da hierarquia `year=/quarter=/part=/` e vira `data/parquet/dim_openfda/`,
escrita em pedaços, com a colheita mantendo em memória só o conjunto de chaves já vistas.
**Onde:** `src/hindsight/normalize.py`, `write.py`, `analysis/prr.py` (a junção muda de caminho)
**Depende de:** T8 · **Requisito:** M1-06

**Pronta quando:**
- [ ] `OpenfdaDimension` aceita um conjunto de chaves pré-existentes e só emite blocos novos
- [ ] `KeyCollision` continua valendo — dois blocos diferentes com a mesma chave truncada falham alto
- [ ] `openfda` ausente e `openfda: {}` continuam sendo coisas diferentes
- [ ] As queries de `analysis/prr.py` e `metrics.py` apontam para o novo caminho
- [ ] As duas partições reingeridas produzem **2.513 blocos no total**, não 3.379

**Verify:**
```bash
rm -rf data/parquet
uv run hindsight ingest 2004q1/0001-of-0005
uv run hindsight ingest 2025q1/0001-of-0028
uv run python -c "
import duckdb, glob, os
print('blocos:', duckdb.connect().sql(\"select count(*) from 'data/parquet/dim_openfda/*.parquet'\").fetchone())
print('bytes dim:', sum(os.path.getsize(f) for f in glob.glob('data/parquet/dim_openfda/*.parquet')))"
uv run pytest -q -m "slow or not slow"
```
Esperado: **2.513 blocos** — a união medida em T8, não a soma. E o round trip segue verde: a dimensão
mudou de lugar, não de conteúdo.

**Commit:** `feat(write): dedup do openfda passa a ser de corpus e não de partição`

---

### T10: Sincronização com o alvo remoto

**O quê:** `hindsight sync` — sobe o Parquet local para o alvo de T7, por era, retomável.
**Onde:** `src/hindsight/sync.py` (novo), `cli.py`, `Makefile`
**Depende de:** T7, T9 · **Requisito:** M1-07

**Pronta quando:**
- [ ] Sincroniza uma era por chamada, e uma era já sincronizada é no-op
- [ ] Um upload interrompido não deixa o remoto num estado que a próxima execução trate como completo
- [ ] Um commit por era, não por partição (AD-012: HF é git+LFS e a história precisa ficar sã)
- [ ] `make sync` existe e o `help` o descreve

**Verify:** sincronizar as duas partições ingeridas, apagar `data/parquet/` local, e rodar a query da
página lendo do remoto. Deve devolver os mesmos números.

**Commit:** `feat(sync): publica o Parquet no alvo remoto por era`

---

## Fase 2 — Era medida

### T11: O módulo `sweep`

**O quê:** a Fase A por partição — baixar, varrer todos os registros, gravar os caminhos de campo e
seus tipos JSON em `schema/observed/<partição>.json`, descartar o zip.
**Onde:** `src/hindsight/sweep.py` (novo), `cli.py`
**Depende de:** nada em código, mas roda depois de T6 na ordem do plano · **Requisito:** M1-08

**Pronta quando:**
- [ ] Reusa `schema.infer` — a varredura é a passagem 1 que já existe, não uma segunda implementação
- [ ] O arquivo de saída é pequeno o bastante para 1.767 deles serem versionados
- [ ] Grava também a contagem de registros e o `export_date`, para que a fronteira de era seja
      auditável sem a rede
- [ ] Uma partição já varrida é pulada, a menos que `--reobserve`

**Verify:**
```bash
uv run hindsight sweep 2004q1/0001-of-0005
uv run hindsight sweep 2025q1/0001-of-0028
ls -la schema/observed/ && du -sh schema/observed/
```
Esperado: dois arquivos, e o tamanho de cada um multiplicado por 1.767 cabendo confortavelmente no
repositório. Se não couber, o formato precisa mudar antes de T12 e não depois.

**Commit:** `feat(sweep): registra os caminhos de campo observados por partição`

---

### T12: A varredura do corpus inteiro

**O quê:** rodar `sweep` sobre as 1.767 partições, retomável. Rodada longa de máquina — ~2,7 h de
transferência pura a 11,6 MB/s, mais o parse.
**Onde:** `src/hindsight/sweep.py`, `schema/observed/`
**Depende de:** T11 · **Requisito:** M1-08

**Pronta quando:**
- [ ] 1.767 arquivos em `schema/observed/`, um por partição do manifesto
- [ ] A varredura sobrevive a `kill -9` e retoma sem revarrer o que já fez
- [ ] O pico de disco fica em ~1 partição, exceto o que a retenção de T15 decidir guardar
- [ ] **Medido e registrado no STATE:** quantos blocos `openfda` distintos o corpus tem — é o número
      que dimensiona o `set` em memória de AD-024, e a Fase 3 depende dele
- [ ] Tempo de parede e volume transferido registrados

**Verify:**
```bash
ls schema/observed/*.json | wc -l
uv run python -c "
import json, glob
obs = [json.load(open(f)) for f in glob.glob('schema/observed/*.json')]
print('partições:', len(obs), 'registros:', sum(o['records'] for o in obs))"
```
Esperado: `1767` e `20692690` — os fatos de corpus do STATE, re-derivados pela varredura em vez de
herdados do manifesto.

**Commit:** `chore(sweep): varre as 1.767 partições do export`

---

### T13: O mapa de eras

**O quê:** derivar `schema/eras.json` da varredura, pela regra do design: um bucket entra na era
aberta se nenhum caminho conflita de tipo e nenhum caminho de `E` sumiu.
**Onde:** `src/hindsight/era.py` (novo), `schema/eras.json`
**Depende de:** T12 · **Requisito:** M1-09

**Pronta quando:**
- [ ] Nenhuma constante numérica na regra
- [ ] `all_other` é sua própria era, e a razão está escrita no código como teste nomeado, não como
      comentário — o projeto não tem comentários
- [ ] Cada uma das 1.767 partições pertence a exatamente uma era
- [ ] `eras.json` traz, por era: buckets, partições, bytes, registros e os caminhos que a fecharam
- [ ] **A fronteira proposta é revisada à mão uma vez antes do commit.** O falso positivo conhecido é
      um campo esparso ausente de um bucket pequeno por acaso; a alternativa (limiar de cobertura) é
      uma constante medida num export e está rejeitada no design

**Verify:**
```bash
uv run python -c "
import json
e = json.load(open('schema/eras.json'))
print('eras:', len(e['eras']))
for x in e['eras']:
    print(x['id'], x['buckets'][0], '..', x['buckets'][-1], x['partitions'], 'part', round(x['bytes']/2**30,1), 'GiB')
print('soma:', sum(x['partitions'] for x in e['eras']))"
```
Esperado: `soma: 1767`, e uma tabela de eras com o tamanho de cada uma — **que é o número que a M1
inteira estava esperando.** Se der uma ou duas eras, ler a previsão do design: é resultado legítimo,
e significa que "uma era por vez" não é mecanismo de escopo e o disco passa a ser governado por T15.

**Commit:** `feat(era): deriva as fronteiras de era da varredura`

---

### T14: Schema congelado por era

**O quê:** `schema/<era>.json` — a união dos caminhos da era, no mesmo formato dos schemas de partição
de hoje, com um bloco `source` que amarra o schema às partições que o produziram.
**Onde:** `src/hindsight/era.py`, `schema/<era>.json`
**Depende de:** T13 · **Requisito:** M1-10

**Pronta quando:**
- [ ] Um schema por era, no formato que `schema.enforce` já consome
- [ ] `_pin_pipeline_columns` fixa `safetyreportid`, `seq`, `openfda_key`, `ordinal` e `source_shape`
- [ ] Os dois schemas de partição existentes são consistentes com o schema da era a que pertencem
- [ ] O bloco `source` nomeia as partições varridas e o `export_date`

**Verify:**
```bash
uv run python -c "
import json, glob
for f in sorted(glob.glob('schema/era-*.json')):
    s = json.load(open(f))
    print(f, {t: len(c) for t, c in s['tables'].items()})"
```
Esperado: uma linha por era com a largura de cada tabela. A era que contém 2004 deve ter `report_drug`
com pelo menos as 16 colunas medidas em T19; a que contém 2025, pelo menos 29.

**Commit:** `feat(era): congela o schema de cada era`

---

### T15: 🔸 Orçamento de disco e política de retenção

**O quê:** com `eras.json` em mãos, o pico de disco deixa de ser incógnita. Decidir o orçamento e
escrever AD-023, emendando AD-018.
**Onde:** `.specs/project/STATE.md`, `src/hindsight/crawl.py` (a flag)
**Depende de:** T13 · **Requisito:** M1-11

**Pronta quando:**
- [ ] O tamanho da maior era está medido e escrito
- [ ] AD-023 escrito: a retenção é condicional a um orçamento declarado; era que cabe é lida do cache,
      era que não cabe é rebaixada
- [ ] O orçamento é argumento de linha de comando com padrão explícito, não constante no código — é
      propriedade da máquina, não do dado
- [ ] Está escrito o que a M1 paga em cada caso: ~2,7 h de transferência nas eras que couberem, ~5,4 h
      nas que não

**Verify:** `uv run hindsight crawl --dry-run --disk-budget 20GB` imprime, por era, se ela cabe e
quanto de transferência a decisão custa. Nenhum byte baixado.

**Commit:** `docs(state): emenda AD-018 com orçamento de disco explícito`

---

## Fase 3 — Crawler e colheita

### T16: Registro de progresso durável

**O quê:** `data/progress.json` — por partição, um estado em `{pendente, varrida, escrita, quarentena,
falha}` com timestamp e razão. Substitui o `glob` atrás de `report.parquet`, que hoje não distingue
um diretório meio escrito de um nunca iniciado.
**Onde:** `src/hindsight/progress.py` (novo)
**Depende de:** T14 · **Requisito:** M1-12

**Pronta quando:**
- [ ] A escrita do progresso é atômica (`.part` + `replace`, como o resto do projeto)
- [ ] Uma partição só vira `escrita` **depois** dos cinco `replace` da `write_partition`
- [ ] Dois processos não escrevem a mesma partição ao mesmo tempo
- [ ] `analysis.prr.partitions()` passa a ler o progresso em vez de dar `glob`

**Verify:** matar o processo entre o `flush` e o `replace` (com uma exceção injetada num teste),
verificar que a partição segue `pendente` e que a execução seguinte a refaz do zero.

**Commit:** `feat(progress): registra o estado de cada partição da colheita`

---

### T17: Quarentena e eventos de drift

**O quê:** `UnknownField` deixa de derrubar o processo. O crawler o captura, grava
`data/quarantine/<partição>.json` com o campo, o valor de exemplo e a era, e segue (AD-017).
**Onde:** `src/hindsight/crawl.py` (novo), `data/quarantine/`
**Depende de:** T16 · **Requisito:** M1-13

**Pronta quando:**
- [ ] Partição em quarentena não é escrita, o schema da era não é alargado, o crawl não para
- [ ] `schema.enforce` continua sendo o gatilho — muda quem o pega, não o detector (AD-017)
- [ ] O evento nomeia o campo, a partição, a era e o caminho completo
- [ ] `data/quarantine/` é versionado — buraco declarado é artefato público, padrão nº 2 do projeto

**Verify:** injetar um campo desconhecido num fixture, rodar o crawler sobre duas partições, e ver a
primeira em quarentena e a **segunda escrita normalmente**. É a única forma de provar que o crawl
seguiu.

**Commit:** `feat(crawl): põe em quarentena a partição com campo desconhecido`

---

### T18: Rede que falha sem derrubar a colheita

**O quê:** retry com backoff exponencial em `manifest` e `fetch`. Esgotado, a partição vira `falha` no
progresso e o crawl segue. Hoje um `503` do openFDA sobe como traceback.
**Onde:** `src/hindsight/fetch.py`, `manifest.py`, `crawl.py`
**Depende de:** T17 · **Requisito:** M1-14

**Pronta quando:**
- [ ] Timeout, `5xx` e conexão morta são retentados com backoff; `404` não é — é reparticionamento
      (L-006) e vira evento registrado
- [ ] `ChecksumMismatch` **não** é retentado: é a origem tendo reescrito os bytes, e insistir não
      conserta
- [ ] O número de tentativas e o teto do backoff são explícitos, e a espera total por partição tem
      limite
- [ ] Uma partição em `falha` é retomável numa execução seguinte sem intervenção

**Verify:** um teste com um servidor local devolvendo `503` três vezes e `200` na quarta. O download
completa e o log mostra as três tentativas.

**Commit:** `feat(fetch): retenta erro transitório do openFDA com backoff`

---

### T19: `hindsight crawl`

**O quê:** o comando que amarra tudo — itera as eras de `eras.json`, e dentro de cada uma as
partições, respeitando progresso, orçamento de disco, retenção e quarentena.
**Onde:** `src/hindsight/crawl.py`, `cli.py`, `Makefile`
**Depende de:** T15, T18 · **Requisito:** M1-14

**Pronta quando:**
- [ ] `--era`, `--disk-budget`, `--dry-run` e `--limit` existem, e `--limit` é o que torna a task
      testável sem 1.767 partições
- [ ] A saída no terminal diz onde está: era, partição, quantas faltam, taxa
- [ ] `make crawl` existe e o `help` o descreve
- [ ] Ele não importa `roundtrip` — a prova continua independente do escritor

**Verify:**
```bash
uv run hindsight crawl --era <primeira> --limit 5
kill -9 <pid>   # no meio
uv run hindsight crawl --era <primeira> --limit 5
```
Esperado: a segunda execução retoma, não reescreve o que já estava `escrita`, e não pula nada.

**Commit:** `feat(crawl): colhe o corpus uma era por vez, retomável`

---

### T20: A colheita

**O quê:** rodar. 1.767 partições. Rodada longa de máquina, várias sessões, interrompida de propósito
pelo menos uma vez para provar a retomada em condições reais.
**Onde:** `data/parquet/`, `.specs/project/STATE.md`
**Depende de:** T10, T19 · **Requisito:** M1-15

**Pronta quando:**
- [ ] `report` soma **20.692.690 linhas menos a quarentena**, e a diferença é declarada, não arredondada
- [ ] O tamanho real do corpus em disco é medido, **com a dimensão contada**, contra a projeção de
      1,7–3,6 GB de fatos e contra o `< 5 GB` da G1
- [ ] A dimensão global tem seu tamanho e sua contagem de blocos medidos, contra a projeção de T12
- [ ] Tempo de parede, volume transferido, pico de disco e pico de RSS registrados no STATE
- [ ] O corpus está sincronizado no alvo remoto (T10)
- [ ] Uma lição nova no STATE com o que a colheita descobriu — porque ela vai descobrir alguma coisa

**Verify:**
```bash
uv run python -c "
import duckdb, glob, os
c = duckdb.connect()
print('relatos:', c.sql(\"select count(*) from 'data/parquet/year=*/quarter=*/part=*/report.parquet'\").fetchone())
print('blocos openfda:', c.sql(\"select count(*) from 'data/parquet/dim_openfda/*.parquet'\").fetchone())
print('bytes:', sum(os.path.getsize(f) for f in glob.glob('data/parquet/**/*.parquet', recursive=True)))"
ls data/quarantine/ | wc -l
```
Esperado: os três números que a M1 existe para produzir.

**Commit:** `chore(crawl): colhe o corpus completo`

---

## Fase 4 — Continuidade e qualidade

### T21: Refresh incremental agendado

**O quê:** cron no GitHub Actions que compara o `export_date` do manifesto com os pins versionados e
ingere só o que mudou.
**Onde:** `.github/workflows/refresh.yml`, `src/hindsight/crawl.py`
**Depende de:** T20 · **Requisito:** M1-16

**Pronta quando:**
- [ ] Só partições novas ou com SHA-256 diferente são reingeridas
- [ ] Um id que some do manifesto é **evento registrado**, não erro (L-006)
- [ ] Um campo novo numa era congelada cai na quarentena de T17 — **é aqui que o drift acontece de
      verdade**, e não na colheita inicial
- [ ] O job cabe no limite de 6 h e no disco de uma Action, ou a razão de não caber está escrita
- [ ] O job publica o que fez, mesmo quando não fez nada

**Verify:** rodar o workflow com `workflow_dispatch` sem nenhuma mudança no export. Deve terminar
verde dizendo "nada mudou", não deve baixar nada, e o progresso não deve ser alterado.

**Commit:** `ci: agenda o refresh incremental do corpus`

---

### T22: Round trip por era, em agenda

**O quê:** o job de AD-019 — uma partição por era, em agenda, separado do CI de push, que continua no
fixture de ~100 relatos.
**Onde:** `.github/workflows/roundtrip.yml`, `reports/data/eras_verified.csv`
**Depende de:** T13, T20 · **Requisito:** M1-17

**Pronta quando:**
- [ ] Uma partição por era, sequencial, dentro do teto de memória que T5 abriu
- [ ] O resultado por era é gravado em `reports/data/eras_verified.csv` com a data da verificação
- [ ] Falha em qualquer era deixa o job vermelho e a era marcada como **não verificada**, não omitida
- [ ] O CI de push **não** muda: 155 MB por commit segue recusado

**Verify:** rodar o workflow à mão, abrir o CSV, conferir uma linha por era com data e resultado.

**Commit:** `ci: verifica o round trip de uma partição por era em agenda`

---

### T23: Série temporal de métricas de qualidade

**O quê:** empilhar os `metrics.json` por partição numa série consultável: contagens de linha, taxas
de nulo, eventos de drift, fila de quarentena, `repeated_report_ids`, atraso de frescor.
**Onde:** `src/hindsight/quality.py` (novo), `reports/data/quality.csv`
**Depende de:** T20 · **Requisito:** M1-18

**Pronta quando:**
- [ ] Uma linha por partição por rodada, com a data da rodada
- [ ] Coluna ausente na era daquela partição vira `None` e **não zero** — `Schemas.has_column` já faz
      essa distinção e a série precisa preservá-la
- [ ] `repeated_report_ids` do corpus inteiro é um número publicado — hoje se sabe 0 em 2025 e 6 em
      2004, e nada sobre as outras 1.765
- [ ] O CSV é versionado e a página o lê, como o `prr_top.csv` já faz

**Verify:**
```bash
uv run hindsight quality --csv
uv run python -c "
import csv
rows = list(csv.DictReader(open('reports/data/quality.csv')))
print(len(rows), 'linhas')
print('ids repetidos no corpus:', sum(int(r['repeated_report_ids']) for r in rows))"
```
Esperado: 1.767 linhas e um número de ids repetidos no corpus — o primeiro que existe.

**Commit:** `feat(quality): empilha as métricas por partição numa série`

---

### T24: A página que se autoavalia

**O quê:** a página de qualidade de dados: eras verificadas e quando, fila de quarentena, eventos de
drift, cobertura de campos por era, a série temporal.
**Onde:** `reports/quality.qmd`, `_quarto.yml`
**Depende de:** T23 · **Requisito:** M1-19

**Pronta quando:**
- [ ] As eras **não** verificadas aparecem com o mesmo destaque das verificadas
- [ ] A quarentena aparece como número e como lista, não como nota de rodapé
- [ ] "Byte-identical" na página tem alcance declarado por era, não alcance presumido
- [ ] O disclaimer de não causalidade segue em todo rodapé
- [ ] A guarda de procedência de AD-022 cobre os CSVs novos, ou está escrito por que não cobre

**Verify:** `make site` e abrir a página. Um leitor que não conhece o projeto deve conseguir dizer,
em 30 segundos, quanto do corpus está provado e quanto não está.

**Commit:** `feat(site): publica a página de qualidade de dados`

---

## Fase 5 — G1, exclusão, relatório, tradução

### T25: Revisar a lista de exclusão

**O quê:** a lista foi curada contra uma partição e o cabeçalho dela promete que é um piso, não uma
enumeração. Revisar contra o corpus varrido.
**Onde:** `reference/excluded_terms.csv`
**Depende de:** nada · **Requisito:** M1-20

**Pronta quando:**
- [ ] Os termos MedDRA do corpus inteiro são ranqueados e a lista revisada contra eles
- [ ] Termos que existem só em eras antigas entram — a lista foi feita em 2025
- [ ] As duas versões de MedDRA que a M0 achou numa partição (27.1 e 28.0) viram quantas no corpus, e
      o número é registrado
- [ ] Os termos de procedimento (`Chemotherapy`, `Radiotherapy`) seguem **fora**, com a razão no
      cabeçalho: precisam da hierarquia MedDRA, que o openFDA não publica
- [ ] O cabeçalho registra contra o que a revisão foi feita e quando

**Verify:** ranquear os termos antes e depois. A M0 mediu 187 termos mordendo 15,4% das linhas de
reação numa partição; a Verify aqui é o mesmo número sobre o corpus.

**Commit:** `chore(reference): revisa a lista de exclusão contra o corpus`

---

### T26: A query da G1

**O quê:** contagem de pares medicamento-evento distintos sobre o corpus inteiro, com a lista de
exclusão aplicada, medida e publicada seja qual for o número (AD-021).
**Onde:** `src/hindsight/corpus.py` (novo), `cli.py`
**Depende de:** T13, T20, T25 · **Requisito:** M1-21

**Pronta quando:**
- [ ] A query usa **apenas** colunas presentes no schema de todas as eras, e esse conjunto é derivado
      de `schema/eras.json` — não suposto. Medido nas duas eras conhecidas: `report_reaction` tem 3
      colunas em 2004 contra 5 em 2025
- [ ] As células contam relatórios distintos, não linhas juntadas — a lição de L-009 vale no corpus
- [ ] `prr._directory` **continua recusando** múltiplas partições. Esta é outra query, não uma
      frouxidão naquela
- [ ] O tempo é medido e publicado com o hardware em que foi medido
- [ ] Se der muito acima de 5 s, o STATE registra a decisão: muda a G1 ou muda a arquitetura de
      consulta. Descobrir isso agora custa uma tarde; na M5 custa o argumento

**Verify:**
```bash
time uv run hindsight corpus --distinct-pairs
```
Esperado: um número e um tempo. **Os dois são publicáveis independentemente de serem bons** — é
literalmente o que AD-021 decidiu.

**Commit:** `feat(corpus): mede a query nomeada da G1 sobre o corpus inteiro`

---

### T27: Cobertura openFDA contra o FAERS ASCII

**O quê:** o todo que AD-002 deixou e a M0 não precisava — confrontar os campos do dicionário do FAERS
ASCII com os caminhos que a varredura observou.
**Onde:** `.specs/project/STATE.md`, `reports/m1.qmd`
**Depende de:** T12 · **Requisito:** M1-22

**Pronta quando:**
- [ ] O dicionário do FAERS ASCII é obtido e os campos listados
- [ ] O diff contra `schema/observed/` está escrito, por era
- [ ] Campo ausente que M2, M3 ou M4 precisam vira **bloqueador declarado** no STATE, não descoberta
      na M4
- [ ] O todo do STATE é fechado

**Verify:** uma tabela de três colunas — campo do ASCII, presente no openFDA, milestone que precisa
dele.

**Commit:** `docs(state): confronta a cobertura de campos do openFDA com o FAERS ASCII`

---

### T28: O relatório da M1

**O quê:** as notebooks da M1 e `reports/m1.qmd`, sob as regras de AD-016 — ~350 palavras, títulos que
afirmam, limitações fechando a análise, um gráfico, paleta Okabe-Ito.
**Onde:** `notebooks/04..`, `reports/m1.qmd`
**Depende de:** T24, T26 · **Requisito:** M1-23

**Pronta quando:**
- [ ] Três ou mais notebooks numeradas, uma por análise que **de fato** rodou — não a forma de um
      workflow de exploração sem o conteúdo (AD-016)
- [ ] `reports/m1.qmd` dentro do orçamento de palavras
- [ ] O arco narrativo continua **entre** milestones: a M0 foi montagem de dados e primeira análise; a
      M1 é escala e continuidade. A M1 não fabrica uma seção de modelagem, que é M3
- [ ] O gráfico codifica uma variável em cor e sobrevive em escala de cinza
- [ ] A navegação por milestone do `_quarto.yml` ganha a M1

**Verify:** `make site`, contar as palavras, abrir a página, imprimir em preto e branco.

**Commit:** `feat(site): publica o relatório da M1`

---

### T29: Passada de tradução nos specs

**O quê:** a regra de idioma mudou em 14/08/2026 e `PROJECT.md`, `ROADMAP.md`, `STATE.md` e os specs
da M0 seguem majoritariamente em inglês. Traduzir.
**Onde:** `.specs/`, `README.md`
**Depende de:** nada · **Requisito:** M1-24

**Pronta quando:**
- [ ] Prosa em pt-BR nos arquivos listados
- [ ] **Ficam em inglês, e não é inconsistência:** identificadores de código, nomes de campo do FAERS,
      nomes de coluna dos artefatos, e o histórico de commits anterior a 14/08/2026
- [ ] Nenhum número muda na tradução — conferido, não presumido
- [ ] O todo do STATE é fechado

**Verify:** `git diff --stat` mostra só arquivos de prosa, e um `grep` pelos números do STATE
(`20.692.690`, `175×`, `78,8×`, `12.000`) devolve os mesmos valores antes e depois.

**Commit:** `docs: traduz os specs para pt-BR`

---

## Critério de falha do milestone

Dois portões, e nenhum é negociável no meio:

1. **Se a Fase 0 passar de 14 h**, B-004 e B-005 são uma mudança de modelo de dados maior do que a M1
   supõe. Parar e revisar o ROADMAP antes de começar a Fase 2.
2. **Se T6 não fechar verde nas duas eras**, a Fase 3 não começa. Uma colheita de 1.767 partições sem
   a prova fechada é 1.767 partições sem prova.
