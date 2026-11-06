---
name: "relatorios-seminovos-grand-brasil"
description: "Modelo fixo de dois relatórios mensais de seminovos da Grand Brasil — (1) Relatório de Vendas do mês e (2) Relatório de Cobertura Estoque vs Vendas (dias de estoque, meta 30 dias). Use SEMPRE que o Henri enviar um Excel de vendas de seminovos (arquivo tipo \"Vendas_Mês_Ano.xlsx\"), de estoque (tipo \"Estoque_DD_MM_AA.xlsx\") ou o extrato RAW do ERP (arquivo tipo \"Relatorio_-_data.xls\", que na verdade é HTML), ou pedir \"fechamento do mês\", \"relatório de vendas\", \"como foi o mês\", \"análise de estoque\", \"dias de estoque\", \"cobertura de estoque\", \"vs mês anterior\" no contexto de seminovos. Use também quando ele mandar dois ou mais meses e pedir comparativo. Contém o layout exato das colunas, as regras de leitura do extrato RAW, a fórmula de margem, as regras de normalização de modelo (shortname), filial e marca, os cortes obrigatórios e o cálculo de dias de estoque a custo. Mesmo que ele só anexe o arquivo sem escrever nada, rode este modelo."
---

# Relatórios Mensais de Seminovos — Grand Brasil

Dois relatórios padronizados, gerados a partir dos extratos brutos do sistema. Este skill define
o layout, as regras de cálculo e os cortes obrigatórios para que o resultado seja comparável mês a mês.

Para thresholds operacionais (DME, CTM, PTM, buckets, Grasso/Graspo, árvore de decisão),
consulte a skill **gestao-seminovos-grand-brasil**. Este skill cuida do *formato do relatório*;
aquele cuida do *julgamento operacional*.

## Arquivos de entrada

| Arquivo | Nome típico | Header | Observação |
|---|---|---|---|
| Vendas do mês | `Vendas_<Mês>_<Ano>.xlsx` | linha 2 (`header=1`) | coluna A vazia; 1 linha por carro vendido |
| Estoque (foto do dia) | `Estoque_DD_MM_AA.xlsx` | linha 2 (`header=1`) | coluna A vazia; 1 linha por carro em estoque |
| **Estoque RAW do ERP** | `Relatório_-_<timestamp>.xls` | n/a | **é HTML, não xls** — ver seção própria abaixo |
| Base de shortnames | `Tag_Modelos.xlsx` | linha 2 (`header=1`) | em `assets/`; usar a versão mais recente que o Henri enviar |

Sempre: `pd.read_excel(path, header=1).drop(columns=['Unnamed: 0'], errors='ignore')`.

### Layout alternativo — planilha de trabalho consolidada

O Henri também mantém um arquivo de acompanhamento (`Atualização_vendas_geral_-_XXX_XX.xlsx`)
com várias abas, uma por mês (`Vendas junho`, `vendas`, `Sheet1` com o histórico). Esse layout já
vem enriquecido: tem `Marca`, `Shortname` e `Filial(2)` prontos, mas **não tem `Loja Venda` nem
`Situação NBS`**, e a coluna de FIPE se chama `FIPE` em vez de `Valor Fipe`.

`load_vendas(path, sheet=...)` já trata isso: renomeia `FIPE` e cria `Loja Venda` / `Situação NBS`
vazias. Consequência prática: **para meses vindos desse arquivo, o corte "Varejo por Loja Venda"
e a flag de blindado não existem.** Reportar esses cortes só para os meses que têm o extrato
completo, e dizer explicitamente que o mês antigo ficou de fora — não inventar substituto
usando `Filial`.

---

# Estoque RAW do ERP — regras de leitura

De vez em quando o Henri manda a foto do estoque **sem mastigar**, direto do ERP, com nome tipo
`Relatório_-_2026-10-06T145918.146.xls`. Nesse caso:

**O arquivo não é .xls.** É um HTML com uma tabela única. Ler com
`pd.read_html(io.StringIO(html))[0]` — tentar decodificar em `utf-8` e cair para `latin1`.

**Pré-tratamento obrigatório, nesta ordem:**

1. Descartar a linha de rodapé onde `FILIAL == 'Total'`.
2. **Descartar linhas sem `PLACA`.** São erro de cadastro em correção, normalmente resolvido no
   mesmo dia. Acontece de vez em quando. Reportar quantas saíram e quais eram, sem perguntar.
