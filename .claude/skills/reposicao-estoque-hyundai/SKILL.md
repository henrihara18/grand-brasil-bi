---
name: "reposicao-estoque-hyundai"
description: Modelo fixo de sugestão de compra de carros 0 km Hyundai com a montadora para a Grand Brasil, mirando 30 dias de estoque por Versão x Cor Externa (e rateio por Cor Interna). Use SEMPRE que o Henri enviar um Excel de estoque Hyundai (tipo "Estoque_Hyundai_DD_MM.xlsx") junto com arquivos de vendas/faturados 0 km (tipo "Vendas_Jun-ago.xlsx", "Vendas_set_ate_22.xlsx"), ou pedir "reposição Hyundai", "sugestão de compra Hyundai", "pedido montadora Hyundai", "cobertura de estoque 0 km Hyundai", "30 dias de estoque" para Hyundai. Mesmo que ele só anexe os arquivos sem escrever nada, rode este modelo. Não usar para seminovos.
---

# Reposição de estoque 0 km Hyundai — Grand Brasil

## Fluxo principal (desde out/26): dashboard "Reposição Hyundai"

Entrada típica: dois relatórios do ERP `Relatório - <data>.xls` (são HTML, números em formato BR):
um de **vendas** (cabeçalho começa em `Família`; tem 3 meses cheios + mês corrente) e um de **estoque** (cabeçalho começa em `ST`). Identifique pelo cabeçalho, não pelo nome.

1. Gere as bases: `python scripts/prep_dashboard.py <vendas.xls> <estoque.xls> <AAAA-MM-DD da foto do estoque> <pasta_saida>` → `vendas_hyundai.json` e `estoque_hyundai.json` (sem nome de cliente).
2. Teste o cálculo localmente com `scripts/compute.js` em node (`global.window={}; require('./compute.js'); window.repoCompute(vendas, estoque, window.repoDefaults)`); confira que a soma das internas bate com a compra por cor.
3. Atualize o dashboard existente `https://claude.ai/artifact/BHDLmp6iqZVKGrThXGtGCN` (tipo Dashboard): `upload_asset` dos dois JSON e `update` em `datasets/vendas` e `datasets/estoque` (url, name, updated, título com a data). Se `compute.js` ou a página mudarem, `set` em `files/compute.js` / `files/index.html` (cópias em `scripts/`). Depois leia o `check`.
4. Responda com os dois cenários (A = 3 meses cheios; B = último mês + corrente), onde divergem (coluna Leitura), famílias curtas, excesso e parados > 90 dias.

Regras de classificação do estoque (definidas pelo Henri, out/26):
- `Disponível` (SIT ESTOQUE) → disponível.
- `Proposta: Reserva: 0 … Cliente: ACESSÓRIOS/ACESSORIOS GUARULHOS` → **disponível para venda** (só reservado para instalar acessório).
- `Proposta: <número> … Cliente: <pessoa>` → **vendido no mês, ainda não faturado**: sai do estoque e abate das vendas que faltam no mês (não é somado à demanda para não contar duas vezes, pois a curva é por data de faturamento).
- `Cliente: BLINDADO MASTER` (localização EM PROD BLINDAGEM MASTER) → fora da conta (confirmar com o Henri se é estoque próprio sendo blindado).
- TRÂNSITO livre → estoque (premissa); DEMOSTRAÇÃO → fora.
Dia de corte = véspera da foto do estoque (ou último dia faturado, se maior).

A planilha abaixo continua disponível quando ele pedir Excel.

Rodada recorrente ao longo do mês. Entrada: foto do estoque + vendas dos últimos 3 meses cheios + faturados do mês corrente até hoje. Saída: planilha com fórmulas vivas (`Reposicao_Hyundai_DD_MM.xlsx`) e um resumo em chat.

## Como rodar

```bash
python /mnt/skills/user/reposicao-estoque-hyundai/scripts/reposicao.py \
  --estoque /mnt/user-data/uploads/Estoque_Hyundai_DD_MM.xlsx \
  --vendas /mnt/user-data/uploads/<vendas meses cheios>.xlsx /mnt/user-data/uploads/<vendas mês atual>.xlsx \
  --out /mnt/user-data/outputs/Reposicao_Hyundai_DD_MM.xlsx
python /mnt/skills/public/xlsx/scripts/recalc.py /mnt/user-data/outputs/Reposicao_Hyundai_DD_MM.xlsx 90
```
Opções: `--dias-meta 30`, `--meses 3`, `--transito SIM|NAO`, `--lancamento "HYUNDAI I20=2026-07-01"` (repetível; 1º mês cheio a contar para família recém-lançada), `--data-base AAAA-MM-DD` (força a data de corte).
Vendas duplicadas entre arquivos são removidas por Chassi. Depois do recalc, leia as abas com pandas para montar o resumo (nunca digite números à mão).

