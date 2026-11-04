---
name: gestao-seminovos-grand-brasil
description: Framework de análise e gestão de estoque de seminovos da Grand Brasil. Contém glossário de métricas, fórmulas de cálculo, thresholds calibrados para a operação (Toyota, BYD, Hyundai, BMW), regra de buckets de envelhecimento 30/60/90/120 dias, classificação Grasso/Graspo, e árvore de decisão preço/repasse. Use SEMPRE que o usuário pedir análise de estoque de seminovos, decisões sobre preço, desconto, repasse, anúncios, indicadores como DME, Cost to Market, Price to Market, Market Days Supply, giro, ROI de seminovos, ou ao construir dashboards/relatórios sobre o estoque. Use também quando o pedido envolver classificar veículos, recomendar ações sobre carros parados, calcular metas de estoque, ou montar visualizações de KPIs operacionais de seminovos. Mesmo que o usuário não cite o nome dessas métricas explicitamente, qualquer pergunta sobre "o que fazer com esse carro", "esse carro está caro?", "vale a pena segurar?" sobre seminovos deve consultar esta skill.
---

# Gestão de Seminovos — Grand Brasil

Framework de análise e tomada de decisão para o estoque de seminovos da Grand Brasil. Calibrado para operação multi-marca (Toyota, BYD, Hyundai, BMW) com ticket médio em torno de R$ 130 mil.

## Princípios fundamentais

1. **O lucro é feito na compra, não na venda.** A margem é definida no momento da aquisição. Compra ruim raramente é corrigida na venda.
2. **ROI vence margem unitária.** Vender mais carros com margem menor e giro rápido bate vender poucos com margem alta. Velocity 2.0: 15-16 giros/ano.
3. **Tempo no pátio é o maior inimigo do lucro.** Cada dia adicional consome 0,5-1% em depreciação e custos.
4. **Carro barato sem demanda não vende.** Reduzir preço só resolve problema de preço; problema de demanda exige repasse.
5. **Receitas adicionais (F&I, acessórios, despachante) devem cobrir 100% dos custos fixos.** Margem do carro é só uma parte da rentabilidade.

## Glossário de métricas

### DME — Dias Médios de Estoque
Quantos dias um veículo permanece no pátio desde a entrada/compra até a venda. Mede o giro do estoque.

**Cálculo (por veículo):** `data_atual − data_entrada_estoque`
**Cálculo (agregado):** média ponderada do DME de todos os veículos no período

### Cost to Market (CTM)
Spread entre o custo total do veículo (compra + recondicionamento) e o preço médio de varejo do mesmo modelo no mercado.

**Cálculo:** `(Preço de compra + Recondicionamento) ÷ Preço FIPE × 100`

Quanto mais baixo, maior o potencial de lucro. Indica liquidez do estoque.

### Price to Market (PTM)
Spread entre o preço de venda anunciado e o preço médio de mercado do mesmo modelo.

**Cálculo:** `Preço de venda anunciado ÷ Preço FIPE × 100`

Indica posicionamento competitivo. Faixa apropriada típica: 98-101% PTM contra mercado real. **Como Grand Brasil usa FIPE como referência (e FIPE costuma estar acima do mercado real praticado), as faixas são ajustadas — ver thresholds abaixo.**

### Market Days Supply (MDS)
Mede oferta vs demanda de um modelo no mercado regional. Indica quantos dias o estoque atual de mercado levaria pra ser absorvido na velocidade de vendas atual.

**Cálculo:** `Estoque disponível no mercado regional ÷ Média de vendas diárias dos últimos 30-45 dias`

A concessionária não influencia o MDS — é uma medida do mercado. Use para decidir se é hora de comprar mais (MDS baixo = alta demanda, escassez) ou de não comprar (MDS alto = excesso de oferta).

### Giro de Estoque
Quantas vezes o capital investido em estoque "rodou" (foi vendido e reposto) no período.

