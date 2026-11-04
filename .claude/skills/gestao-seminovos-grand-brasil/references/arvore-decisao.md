# Árvore de Decisão — O que fazer com cada carro

Este arquivo detalha a lógica de decisão Grand Brasil para cada veículo do estoque. Use sempre que precisar recomendar ação sobre um veículo específico, ou ao implementar lógica de alertas em dashboards.

## Inputs necessários

Para qualquer decisão precisa, são necessários:
- **Dias em estoque** (calculado a partir da data de entrada)
- **Dias efetivamente disponível** (descontando dias em recondicionamento, em trânsito, sem fotos) — opcional, usado pra justificar inação em buckets anteriores
- **Preço atual de venda** anunciado
- **Preço FIPE** atual do modelo/ano
- **PTM** = preço venda ÷ FIPE × 100
- **Status BLINDADO** (sim/não) — define qual faixa de PTM aplicar
- **Classificação Grasso/Graspo** (visual apenas, não muda regra)
- **Custo total** (compra + recondicionamento) — quando disponível
- **CTM** = custo total ÷ FIPE × 100 — quando disponível
- **Valor mínimo de repasse** (obrigatório no bucket 90+)
- (Opcional) histórico da última ação tomada: tipo, data

## Tabela de decisão por bucket

### Bucket 1 — Apresentação (0-30 dias)

| Cenário | PTM atual | Ação recomendada |
|---------|-----------|------------------|
| Padrão (não-blindado) | 96-102% | **Manter preço.** Investir em apresentação visual e descrição. |
| Padrão (blindado) | 105-135% | **Manter preço.** Faixa esperada para blindados. |
| Subprecificado (não-blindado) | < 96% | **Revisar preço para cima** para 96-102%. Pode haver erro de cadastro ou avaliação conservadora. |
| Acima da faixa (não-blindado) | 102-110% | Aceitável neste bucket se houver justificativa (carro novo, baixa quilometragem, opcional valorizado). Ajustar para 96-102% se passar pra bucket 31-60. |
| Sobreprecificado (não-blindado) | > 110% | **Reduzir agora** para 96-102%. Acima de 110% raramente gera tráfego. |
| Sobreprecificado (blindado) | > 135% | Verificar se a blindagem justifica. Se não, reduzir. |

### Bucket 2 — Reavaliação (31-60 dias)

**A regra principal: revisão obrigatória, redução opcional.**

| Cenário | Ação recomendada |
|---------|------------------|
| Padrão | **Revisão obrigatória do anúncio:** qualidade das fotos, descrição, opcionais listados, posição no pátio. Pode-se ajustar mídia/destaque sem alterar preço. |
| PTM acima da faixa ideal (não-blindado >102%, blindado >135%) | Trazer pra faixa ideal. |
| PTM já está na faixa ideal | Reavaliar canais e investimento em mídia, **redução de preço é opcional e leve** (até 5%). |
| Já houve redução recente (últimos 15 dias) e não vendeu | Aguardar mais alguns dias antes de mexer no preço de novo. Investigar problema invisível (fotos, condição). |
| Carro estava indisponível antes (recondicionamento, trânsito) | Considerar tempo efetivamente disponível em vez de dias totais. Pode permanecer no bucket 1 se exposição real foi <30 dias. Justificativa registrada. |

**⚠️ Alerta:** carro entra no bucket 31-60 e ainda não teve nenhuma revisão registrada → badge vermelha "ação pendente" no dashboard.

### Bucket 3 — Liquidação (61-90 dias)

**A regra principal: redução de 10-15% é o padrão, transferência interfilial entra em paralelo, cotação com lojista é opcional.**

| Cenário | Ação recomendada |
|---------|------------------|
| Padrão | **Redução de 10-15% no preço** + abrir transferência interfilial em paralelo. Cotação com lojista opcional. |
| Carro estava indisponível antes | Redução pode ser menor (5-10%) com justificativa registrada. Avaliar se é caso de estender bucket 31-60 contando dias efetivos. |
| Já reduziu 1x no bucket anterior (31-60) | Reduzir mais 5-10% (somar com a redução anterior pra chegar próximo dos 10-15%). |
| Já reduziu 2x e segue parado | Pular pra repasse interfilial direto. Reduções adicionais têm retorno marginal decrescente. |
| PTM já está abaixo da faixa ideal e não vende (não-blindado <96%) | Problema não é preço — investigar antes de reduzir mais. Verificar fotos, descrição, condição, histórico DETRAN. |
| Graspo (badge visual) | Mesmo critério de redução, **mas considerar acelerar repasse interfilial** dado o ciclo naturalmente mais longo. |

**⚠️ Alertas:**
- Carro está no bucket 61-90 sem nenhuma ação tomada → badge vermelha "ação pendente"
- Reduziu 2+ vezes e segue parado → badge "candidato a repasse"

### Bucket 4 — Ação compulsória (90+ dias)

**A regra principal: cotação com lojistas obrigatória, valor mínimo de repasse definido, prejuízo controlado aceitável.**