3. Converter os números: vêm em formato brasileiro (`1.234,56`) **como texto**. Tirar o ponto de
   milhar, trocar vírgula por ponto. Afeta `VL VENDA`, `VL CUSTO`, `CUSTO AJUSTADO`, `VALOR FIPE`,
   `DESPESA OPERACIONAL`, `VL BÔNUS`, `RESULTADO VENDA`, `% RV`. Sem isso **tudo vira NaN em
   silêncio** e as somas dão zero.
4. `% RV` vem como inteiro sem separador: `795` = 7,95%. Dividir por 10.000.

**Colunas que não existem no arquivo mastigado:**

| Coluna | O que é |
|---|---|
| `MARGEM` | **não é número** — é classificação do ERP: `Ideal` / `Baixa` / `Mínima`. As faixas de `% RV` se sobrepõem, então a regra não é só o `% RV`. Manter na base, não usar em cálculo até o Henri explicar a regra. |
| `SIT` | `ESTOQUE` / `DEMOSTRAÇÃO` / `TRÂNSITO`. **Desconsiderar.** `DEMOSTRAÇÃO` significa apenas que o carro está num pátio diferente do que entrou — não que esteja fora de venda. Para localização física usar `LOCALIZAÇÃO`. |
| `FT` | vem 100% vazia |
| `RENAVAM`, `CÓDIGO FIPE` | identificadores, sem uso analítico |

## A coluna ST do RAW

Vem em duas formas. Ou é texto curto (`Disponível`, `TRÂNSITO`), ou é um **blob concatenado sem
separador** com os campos da proposta/reserva:

```
Proposta: 320163161Reserva: Bloqueio: Data Abertura: 2026-09-25Data Validade: Dias Em Aberto: 11Cliente: nome do clienteVendedor: nome do vendedor
```

Parsear com um regex único e nomeado:

```python
BLOB = re.compile(
    r"Proposta:\s*(?P<proposta>\d*)\s*"
    r"Reserva:\s*(?P<reserva>\d*)\s*"
    r"Bloqueio:\s*(?P<bloqueio>.*?)\s*"
    r"Data Abertura:\s*(?P<dt_abertura>[\d\-/]*)\s*"
    r"Data Validade:\s*(?P<dt_validade>[\d\-/]*)\s*"
    r"Dias Em Aberto:\s*(?P<dias_aberto>\d*)\s*"
    r"Cliente:\s*(?P<cliente>.*?)\s*"
    r"Vendedor:\s*(?P<vendedor>.*)$", re.S)
```

O campo `Bloqueio:` costuma vir vazio. Se algum dia vier preenchido, **parar e perguntar** o que
significa.

## Ordem de precedência da classificação — não reordenar

Regras confirmadas pelo Henri em 06/10/2026. **Não reabrir.**

1. **`SITUAÇÃO NBS == 'Indisponível'` resulta em `Indisponível`.** Manda sobre tudo: proposta
   aberta, reserva de revenda, `ST = Disponível`. (Caso que definiu: Fox `FRD-5234`, NBS
   Indisponível com reserva escrita `REVENDA`, classificado como Indisponível.)
2. `ST == 'Disponível'` resulta em **`Disponível`**.
3. `ST == 'TRÂNSITO'` resulta em **`Indisponível`** (ainda não chegou).
4. Blob **com** número em `Proposta:` é carro **vendido com proposta**:
   - `Vendedor` = `JULIO CESAR SILVEIRA` resulta em **`Revenda`**
   - qualquer outro vendedor resulta em **`Vendido`** (loja)
5. Blob **sem** número de proposta é **reserva**; classificar pelo motivo escrito em `Cliente`.

### Classificação da reserva pelo campo `Cliente`

Comparar sempre em maiúsculas e sem acento.

| Motivo contém | Classe | Rótulo |
|---|---|---|
| `REVENDA` ou `REPASSE` | `Revenda` | Reserva para revenda/repasse |
| começa com `VENDIDO` **e** quem reservou é o Julio Cesar | `Revenda` | Repasse vendido sem proposta lançada |
| começa com `VENDIDO`, outro vendedor | `Vendido` | Vendido sem proposta lançada |
| `REPROVAD` | `Indisponível` | Reprovado |
| `PROCESSO`, `JURIDIC` | `Indisponível` | Processo / jurídico |
| `AVARIA`, `FURTAD`, `SINISTR`, `MOTOR`, `OXIDAD`, `GARANTIA`, `MANUTENC`, `OFICINA`, `FUNILARIA`, `LAUDO`, `RETRABALHO` | `Indisponível` | Avaria / manutenção / garantia |
| `TESTE DRIVE`, `DEMONSTRA`, `FROTA` | `Indisponível` | Uso interno |
| `CONSULTAR` seguido de nome, `HARA`, `DIRETORIA` | `Indisponível` | Bloqueio administrativo |
| vazio | `Indisponível` | Reserva sem motivo informado |
| nada acima | `Indisponível` | `Outro:` mais o texto original — **listar para o Henri confirmar** |