**Cálculo (mensal):** `Veículos vendidos no mês ÷ Estoque médio do mês`
**Cálculo (anual):** `Giro mensal × 12`

### Margem
Percentual do preço de venda que corresponde ao lucro.

**Cálculo:** `(Preço de venda − Custo total) ÷ Preço de venda × 100`

Onde **custo total** = compra + recondicionamento + custos diretos (frete, despachante, etc.)

### ROS — Return on Sales
Mede eficiência operacional. "De tudo que faturei, quanto virou lucro?"

**Cálculo:** `Lucro líquido total ÷ Receita total × 100`

Inclui margem do carro + F&I + acessórios + serviços.

### ROI — Return on Investment
Mede eficiência do capital investido. "Para cada R$ que coloquei no negócio, quanto voltou?"

**Cálculo:** `Lucro total ÷ Capital investido × 100`

Fortemente impactado pelo giro. ROI alto vem de giro rápido, não de margem unitária alta.

### Taxa de Captação
Relação entre veículos avaliados e veículos efetivamente comprados.

**Cálculo:** `Veículos comprados ÷ Veículos avaliados × 100`

### Taxa de Trade-in
Percentual das vendas de 0km que tiveram um usado entrando como parte do pagamento.

**Cálculo:** `Vendas com trade-in ÷ Total de vendas 0km × 100`

## Thresholds Grand Brasil

Estes são os números calibrados para a operação. Use-os como cores de alerta em dashboards e como referência em análises.

### DME — Dias Médios de Estoque

| Status | Faixa | Cor |
|--------|-------|-----|
| Saudável | DME médio ≤ 45 dias | 🟢 Verde |
| Atenção | DME médio entre 46 e 60 dias | 🟡 Amarelo |
| Crítico | DME médio > 60 dias | 🔴 Vermelho |

**KPI duro adicional:** ≤ 15% do estoque com mais de 90 dias. Este é o indicador prioritário da operação Grand Brasil.

| Status | % do estoque com 90+ dias | Cor |
|--------|---------------------------|-----|
| Saudável | ≤ 10% | 🟢 Verde |
| Atenção | 10% a 15% | 🟡 Amarelo |
| Crítico | > 15% | 🔴 Vermelho |

### Cost to Market (vs FIPE)

Como Grand Brasil usa FIPE (que tende a ficar acima do preço de mercado real), as faixas são ajustadas para baixo em relação ao treinamento padrão.

| Status | CTM vs FIPE | Interpretação |
|--------|-------------|---------------|
| 🟢 Excelente | ≤ 78% | Compra muito boa, alta margem potencial |
| 🟢 Saudável | 78% a 82% | Compra dentro do esperado |
| 🟡 Atenção | 82% a 87% | Margem apertada, exigirá venda rápida |
| 🔴 Crítico | > 87% | Compra mal feita, margem comprometida |

### Price to Market (vs FIPE) — carros não-blindados

A política Grand Brasil é trabalhar próximo da FIPE, com leve premium aceitável.

| Status | PTM vs FIPE | Interpretação |
|--------|-------------|---------------|
| 🔴 Subprecificado | < 96% | Está deixando dinheiro na mesa, ou o carro é problemático |
| 🟢 Ideal | 96% a 102% | Faixa de operação Grand Brasil. PTM próximo de 100% é alvo. |
| 🟡 Acima FIPE | 102% a 110% | Aceitável em bucket 0-30 com justificativa. Reduzir se passar pra 31-60. |
| 🔴 Sobreprecificado | > 110% | Dificilmente gera volume. Reavaliar imediatamente. |

### Price to Market — carros BLINDADOS

Veículos blindados naturalmente operam acima da FIPE, porque a FIPE não captura o custo da blindagem. **Não aplicar os thresholds acima a blindados.**