Quando o i20 tiver 3 meses cheios dentro da janela (a partir de out/26 → janela jul–set), o parâmetro de lançamento deixa de ter efeito sozinho; pode manter.

## Colunas dos arquivos (definidas pelo Henri)

Os `.xls` do ERP são HTML: `reposicao.py` já lê os dois formatos.

Estoque (`header` na 1ª linha; última linha = Total, descartar):
- **A · ST** — disponibilidade. Considerar só `Disponível` (e SIT = ESTOQUE; o carro `DEMOSTRAÇÃO` sai). `TRÂNSITO` = já comprado, conta como estoque (premissa, confirmar). `Proposta: <nº>…` = reserva de cliente (sai do estoque e abate das vendas restantes do mês). `Proposta: Reserva: 0…Cliente: ACESSORIOS` = disponível (regra de out/26); `BLINDADO MASTER` = bloqueio interno (fora da conta).
- **M · COR** (externa), **N · COR INTERNA**, **O · D.E** (dias em estoque — carro parado há muito tempo = giro menor, cuidado).
- MODELO = versão; FAMÍLIA = modelo.

Vendas (`header` na 1ª linha; linhas Total/Média no fim, descartar):
- **C · Cor** (externa), **AB · Cor Interna**, **L · D.E** (dias de estoque na venda), **T · Marg. Ini.** (margem preliminar R$; comparação feita pelo **U · % MI** porque R$ não compara entre versões), K · Dt Venda.
- i20 lançado fim de junho/início de julho 2026: contar só a partir de julho.

## Lógica (tudo parametrizado na aba Premissas)

1. **Curva do mês**: % das vendas dos meses cheios feitas até o dia de corte (ex.: até dia 21 ≈ 45%; o último dia útil concentra 20–40% do mês). Projeção do mês = vendas até o corte ÷ curva.
2. **Peso de cada venda**: 1,0; ×0,5 se % MI < média da versão − 3 pp ou < 2% (venda "comprada" com desconto); ×0,5 se D.E na venda > 90 dias.
3. **Demanda mensal** por Versão x Cor = vendas ponderadas ÷ meses equivalentes (meses cheios considerados + curva). i20: 2 meses cheios.
4. **Estoque considerado** = Disponível + Trânsito. **Projetado fim do mês** = considerado − max(0, demanda × (1 − curva) − reservados).
5. **Meta** = demanda × 30/30. **Necessidade** = meta − projetado.
6. **Trava de envelhecimento**: cor com carro disponível > 90 dias → fator 0 (não compra, girar antes); > 60 dias → fator 0,5.
7. **Compra** = arredondamento de necessidade × fator (≥ 0,5 sobe).
8. **Interna**: compra da cor externa rateada pelo déficit de cada interna (sem déficit → mix de vendas), método do maior resto. Coluna "Soma internas (check)" tem que bater.

Status: COMPRAR / COMPRAR (reduzido) / TRAVADO / EXCESSO / SEM VENDA NO PERÍODO / BAIXO GIRO - só sob pedido / OK.

## Abas da saída

Resumo · Compra_Cor (principal) · Compra_Interna · Por_Versao (inclui % MI da versão vs média da família) · Envelhecidos (> 60 dias) · Premissas · Vendas · Estoque.

## Resumo em chat (formato)

Em português, prosa curta, sem excesso de bullets:
- Projeção do mês (vendas até o corte, curva, total projetado) e cobertura atual total em dias.
- Total sugerido de compra e onde está (por família/versão), destacando as maiores linhas de Versão x Cor x Interna.
- Onde há excesso e estoque envelhecido (> 90 dias) — o que não comprar e o que precisa girar.
- Alertas de margem: versões com % MI bem abaixo da família que o modelo manda comprar.
- Aviso de sensibilidade se a demanda ponderada estiver muito abaixo da projeção do mês (tendência de alta).
- Qualquer premissa nova ou dado estranho no arquivo (nova versão, cor nova, ST com texto diferente).