(Caso que definiu a regra do Julio: Taos `FCZ6H35`, `VENDIDO PAGA SEGUNDA`, reservado pelo Julio
Cesar, classificado como `Revenda`.)

A classe resultante é equivalente ao `ST` do arquivo mastigado: `Disponível` · `Revenda` ·
`Vendido` · `Indisponível`. Daí para frente a análise é idêntica.

## Conferência obrigatória do RAW

Quando existir um arquivo mastigado de data próxima, **cruzar por `CHASSI`** e checar que a
diferença de `D.E` entre os dois é igual ao número de dias entre as datas, para todos os carros em
comum. Se não fechar, há deslocamento de linha ou erro de leitura — parar.

Reportar sempre: linhas lidas, linhas descartadas por falta de placa, e a contagem por classe.

### Capital travado em `Indisponível`

Esses carros têm custo lançado normalmente. Os `D.E` absurdos (3.000+ dias) **não são erro de
cadastro** — são processos jurídicos e casos de avaria/garantia parados há anos. Reportar
separadamente e **nunca** incluir no DME ponderado da base operacional.

---

## Colunas — Vendas

| Coluna | Uso |
|---|---|
| `Família` | marca (tirar prefixo `VU-`) |
| `Modelo` | normalizar via shortname |
| `KM`, `Ano Modelo` | faixas de KM e ano (ano = parte depois da `/`) |
| `Vl Venda` | **valor real de venda** |
| `Vl Impostos` | entra na margem |
| `Custo Ajustado` | **custo real do carro** (já líquido de bônus) |
| `Situação` | `Loja` = varejo/showroom · `Revenda` = repasse |
| `Filial` | loja que **comprou** o carro |
| `Loja Venda` | loja física que **vendeu** o carro |
| `Situação NBS` | `BLINDADO` sinaliza blindado |
| `Valor Fipe` | FIPE na data da venda |
| `D.E` | dias em estoque na venda (DME realizado) |
| `Vendedor` | vendedor da venda — base de qualquer análise de comissionamento |
| `Era Showroom` / `Era Showroom.1` | quando existir: separa as três carteiras (showroom, repasse corrente, repasse saneamento) |

`Marg. Ini.` é **igual** a `Vl Venda` menos `Vl Impostos` menos `Custo Ajustado` — confirmado linha
a linha. É o "lucro" que o Henri usa como base de comissão de vendedor. `Margem Final` é depois de
O. Custo e roda ~33% abaixo da inicial; usar só quando a pergunta for sobre o que sobra de fato.

**Ignorar:** `Custo`, `Despesa Operacional`, `% DV`, `Vl Bônus`, `% MI`, `O. Custo`, `% MF`,
`Diferença Fipe`.

### Quirks por arquivo já encontrados

| Arquivo | Aba | Header | Detalhe |
|---|---|---|---|
| `Vendas_Maio_26.xlsx` | `Vendas Maio` | 3 | usa `Loja venda` (v minúsculo) |
| `Atualização_vendas_geral_-_005_26.xlsx` | `Vendas junho` | 1 | sem `Loja Venda` nem `Situação NBS`; FIPE = `FIPE` |
| `Vendas_Julho_2026.xlsx` | 0 | 1 | — |
| `Vendas_Agosto_2026.xlsx` | `Relatório` | 3 | `Era showroom` + `Era showroom.1` |
| `Vendas_Setembro.xlsx` | `Relatório` | 1 | `Era Showroom` (S maiúsculo); `Situação` em **minúsculas** (`loja`/`revenda`) |

Detectar o header procurando as colunas-chave nas primeiras 8 linhas, nunca fixar o número.
Normalizar `Situação` com `.str.capitalize()`.

## Colunas — Estoque

