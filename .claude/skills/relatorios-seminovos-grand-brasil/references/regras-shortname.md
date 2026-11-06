# Regras de normalização de Modelo → Shortname

O extrato do sistema traz o modelo com a especificação técnica completa
(`CRETA 1.0 TGDI FLEX LIMITED AUTOMÁTICO`). Para agregar por modelo é preciso reduzir isso ao nome
comercial (`CRETA LIMITED`). A base de referência é `assets/Tag_Modelos.xlsx` (~1.500 linhas,
~326 shortnames distintos).

## Princípio geral

**Shortname = nome da família comercial**, ou seja, os tokens antes da cilindrada / especificação.

```
SANDERO 1.6 16V SCE FLEX STEPWAY 4P MANUAL   → SANDERO
DISCOVERY SPORT 2.0 16V D180 TURBO DIESEL    → DISCOVERY SPORT
TIGGO 7 PRO 1.5 TCI FLEX HYBRID CVT          → TIGGO 7 PRO
SONG PLUS 1.5 16V AUT. (HIBRIDO)             → SONG PLUS
```

## Exceção: famílias em que o acabamento faz parte do shortname

Só três, e é uma decisão de negócio (volume alto e diferença real de preço entre versões):

- **CRETA** → `CRETA LIMITED`, `CRETA PLATINUM`, `CRETA ACTION`, `CRETA COMFORT`, `CRETA ULTIMATE`,
  `CRETA N LINE`, `CRETA PULSE`, `CRETA SMART`, `CRETA PRESTIGE`, `CRETA ATTITUDE`, `CRETA SPORT`,
  variantes `... PLUS` / `... SAFETY` / `N LINE NIGHT EDITION`
- **COROLLA** → `COROLLA XEI`, `COROLLA ALTIS`, `COROLLA ALTIS HIBRIDO`, ou `COROLLA` puro
- **COROLLA CROSS** → `COROLLA CROSS XR`, `XRE`, `XRX`, `XRV`, `GR-S`, `GRS`

Qualquer outra família ignora o acabamento (`COMPASS LIMITED` e `COMPASS SPORT` viram `COMPASS`).

## Casos especiais

- **Mercedes / BMW série M / Lexus:** letra(s) + número formam a família — `A 250`, `C 180`,
  `GLA 200`, `GLC 43 AMG`, `M 340`, `ES 300H`, `NX 300H`. Nunca reduzir a `A`, `C`, `M`.
- **Prefixo de marca** no nome: remover — `JEEP COMPASS LONGITUD` → `COMPASS`,
  `TOYOTA RAV4H SX` → `RAV4`, `I/SUBARU XV` → `SUBARU XV`.
- **`NEW` / `ALL NEW`**: remover — `NEW HB20 1.0 COMFORT PLUS` → `HB20`.
- **Sufixos de carroceria que são modelo próprio**: manter — `HB20S`, `HB20X`, `ONIX SEDAN`,
  `HILUX SW4`, `DOLPHIN MINI`, `YUAN PLUS` / `YUAN PRO`, `SONG PLUS` / `SONG PRO`.

## Algoritmo implementado (`scripts/tagger.py`)

1. Match exato contra `Tag_Modelos.xlsx` (após normalizar caixa/espaços e remover `I/`).
2. Se a string começa com `CRETA` / `COROLLA` / `COROLLA CROSS`, procurar no resto um acabamento
   conhecido dessa família (maior número de tokens primeiro) e concatenar.
3. Maior prefixo de tokens que bata com uma família conhecida da base (ordenado do mais longo
   para o mais curto, para `TIGGO 5X PRO` ganhar de `TIGGO 5X`).
4. Heurística: tokens até o primeiro que pareça especificação técnica (`1.0`, `16V`, `TURBO`,
   `FLEX`, `TSI`, `4X4`, `KW`, ...), com o tratamento de letra+número para as premium.

Acurácia medida ignorando o passo 1: **95,0%** contra a base de 1.488 linhas. A maior parte das
divergências restantes é inconsistência da própria base (`GOLF`→`GOL`, `328I`→`320I`,
`EVOQUE` vs `RANGE ROVER EVOQUE`).

## Processo mensal

Todo mês, listar os modelos que caíram nos passos 2–4 (não estavam na base) com o shortname
atribuído, para o Henri validar. Os confirmados entram na próxima versão de `Tag_Modelos.xlsx`,
que passa a ser o `assets/` da skill.

### Confirmado pelo Henri (03/08/2026)

- **`YARIS CROSS` é família própria**, não `YARIS`. Já está em `EXTRA_FAMILIES` no `tagger.py`.
  Sempre que o Henri confirmar um modelo novo que não está na base, adicionar ali (ou na próxima
  versão de `Tag_Modelos.xlsx`), nunca deixar só na heurística.

### Pendências ainda abertas

- `CRETA ... COMFORT SAFETY` resolve para `CRETA COMFORT` (a base tem `LIMITED SAFETY` mas não
  `COMFORT SAFETY`).
- `RANGE ROVER VELAR` vs `VELAR`, `RANGE ROVER EVOQUE` vs `EVOQUE`: a base usa os dois. Padronizar.