| Status | PTM vs FIPE | Interpretação |
|--------|-------------|---------------|
| 🟢 Esperado | 105% a 135% | Faixa típica de blindados, depende do nível de blindagem (III-A, III) |
| 🟡 Atenção | > 135% | Verificar se a blindagem justifica o premium tão alto |

**Importante:** sempre filtrar/segmentar análises de PTM por status de blindagem. Misturar blindados e não-blindados em médias agregadas distorce o diagnóstico.

**Truque do treinamento:** preços terminados em ".990" (R$ 49.990 vs R$ 50.000) geram mais buscas em portais. Vale aplicar.

### Buckets de envelhecimento (30/60/90/120) — Regras Grand Brasil

| Bucket | Dias | Estratégia | Margem esperada |
|--------|------|------------|-----------------|
| **Apresentação** | 0-30 | Manter preço (PTM ~100%, blindados acima). Foco em qualidade do anúncio (fotos, descrição) e mídia. Sem redução. | 15-25% |
| **Reavaliação** | 31-60 | **Revisão obrigatória do anúncio e do pátio** (qualidade das fotos, posicionamento, descrição). Redução de preço opcional e leve quando aplicada. | 10-18% |
| **Liquidação** | 61-90 | **Redução de 10-15% recomendada** (pode ser menor com justificativa, ex: carro indisponível antes). Abrir transferência interfilial em paralelo. Cotar lojista opcional. | 5-12% |
| **Ação compulsória** | 90+ | **Cotação com lojistas obrigatória.** Definir valor mínimo de repasse aceitável. Aceita-se prejuízo controlado pra liberar capital. | Pode aceitar prejuízo controlado |

**Princípios operacionais:**

1. **No bucket 61-90, redução é o padrão mas não é cego.** Se o carro estava indisponível por estar em recondicionamento, sem fotos, ou em trânsito até há pouco, a "idade" não reflete tempo real de exposição. Nesse caso, redução pode ser menor ou adiada — mas a justificativa deve ser registrada.

2. **No bucket 90+, ter um "valor mínimo de repasse" definido é obrigatório.** É o preço pelo qual a gestão aceita liberar o veículo pra lojista. Sem isso, toda negociação vira ad hoc e perde-se referência pra decidir entre "fechar" e "renegociar".

3. **Carros que entram em bucket sem ação tomada são alertas vermelhos.** Bucket 61-90 sem nenhuma ação registrada (sem revisão, sem redução, sem repasse aberto) é o pior cenário operacional.

### Giro e margem (metas operacionais)

| Métrica | Meta Grand Brasil |
|---------|-------------------|
| DME médio | 35-45 dias |
| % estoque 90+ dias | ≤ 15% |
| Margem média | 12-18% |
| Giro anual | 8-10x (meta ambiciosa: 15-16x) |
| ROI 12 meses | ≥ 100% |

## Classificação Grasso vs Graspo

Híbrida: começa automática, equipe pode sobrescrever manualmente.

### Inferência automática

Baseada no DME histórico do modelo na operação Grand Brasil (média dos últimos N veículos vendidos do mesmo modelo):

| Classificação | DME histórico do modelo | Estratégia |
|---------------|-------------------------|------------|
| **Grasso** | ≤ 30 dias | Alta demanda. Comprar mais. Margem moderada e giro rápido. |
| **Neutro** | 31 a 59 dias | Demanda média. Manter. |
| **Graspo** | ≥ 60 dias | Baixa demanda. Cuidado ao comprar. Exige preço agressivo e/ou repasse mais cedo. |

### Override manual

A equipe pode reclassificar um veículo específico se conhecer particularidades (cor difícil, opcional inusitado, motor pouco procurado, etc.) que não aparecem na média do modelo.

**Regra:** se houver classificação manual, ela tem prioridade sobre a automática.

## Árvore de decisão: o que fazer com cada carro

