# Dashboard de Seminovos — KPIs e Visualizações

Guia para construir dashboards visuais do estoque de seminovos da Grand Brasil. Use sempre que o usuário pedir construção, redesenho, ou expansão de um dashboard, relatório visual, ou painel de acompanhamento.

## Princípios de design

1. **Visão geral primeiro, detalhe sob demanda.** Topo do dashboard com 4-6 KPIs grandes; detalhe por filial / marca / veículo logo abaixo.
2. **Cores sempre seguindo os thresholds da skill.** Verde / amarelo / vermelho conforme as faixas definidas em `SKILL.md`.
3. **O bucket de envelhecimento é o eixo principal.** Praticamente todo gráfico relevante se beneficia de quebrar por 0-30 / 31-60 / 61-90 / 90+ dias.
4. **Filtros essenciais:** filial, marca, modelo, faixa de preço, classificação Grasso/Graspo, bucket de envelhecimento.
5. **Mostrar contagem E valor.** "23 carros parados há 90+ dias" tem peso diferente de "R$ 4,2M parados há 90+ dias".

## KPIs do topo (Hero metrics)

Linha superior do dashboard, sempre visível. 4-6 cartões grandes:

| KPI | Cálculo | Cor |
|-----|---------|-----|
| **% Estoque 90+ dias** ⭐ | Veículos 90+ dias ÷ Total no estoque × 100 | Pelo threshold (verde ≤10%, amarelo 10-15%, vermelho >15%) |
| **DME médio** | Média de dias em estoque de todos os veículos | Pelo threshold (verde ≤45, amarelo 46-60, vermelho >60) |
| **Total no estoque** | Contagem de veículos disponíveis | Neutro |
| **Capital imobilizado** | Soma do custo total de todos os veículos no estoque | Neutro |
| **Giro mensal** | Vendas do mês ÷ estoque médio do mês | Pelo threshold (verde ≥0,8; amarelo 0,5-0,8; vermelho <0,5) |
| **Margem média (vendas do mês)** | Média de margem das vendas concluídas no período | Pelo threshold (verde ≥12%, amarelo 8-12%, vermelho <8%) |

⭐ = KPI prioritário, destacar visualmente (maior, ou com badge).

## Gráficos essenciais

### 1. Distribuição por bucket de envelhecimento (gráfico de barras empilhadas)

**Eixo X:** filiais (ou marcas, conforme filtro)
**Eixo Y:** quantidade de veículos
**Cores:** 0-30 (verde claro), 31-60 (amarelo), 61-90 (laranja), 90+ (vermelho)

Permite ver instantaneamente onde o problema está concentrado.

### 2. Heatmap modelo × bucket

**Linhas:** modelos (top 20 por volume)
**Colunas:** buckets de envelhecimento
**Cores:** intensidade conforme contagem ou valor imobilizado

Mostra quais modelos estão atolando.

### 3. Scatter plot CTM × DME

**Eixo X:** Cost to Market (%)
**Eixo Y:** DME atual (dias)
**Tamanho do ponto:** custo total
**Cor:** classificação Grasso/Graspo (verde/cinza/vermelho)

Os pontos no canto superior direito (CTM alto E DME alto) são os carros problemáticos. Os no canto inferior esquerdo são os ideais.

### 4. Distribuição PTM (histograma)

**Eixo X:** faixa de PTM (intervalos de 2%, de 80% a 110%)
**Eixo Y:** contagem de veículos
**Cor:** pelo threshold de PTM

Mostra a saúde geral do posicionamento de preço.

### 5. Tabela de "carros que precisam de ação" (tabela ordenável)

Colunas mínimas:
- Filial
- Modelo / Versão / Ano
- Dias em estoque
- Bucket
- Preço atual
- FIPE
- PTM (%)
- Custo total
- CTM (%)
- Classificação (Grasso/Neutro/Graspo)
- **Ação recomendada** (resultado da árvore de decisão)
- **Última ação tomada** (data + tipo: redução, mídia, etc.)
- Dias desde a última ação

Ordenação padrão: por dias em estoque (decrescente), depois por valor imobilizado.

Default filter: só mostrar veículos com 30+ dias e ação recomendada não-nula. Permitir alternar para "ver tudo".

### 6. Tendência mensal (linha)

**Eixo X:** meses
**Eixo Y duplo:**
- Linha 1: % estoque com 90+ dias
- Linha 2: DME médio
- Linha 3: giro mensal

