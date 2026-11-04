# Glossário Rápido — Seminovos Grand Brasil

Consulta rápida de fórmulas, siglas e thresholds. Para detalhes e lógica, ver `SKILL.md` e `references/arvore-decisao.md`.

## Siglas

| Sigla | Significado |
|-------|-------------|
| DME | Dias Médios de Estoque |
| CTM | Cost to Market |
| PTM | Price to Market |
| MDS | Market Days Supply |
| ROS | Return on Sales |
| ROI | Return on Investment |
| F&I | Finanças e Seguros |
| FIPE | Fundação Instituto de Pesquisas Econômicas (referência de preço) |

## Fórmulas

| Métrica | Fórmula |
|---------|---------|
| DME (veículo) | data_atual − data_entrada |
| DME (agregado) | Σ dias_estoque ÷ N veículos |
| CTM | (compra + recondicionamento) ÷ FIPE × 100 |
| PTM | preço_anúncio ÷ FIPE × 100 |
| MDS | estoque_mercado ÷ vendas_diárias_30d |
| Giro mensal | vendidos_mês ÷ estoque_médio_mês |
| Giro anual | giro_mensal × 12 |
| Margem | (venda − custo_total) ÷ venda × 100 |
| ROS | lucro_líquido ÷ receita_total × 100 |
| ROI | lucro_total ÷ capital_investido × 100 |

## Thresholds (resumo)

### DME médio
🟢 ≤ 45d • 🟡 46-60d • 🔴 > 60d

### % estoque 90+ dias (KPI duro)
🟢 ≤ 10% • 🟡 10-15% • 🔴 > 15%

### CTM (vs FIPE)
🟢 ≤ 82% • 🟡 82-87% • 🔴 > 87%

### PTM (vs FIPE) — não-blindados
🔴 < 96% (subprecificado) • 🟢 96-102% (ideal) • 🟡 102-110% (acima FIPE) • 🔴 > 110% (sobreprecificado)

### PTM (vs FIPE) — blindados
🟢 105-135% (esperado) • 🟡 > 135% (atenção)

### Margem média
🟢 ≥ 12% • 🟡 8-12% • 🔴 < 8%

### Giro anual
🟢 ≥ 8x • 🟡 5-8x • 🔴 < 5x (meta velocity 2.0: 15-16x)

## Buckets de envelhecimento

| Bucket | Dias | Estratégia rápida |
|--------|------|-------------------|
| Apresentação | 0-30 | Manter preço, focar em qualidade do anúncio |
| Reavaliação | 31-60 | Revisão obrigatória do anúncio/pátio. Redução opcional e leve |
| Liquidação | 61-90 | Redução 10-15% + transferência interfilial. Lojista opcional |
| Ação compulsória | 90+ | Cotar lojistas obrigatoriamente. Valor mínimo de repasse definido |

## Classificação Grasso/Graspo

| Tipo | DME histórico do modelo | Estratégia |
|------|-------------------------|------------|
| Grasso | ≤ 30d | Comprar mais, giro rápido |
| Neutro | 31-59d | Manter |
| Graspo | ≥ 60d | Cuidado ao comprar, repasse mais cedo |

## Alavancas operacionais Grand Brasil

1. **Reduzir preço de anúncio**
2. **Repasse interfilial** (transferência interna entre filiais)
3. **Repasse para lojista** (parceiro / atacado)

## Metas operacionais

| Métrica | Meta |
|---------|------|
| DME médio | 35-45 dias |
| % estoque 90+ dias | ≤ 15% |
| Margem média | 12-18% |
| Giro anual | 8-10x (ambicioso 15-16x) |
| ROI 12 meses | ≥ 100% |
| Receitas adicionais | cobrir 100% custo fixo |
