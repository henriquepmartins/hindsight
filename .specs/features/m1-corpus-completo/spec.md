# M1 — Corpus completo: especificação

**Milestone:** M1 (ROADMAP.md)
**Orçamento:** ~44 h no ROADMAP · ~52 h nesta decomposição — a diferença está explicada em [Orçamento](#orçamento-e-a-diferença-para-o-roadmap)
**Status:** Rascunho — revisado em 18/08/2026, **9 bloqueantes abertos**. Não implementar como está; ver o cabeçalho de `.specs/project/STATE.md`

---

## Problema

O M0 provou a cadeia inteira sobre **duas** partições de 1.767, e ao fazer isso descobriu que
metade das suposições que sustentavam a M1 valia numa era e não na outra. Três coisas ficaram
verdadeiras ao mesmo tempo:

1. **O pipeline funciona.** `make all` num clone limpo leva 78,1 s e o CSV que ele escreve é
   byte-idêntico ao versionado.
2. **A prova central não cobre o corpus.** Em `2004q1/0001-of-0005` o round trip recusa 12
   relatórios por id ambíguo (B-004) e não tem nada a dizer sobre os outros 11.988, porque a
   partição carrega null explícito em 12.000 de 12.000 relatos e a comparação vira
   autocertificante (B-005). "Byte-identical" é hoje propriedade de uma era, não do corpus.
3. **O dimensionamento foi feito por partição e o corpus não é a soma das partições.** A
   `dim_openfda` é deduplicada *dentro* de cada partição, e 866 dos 1.128 blocos de 2004
   reaparecem na partição de 2025 — 21 anos depois. Escrita como está, a dimensão custa ~3,7 GB
   sobre 1.767 partições, contra 1,7–3,6 GB de fatos.

A M1 é onde o pipeline deixa de rodar em duas partições supervisionadas e passa a rodar em 1.767
sem ninguém olhando. Isso não é a mesma tarefa em escala maior: é uma tarefa diferente, porque
tudo o que hoje falha com uma exceção nomeada e um humano ao lado precisa passar a falhar de um
jeito que um cron consiga sobreviver.

## Objetivos

- [ ] Os 20.692.690 relatos ingeridos, normalizados e consultáveis
- [ ] O corpus se reconstrói sem supervisão, retomando de onde parou
- [ ] O round trip tem alcance **declarado por era**, e a página diz quais eras foram verificadas e quando
- [ ] A query nomeada da G1 tem um número medido e publicado, seja ele qual for (AD-021)
- [ ] O corpus cabe abaixo dos 5 GB da G1 — com a dimensão contada, não só os fatos

## Fora de escopo

| Excluído | Razão |
|---|---|
| Resolução de entidades e deduplicação | M2. A M1 ingere `medicinalproduct` cru e os números seguem provisórios no sentido forte de L-010 |
| Shrinkage bayesiano, ROR, intervalos de confiança | M3 |
| Qualquer lógica de backtest ou ponto-no-tempo | M4 |
| Postgres | Nenhum mart precisa ser servido ainda |
| Corrigir a lotação (L-011) | Exige resolução de entidades. A M1 **mede** a lotação no corpus; não a remove |
| Reescrever o PRR para somar entre partições | O PRR é reportado por partição e a recusa de `prr._directory` fica. A G1 ganha uma query própria (M1-21), não uma frouxidão na existente |
| Retomada dentro de uma partição | Uma partição interrompida recomeça do zero. Custa uma segunda leitura de um zip, não um download |

---

## Histórias

### P1: Um relato é identificável em qualquer era ⭐ MVP

**História:** Como o pipeline, quero uma chave que identifique um relato em qualquer era do corpus,
para que a reconstrução funcione onde `safetyreportid` não é único.

**Por que P1:** é uma mudança na chave de junção das cinco tabelas. Feita antes da colheita custa
uma migração de duas partições; feita depois custa reescrever 1.767. B-004 está aberto exatamente
aqui, e a colheita não pode começar antes dele.

**Critérios de aceitação:**

1. QUANDO uma partição é escrita ENTÃO cada linha de `report` SHALL carregar sua posição no
   arquivo, e as quatro tabelas filhas SHALL referenciar essa posição
2. QUANDO dois relatos compartilham um `safetyreportid` ENTÃO ambos SHALL reconstruir
   corretamente, e nenhum SHALL ser recusado por ambiguidade
3. QUANDO `metrics.json` é escrito ENTÃO `repeated_report_ids` SHALL continuar sendo contado —
   a chave substituta resolve a reconstrução, não a duplicata, que é M2
4. QUANDO a chave é documentada ENTÃO SHALL estar dito que ela **não é estável entre exports**,
   porque o openFDA reparticiona trimestres (L-006)

**Teste independente:** reingerir `2004q1/0001-of-0005` e rodar o round trip. 12.000/12.000, zero
recusados.

---

### P1: Ausente, nulo e vazio são três coisas ⭐ MVP

**História:** Como leitor cético, quero que "byte-identical" signifique o mesmo na era antiga e na
nova, para que a afirmação central do projeto tenha alcance de corpus.

**Por que P1:** B-005 é o bloqueador maior dos dois. Hoje a comparação do round trip remove nulls
dos dois lados, o que só é o inverso da escrita se a fonte nunca carregar um null explícito — e em
2004 ela carrega em 12.000 de 12.000. O teste **recusa** em vez de mentir, que é o desenho
funcionando, e o efeito prático é que a era antiga não tem prova nenhuma.

**Critérios de aceitação:**

1. QUANDO a fonte traz um campo com valor `null` ENTÃO o modelo SHALL registrar que aquele caminho
   chegou explicitamente nulo, distinguindo-o de um campo ausente
2. QUANDO a fonte traz um array vazio ENTÃO o modelo SHALL registrá-lo como vazio, distinguindo-o
   de um campo ausente — fecha o buraco de L-007, que hoje não tem instância conhecida e teria uma
   em algum lugar de 1.767 partições
3. QUANDO a reconstrução roda ENTÃO ela SHALL emitir `null` onde a fonte tinha `null`, `[]` onde a
   fonte tinha `[]`, e omitir a chave onde a fonte a omitia
4. QUANDO a comparação do round trip roda ENTÃO ela SHALL comparar os documentos **sem remover
   nulls de nenhum dos dois lados** — a normalização que L-008 mandou desconfiar deixa de existir
   em vez de ser justificada de novo
5. QUANDO o round trip roda sobre `2004q1/0001-of-0005` ENTÃO SHALL passar em 12.000 de 12.000

**Teste independente:** o teste `test_the_source_carries_no_explicit_nulls` deixa de ser necessário
e é removido. Se ele ainda for necessário, o critério 4 não foi cumprido.

---

### P1: A reconstrução cabe na memória ⭐ MVP

**História:** Como o job agendado de round trip, quero reconstruir uma partição sem segurá-la
inteira em memória, para que o job mais caro do projeto rode numa máquina de CI.

**Por que P1:** `Tables.load` mantém uma partição inteira em dicionários Python — 266 MB para 4,62 MB
de Parquet. `make all` chega a 486,8 MB contra o teto de 500 MB: **13 MB de folga.** A condição que
o todo do STATE marcava para revisitar já aconteceu, e o job por era de AD-019 roda uma partição por
era, sequencialmente, no mesmo processo.

**Critérios de aceitação:**

1. QUANDO o round trip roda sobre uma partição inteira ENTÃO o pico de RSS SHALL ficar abaixo de
   250 MB — metade do teto, para que a folga volte a existir
2. QUANDO a reconstrução roda ENTÃO ela SHALL segurar um relato por vez, não a partição
3. QUANDO a reconstrução roda ENTÃO ela SHALL continuar importando **apenas** `normalize` — a prova
   não pode virar espelho do escritor (ARCHITECTURE §Hierarquia de dependências)
4. QUANDO `make all` roda num clone limpo ENTÃO o pico SHALL ser medido e registrado

**Teste independente:** `/usr/bin/time -l uv run pytest -m slow` nas duas partições ingeridas.

---

### P1: A dimensão converge em vez de multiplicar ⭐ MVP

**História:** Como o orçamento de armazenamento, quero que blocos `openfda` idênticos sejam
guardados uma vez no corpus, para que a G1 caiba nos 5 GB com a dimensão contada.

**Por que P1:** medido nas duas partições ingeridas — **866 dos 1.128 blocos de 2004 reaparecem em
2025, 76,8%**, entre as duas partições mais distantes que o corpus tem. A dedup por conteúdo já é
global por construção (SHA-1 do bloco canônico), só a *escrita* é por partição. Sobre 1.767
partições isso custa ~3,7 GB de dimensão contra 1,7–3,6 GB de fatos, e a G1 promete `< 5 GB`.

**Critérios de aceitação:**

1. QUANDO a colheita roda ENTÃO blocos `openfda` idênticos SHALL ser gravados uma vez, não uma vez
   por partição
2. QUANDO a dimensão é escrita ENTÃO `KeyCollision` SHALL continuar valendo — dois blocos diferentes
   com a mesma chave truncada falham alto, não se fundem
3. QUANDO uma partição é consultada ENTÃO a junção com a dimensão SHALL funcionar sem que a
   partição carregue sua própria cópia
4. QUANDO a colheita termina ENTÃO o tamanho real da dimensão de corpus SHALL ser medido e
   publicado, contra a projeção
5. QUANDO a dimensão é escrita ENTÃO seu schema SHALL ser o mesmo em todas as eras — medido: as
   19 colunas de `dim_openfda` são idênticas em 2004 e 2025

**Teste independente:** somar os bytes de `data/parquet/` ao fim da colheita e comparar com
`1,7–3,6 GB + dimensão`.

---

### P1: Era é medida, não escrita à mão ⭐ MVP

**História:** Como o detector de drift, quero que a fronteira de era venha de uma medição sobre o
corpus, para que ela seja verificável pelo mesmo mecanismo que a usa.

**Por que P1:** AD-017 decidiu isso e nada implementa. Uma fronteira escrita no papel seria mais uma
constante medida numa partição e aplicada a 2004–2025, que é o erro de L-006.

**Critérios de aceitação:**

1. QUANDO a varredura roda ENTÃO ela SHALL registrar o conjunto de caminhos de campo e seus tipos
   JSON por partição, sobre **todos** os registros de cada uma
2. QUANDO a varredura é interrompida ENTÃO ela SHALL retomar de onde parou
3. QUANDO o mapa de eras é derivado ENTÃO ele SHALL sair da varredura por uma regra sem constante
   numérica, e SHALL ser um artefato versionado
4. QUANDO uma fronteira é proposta ENTÃO ela SHALL ser aceita por *commit*, não automaticamente —
   a regra propõe, o humano aceita uma vez, e depois disso ela é mecanismo
5. QUANDO o bucket `all_other` é encontrado ENTÃO ele SHALL ser sua própria era por construção, e a
   razão SHALL estar escrita — ele não tem posição na linha do tempo, então não pertence a nenhuma
   corrida cronológica
6. QUANDO o mapa de eras existe ENTÃO o tamanho em bytes de cada era SHALL ser derivável dele mais o
   manifesto, sem nova rede

**Teste independente:** `schema/eras.json` existe, soma 1.767 partições, e cada partição pertence a
exatamente uma era.

---

### P1: A colheita roda sozinha e sobrevive a si mesma ⭐ MVP

**História:** Como o projeto, quero que as 1.767 partições sejam ingeridas por um processo que pode
morrer e ser reiniciado, para que a restrição "roda sem supervisão a partir da M1" seja verdadeira.

**Critérios de aceitação:**

1. QUANDO a colheita é interrompida ENTÃO ela SHALL retomar da próxima partição não concluída, e o
   progresso SHALL ser um registro durável — não um `glob` atrás de `report.parquet`, que hoje não
   distingue um diretório meio escrito de um nunca iniciado
2. QUANDO uma partição carrega um campo que o schema da era não tem ENTÃO o pipeline SHALL registrar
   o evento de drift, pôr a partição em quarentena e **seguir** (AD-017)
3. QUANDO uma partição é posta em quarentena ENTÃO ela SHALL NOT ser escrita, o schema da era SHALL
   NOT ser alargado sozinho, e o crawl SHALL NOT parar
4. QUANDO o openFDA devolve `5xx`, timeout ou conexão morta ENTÃO a partição SHALL ser reagendada com
   backoff, e o crawl SHALL NOT morrer — hoje a exceção do `httpx` sobe sem tratamento
5. QUANDO a colheita termina ENTÃO a soma de linhas de `report` SHALL ser 20.692.690 menos o que
   estiver em quarentena, e a diferença SHALL ser declarada, não arredondada
6. QUANDO a colheita roda ENTÃO o pico de disco SHALL ficar dentro de um orçamento declarado, e o
   orçamento SHALL ser um número medido do manifesto antes de a colheita começar

**Teste independente:** matar o processo no meio, reiniciar, verificar que nenhuma partição é
reescrita e nenhuma é pulada.

---

### P1: O round trip tem alcance declarado ⭐ MVP

**História:** Como leitor cético, quero saber **quais** eras foram verificadas e **quando**, para
que "lossless" tenha alcance declarado em vez de presumido (AD-019).

**Critérios de aceitação:**

1. QUANDO o job agendado roda ENTÃO ele SHALL baixar uma partição por era e rodar a reconstrução
   completa sobre ela
2. QUANDO o job termina ENTÃO o resultado por era SHALL ser gravado como artefato versionado com a
   data da verificação
3. QUANDO a página é publicada ENTÃO ela SHALL nomear as eras verificadas, a data de cada
   verificação, e as eras **não** verificadas
4. QUANDO o CI de push roda ENTÃO ele SHALL continuar no fixture de ~100 relatos — 155 MB de download
   por commit segue recusado (spec da M0, P1 AC5)

**Teste independente:** abrir a página e ler a tabela de eras verificadas.

---

### P2: Continuidade — o corpus se atualiza sozinho

**História:** Como o projeto, quero que exports novos entrem no corpus sem intervenção.

**Critérios de aceitação:**

1. QUANDO o cron roda ENTÃO ele SHALL comparar o `export_date` do manifesto com os pins versionados
   e ingerir apenas partições novas ou alteradas
2. QUANDO um id de partição some do manifesto ENTÃO isso SHALL ser um evento registrado, não um erro
   — reparticionamento não é mudança de conteúdo (L-006)
3. QUANDO uma partição muda de SHA-256 sob o mesmo id ENTÃO ela SHALL ser reingerida e a substituição
   SHALL ser registrada
4. QUANDO o refresh encontra um campo novo numa era congelada ENTÃO SHALL cair na quarentena de
   AD-017 — é aqui que o drift acontece de verdade, não na primeira colheita

---

### P2: O sistema se autoavalia em série temporal

**História:** Como leitor, quero ver a qualidade do corpus ao longo do tempo, não num instantâneo.

**Critérios de aceitação:**

1. QUANDO uma rodada termina ENTÃO as métricas por partição SHALL ser empilhadas numa série
   consultável — contagens de linha, taxas de nulo, eventos de drift, fila de quarentena,
   `repeated_report_ids`, atraso de frescor
2. QUANDO a página de qualidade é publicada ENTÃO ela SHALL mostrar a fila de quarentena e os eventos
   de drift como artefato público, não como remendo escondido
3. QUANDO uma coluna não existe na era de uma partição ENTÃO a métrica SHALL ser `None` e não zero —
   `Schemas.has_column` já faz isso e a série precisa preservar a distinção

---

### P2: A G1 ganha um número

**História:** Como a meta que justifica a arquitetura de armazenamento, quero ser medida.

**Critérios de aceitação:**

1. QUANDO a query nomeada roda ENTÃO ela SHALL contar pares medicamento-evento distintos sobre o
   corpus inteiro, com a lista de exclusão aplicada
2. QUANDO ela é escrita ENTÃO SHALL usar apenas colunas presentes no schema de **todas** as eras, e
   esse conjunto SHALL ser derivado de `schema/eras.json`, não suposto
3. QUANDO o tempo é medido ENTÃO o número SHALL ser publicado seja ele qual for, e o `< 5 s` SHALL
   ser tratado como expectativa prévia e não como critério (AD-021)
4. QUANDO a medição existe ENTÃO `prr._directory` SHALL continuar recusando múltiplas partições — a
   query da G1 é outra query, não uma frouxidão nessa

---

### P3: Cobertura de campos contra a fonte primária

**História:** Como o projeto, quero saber o que o openFDA não traz em relação aos arquivos ASCII do
FAERS, porque AD-002 marcou isso para verificar e a M0 não precisava.

**Critérios de aceitação:**

1. QUANDO a comparação roda ENTÃO os campos do dicionário do FAERS ASCII SHALL ser confrontados com
   os caminhos observados pela varredura
2. QUANDO um campo necessário a M2/M3/M4 estiver ausente ENTÃO isso SHALL virar bloqueador declarado,
   não descoberta na M4

---

## Casos de borda

- QUANDO uma partição do manifesto tem 0 registros ENTÃO ela SHALL ser ingerida como partição vazia
  declarada, não pulada — a menor do export tem 324 registros e nenhuma reporta zero, mas o refresh
  pode criar uma
- QUANDO duas eras adjacentes diferem apenas por um campo esparso ausente por acaso ENTÃO a fronteira
  proposta SHALL ser revisada antes de ser commitada — é o falso positivo conhecido da regra, e a
  alternativa (um limiar de cobertura) é uma constante medida num export
- QUANDO o disco enche no meio da colheita ENTÃO o crawl SHALL parar com erro nomeado antes de
  escrever um Parquet truncado
- QUANDO o cron e uma colheita manual rodam ao mesmo tempo ENTÃO o registro de progresso SHALL
  impedir escrita concorrente na mesma partição
- QUANDO uma era inteira cai em quarentena ENTÃO isso SHALL aparecer na página com o mesmo destaque
  que as eras verificadas — padrão nº 2 do projeto

---

## Rastreabilidade

| ID | História | Task | Status |
|---|---|---|---|
| M1-01 | Chave substituta identifica um relato em qualquer era | T1, T2 | Pendente |
| M1-02 | Ausente, nulo e vazio distinguidos | T3, T4 | Pendente |
| M1-03 | Reconstrução em streaming, pico < 250 MB | T5 | Pendente |
| M1-04 | Round trip verde nas duas eras ingeridas | T6 | Pendente |
| M1-05 | Alvo de armazenamento remoto decidido e escrito | T7 | Pendente |
| M1-06 | `dim_openfda` converge no corpus | T8, T9 | Pendente |
| M1-07 | Sincronização com o alvo remoto, por era | T10 | Pendente |
| M1-08 | Varredura de campos sobre o corpus, retomável | T11, T12 | Pendente |
| M1-09 | Mapa de eras derivado da varredura | T13 | Pendente |
| M1-10 | Schema congelado por era | T14 | Pendente |
| M1-11 | Pico de disco medido e orçamento declarado | T15 | Pendente |
| M1-12 | Registro de progresso durável | T16 | Pendente |
| M1-13 | Drift registra e põe em quarentena | T17 | Pendente |
| M1-14 | Crawler retomável, uma era por vez, com backoff | T18, T19 | Pendente |
| M1-15 | Corpus completo ingerido | T20 | Pendente |
| M1-16 | Refresh incremental agendado | T21 | Pendente |
| M1-17 | Round trip por era em agenda, alcance publicado | T22 | Pendente |
| M1-18 | Série temporal de métricas de qualidade | T23 | Pendente |
| M1-19 | Página de qualidade pública | T24 | Pendente |
| M1-20 | Lista de exclusão revisada | T25 | Pendente |
| M1-21 | Query da G1 medida e publicada | T26 | Pendente |
| M1-22 | Cobertura openFDA vs. FAERS ASCII | T27 | Pendente |
| M1-23 | Relatório da M1 publicado | T28 | Pendente |
| M1-24 | Specs em pt-BR | T29 | Pendente |

**Cobertura:** 24 requisitos, 24 mapeados, 0 sem task.

---

## Orçamento, e a diferença para o ROADMAP

O ROADMAP dimensiona a M1 em ~44 h. Esta decomposição soma **~52 h**, e a diferença tem uma causa
só: as features listadas no ROADMAP supõem que a M0 fechou, e a M0 fechou deixando três coisas
abertas que mudam o modelo de armazenamento.

| Bloco | Horas | No ROADMAP? |
|---|---|---|
| Fase 0 — dívida da M0 que bloqueia a colheita (B-004, B-005, memória) | ~10 h | Não |
| Fase 1 — armazenamento (alvo remoto, dimensão global) | ~7 h | Parcialmente — a dimensão global não estava |
| Fase 2 — era medida | ~8 h | Sim |
| Fase 3 — crawler e colheita | ~13 h | Sim |
| Fase 4 — continuidade e qualidade | ~10 h | Sim |
| Fase 5 — G1, exclusão, relatório, tradução | ~9 h | Sim |

**As ~8 h a mais são a Fase 0 e a dimensão global.** Nenhuma das duas é opcional na ordem em que
está: uma colheita de 1.767 partições escrita contra a chave errada ou contra uma dimensão por
partição não é uma colheita a corrigir depois, é uma colheita a refazer.

---

## Critérios de sucesso

- [ ] `report` soma 20.692.690 linhas menos a quarentena, e a quarentena é um número publicado
- [ ] O corpus em disco cabe abaixo de 5 GB **com a dimensão contada**
- [ ] O round trip passa em 12.000/12.000 nas duas eras já ingeridas, e a página lista as eras
      verificadas com data
- [ ] O crawl sobrevive a `kill -9` e a um `503` do openFDA
- [ ] A query da G1 tem um número medido, publicado com o hardware em que foi medido
- [ ] Um export novo entra no corpus sem ninguém rodar nada à mão

**Critério de falha:** se a Fase 0 passar de 14 h, o problema não é a M1 — é que B-004 e B-005 são
uma mudança de modelo de dados e mereciam um milestone próprio. Parar e revisar o ROADMAP antes de
começar a Fase 2.