Este é o bucket que conta para o **KPI duro de ≤ 15% do estoque**. Toda ação aqui é prioridade máxima.

| Cenário | Ação recomendada |
|---------|------------------|
| Entrou agora no 90+ | **Cotar com 2-3 lojistas em paralelo** + manter transferência interfilial aberta + última possibilidade de redução de preço. |
| Sem valor mínimo de repasse definido | **Definir o valor mínimo agora.** É o preço pelo qual a gestão aceita liberar pro lojista. Sem isso, negociação vira ad hoc. |
| Lojista ofereceu acima do valor mínimo | 🟢 Fechar. |
| Lojista ofereceu próximo do valor mínimo (até 5% abaixo) | 🟡 Negociar. Pode aceitar dependendo do tempo total já gasto. |
| Lojista ofereceu muito abaixo do valor mínimo | 🔴 Reavaliar valor mínimo (pode estar fora do mercado de atacado) ou seguir pra leilão. |
| Filial irmã topou transferência | Avaliar: transferir tem custo (frete, retrabalho) — vale só se a filial destino tiver mercado real pro modelo. |

**Princípio:** após 90 dias, o objetivo deixa de ser maximizar lucro daquele carro e passa a ser **liberar capital**. O custo de oportunidade do capital preso é maior que a perda residual.

## Sinalizações visuais (badges) no dashboard

Independentes da regra de bucket — são marcações que ajudam o gestor a contextualizar:

| Badge | Significado | Quando aplicar |
|-------|-------------|----------------|
| 🟠 **Graspo** | Modelo de demanda baixa | Sempre que classificação automática ou manual indicar Graspo |
| 🟢 **Grasso** | Modelo de demanda alta | Sempre que classificação automática indicar Grasso (DME histórico ≤30d) |
| 🛡️ **Blindado** | Veículo blindado | Quando coluna BLINDADO = SIM. Aplica thresholds de PTM diferentes. |
| 🚚 **Em trânsito** | Anunciado, ainda não no estoque | Quando data de entrada está vazia mas anúncio está ativo |
| 🔧 **Indisponível antes** | Já passou tempo em recondicionamento | Quando dias efetivamente disponível < dias totais em estoque |
| ⚠️ **Ação pendente** | Bucket 31-60 ou 61-90 sem ação registrada | Carro entrou no bucket e nenhuma ação foi tomada |
| 💰 **Candidato a repasse** | Reduções esgotadas | 2+ reduções de preço sem venda |
| 🎯 **Acima do valor mínimo** | Lojista deu boa oferta | Bucket 90+ com oferta acima do valor mínimo definido |

## Casos especiais

### Carro com CTM > 87% na entrada (compra ruim)

*Aplicável quando custo de preparação + compra estiverem preenchidos.*

Sinalizar imediatamente como **risco de margem comprometida desde o nascimento**. Estratégia:
- Acelerar todos os prazos: tratar como bucket 30 a partir de 21 dias, bucket 60 a partir de 42 dias, etc.
- Aceitar margem menor desde o início
- Se chegar a 60+ dias, repasse é geralmente preferível a redução, porque a margem já estava apertada

### Carro com PTM < 96% (não-blindado) que não vende em 30+ dias

**Vermelho operacional.** Carro está barato e não vende — problema não é preço. Verificar:
1. Qualidade das fotos (refazer)
2. Descrição completa? Opcionais listados?
3. Histórico DETRAN limpo? Há indicação de sinistro/leilão visível ao consumidor?
4. Condição estética real (precisa de reparo cosmético?)
5. Já foi visto presencialmente nos últimos 15 dias?

Antes de qualquer outra ação, resolver o problema invisível.

### Carro blindado parado

Blindados têm mercado mais nichado e ciclo mais longo por natureza. Mesmo assim, valem as regras de bucket — só que **com tolerância maior pra "indisponível antes" e ciclo Graspo**. A maioria dos blindados deveria ser classificada Graspo automaticamente pelo histórico.

## Output esperado de uma análise

Quando aplicar esta árvore para um veículo específico, estruturar a resposta como:

1. **Diagnóstico em 1 frase**: "Este Yaris XLS 2022 está no bucket de Liquidação (78 dias), classificado como Graspo, com PTM atual de 101% (ideal)."
2. **Ação principal recomendada**: "Aplicar redução de 10-15% (de R$ X para R$ Y) e abrir transferência interfilial."
3. **Ação secundária**: "Cotação com lojistas é opcional neste bucket — se não houver retorno em 15-20 dias, vira obrigatória ao entrar no bucket 90+."
4. **Sinalizações**: "Carro está marcado como Graspo (modelo de ciclo mais longo) e teve sua última redução há 25 dias."
5. **Risco se não agir**: "Sem ação, em 12 dias entra no bucket 90+ onde cotação com lojista vira obrigatória e prejuízo controlado é aceitável."

Sempre evitar entregar uma lista de 5 ações simultâneas — escolher a 1 ou 2 mais prováveis de resolver e deixar claro qual é o plano B.