| Coluna | Uso |
|---|---|
| `ST` | `Disponível` · `Revenda` · `Vendido` · `Indisponível` (no RAW, ver seção própria) |
| `MARCA`, `MODELO` | marca e shortname |
| `A/M`, `KM` | ano (parte depois da `/`) e quilometragem |
| `FILIAL` | loja que comprou |
| `LOCALIZAÇÃO` | onde o carro está fisicamente — diverge de `FILIAL` em ~20% dos carros |
| `CUSTO AJUSTADO` | **sempre a coluna de custo** |
| `VALOR FIPE` | FIPE do mês corrente |
| `D.E` | dias em estoque |
| `SITUAÇÃO NBS` | `Blindado` sinaliza blindado · `Indisponível` tem precedência |

**Ignorar:** `VL VENDA` e `RESULTADO VENDA` do estoque — não são valores confiáveis.

### Base de estoque a considerar

Padrão em toda análise de cobertura: **`ST` em {`Disponível`, `Revenda`}** — é o estoque que ainda
precisa ser vendido. `Vendido` já saiu; `Indisponível` está travado. Reportar os dois últimos
separadamente como nota de rodapé, nunca somados na base principal.

## Regras confirmadas pelo Henri — não reabrir

**03/08/2026**

- Margem = `Vl Venda` menos `Vl Impostos` menos `Custo Ajustado`. Não usar `Margem Final`.
- %FIPE ignora linhas com FIPE = 0.
- Base de estoque = `Disponível` + `Revenda`; `Vendido - A Faturar` fica fora.
- Denominador dos dias de estoque = custo vendido **total** (Loja + Revenda).
- `75 - HYU PATIO BARRA FUNDA` é a mesma loja que `71 - HYU BARRA FUNDA`.
- `YARIS CROSS` é família própria de shortname.

**06/10/2026 (leitura do RAW)**

- `SITUAÇÃO NBS = Indisponível` tem precedência sobre proposta, reserva e `ST`.
- Reserva `VENDIDO` feita pelo Julio Cesar = `Revenda`.
- Coluna `SIT` desconsiderada — `DEMOSTRAÇÃO` é só outro pátio.
- Linha sem `PLACA` sai da análise (erro de cadastro em correção).

## Fórmulas obrigatórias

```
Margem      = Vl Venda - Vl Impostos - Custo Ajustado
Margem %    = Margem / Vl Venda
Margem/carro= Margem / nº de carros
%FIPE       = SOMA(Vl Venda) / SOMA(Valor Fipe)      -- média ponderada, nunca média simples
CTM estoque = SOMA(Custo Ajustado) / SOMA(Valor FIPE)
DME pond.   = média de D.E ponderada por custo (estoque) ou por Vl Venda (vendas)
```

**%FIPE só considera linhas com `Valor Fipe > 0`.** Blindados e alguns importados vêm com FIPE
zerada; incluí-los no denominador distorce a média (ex.: Toyota passa a aparecer com 127% de FIPE).
Excluir essas linhas do numerador *e* do denominador, e informar quantas foram excluídas.

## Normalização

**Modelo para Shortname:** usar `scripts/tagger.py` (classe `Tagger`). Ordem: match exato na base,
depois família com trim (`CRETA`, `COROLLA`, `COROLLA CROSS`), depois maior prefixo de família
conhecida, depois heurística (tokens até a primeira especificação técnica). Acurácia ~95% contra
a base. **Ao final, sempre listar os modelos novos resolvidos por regra** para o Henri confirmar e
incorporar na base. Detalhes em `references/regras-shortname.md`.

**Marca:** `Família` sem `VU-`. Ajustes: `BMW AUTOS` para `BMW`, `KIAMOTORS` para `KIA`,
`MERCEDES-BENZ` para `MERCEDES`.

**Filial:** tirar prefixo de marca e o código numérico. `75 - HYU PATIO BARRA FUNDA` é a mesma loja
que `Hyundai Barra Funda`. `BYD Moema` é `BYD Ibirapuera`. `33 - BYD PATIO ALPHAVILLE` e
`34 - BYD PATIO TAMBORE` são `BYD Alphaville`.

**Localização:** `HYUNDAI GUARULHOSGSG` e `HYUNDAI SEMINOVOS GUARULHOS` são `Hyundai Guarulhos`;
`HYUNDAI BARRA FUNDAGSB` e `HYUNDAI PATIO BFSP` são `Hyundai Barra Funda`.

**Faixas fixas (não alterar — são a base de comparabilidade):**

- KM: `Até 20 mil` · `20-50 mil` · `50-100 mil` · `+100 mil`
- Ano modelo: `Até 2017` · `2018-2022` · `2023+`
- Buckets de dias em estoque: `0-30` · `31-60` · `61-90` · `91-120` · `+120`

