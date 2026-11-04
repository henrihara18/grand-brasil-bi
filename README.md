# Grand Brasil — BI de Seminovos

Dashboard Streamlit com dois fluxos: **avaliação de troca** (sugere quanto pagar num seminovo a
partir do histórico de avaliações e de vendas da Grand Brasil) e **estoque** (envelhecimento,
redução de preço, candidatos a repasse).

Quem chega agora deve ler, nesta ordem:

1. `CLAUDE.md` — fontes de dados, arquitetura de precificação, convenções. O Claude Code lê este
   arquivo sozinho ao abrir a pasta; ele vale também para pessoas.
2. `REVISAO_PRECIFICACAO.md` — a revisão do algoritmo (out/2026): o que foi medido, o que foi
   adotado, o que foi descartado e por quê, com os números antes e depois.
3. `.claude/skills/` — as regras de negócio dos relatórios mensais, da gestão de estoque e da
   reposição Hyundai, no formato de skills do Claude. Ficam disponíveis automaticamente para
   quem clonar o repositório e abrir a pasta no Claude Code.

## Rodar localmente

Requisitos: Python 3.12 e Git.

```bash
git clone https://github.com/henrihara18/grand-brasil-bi.git
cd grand-brasil-bi
py -3.12 -m pip install -r requirements.txt
```

Os dados **não estão no repositório** (são dados de clientes). Antes de rodar a tela de
avaliação é preciso ter, na raiz do projeto ou via secrets:

| base | arquivo local (raiz) | ou secret no `.streamlit/secrets.toml` |
|---|---|---|
| vendas 2025–26 | `Vendas 2025-2026 processado.xlsx` | `SALES_HISTORY_URL` (planilha Google publicada) |
| avaliações 2026+ | — | `APPRAISAL_HISTORY_URL` (export da plataforma, planilha Google publicada) |
| avaliações 2025 (legado) | `Avaliações 2025 e 2026.xlsx` | `APPRAISAL_LEGACY_URL` (planilha Google publicada) |
| senha da tela | — | `APP_PASSWORD` |

Peça os arquivos ou os links a quem administra o projeto; nunca os commite. O `.gitignore` já
bloqueia `*.xlsx`, `.env` e `.streamlit/`.

Exemplo de `.streamlit/secrets.toml`:

```toml
APP_PASSWORD = "..."
APPRAISAL_HISTORY_URL = "https://docs.google.com/spreadsheets/d/e/.../pubhtml"
APPRAISAL_LEGACY_URL = "https://docs.google.com/spreadsheets/d/.../edit"
SALES_HISTORY_URL = "https://docs.google.com/spreadsheets/d/.../edit"
```

Subir a tela (porta 8501):

```bash
py -3.12 run.py
```

## Testes e backtest

```bash
py -3.12 -m pytest tests/ -q
```

O backtest temporal (walk-forward, mês a mês, só com vendas já fechadas) é a régua de qualquer
mudança no algoritmo. Toda alteração de regra é medida nele antes de entrar:

```bash
py -3.12 scripts/backtest.py --label minha-mudanca
```

Os resultados vão para `backtest_results/` (ignorado pelo git); os números que importam ficam
registrados em `REVISAO_PRECIFICACAO.md`.

## Regras de trabalho

- Thresholds de negócio ficam em `config.yaml`, nunca no código.
- Lógica em `grand_brasil/analysis/`; a tela (`grand_brasil/dashboard/`) só apresenta.
- Mudança no algoritmo: uma por vez, medida no backtest, documentada na revisão.
- Rodar a suíte completa antes de entregar.
- Branches `feature/`, `fix/`, `refactor/`; commits curtos dizendo o porquê.

## Atualizar as bases

- **Vendas**: o RAW do ERP ("Relatório - <data>.xls", HTML disfarçado) vira o Excel processado
  com `py -3.12 scripts/build_sales_history.py --raw <arquivo>`. As regras de leitura estão na
  skill `relatorios-seminovos-grand-brasil`.
- **Avaliações**: a planilha publicada é o export da plataforma de avaliação; basta republicar.
- **Confiança calibrada**: a cada mês novo, `scripts/confidence_curve.py` regenera
  `data/confidence_calibration.json` (comando completo no `CLAUDE.md`).