A skill considera **três alavancas operacionais** disponíveis na Grand Brasil:
1. **Reduzir preço** do anúncio
2. **Repassar para outra filial** Grand Brasil (transferência interna)
3. **Repassar para lojista** parceiro / atacado

Para a árvore de decisão completa que combina tempo de estoque, PTM e classificação Grasso/Graspo, ver `references/arvore-decisao.md`.

**Resumo da lógica:**

- **0-30 dias:** manter preço, foco em qualidade do anúncio e mídia
- **31-60 dias:** revisão obrigatória do anúncio/pátio. Redução de preço opcional e leve, sem corte automático
- **61-90 dias:** redução de 10-15% recomendada (pode ser menor com justificativa) + transferência interfilial em paralelo + cotação com lojista opcional
- **90+ dias:** cotação com lojistas obrigatória + valor mínimo de repasse definido + aceita-se prejuízo controlado

**Sinalizações visuais importantes (independentes da regra de bucket):**
- **Graspo**: badge visual em todos os buckets (sinaliza ciclo naturalmente mais longo, mas não muda regra)
- **Sem ação no bucket**: badge vermelha "ação pendente" quando carro entra em 31-60 ou 61-90 sem nenhuma ação registrada
- **Indisponível antes**: campo opcional "dias efetivamente disponível" que justifica não ter agido em buckets anteriores

## Receitas adicionais (F&I e agregados)

O treinamento enfatiza que **a meta é cobrir 100% dos custos fixos da operação com receitas adicionais**, deixando a margem do carro como "lucro limpo". Componentes:

- **F&I (Finanças e Seguros):** comissão de financiamento, seguro auto, garantia estendida, seguro prestamista
- **Acessórios e estética:** películas, vitrificação, centrais multimídia, sensores, rodas
- **Serviços e pós-venda:** despachante, pacotes de revisão, higienização, rastreador

Em análises de rentabilidade do estoque, sempre que possível separar:
- Lucro do carro (margem direta)
- Lucro de F&I por unidade
- Lucro de acessórios/serviços por unidade

## Armadilhas a evitar (sinais de alerta no dashboard)

Estas situações merecem destaque visual em qualquer dashboard:

1. **Apego emocional ao estoque** — carro com 60+ dias sem nenhuma ação registrada (sem redução de preço, sem aumento de mídia)
2. **Precificação fixa** — carro com 45+ dias e mesmo preço da entrada
3. **Compra ruim** — CTM > 87% no momento da entrada
4. **Sub-precificação cega** — PTM < 92% sem justificativa (carro pode ter problema oculto)
5. **Sazonalidade ignorada** — não ajustar preços/estratégia em períodos de alta (verão, fim de ano) e baixa demanda

## Quando referenciar arquivos auxiliares

- `references/arvore-decisao.md` — quando o usuário pedir análise específica de "o que fazer com este carro" ou ao montar lógica de alertas e recomendações no dashboard
- `references/dashboard-kpis.md` — quando o pedido for construir dashboard, escolher gráficos, ou definir layout de visualização
- `references/glossario-rapido.md` — para consulta rápida de fórmulas e siglas em respostas curtas

## Como usar esta skill em diferentes contextos

**Em conversas analíticas** ("este carro tem 75 dias, PTM 98%, é Graspo — o que faço?"):
- Aplicar árvore de decisão diretamente
- Citar o threshold relevante
- Recomendar 1-2 ações concretas, não 5

**Em construção de dashboard:**
- Usar os thresholds desta skill como cores de alerta
- Implementar buckets 30/60/90/120 como agrupamento padrão
- Destacar visualmente o KPI duro de "% estoque 90+ dias"
- Mostrar Grasso/Graspo como filtro/cor

**Em análise de planilha de estoque:**
- Calcular DME, CTM, PTM linha a linha quando os dados permitirem
- Classificar cada veículo no bucket de envelhecimento
- Inferir Grasso/Graspo se houver histórico suficiente
- Sumarizar % saudável vs atenção vs crítico
