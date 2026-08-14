# Hindsight

**Dava para saber antes?**

Quando um medicamento faz mal a alguém — uma erupção, um infarto, uma morte — um relato é registrado no FDA. Vinte milhões deles estão num arquivo público. Às vezes, anos depois, o FDA emite um alerta de segurança sobre aquele medicamento.

Este projeto faz a pergunta óbvia que ninguém respondeu de forma sistemática: **o alerta já estava visível nos relatos, e com quanta antecedência?**

🔗 **[henriquepmartins.github.io/hindsight](https://henriquepmartins.github.io/hindsight/)**

---

## O que é

Um pipeline de ponta a ponta que ingere o FAERS completo (o sistema de eventos adversos do FDA), limpa os dados até virarem consultáveis, roda as estatísticas de desproporcionalidade que os reguladores de fato usam e então — a parte que importa — **rebobina o tempo**.

Para cada alerta de segurança real emitido pelo FDA, o sistema recalcula seus sinais usando *apenas* os relatórios que existiam antes daquela data, e mede com quanta antecedência teria levantado a bandeira. Os erros e os falsos alarmes são publicados com o mesmo destaque dos acertos.

Esse backtest é o ponto inteiro. É a diferença entre "construí uma coisa" e "construí uma coisa, e aqui está a evidência de que funciona".

> **Isto não é orientação médica e não faz nenhuma afirmação causal.** Análise de desproporcionalidade mede *padrões de reporte*, não causalidade. Um sinal quer dizer "esta combinação aparece mais do que o esperado numa base de reporte voluntário" — nada além disso.

---

## Status

**M0 fechado.** O pipeline roda de ponta a ponta sobre uma partição e publica uma página com um gráfico real.

Um clone limpo, um comando:

```bash
git clone https://github.com/henriquepmartins/hindsight && cd hindsight
make all
```

**47 s do checkout vazio ao site renderizado, com pico de 325 MB de memória** — medido com `/usr/bin/time -l` num clone recém-feito, contra um teto de projeto de 500 MB e um orçamento de 15 min. O CSV que a página publica sai byte a byte igual ao versionado no repositório, que é o que torna a página verificável em vez de confiável.

Ressalva honesta: o cache de pacotes do `uv` estava quente. Numa máquina que nunca viu essas dependências, some o tempo de baixá-las.

| Milestone | O que entrega | Status |
|---|---|---|
| **M0** Esqueleto ambulante | Uma partição por todas as camadas → uma página pública | ✅ Fechado |
| **M1** Corpus completo | Os 20,7M de relatórios, atualizando sozinho | ⬜ Planejado |
| **M2** Limpeza e resolução de entidades | "Tylenol" e "paracetamol" viram um medicamento só | ⬜ Planejado |
| **M3** Detecção de sinal | PRR / ROR / shrinkage bayesiano em cada par | ⬜ Planejado |
| **M4** O backtest Hindsight | Antecedência contra alertas reais do FDA | ⬜ Planejado |
| **M5** Artefatos públicos | Dataset aberto + site do relatório | ⬜ Planejado |

Plano completo em [`.specs/project/ROADMAP.md`](.specs/project/ROADMAP.md). Decisões e riscos abertos em [`.specs/project/STATE.md`](.specs/project/STATE.md).

---

## O que os dados são de verdade

Medido diretamente, não estimado:

| | |
|---|---|
| Relatórios no arquivo | **20.692.690** |
| Export em massa | 1.767 arquivos, **111 GB** comprimidos |
| Relatórios num arquivo | 12.000 — em **807 MB** de JSON |
| Vazão de download | 11,5 MB/s |

Isso dá cerca de 67 KB por relatório, absurdo para o que é essencialmente uma lista de medicamentos e sintomas — então medi para onde vão os bytes.

**92,7% do arquivo inteiro é um único bloco de lookup, copiado em cada linha de medicamento.** O campo de enriquecimento `openfda` — nomes comerciais, códigos NDC, classes farmacológicas, identificadores UNII — responde por 641 MB de um payload de 692 MB.

Puxando ele para uma tabela de dimensão e medindo numa partição real:

| etapa | tamanho |
|---|---|
| zip de origem | 162 MB |
| JSON cru | 807 MB |
| **Parquet, ZSTD-9** | **4,62 MB** |

**175× menor que o JSON, 35× menor que a origem comprimida — e comprovadamente sem perdas.**

A razão depende da era, e o tamanho anda ao contrário dela. A partição mais antiga do export, de 2004q1, comprime **78,8×** — e ainda assim sai **menor**, 2,78 MB, porque a fonte é menos redundante para começar. Sobre os 20,7M de relatórios, só as tabelas de fato projetam **1,7 a 3,6 GB**.

Não "sem perdas" como afirmação. O pipeline reconstrói o JSON aninhado original a partir das tabelas normalizadas e compara com a fonte, relatório por relatório: **12.000 de 12.000 idênticos byte a byte, zero divergências.**

Esse teste se pagou de imediato. Pegou uma versão anterior descartando `patient.summary` (presente em 49% dos relatórios) e `reportduplicate` — este último um campo do qual a própria deduplicação do projeto depende. Depois pegou um mais sutil: um `openfda: {}` vazio tratado como campo ausente, apagando a diferença entre *"verificamos e não achamos nada"* e *"nunca olhamos"*. 550 entradas de medicamento, em exatamente 492 relatórios. Um número de compressão sem teste de round trip é um chute.

**O corpus completo de 20,7M projeta para ~3,4 GB**, e o pico de disco durante a ingestão é ~1,5 GB, já que as partições são transmitidas e descartadas uma por vez. Os 111 GB são algo por onde o pipeline *passa* — nunca algo que ele guarda.

---

## O achado do M0

Rodar PRR sobre uma partição produziu um ranking aritmeticamente correto e clinicamente absurdo: micose de unha num adesivo de buprenorfina no topo. As marginais estavam certas — a soma bate em exatamente 12.000.

Seguindo os pares até os documentos: **125 relatórios de 12.000 — 1,04% — sustentam 18.946 dos 28.540 pares. Dois terços da tabela.** Um relatório que nomeia 90 medicamentos afirma um par contra cada evento que carrega, e nove desses relatórios são um paciente só, registrado por seis fabricantes diferentes.

Nenhum limiar resolve. O critério de Evans mantém 85% dos pares e todos os implausíveis passam com folga. Isso transforma "deduplicação é um milestone que decide tudo" de asserção em medição.

---

## Arquitetura

```
openFDA S3  ──▶  zip fixado por SHA-256 (cache, não acervo)
                      │
                      ▼
              stream-parse ──▶ normalize ──▶ Parquet particionado
                                   │          (ano/trimestre/partição)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
              DuckDB (análise)              CSV versionado
                    │                             │
                    ▼                             ▼
        detecção de sinal · backtest        site gerado (Quarto)
```

**Princípios:**

- **Reprodutibilidade por fixação, não por acúmulo.** Guardar os 111 GB de origem é inviável em plano gratuito, então o pipeline fixa a data do export e o manifesto da partição, e qualquer partição pode ser rebaixada byte a byte de uma fonte pública oficial. O teste de round trip é o que garante que o corpus derivado bate com ela.
- **Nunca segurar 111 GB.** Stream → transforma → descarta, uma partição por vez.
- **Plano gratuito força o desenho certo.** Nenhum Postgres hospedado cabe isso, então o corpus é colunar — que é a arquitetura correta de qualquer jeito.
- **Point-in-time ou não vale.** O backtest nunca pode ver um byte que não existia na data simulada. Impedir vazamento é o conteúdo científico inteiro do projeto.

**Stack:** Python 3.12 · DuckDB · pyarrow · Parquet · matplotlib + seaborn · GitHub Actions · Quarto → GitHub Pages

**Deliberadamente fora:** sem frontend React, sem camada de LLM, sem deep learning. Cada um foi considerado e rejeitado por razões escritas — veja AD-004 a AD-006 no [`STATE.md`](.specs/project/STATE.md).

---

## O padrão que este projeto se impõe

1. **Reproduza antes de descobrir.** Os métodos precisam primeiro recuperar ao menos três associações medicamento–evento já estabelecidas na literatura. Um método que não reproduz resultados conhecidos não tem por que reivindicar novos.
2. **Publique os erros.** Os resultados de antecedência incluem os alertas que o sistema teria perdido por completo, e os falsos alarmes que teria levantado.
3. **Meça a limpeza.** Resolução de entidades e deduplicação saem com taxas de acurácia sobre uma amostra rotulada à mão — não "parece melhor".
4. **O sistema se avalia.** Uma página pública acompanha atualidade dos dados, contagens, taxas de nulo e cada evento de deriva de schema capturado.
5. **Página de limitações escrita primeiro.** Antes da página de resultados.

---

## Estado da arte e posicionamento honesto

Detecção de sinal no FAERS é uma disciplina real e madura — FDA, EMA e o Uppsala Monitoring Centre fazem isso, e os métodos estatísticos usados aqui vêm dessa literatura em vez de terem sido inventados para este projeto. O openFDA já deixa os dados consultáveis, e estudos acadêmicos analisaram o FAERS extensamente.

O que não existe publicamente, até onde consegui encontrar: **um pipeline aberto, reprodutível e de ponta a ponta que reconstrói o corpus a partir da fonte crua e depois mede sua própria antecedência histórica contra ação regulatória real.** É essa lacuna que isto preenche.

Se alguém já fez isso, quero saber — abra uma issue.

---

## Licença

Código: MIT. Dataset derivado: CC BY 4.0. Dados de origem são domínio público dos EUA (openFDA).
