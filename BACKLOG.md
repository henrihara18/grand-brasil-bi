# Backlog — Precificação de Seminovos

Documento fixo. Cada item sai daqui só quando for medido na régua (backtest temporal + acerto vs mesa)
e documentado em `REVISAO_PRECIFICACAO.md`. Ordem: primeiro aprimorar o algoritmo de hoje, depois
a automação. Nenhuma mudança entra sem medição, uma por vez.

## Objetivo mestre

**60% das avaliações válidas (compradas ou não) com o algoritmo a até 2,5% do valor da mesa.**
Hoje: 18,5% (3.048 avaliações válidas de set–out/2026, motor com a base de hoje). Teto físico medido:
a própria mesa repete o próprio número a 2,5% em 68% dos carros iguais no mesmo mês.
Métrica de controle paralela: erro vs custo ideal na régua de vendas (hoje 6,2% geral, 4,7% no portão),
para a busca pelo 60% não destruir o preço de compra.

## Fase A — aprimorar o algoritmo de hoje (antes da automação)

Diagnóstico (06/11/2026): o algoritmo fica em mediana **+6,6% acima da oferta da mesa**, gap uniforme
de 4–6 pontos de FIPE em qualquer idade e KM; nas compradas, viés vs custo ideal ≈ 0. A mesa abre
~5% abaixo do que paga. Tetos: nível ×0,95 → 28%; viés por marca → 31%; por modelo → 41%;
por modelo+ano (in-sample) → 58%.

| # | mudança | evidência | efeito esperado |
|---|---|---|---|
| A0 | **Modelo de dois preços**: *preço de abertura* (calibrado na oferta da mesa, meta 2,5%) e *preço máximo* (custo ideal, régua atual). Decisão de negócio pendente do Henri. | oferta da mesa e custo ideal estão 5% um do outro; otimizar um estraga o outro | define o alvo de A1–A5 |
| A1 | **Âncora de ofertas**: usar todas as avaliações (não só compras) como comparáveis — mesa/FIPE do mesmo modelo, ano ±1, KM ±15 mil, 120 dias, peso por recência | sozinha acerta 36% quando há KM parecido (cobertura 89%); algoritmo atual 20% nas mesmas | 18,5% → 32–38% |
| A2 | **Fator de nível por marca e faixa de preço**, aprendido só com ofertas anteriores (walk-forward) | mesa desconta Jeep +10%, Chery +11%, Ford +9%, BMW +9%, Fiat +8%, VW +7% vs BYD +2,7%, Honda/Nissan/Toyota +4%; carro >220 mil +10%, 120–160 mil +9%, 60–90 mil +3,6% | +5 a +10 pontos sobre A1 |
| A3 | **Fator de KM mais forte acima de 130 mil km** | algoritmo +10% vs mesa nessa faixa, +6% nas demais | pontual |
| A4 | **Mínimo de compras fechadas e KM casado para preço oficial** | tier sem KM +13%, fallback de modelo +11%, zero fechadas +9%; casos Tiggo 7 2026, Haval 2025, Renegade 2019 | menos erro grosso no portão |
| A5 | **Dinamika como entrada** (se for referência externa disponível antes da avaliação) | presente em 49% das avaliações; mesa/Dinamika mediana 0,983; Dinamika ×0,983 acerta 42% sozinho vs 19% do algoritmo nas mesmas | grande, depende do que é o campo |
| A6 | Reduzir o erro na Revenda (7,0%, margem apertada) | régua semred1 | — |
| A7 | Ler versão e opcionais (hoje preso à média do modelo) | Corolla XEi 2023 mesa 150 vs algo 112 | — |
| A8 | Ampliar a lista de modelos precisos (erro ≤3% sem outliers): Corolla XEi, Tracker, Corolla Cross XRE estão a 3,5–4% | tabela 4.9 da revisão | cobertura do preço oficial 19% → ~30% |

## Fase B — automação sem o algoritmo aprender com a própria sombra

Risco: quando a mesa passar a pagar o que o algoritmo sugere, a base de avaliações vira espelho e
congela no mercado de hoje. Quatro frentes:

| # | frente | o que é |
|---|---|---|
| B1 | **Separar sugestão de decisão** | gravar por avaliação: sugestão do algoritmo, valor fechado pela mesa, venda posterior (hoje só `data/appraisal_feedback.csv`, 1 linha). Compra em que a mesa só copiou a sugestão entra com peso ~0 na âncora de compras; compra em que a mesa mudou o número, ou com venda confirmada, entra com peso cheio |
| B2 | **Tabela mestra: % da FIPE por modelo × ano × faixa de KM** | alimentada pela venda realizada (venda − imposto − margem-alvo, ajuste de KM), recalculada por mês fechado, versionada em arquivo, com overrides manuais em arquivo separado (quem, quando, por quê) e limite de variação por mês. O motor lê dela em vez de recomputar. A FIPE atualiza o nível; a venda atualiza o % sobre ela. **Item 0 da fase B**: a âncora de ofertas (A1) também se realimenta e precisa do mesmo tratamento |
| B3 | **Sinais externos e de giro** | dias em estoque e margem realizada por modelo movem o % da FIPE (régua 30/60/90 da gestão de estoque); anúncios de concorrentes (scraper Webmotors, standby) e Dinamika como alerta de deriva, não como âncora |
| B4 | **Amostra cega** | em 15–20% das avaliações a mesa lança o número antes de ver a sugestão. Única medida limpa de deriva; diferença acima do limite por dois meses → revisão da tabela daquele modelo |
| B5 | Recalibrar a confiança a cada mês fechado; relatório mensal de erro, cobertura e casos fora | `scripts/confidence_curve.py` |
| B6 | Relatório semanal de **repescagem** (não fechadas em que o algoritmo pagaria mais, filtro: confiança alta, ≥2 compras iguais, +5% a +25%) | 40 casos / R$ 418 mil na última semana de out/2026 |

## Processo e dados

- Avaliador lança `custo de reparo` quando o laudo derruba o preço (caso HB20 2024 "após laudo").
- Flag de blindado preenchida na plataforma, não só na observação.
- Vendas das filiais BMW, JLR, Denza e Mini entram na base (`scripts/build_sales_history.py --raw`).
- Export da plataforma tem linhas duplicadas (650 em set–out): tratar na ingestão.
- Erros de escala no Valor Mesa (105.000 digitado como 10.500): já excluídos da régua; validar na origem.

## Infra

- Streamlit Community Cloud: código pronto (`APPRAISAL_LEGACY_URL`, `SALES_HISTORY_URL`); falta o Henri
  publicar as duas planilhas no Google e logar no share.streamlit.io.
- Feedback de valor pago em CSV some na nuvem: gravar em planilha (liga com B1).
- Repositório público: avaliar tornar privado.
