#!/usr/bin/env python3
"""
Reposição de estoque 0 km Hyundai — Grand Brasil
Gera uma planilha (com fórmulas vivas) de sugestão de compra para atingir N dias de
estoque por Versão x Cor Externa, com rateio por Cor Interna.

Uso:
  python reposicao.py --estoque Estoque_Hyundai_22_09.xlsx \
                      --vendas Vendas_Jun-ago.xlsx Vendas_set_ate_22.xlsx \
                      --out Reposicao_Hyundai_22_09.xlsx
Opções:
  --dias-meta 30            meta de dias de estoque
  --meses 3                 meses cheios de histórico
  --transito SIM|NAO        conta carros em trânsito como estoque
  --lancamento "HYUNDAI I20=2026-07-01" (pode repetir) 1º mês cheio a considerar p/ família
  --data-base 2026-09-21    força a data base (padrão: última venda da base)
"""
import argparse
import datetime as dt
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter as L
from openpyxl.comments import Comment

FONT = "Arial"
F_BASE = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=14, bold=True)
F_INPUT = Font(name=FONT, size=10, color="0000FF", bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="555555")
FILL_HEAD = PatternFill("solid", fgColor="002C5F")      # azul Hyundai
FILL_CALC = PatternFill("solid", fgColor="EAF1FB")
FILL_INPUT = PatternFill("solid", fgColor="FFFF00")
FILL_KEY = PatternFill("solid", fgColor="D9EAD3")
FILL_TOT = PatternFill("solid", fgColor="D9D9D9")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(bottom=THIN)

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# --------------------------------------------------------------------------- leitura
def _read_any(path, header=None):
    """Aceita .xlsx e o .xls do ERP (que na verdade é HTML com números em formato BR)."""
    with open(path, "rb") as fh:
        head = fh.read(200).lower()
    if b"<html" in head:
        import io
        df = pd.read_html(io.StringIO(open(path, encoding="utf-8").read()), decimal=",", thousands=".")[0]
        if header is None:
            return pd.concat([pd.DataFrame([df.columns.tolist()], columns=df.columns), df], ignore_index=True).set_axis(range(df.shape[1]), axis=1)
        return df
    return pd.read_excel(path, header=header)


def read_report(path, key_col):
    raw = _read_any(path, header=None)
    hdr = None
    for i in range(min(10, len(raw))):
        vals = [str(x).strip() for x in raw.iloc[i].tolist()]
        if key_col in vals:
            hdr = i
            break
    if hdr is None:
        raise ValueError(f"Cabeçalho com '{key_col}' não encontrado em {path}")
    with open(path, "rb") as fh:
        is_html = b"<html" in fh.read(200).lower()
    df = _read_any(path, header=0) if is_html else pd.read_excel(path, header=hdr)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def up(s):
    return s.astype(str).str.strip().str.upper().replace({"NAN": ""})


def load_estoque(path):
    e = read_report(path, "ST")
    e = e[e["MARCA"].notna()].copy()           # tira linha de Total
    for c in ["ST", "SIT", "FAMÍLIA", "MODELO", "COR", "COR INTERNA", "FILIAL", "LOCALIZAÇÃO"]:
        e[c] = e[c].astype(str).str.strip().replace({"nan": ""})
    for c in ["FAMÍLIA", "MODELO", "COR", "COR INTERNA"]:
        e[c] = up(e[c])
    e["D.E"] = pd.to_numeric(e["D.E"], errors="coerce").fillna(0)
    return e


def load_vendas(paths):
    frames = []
    for p in paths:
        v = read_report(p, "Família")
        v = v[v["Família"].notna() & v["Modelo"].notna()].copy()
        frames.append(v)
    v = pd.concat(frames, ignore_index=True)
    v["Dt Venda"] = pd.to_datetime(v["Dt Venda"], errors="coerce", dayfirst=True)
    v = v[v["Dt Venda"].notna()]
    v = v.drop_duplicates(subset=["Chassi"], keep="last")
    for c in ["Família", "Modelo", "Cor", "Cor Interna"]:
        v[c] = up(v[c])
    for c in ["D.E", "Marg. Ini.", "% MI", "Vl Bônus", "% MF", "Vl Venda"]:
        v[c] = pd.to_numeric(v[c], errors="coerce").fillna(0)
    return v.sort_values("Dt Venda").reset_index(drop=True)


# --------------------------------------------------------------------------- helpers
def style_header(ws, row, ncols, height=42):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = F_HEAD
        cell.fill = FILL_HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[row].height = height


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[L(i)].width = w


def base_font(ws):
    for row in ws.iter_rows():
        for cell in row:
            if cell.font is None or cell.font.name != FONT:
                f = cell.font
                cell.font = Font(name=FONT, size=f.size or 10, bold=f.bold, italic=f.italic, color=f.color)


def mes_label(d):
    return f"{MESES_PT[d.month - 1]}/{str(d.year)[2:]}"