---

# Relatório 1 — Vendas do mês

Sempre nesta ordem, com as mesmas 5 métricas em cada corte: **Volume · Faturamento · Margem R$ ·
Margem % · Margem/carro** (`%FIPE` como coluna extra sempre que houver FIPE válida).

1. **Cabeçalho** — Total do mês, e a quebra Loja vs Revenda lado a lado.
2. **Por marca** — total (Loja + Revenda), ordenado por volume.
3. **Só LOJA, por faixa de KM** — 4 faixas.
4. **Só LOJA, por faixa de ano** — 3 faixas.
5. **Só LOJA, KM por Ano** — matriz cruzada.
6. **Total (Loja + Revenda) por FILIAL** — quem comprou o carro.
7. **Varejo (só Loja) por LOJA VENDA** — quem vendeu o carro.
8. **Por modelo (shortname), separado em Loja e Revenda** — top 20 de cada, ordenado por volume.

**Comparativo vs mês anterior** (quando houver mais de um mês): repetir os cortes 1, 2, 6 e 7 com
colunas de delta de volume, faturamento, margem R$ e margem p.p. Não comparar cortes de modelo
(cauda longa demais, o ruído domina).

# Relatório 2 — Cobertura Estoque vs Vendas

**Meta: ~30 dias de estoque, medida a custo.**

```
Dias de estoque (custo)   = Custo do estoque / (Custo dos carros vendidos no mês / dias do mês)
Dias de estoque (unidade) = Nº em estoque    / (Nº vendido no mês / dias do mês)
```

Reportar **as duas**. A divergência entre elas é diagnóstico: se dias-a-custo é maior que
dias-a-unidade, o ticket médio do que está entrando é maior que o do que está saindo — a operação
está comprando carro mais caro do que consegue girar. Sempre calcular e comentar o ticket médio de
estoque vs ticket médio de venda quando o gap passar de ~15%.

Cortes obrigatórios:

1. **Global** — dias a custo e a unidade, capital imobilizado, CTM médio do estoque.
2. **Por filial** — dias a custo, dias a unidade, ticket estoque vs ticket venda, excesso/falta em R$
   contra a meta de 30 dias (`Custo estoque` menos `30 x custo vendido/dia`).
3. **Por localização** — mesma lógica. Filial e localização divergem bastante; reportar as duas.
4. **Por marca** — mesma lógica.
5. **Por modelo (shortname)** — top 25 por custo em estoque. Destacar modelos com dias acima de 90 e
   modelos com estoque positivo e vendas zero no mês (cobertura infinita).
6. **Buckets de envelhecimento** — nº e % do custo em cada faixa, global e por filial/localização.
   O KPI duro é **% do custo em 90+ no máximo 15%**.
7. **Perfil do estoque vs perfil das vendas** — distribuição por faixa de KM e de ano nos dois lados,
   para checar se o que está no pátio é o que o mercado está comprando.

Fechar com **3 a 5 leituras acionáveis** (onde sobra capital, onde falta carro, qual modelo travou),
não uma lista genérica.

---

## Entregáveis

1. **Resumo no chat** — tabelas em markdown, tom direto, sem explicar conceito básico.
   R$ com separador de milhar sem centavos; percentuais com 1 casa.
2. **Excel** com uma aba por corte, mais uma aba `Base Vendas` e `Base Estoque` com as colunas
   calculadas (Shortname, Marca, Filial_N, Local_N, Margem, Margem %, %FIPE, Faixa_KM, Faixa_Ano,
   Bucket). Quando a entrada for o RAW, incluir também `ST (interpretado)`, `Motivo`, `Nº proposta`,
   `Vendedor` e `Observação reserva`, mais uma aba documentando como o arquivo foi lido.

## Checagens antes de entregar

- Linhas com `Valor Fipe = 0` — contar e informar.
- Modelos novos resolvidos por regra — listar para confirmação.
- Filiais ou lojas que não estão no de-para — **parar e perguntar**, nunca inferir.
- Motivos de reserva que caíram no `Outro:` — listar para confirmação.
- Vendas com margem negativa relevante — listar as 5 piores; em revenda é esperado, em loja não.
- Se o total de linhas ou o faturamento fugir muito do mês anterior, sinalizar antes de seguir.
- No RAW: conferir que as somas de custo não deram zero (sintoma do número brasileiro não convertido).