Mostra se a operação está melhorando ou piorando ao longo do tempo. Marcar metas com linhas tracejadas.

### 7. Funil de captação

Visualização do business plan do treinamento:
- Clientes atendidos → Avaliações abertas → Captações → Trade-ins efetivados

Permite ver onde o funil está vazando.

## Layout sugerido (uma única página)

```
┌─────────────────────────────────────────────────────────────┐
│  FILTROS: Filial ▾  Marca ▾  Modelo ▾  Bucket ▾  Período ▾ │
├─────────────────────────────────────────────────────────────┤
│  [% 90+ dias]  [DME médio]  [Estoque]  [Capital]  [Giro]   │ ← Hero
├─────────────────────────────────────────────────────────────┤
│  ┌─ Buckets por filial ─┐  ┌─ Distribuição PTM ──────────┐│
│  │   Barras empilhadas  │  │   Histograma                 ││
│  └──────────────────────┘  └──────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  ┌─ CTM × DME (scatter) ─┐ ┌─ Heatmap modelo × bucket ──┐ │
│  │                        │ │                             │ │
│  └────────────────────────┘ └─────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  TABELA: Carros que precisam de ação                       │
│  [colunas conforme #5]                                      │
└─────────────────────────────────────────────────────────────┘
```

Tendência mensal e funil de captação podem ficar em uma segunda aba/seção, ou expandidos sob demanda.

## Cores e tipografia (sugestão)

- Fundo: cinza muito claro (#F8F9FA) ou branco
- Verde saudável: #10B981
- Amarelo atenção: #F59E0B
- Vermelho crítico: #EF4444
- Neutro: #64748B
- Texto principal: #1F2937
- Use uma fonte sans-serif legível (Inter, system-ui, etc.)
- KPIs do topo em fonte grande (32-48px) com label menor acima

## Stack técnico recomendado

Para a operação Grand Brasil (uso por 2-3 pessoas, dados em Google Sheets):

**Opção A — Mais leve, mais rápida de fazer:**
- HTML estático + Tailwind + Chart.js ou Recharts
- Lê direto do Google Sheets via API pública (publicar planilha como CSV ou usar Sheets API)
- Hospedagem: pode rodar localmente, ou em qualquer hospedagem estática (Vercel, Netlify, GitHub Pages)
- Atualização: refresh manual ou polling a cada N minutos

**Opção B — Mais robusta:**
- Backend Python (FastAPI) que lê Sheets via service account
- Frontend React + Vite + TailwindCSS + Recharts
- Cache de dados (não bate na API a cada page load)
- Hospedagem: Railway, Fly.io, ou servidor próprio

Para começar, **Opção A é o caminho.** Validar o desenho antes de investir em backend.

## Atualização dos dados

A planilha do Google Sheets deve ter, idealmente, estas colunas para que o dashboard funcione bem:

**Identificação:**
- ID interno do veículo
- Filial
- Marca, Modelo, Versão, Ano modelo, Ano fabricação
- Cor, Quilometragem
- Combustível, Câmbio

**Datas:**
- Data de entrada no estoque
- Data prevista de disponibilidade (se em recondicionamento)
- Data de venda (quando vendido)

**Financeiro:**
- Preço de compra (avaliação)
- Custo de recondicionamento
- Custo total
- Preço de anúncio atual
- Histórico de preços (idealmente cada redução com data)
- FIPE atual (alimentado por outra coluna ou lookup)

**Mercado:**
- Classificação Grasso/Graspo (manual, pode ser sobrescrita pela automática)
- Quantidade de visualizações no anúncio (se Webmotors/iCarros tiver API)
- Quantidade de leads recebidos

**Operacional:**
- Status (disponível, reservado, vendido, em repasse)
- Última ação tomada + data (redução, mídia, repasse aberto)

Se algum desses campos não existir hoje, o dashboard ainda funciona com os disponíveis — apenas os gráficos e métricas dependentes daquele campo ficam indisponíveis ou simplificados.

## Próximos passos típicos para o usuário

Quando recomendar implementação:
1. Listar quais campos da skill **já existem** na planilha atual e quais precisariam ser adicionados
2. Sugerir adições incrementais (não pedir 30 colunas novas de uma vez)
3. Começar com os 4-6 KPIs do topo + a tabela de "carros que precisam de ação". O resto vem depois.