# --------------------------------------------------------------------------- build
def build(estoque_path, vendas_paths, out, dias_meta=30, meses=3, transito="SIM",
          lancamentos=None, data_base=None):
    e = load_estoque(estoque_path)
    v = load_vendas(vendas_paths)
    lancamentos = lancamentos or {"HYUNDAI I20": dt.datetime(2026, 7, 1)}

    db = pd.Timestamp(data_base) if data_base else v["Dt Venda"].max()
    mes_corr = pd.Timestamp(db.year, db.month, 1)
    meses_hist = [mes_corr - pd.DateOffset(months=k) for k in range(meses, 0, -1)]

    wb = Workbook()
    wb.remove(wb.active)
    ws_res = wb.create_sheet("Resumo")
    ws_cor = wb.create_sheet("Compra_Cor")
    ws_int = wb.create_sheet("Compra_Interna")
    ws_ver = wb.create_sheet("Por_Versao")
    ws_env = wb.create_sheet("Envelhecidos")
    ws_p = wb.create_sheet("Premissas")
    ws_v = wb.create_sheet("Vendas")
    ws_e = wb.create_sheet("Estoque")

    # ------------------------------------------------------------ Vendas (base)
    nv = len(v)
    lv = nv + 1
    vh = ["Família", "Versão", "Cor Ext", "Cor Int", "Dt Venda", "D.E venda", "Marg. Ini. R$",
          "% MI", "Vl Bônus", "% MF", "Filial", "Vl Venda", "Chassi",
          "Mês Ref", "Dia", "Chave Versão|Cor", "Chave SKU", "Início contagem família",
          "Considera (1/0)", "%MI médio versão", "Margem fora padrão", "D.E alto na venda",
          "Peso da venda", "Mês corrente"]
    ws_v.append(vh)
    for i, r in v.iterrows():
        x = i + 2
        ws_v.append([r["Família"], r["Modelo"], r["Cor"], r["Cor Interna"], r["Dt Venda"].to_pydatetime(),
                     r["D.E"], r["Marg. Ini."], r["% MI"], r["Vl Bônus"], r["% MF"], r.get("Filial", ""),
                     r["Vl Venda"], r["Chassi"],
                     f"=DATE(YEAR(E{x}),MONTH(E{x}),1)",
                     f"=DAY(E{x})",
                     f'=B{x}&" | "&C{x}',
                     f'=B{x}&" | "&C{x}&" | "&D{x}',
                     f"=MAX(Premissas!$B$10,IFERROR(INDEX(Premissas!$E$5:$E$14,MATCH(A{x},Premissas!$D$5:$D$14,0)),0))",
                     f"=IF(AND(N{x}>=R{x},N{x}<=Premissas!$B$8),1,0)",
                     f"=IFERROR(AVERAGEIFS($H$2:$H${lv},$B$2:$B${lv},B{x},$S$2:$S${lv},1),H{x})",
                     f"=IF(S{x}=0,0,IF(OR(H{x}<T{x}-Premissas!$B$15,H{x}<Premissas!$B$16),1,0))",
                     f"=IF(S{x}=0,0,IF(F{x}>Premissas!$B$18,1,0))",
                     f"=S{x}*IF(U{x}=1,Premissas!$B$17,1)*IF(V{x}=1,Premissas!$B$19,1)",
                     f"=IF(N{x}=Premissas!$B$8,1,0)"])
    style_header(ws_v, 1, len(vh))
    for x in range(2, lv + 1):
        ws_v[f"E{x}"].number_format = "dd/mm/yyyy"
        ws_v[f"N{x}"].number_format = "mmm/yy"
        ws_v[f"R{x}"].number_format = "mmm/yy"
        for c in "GIL":
            ws_v[f"{c}{x}"].number_format = "#,##0"
        for c in "HJT":
            ws_v[f"{c}{x}"].number_format = "0.00"
        for c in "NOPQRSTUVWX":
            ws_v[f"{c}{x}"].fill = FILL_CALC
    ws_v.freeze_panes = "A2"
    ws_v.auto_filter.ref = f"A1:{L(len(vh))}{lv}"
    set_widths(ws_v, [15, 40, 17, 12, 11, 8, 11, 7, 10, 7, 20, 11, 20, 9, 5, 50, 60, 11, 9, 9, 9, 9, 8, 8])

    # ------------------------------------------------------------ Estoque (base)
    ne = len(e)
    le = ne + 1
    eh = ["ST", "SIT", "Família", "Versão", "Cor Ext", "Cor Int", "D.E", "Filial", "Localização",
          "A/M", "Chassi", "Vl Venda", "Custo Ajustado", "% RV", "Pago",
          "Categoria", "Chave Versão|Cor", "Chave SKU"]
    ws_e.append(eh)
    for i, r in e.reset_index(drop=True).iterrows():
        x = i + 2
        ws_e.append([r["ST"], r["SIT"], r["FAMÍLIA"], r["MODELO"], r["COR"], r["COR INTERNA"], r["D.E"],
                     r["FILIAL"], r["LOCALIZAÇÃO"], r.get("A/M", ""), r["CHASSI"], r["VL VENDA"],
                     r["CUSTO AJUSTADO"], r["% RV"], r.get("PAGO", ""),
                     f'=IF(AND(A{x}="Disponível",B{x}="ESTOQUE"),"Disponível",IF(A{x}="TRÂNSITO","Trânsito",'
                     f'IF(B{x}="DEMOSTRAÇÃO","Demonstração",IF(LEFT(A{x},9)="Proposta:",'
                     f'IF(ISNUMBER(SEARCH("Reserva: 0",A{x})),IF(ISNUMBER(SEARCH("ACESS",A{x})),"Disponível","Bloqueio interno"),"Reserva cliente"),"Outro"))))',
                     f'=D{x}&" | "&E{x}',
                     f'=D{x}&" | "&E{x}&" | "&F{x}'])
    style_header(ws_e, 1, len(eh))
    for x in range(2, le + 1):
        ws_e[f"L{x}"].number_format = "#,##0"
        ws_e[f"M{x}"].number_format = "#,##0"
        ws_e[f"N{x}"].number_format = "0.00"
        for c in "PQR":
            ws_e[f"{c}{x}"].fill = FILL_CALC
        ws_e[f"A{x}"].alignment = Alignment(wrap_text=False)
    ws_e.freeze_panes = "A2"
    ws_e.auto_filter.ref = f"A1:{L(len(eh))}{le}"
    set_widths(ws_e, [22, 12, 16, 42, 17, 12, 6, 30, 24, 10, 20, 11, 12, 7, 6, 16, 50, 60])

    # ------------------------------------------------------------ Premissas
    p = ws_p
    p["A1"] = "Premissas do modelo de reposição"
    p["A1"].font = F_TITLE
    p["A2"] = "Células em azul/amarelo são editáveis; todo o resto do arquivo recalcula a partir delas."
    p["A2"].font = F_NOTE
    for c, t in zip("ABC", ["Parâmetro", "Valor", "Observação"]):
        p[f"{c}3"] = t
    rows = [
        (4, "Dias de estoque meta", dias_meta, True, "Meta por Versão x Cor (definida pelo Henri)"),
        (5, "Incluir carros em trânsito no estoque", transito, True, "SIM = carro já comprado conta como estoque"),
        (6, "Nº de meses cheios de histórico", meses, True, "Meses fechados antes do mês corrente"),
        (7, "Data base (última venda na base)", (db.to_pydatetime() if data_base else f"=MAX(Vendas!$E$2:$E${lv})"),
         True, "Pode sobrescrever com a data de corte desejada"),
        (8, "Mês corrente", "=DATE(YEAR(B7),MONTH(B7),1)", False, ""),
        (9, "Dia de corte", "=DAY(B7)", False, "Vendas do mês corrente consideradas até este dia"),
        (10, "Início da janela de histórico", "=EDATE(B8,-B6)", False, ""),
        (11, "% das vendas do mês feitas até o dia de corte (curva histórica)",
         f"=SUMPRODUCT((Vendas!$N$2:$N${lv}>=B10)*(Vendas!$N$2:$N${lv}<B8)*(Vendas!$O$2:$O${lv}<=B9))"
         f"/SUMPRODUCT((Vendas!$N$2:$N${lv}>=B10)*(Vendas!$N$2:$N${lv}<B8))", False,
         "Vendas não são lineares: final do mês concentra o faturamento"),
        (12, "% do mês ainda por vender", "=1-B11", False, ""),
        (13, "Vendas do mês corrente até o corte", f"=SUM(Vendas!$X$2:$X${lv})", False, ""),
        (14, "Projeção de vendas do mês corrente (total)", "=B13/B11", False, "Vendas até o corte ÷ curva"),
        (15, "Margem fora do padrão: pp abaixo da média da versão", 3, True, "% MI da venda < média da versão − X pp"),
        (16, "Margem fora do padrão: piso absoluto de % MI", 2, True, "ou % MI abaixo deste piso"),
        (17, "Peso de uma venda com margem fora do padrão", 0.5, True, "Venda 'comprada' com desconto conta menos na demanda"),
        (18, "D.E na venda acima de (dias) = venda de carro parado", 90, True, ""),
        (19, "Peso de uma venda com D.E alto", 0.5, True, "Pesos multiplicam: margem baixa + D.E alto = 0,25"),
        (20, "Envelhecimento — limite 1 (dias em estoque)", 60, True, ""),
        (21, "Fator de compra se a cor tiver carro acima do limite 1", 0.5, True, "Corta a compra pela metade"),
        (22, "Envelhecimento — limite 2 (dias em estoque)", 90, True, ""),
        (23, "Fator de compra se a cor tiver carro acima do limite 2", 0, True, "0 = não comprar até girar o antigo"),
        (24, "Arredondamento: fração mínima para comprar +1 un.", 0.5, True, "0,5 = arredondamento normal"),
    ]
    for r_, name, val, is_input, note in rows:
        p[f"A{r_}"] = name
        p[f"B{r_}"] = val
        p[f"C{r_}"] = note
        p[f"C{r_}"].font = F_NOTE
        if is_input:
            p[f"B{r_}"].font = F_INPUT
            p[f"B{r_}"].fill = FILL_INPUT
    p["B7"].number_format = "dd/mm/yyyy"
    p["B8"].number_format = "mmm/yy"
    p["B10"].number_format = "mmm/yy"
    p["B11"].number_format = "0.0%"
    p["B12"].number_format = "0.0%"
    p["B14"].number_format = "0"
    for c in ["B17", "B19", "B21", "B23"]:
        p[c].number_format = "0.00"

    p["D3"] = "Família"
    p["E3"] = "1º mês cheio a considerar (lançamento)"
    for k, (fam, d0) in enumerate(lancamentos.items()):
        p[f"D{5 + k}"] = fam
        p[f"E{5 + k}"] = pd.Timestamp(d0).to_pydatetime()
        p[f"D{5 + k}"].font = F_INPUT
        p[f"E{5 + k}"].font = F_INPUT
        p[f"D{5 + k}"].fill = FILL_INPUT
        p[f"E{5 + k}"].fill = FILL_INPUT
    for r_ in range(5, 15):
        p[f"E{r_}"].number_format = "mmm/yy"
    p["D4"] = "(linhas 5–14; ex.: I20 lançado fim de junho → conta a partir de jul)"
    p["D4"].font = F_NOTE

    p["G3"] = "Curva — mês"
    p["H3"] = "Vendas até o dia de corte"
    p["I3"] = "Total do mês"
    p["J3"] = "% até o corte"
    for k in range(meses):
        r_ = 4 + k
        p[f"G{r_}"] = f"=EDATE($B$8,{k - meses})"
        p[f"G{r_}"].number_format = "mmm/yy"
        p[f"H{r_}"] = f'=COUNTIFS(Vendas!$N$2:$N${lv},G{r_},Vendas!$O$2:$O${lv},"<="&$B$9)'
        p[f"I{r_}"] = f"=COUNTIFS(Vendas!$N$2:$N${lv},G{r_})"
        p[f"J{r_}"] = f"=IFERROR(H{r_}/I{r_},0)"
        p[f"J{r_}"].number_format = "0.0%"
    style_header(p, 3, 10, 32)
    set_widths(p, [58, 14, 52, 22, 22, 3, 12, 14, 11, 11])

    # ------------------------------------------------------------ chaves (Versão x Cor)
    kv = v[["Família", "Modelo", "Cor"]].rename(columns={"Modelo": "Versão", "Cor": "CorExt"})
    ke = e[["FAMÍLIA", "MODELO", "COR"]].rename(columns={"FAMÍLIA": "Família", "MODELO": "Versão", "COR": "CorExt"})
    keys = pd.concat([kv, ke]).drop_duplicates(["Versão", "CorExt"])
    vol = v.groupby(["Modelo", "Cor"]).size()
    keys["vol"] = [vol.get((a, b), 0) for a, b in zip(keys["Versão"], keys["CorExt"])]
    vver = v.groupby("Modelo").size()
    keys["vver"] = keys["Versão"].map(vver).fillna(0)
    keys = keys.sort_values(["Família", "vver", "Versão", "vol"], ascending=[True, False, True, False]).reset_index(drop=True)

    # ------------------------------------------------------------ Compra_Cor
    c = ws_cor
    c["A1"] = "Sugestão de compra Hyundai — Versão x Cor Externa"
    c["A1"].font = F_TITLE
    c["A2"] = ("Demanda = vendas ponderadas (margem fora do padrão e D.E alto pesam menos) ÷ meses equivalentes "
               "(meses cheios + fração do mês corrente pela curva). Compra = meta − estoque projetado no fim do mês, "
               "ajustada pela trava de envelhecimento.")
    c["A2"].font = F_NOTE
    hdr = ["Família", "Versão", "Cor Externa", "Chave",
           *[f"Vendas {mes_label(m)}" for m in meses_hist], f"Vendas {mes_label(mes_corr)} (até corte)",
           "Vendas ponderadas consideradas", "Meses equivalentes", "Demanda mensal (un/mês)",
           "Disponível", "Trânsito", "Reservado cliente", "Bloqueio interno / Demo",
           "Estoque considerado", "Dias de estoque hoje",
           "D.E médio disponível", "D.E máx disponível", f"Qtd > limite 1", f"Qtd > limite 2",
           "Vendas restantes projetadas no mês", "Estoque projetado fim do mês",
           "Meta (un)", "Necessidade bruta", "Fator envelhecimento",
           "COMPRA SUGERIDA", "Excesso (un)", "Dias de estoque pós-compra",
           "% vendas margem fora padrão", "% MI médio vendas", "D.E médio na venda", "Status", "Soma internas (check)"]
    HR = 4
    for j, t in enumerate(hdr, start=1):
        c.cell(row=HR, column=j, value=t)
    style_header(c, HR, len(hdr), 58)
    first = HR + 1
    nk = len(keys)
    last = first + nk - 1
    nm = meses
    # column letters
    col = {name: L(i) for i, name in enumerate(hdr, start=1)}
    cV = f"Vendas!$P$2:$P${lv}"
    cVN = f"Vendas!$N$2:$N${lv}"
    cVW = f"Vendas!$W$2:$W${lv}"
    cVS = f"Vendas!$S$2:$S${lv}"
    cE = f"Estoque!$Q$2:$Q${le}"
    cEC = f"Estoque!$P$2:$P${le}"
    cED = f"Estoque!$G$2:$G${le}"
    for k, kr in keys.iterrows():
        x = first + k
        c[f"A{x}"] = kr["Família"]
        c[f"B{x}"] = kr["Versão"]
        c[f"C{x}"] = kr["CorExt"]
        c[f"D{x}"] = f'=B{x}&" | "&C{x}'
        mcols = [L(5 + j) for j in range(nm + 1)]
        for j in range(nm):
            c[f"{mcols[j]}{x}"] = f"=COUNTIFS({cV},$D{x},{cVN},EDATE(Premissas!$B$8,{j - nm}))"
        c[f"{mcols[nm]}{x}"] = f"=COUNTIFS({cV},$D{x},{cVN},Premissas!$B$8)"
        g = {n: col[n] for n in hdr}
        c[f"{g['Vendas ponderadas consideradas']}{x}"] = f"=SUMIFS({cVW},{cV},$D{x})"
        st = f"MAX(Premissas!$B$10,IFERROR(INDEX(Premissas!$E$5:$E$14,MATCH($A{x},Premissas!$D$5:$D$14,0)),0))"
        c[f"{g['Meses equivalentes']}{x}"] = (f"=MAX(0,(YEAR(Premissas!$B$8)*12+MONTH(Premissas!$B$8))-(YEAR({st})*12+MONTH({st})))"
                                              f"+Premissas!$B$11")
        W_, ME, DM = g['Vendas ponderadas consideradas'], g['Meses equivalentes'], g['Demanda mensal (un/mês)']
        c[f"{DM}{x}"] = f"=IFERROR({W_}{x}/{ME}{x},0)"
        DI, TR, RC, BL = g['Disponível'], g['Trânsito'], g['Reservado cliente'], g['Bloqueio interno / Demo']
        c[f"{DI}{x}"] = f'=COUNTIFS({cE},$D{x},{cEC},"Disponível")'
        c[f"{TR}{x}"] = f'=COUNTIFS({cE},$D{x},{cEC},"Trânsito")'
        c[f"{RC}{x}"] = f'=COUNTIFS({cE},$D{x},{cEC},"Reserva cliente")'
        c[f"{BL}{x}"] = (f'=COUNTIFS({cE},$D{x},{cEC},"Bloqueio interno")+COUNTIFS({cE},$D{x},{cEC},"Demonstração")'
                         f'+COUNTIFS({cE},$D{x},{cEC},"Outro")')
        EC = g['Estoque considerado']
        c[f"{EC}{x}"] = f'={DI}{x}+IF(UPPER(Premissas!$B$5)="SIM",{TR}{x},0)'
        c[f"{g['Dias de estoque hoje']}{x}"] = f'=IF({DM}{x}>0,{EC}{x}/{DM}{x}*30,"")'
        c[f"{g['D.E médio disponível']}{x}"] = f'=IFERROR(AVERAGEIFS({cED},{cE},$D{x},{cEC},"Disponível"),"")'
        c[f"{g['D.E máx disponível']}{x}"] = f'=IF({DI}{x}=0,"",_xlfn.MAXIFS({cED},{cE},$D{x},{cEC},"Disponível"))'
        Q1, Q2 = g['Qtd > limite 1'], g['Qtd > limite 2']
        c[f"{Q1}{x}"] = f'=COUNTIFS({cE},$D{x},{cEC},"Disponível",{cED},">"&Premissas!$B$20)'
        c[f"{Q2}{x}"] = f'=COUNTIFS({cE},$D{x},{cEC},"Disponível",{cED},">"&Premissas!$B$22)'
        VR, PF = g['Vendas restantes projetadas no mês'], g['Estoque projetado fim do mês']
        c[f"{VR}{x}"] = f"={DM}{x}*Premissas!$B$12"
        c[f"{PF}{x}"] = f"=MAX(0,{EC}{x}-MAX(0,{VR}{x}-{RC}{x}))"
        MT, NB, FE, CS = g['Meta (un)'], g['Necessidade bruta'], g['Fator envelhecimento'], g['COMPRA SUGERIDA']
        c[f"{MT}{x}"] = f"={DM}{x}*Premissas!$B$4/30"
        c[f"{NB}{x}"] = f"={MT}{x}-{PF}{x}"
        c[f"{FE}{x}"] = f"=IF({Q2}{x}>0,Premissas!$B$23,IF({Q1}{x}>0,Premissas!$B$21,1))"
        c[f"{CS}{x}"] = (f"=IF({NB}{x}*{FE}{x}<=0,0,INT({NB}{x}*{FE}{x})"
                         f"+IF({NB}{x}*{FE}{x}-INT({NB}{x}*{FE}{x})>=Premissas!$B$24,1,0))")
        EX = g['Excesso (un)']
        c[f"{EX}{x}"] = f"=MAX(0,{PF}{x}-{MT}{x})"
        c[f"{g['Dias de estoque pós-compra']}{x}"] = f'=IF({DM}{x}>0,({PF}{x}+{CS}{x})/{DM}{x}*30,"")'
        c[f"{g['% vendas margem fora padrão']}{x}"] = (f'=IFERROR(SUMIFS(Vendas!$U$2:$U${lv},{cV},$D{x})'
                                                        f'/COUNTIFS({cV},$D{x},{cVS},1),"")')
        c[f"{g['% MI médio vendas']}{x}"] = f'=IFERROR(AVERAGEIFS(Vendas!$H$2:$H${lv},{cV},$D{x},{cVS},1),"")'
        c[f"{g['D.E médio na venda']}{x}"] = f'=IFERROR(AVERAGEIFS(Vendas!$F$2:$F${lv},{cV},$D{x},{cVS},1),"")'
        c[f"{g['Status']}{x}"] = (
            f'=IF(AND({DM}{x}=0,{EC}{x}>0),"SEM VENDA NO PERÍODO - não comprar",'
            f'IF({CS}{x}>0,IF({FE}{x}<1,"COMPRAR (reduzido - estoque envelhecido)","COMPRAR"),'
            f'IF(AND({NB}{x}>=Premissas!$B$24,{FE}{x}=0),"TRAVADO - girar estoque > limite 2",'
            f'IF({EX}{x}>=1,"EXCESSO",IF({DM}{x}=0,"sem giro",IF({EC}{x}=0,"BAIXO GIRO - só sob pedido","OK"))))))')
        c[f"{g['Soma internas (check)']}{x}"] = f"=SUMIFS(Compra_Interna!$X:$X,Compra_Interna!$E:$E,$D{x})"
        # formats
        for n in ["Vendas ponderadas consideradas", "Meses equivalentes", "Demanda mensal (un/mês)",
                  "Vendas restantes projetadas no mês", "Estoque projetado fim do mês", "Meta (un)",
                  "Necessidade bruta", "Excesso (un)", "% MI médio vendas"]:
            c[f"{g[n]}{x}"].number_format = "0.0"
        for n in ["Dias de estoque hoje", "D.E médio disponível", "Dias de estoque pós-compra", "D.E médio na venda"]:
            c[f"{g[n]}{x}"].number_format = "0"
        c[f"{g['% vendas margem fora padrão']}{x}"].number_format = "0%"
        c[f"{FE}{x}"].number_format = "0.0"
        c[f"{CS}{x}"].font = F_BOLD
        c[f"{CS}{x}"].fill = FILL_KEY
    # totals
    tr = last + 1
    c[f"A{tr}"] = "TOTAL"
    sum_cols = [L(5 + j) for j in range(nm + 1)] + [col[n] for n in [
        "Vendas ponderadas consideradas", "Demanda mensal (un/mês)", "Disponível", "Trânsito", "Reservado cliente",
        "Bloqueio interno / Demo", "Estoque considerado", "Qtd > limite 1", "Qtd > limite 2",
        "Vendas restantes projetadas no mês", "Estoque projetado fim do mês", "Meta (un)", "COMPRA SUGERIDA",
        "Excesso (un)", "Soma internas (check)"]]
    for cc in sum_cols:
        c[f"{cc}{tr}"] = f"=SUM({cc}{first}:{cc}{last})"
        c[f"{cc}{tr}"].number_format = "0"
    DM, EC, PF, CS = col['Demanda mensal (un/mês)'], col['Estoque considerado'], col['Estoque projetado fim do mês'], col['COMPRA SUGERIDA']
    c[f"{col['Dias de estoque hoje']}{tr}"] = f"=IFERROR({EC}{tr}/{DM}{tr}*30,0)"
    c[f"{col['Dias de estoque pós-compra']}{tr}"] = f"=IFERROR(({PF}{tr}+{CS}{tr})/{DM}{tr}*30,0)"
    c[f"{col['Dias de estoque hoje']}{tr}"].number_format = "0"
    c[f"{col['Dias de estoque pós-compra']}{tr}"].number_format = "0"
    for j in range(1, len(hdr) + 1):
        c.cell(row=tr, column=j).fill = FILL_TOT
        c.cell(row=tr, column=j).font = F_BOLD
    c.freeze_panes = f"E{first}"
    c.auto_filter.ref = f"A{HR}:{L(len(hdr))}{last}"
    widths = [14, 38, 16, 8] + [8] * (nm + 1) + [10, 9, 10, 9, 8, 9, 10, 10, 9, 9, 9, 8, 8, 10, 10, 8, 10, 10, 11, 9, 10, 10, 9, 9, 36, 9]
    set_widths(c, widths)
    c.column_dimensions["D"].hidden = True
    stc = col["Status"]
    rng = f"{stc}{first}:{stc}{last}"
    c.conditional_formatting.add(rng, FormulaRule(formula=[f'LEFT({stc}{first},7)="COMPRAR"'],
                                                  fill=PatternFill("solid", fgColor="C6EFCE")))
    c.conditional_formatting.add(rng, FormulaRule(formula=[f'OR(LEFT({stc}{first},7)="EXCESSO",LEFT({stc}{first},9)="SEM VENDA")'],
                                                  fill=PatternFill("solid", fgColor="FFC7CE")))
    c.conditional_formatting.add(rng, FormulaRule(formula=[f'LEFT({stc}{first},7)="TRAVADO"'],
                                                  fill=PatternFill("solid", fgColor="FFEB9C")))
    cs_rng = f"{CS}{first}:{CS}{last}"
    c.conditional_formatting.add(cs_rng, FormulaRule(formula=[f"{CS}{first}=0"], font=Font(name=FONT, color="BFBFBF")))
    c[f"{col['Fator envelhecimento']}{HR}"].comment = Comment(
        "1 = sem trava; valores menores vêm da aba Premissas (limites de dias em estoque).", "Modelo")
    c[f"{col['Estoque projetado fim do mês']}{HR}"].comment = Comment(
        "Estoque considerado − (vendas restantes projetadas − carros já reservados por cliente). "
        "Reservados já saíram do estoque disponível e serão faturados no mês.", "Modelo")

    # ------------------------------------------------------------ Compra_Interna
    it = ws_int
    it["A1"] = "Rateio da compra por Cor Interna"
    it["A1"].font = F_TITLE
    it["A2"] = ("A compra de cada Versão x Cor Externa é distribuída pelas internas conforme o déficit de cada interna "
                "(meta − estoque projetado). Sem déficit, usa o mix histórico de vendas. Método do maior resto.")
    it["A2"].font = F_NOTE
    ih = ["Família", "Versão", "Cor Externa", "Cor Interna", "Chave Versão|Cor", "Chave SKU",
          "Vendas ponderadas", "Demanda mensal (un/mês)", "Disponível", "Trânsito", "Reservado cliente",
          "Estoque considerado", "Estoque projetado fim do mês", "Meta (un)", "Déficit", "Mix vendas",
          "Base de rateio", "Compra da cor externa", "Alocação bruta", "Parte inteira", "Resto",
          "Sobra do grupo", "Posição no resto", "COMPRA SUGERIDA (interna)", "Dias de estoque hoje"]
    for j, t in enumerate(ih, start=1):
        it.cell(row=HR, column=j, value=t)
    style_header(it, HR, len(ih), 58)
    ks = pd.concat([
        v[["Família", "Modelo", "Cor", "Cor Interna"]].rename(columns={"Modelo": "Versão", "Cor": "CorExt", "Cor Interna": "CorInt"}),
        e[["FAMÍLIA", "MODELO", "COR", "COR INTERNA"]].rename(columns={"FAMÍLIA": "Família", "MODELO": "Versão", "COR": "CorExt", "COR INTERNA": "CorInt"}),
    ]).drop_duplicates(["Versão", "CorExt", "CorInt"])
    order = {(a, b): i for i, (a, b) in enumerate(zip(keys["Versão"], keys["CorExt"]))}
    ks["o"] = [order[(a, b)] for a, b in zip(ks["Versão"], ks["CorExt"])]
    vi = v.groupby(["Modelo", "Cor", "Cor Interna"]).size()
    ks["vol"] = [vi.get((a, b, cc), 0) for a, b, cc in zip(ks["Versão"], ks["CorExt"], ks["CorInt"])]
    ks = ks.sort_values(["o", "vol"], ascending=[True, False]).reset_index(drop=True)
    fi = HR + 1
    li = fi + len(ks) - 1
    cVQ = f"Vendas!$Q$2:$Q${lv}"
    cER = f"Estoque!$R$2:$R${le}"
    corD = f"Compra_Cor!$D${first}:$D${last}"
    for k, kr in ks.iterrows():
        x = fi + k
        it[f"A{x}"] = kr["Família"]
        it[f"B{x}"] = kr["Versão"]
        it[f"C{x}"] = kr["CorExt"]
        it[f"D{x}"] = kr["CorInt"]
        it[f"E{x}"] = f'=B{x}&" | "&C{x}'
        it[f"F{x}"] = f'=B{x}&" | "&C{x}&" | "&D{x}'
        it[f"G{x}"] = f"=SUMIFS({cVW},{cVQ},$F{x})"
        me_col = col['Meses equivalentes']
        it[f"H{x}"] = f"=IFERROR(G{x}/INDEX(Compra_Cor!${me_col}${first}:${me_col}${last},MATCH($E{x},{corD},0)),0)"
        it[f"I{x}"] = f'=COUNTIFS({cER},$F{x},{cEC},"Disponível")'
        it[f"J{x}"] = f'=COUNTIFS({cER},$F{x},{cEC},"Trânsito")'
        it[f"K{x}"] = f'=COUNTIFS({cER},$F{x},{cEC},"Reserva cliente")'
        it[f"L{x}"] = f'=I{x}+IF(UPPER(Premissas!$B$5)="SIM",J{x},0)'
        it[f"M{x}"] = f"=MAX(0,L{x}-MAX(0,H{x}*Premissas!$B$12-K{x}))"
        it[f"N{x}"] = f"=H{x}*Premissas!$B$4/30"
        it[f"O{x}"] = f"=MAX(0,N{x}-M{x})"
        it[f"P{x}"] = f"=IFERROR(G{x}/SUMIFS($G${fi}:$G${li},$E${fi}:$E${li},$E{x}),0)"
        it[f"Q{x}"] = f"=IF(SUMIFS($O${fi}:$O${li},$E${fi}:$E${li},$E{x})>0,O{x}/SUMIFS($O${fi}:$O${li},$E${fi}:$E${li},$E{x}),P{x})"
        cs_col = col['COMPRA SUGERIDA']
        it[f"R{x}"] = f"=IFERROR(INDEX(Compra_Cor!${cs_col}${first}:${cs_col}${last},MATCH($E{x},{corD},0)),0)"
        it[f"S{x}"] = f"=R{x}*Q{x}"
        it[f"T{x}"] = f"=INT(S{x}+0.000001)"
        it[f"U{x}"] = f"=S{x}-T{x}+ROW()/10000000"
        it[f"V{x}"] = f"=R{x}-SUMIFS($T${fi}:$T${li},$E${fi}:$E${li},$E{x})"
        it[f"W{x}"] = f'=COUNTIFS($E${fi}:$E${li},$E{x},$U${fi}:$U${li},">"&U{x})+1'
        it[f"X{x}"] = f"=T{x}+IF(W{x}<=V{x},1,0)"
        it[f"Y{x}"] = f'=IF(H{x}>0,L{x}/H{x}*30,"")'
        for cc in "GHMNOS":
            it[f"{cc}{x}"].number_format = "0.0"
        for cc in "PQ":
            it[f"{cc}{x}"].number_format = "0%"
        it[f"U{x}"].number_format = "0.00"
        it[f"Y{x}"].number_format = "0"
        it[f"X{x}"].font = F_BOLD
        it[f"X{x}"].fill = FILL_KEY
        for cc in "RSTUVW":
            it[f"{cc}{x}"].font = Font(name=FONT, size=9, color="808080")
    ti = li + 1
    it[f"A{ti}"] = "TOTAL"
    for cc in "GHIJKLMNOX":
        it[f"{cc}{ti}"] = f"=SUM({cc}{fi}:{cc}{li})"
        it[f"{cc}{ti}"].number_format = "0"
    for j in range(1, len(ih) + 1):
        it.cell(row=ti, column=j).fill = FILL_TOT
        it.cell(row=ti, column=j).font = F_BOLD
    it.freeze_panes = f"E{fi}"
    it.auto_filter.ref = f"A{HR}:{L(len(ih))}{li}"
    set_widths(it, [14, 38, 16, 16, 8, 8, 9, 9, 9, 8, 9, 9, 10, 8, 8, 8, 8, 9, 8, 7, 7, 7, 7, 12, 9])
    it.column_dimensions["E"].hidden = True
    it.column_dimensions["F"].hidden = True
    it.conditional_formatting.add(f"X{fi}:X{li}", FormulaRule(formula=[f"X{fi}=0"], font=Font(name=FONT, color="BFBFBF")))

    # ------------------------------------------------------------ Por_Versao
    pv = ws_ver
    pv["A1"] = "Resumo por Versão"
    pv["A1"].font = F_TITLE
    vh2 = ["Família", "Versão", "Demanda mensal (un/mês)", "Disponível", "Trânsito", "Reservado cliente",
           "Estoque considerado", "Dias de estoque hoje", "Estoque projetado fim do mês", "Meta (un)",
           "COMPRA SUGERIDA", "Excesso (un)", "Dias pós-compra", "D.E máx disponível", "Qtd > limite 2", "% MI médio vendas",
           "% MI versão − média da família (pp)"]
    for j, t in enumerate(vh2, start=1):
        pv.cell(row=3, column=j, value=t)
    style_header(pv, 3, len(vh2), 44)
    vers = keys[["Família", "Versão"]].drop_duplicates().reset_index(drop=True)
    fr = 4
    lr = fr + len(vers) - 1
    corB = f"Compra_Cor!$B${first}:$B${last}"

    def sc(name):
        cl = col[name]
        return f"Compra_Cor!${cl}${first}:${cl}${last}"

    for k, kr in vers.iterrows():
        x = fr + k
        pv[f"A{x}"] = kr["Família"]
        pv[f"B{x}"] = kr["Versão"]
        for cl, name in zip("CDEFG", ["Demanda mensal (un/mês)", "Disponível", "Trânsito", "Reservado cliente", "Estoque considerado"]):
            pv[f"{cl}{x}"] = f"=SUMIFS({sc(name)},{corB},$B{x})"
        pv[f"H{x}"] = f'=IF(C{x}>0,G{x}/C{x}*30,"")'
        for cl, name in zip("IJKL", ["Estoque projetado fim do mês", "Meta (un)", "COMPRA SUGERIDA", "Excesso (un)"]):
            pv[f"{cl}{x}"] = f"=SUMIFS({sc(name)},{corB},$B{x})"
        pv[f"M{x}"] = f'=IF(C{x}>0,(I{x}+K{x})/C{x}*30,"")'
        pv[f"N{x}"] = f'=IF(D{x}=0,"",_xlfn.MAXIFS({cED},Estoque!$D$2:$D${le},$B{x},{cEC},"Disponível"))'
        pv[f"O{x}"] = f"=SUMIFS({sc('Qtd > limite 2')},{corB},$B{x})"
        pv[f"P{x}"] = f'=IFERROR(AVERAGEIFS(Vendas!$H$2:$H${lv},Vendas!$B$2:$B${lv},$B{x},{cVS},1),"")'
        pv[f"Q{x}"] = (f'=IFERROR(P{x}-AVERAGEIFS(Vendas!$H$2:$H${lv},Vendas!$A$2:$A${lv},$A{x},{cVS},1),"")')
        pv[f"Q{x}"].number_format = "+0.0;-0.0;0.0"
        for cl in "CIJL":
            pv[f"{cl}{x}"].number_format = "0.0"
        for cl in "HMN":
            pv[f"{cl}{x}"].number_format = "0"
        pv[f"P{x}"].number_format = "0.0"
        pv[f"K{x}"].font = F_BOLD
        pv[f"K{x}"].fill = FILL_KEY
    t2 = lr + 1
    pv[f"A{t2}"] = "TOTAL"
    for cl in "CDEFGIJKLO":
        pv[f"{cl}{t2}"] = f"=SUM({cl}{fr}:{cl}{lr})"
        pv[f"{cl}{t2}"].number_format = "0"
    pv[f"H{t2}"] = f"=IFERROR(G{t2}/C{t2}*30,0)"
    pv[f"M{t2}"] = f"=IFERROR((I{t2}+K{t2})/C{t2}*30,0)"
    for j in range(1, len(vh2) + 1):
        pv.cell(row=t2, column=j).fill = FILL_TOT
        pv.cell(row=t2, column=j).font = F_BOLD
    pv[f"H{t2}"].number_format = "0"
    pv[f"M{t2}"].number_format = "0"
    pv.freeze_panes = "C4"
    set_widths(pv, [15, 44, 10, 9, 8, 9, 10, 9, 10, 8, 10, 8, 9, 9, 8, 9, 11])

    # ------------------------------------------------------------ Envelhecidos
    en = ws_env
    en["A1"] = "Estoque disponível envelhecido (acima do limite 1) — prioridade de giro"
    en["A1"].font = F_TITLE
    eh2 = ["Versão", "Cor Externa", "Cor Interna", "D.E", "Filial", "Vl Venda", "% RV", "Chassi",
           "Demanda mensal da cor", "Dias de estoque da cor", "Status da cor"]
    for j, t in enumerate(eh2, start=1):
        en.cell(row=3, column=j, value=t)
    style_header(en, 3, len(eh2), 36)
    ed = e[(e["ST"] == "Disponível") & (e["SIT"] == "ESTOQUE") & (e["D.E"] > 60)].sort_values("D.E", ascending=False)
    for k, (_, r) in enumerate(ed.iterrows()):
        x = 4 + k
        en[f"A{x}"] = r["MODELO"]
        en[f"B{x}"] = r["COR"]
        en[f"C{x}"] = r["COR INTERNA"]
        en[f"D{x}"] = r["D.E"]
        en[f"E{x}"] = r["FILIAL"]
        en[f"F{x}"] = r["VL VENDA"]
        en[f"G{x}"] = r["% RV"]
        en[f"H{x}"] = r["CHASSI"]
        key = f'A{x}&" | "&B{x}'
        for cl, name, fmt in [("I", "Demanda mensal (un/mês)", "0.0"), ("J", "Dias de estoque hoje", "0"), ("K", "Status", None)]:
            en[f"{cl}{x}"] = f'=IFERROR(INDEX({sc(name)},MATCH({key},{corD},0)),"")'
            if fmt:
                en[f"{cl}{x}"].number_format = fmt
        en[f"F{x}"].number_format = "#,##0"
        en[f"G{x}"].number_format = "0.00"
    en["A2"] = "Lista estática do arquivo de estoque (D.E > 60 dias, ST Disponível); colunas I–K são fórmulas."
    en["A2"].font = F_NOTE
    set_widths(en, [42, 16, 12, 6, 32, 11, 7, 20, 10, 10, 38])
    en.freeze_panes = "A4"

    # ------------------------------------------------------------ Resumo
    rs = ws_res
    rs["A1"] = "Reposição de estoque Hyundai — resumo"
    rs["A1"].font = F_TITLE
    rs["A2"] = (f"Estoque: {estoque_path.split('/')[-1]}  |  Vendas: " + ", ".join(p_.split('/')[-1] for p_ in vendas_paths))
    rs["A2"].font = F_NOTE
    items = [
        ("Data base das vendas", "=Premissas!B7", "dd/mm/yyyy"),
        ("Meta de dias de estoque", "=Premissas!B4", "0"),
        ("Vendas do mês até o corte", "=Premissas!B13", "0"),
        ("Curva histórica: % do mês vendido até o dia de corte", "=Premissas!B11", "0.0%"),
        ("Projeção de vendas do mês (total)", "=Premissas!B14", "0"),
        ("Demanda mensal ponderada (un/mês)", f"=Compra_Cor!{col['Demanda mensal (un/mês)']}{tr}", "0"),
        ("Estoque disponível (un)", f"=Compra_Cor!{col['Disponível']}{tr}", "0"),
        ("Em trânsito (un)", f"=Compra_Cor!{col['Trânsito']}{tr}", "0"),
        ("Reservado por cliente (un)", f"=Compra_Cor!{col['Reservado cliente']}{tr}", "0"),
        ("Bloqueio interno / demonstração (fora da conta)", f"=Compra_Cor!{col['Bloqueio interno / Demo']}{tr}", "0"),
        ("Dias de estoque hoje (total)", f"=Compra_Cor!{col['Dias de estoque hoje']}{tr}", "0"),
        ("Estoque projetado no fim do mês", f"=Compra_Cor!{col['Estoque projetado fim do mês']}{tr}", "0"),
        ("COMPRA SUGERIDA (un)", f"=Compra_Cor!{col['COMPRA SUGERIDA']}{tr}", "0"),
        ("Excesso sobre a meta (un)", f"=Compra_Cor!{col['Excesso (un)']}{tr}", "0"),
        ("Dias de estoque pós-compra (total)", f"=Compra_Cor!{col['Dias de estoque pós-compra']}{tr}", "0"),
        ("Carros disponíveis acima do limite 2 de dias", f"=Compra_Cor!{col['Qtd > limite 2']}{tr}", "0"),
    ]
    for k, (lab, f, fmt) in enumerate(items):
        x = 4 + k
        rs[f"A{x}"] = lab
        rs[f"B{x}"] = f
        rs[f"B{x}"].number_format = fmt
        rs[f"B{x}"].font = F_BOLD
    rs["A16"].font = F_BOLD
    rs["B16"].fill = FILL_KEY
    fam_r = 4 + len(items) + 2
    fh = ["Família", "Demanda mensal", "Estoque considerado", "Dias hoje", "Projetado fim do mês", "Meta",
          "COMPRA SUGERIDA", "Excesso", "Dias pós-compra"]
    for j, t in enumerate(fh, start=1):
        rs.cell(row=fam_r, column=j, value=t)
    style_header(rs, fam_r, len(fh), 32)
    fams = sorted(keys["Família"].unique())
    corA = f"Compra_Cor!$A${first}:$A${last}"
    for k, fam in enumerate(fams):
        x = fam_r + 1 + k
        rs[f"A{x}"] = fam
        rs[f"B{x}"] = f"=SUMIFS({sc('Demanda mensal (un/mês)')},{corA},$A{x})"
        rs[f"C{x}"] = f"=SUMIFS({sc('Estoque considerado')},{corA},$A{x})"
        rs[f"D{x}"] = f'=IF(B{x}>0,C{x}/B{x}*30,"")'
        rs[f"E{x}"] = f"=SUMIFS({sc('Estoque projetado fim do mês')},{corA},$A{x})"
        rs[f"F{x}"] = f"=SUMIFS({sc('Meta (un)')},{corA},$A{x})"
        rs[f"G{x}"] = f"=SUMIFS({sc('COMPRA SUGERIDA')},{corA},$A{x})"
        rs[f"H{x}"] = f"=SUMIFS({sc('Excesso (un)')},{corA},$A{x})"
        rs[f"I{x}"] = f'=IF(B{x}>0,(E{x}+G{x})/B{x}*30,"")'
        for cl in "BEFH":
            rs[f"{cl}{x}"].number_format = "0.0"
        for cl in "DI":
            rs[f"{cl}{x}"].number_format = "0"
        rs[f"G{x}"].font = F_BOLD
        rs[f"G{x}"].fill = FILL_KEY
    tf = fam_r + 1 + len(fams)
    rs[f"A{tf}"] = "TOTAL"
    for cl in "BCEFGH":
        rs[f"{cl}{tf}"] = f"=SUM({cl}{fam_r + 1}:{cl}{tf - 1})"
        rs[f"{cl}{tf}"].number_format = "0"
    rs[f"D{tf}"] = f"=IFERROR(C{tf}/B{tf}*30,0)"
    rs[f"I{tf}"] = f"=IFERROR((E{tf}+G{tf})/B{tf}*30,0)"
    rs[f"D{tf}"].number_format = "0"
    rs[f"I{tf}"].number_format = "0"
    for j in range(1, len(fh) + 1):
        rs.cell(row=tf, column=j).fill = FILL_TOT
        rs.cell(row=tf, column=j).font = F_BOLD
    nr = tf + 2
    notes = [
        "Como ler:",
        "• Compra_Cor é a aba principal: uma linha por Versão x Cor Externa, com a sugestão de compra (coluna verde).",
        "• Compra_Interna reparte cada compra entre as cores internas; a coluna 'Soma internas (check)' da Compra_Cor deve bater.",
        "• Estoque considerado = ST Disponível (SIT Estoque) + trânsito (se Premissas!B5 = SIM). Reservas de cliente saem do estoque "
        "e abatem das vendas restantes do mês; bloqueios internos (acessórios/blindagem) e demonstração ficam fora.",
        "• Trava de envelhecimento: cor com carro acima de 90 dias não compra; entre 60 e 90 dias compra pela metade.",
        "• Todas as premissas são editáveis na aba Premissas e recalculam o arquivo inteiro.",
    ]
    for k, t in enumerate(notes):
        rs[f"A{nr + k}"] = t
        rs[f"A{nr + k}"].font = F_BOLD if k == 0 else F_NOTE
    set_widths(rs, [52, 14, 12, 10, 12, 10, 12, 10, 12])

    for ws in wb.worksheets:
        base_font(ws)
        ws.sheet_view.showGridLines = ws.title in ("Vendas", "Estoque")
    wb.active = 0
    wb.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estoque", required=True)
    ap.add_argument("--vendas", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dias-meta", type=int, default=30)
    ap.add_argument("--meses", type=int, default=3)
    ap.add_argument("--transito", default="SIM")
    ap.add_argument("--lancamento", action="append", default=None,
                    help='"FAMÍLIA=AAAA-MM-DD" (1º mês cheio a considerar)')
    ap.add_argument("--data-base", default=None)
    a = ap.parse_args()
    lanc = None
    if a.lancamento:
        lanc = {}
        for s in a.lancamento:
            k, d = s.split("=")
            lanc[k.strip().upper()] = pd.Timestamp(d.strip())
    build(a.estoque, a.vendas, a.out, a.dias_meta, a.meses, a.transito, lanc, a.data_base)
    print("OK ->", a.out)


if __name__ == "__main__":
    main()
