import pandas as pd, io, json, sys, re
rd=lambda f: pd.read_html(io.StringIO(open(f,encoding='utf-8').read()),decimal=',',thousands='.')[0]
vf, ef, foto, out = sys.argv[1:5]
v=rd(vf); e=rd(ef)
v=v[v['Família'].notna() & v['Modelo'].notna()].copy(); e=e[e['MARCA'].notna()].copy()
fam=lambda s: s.replace('HYUNDAI ','').strip().title().replace('Hb20S','HB20S').replace('Hb20','HB20').replace('I20','i20')
up=lambda s: str(s).strip().upper()
v['d']=pd.to_datetime(v['Dt Venda'],dayfirst=True)
loja=lambda s: 'BF' if (' 71 ' in f' {s} ' or '71 -' in s or ' 75 ' in s) else ('GRU' if '72' in s else s)
vendas=[dict(fam=fam(r['Família']),versao=up(r['Modelo']),cor_ext=up(r['Cor']),cor_int=up(r['Cor Interna']),mes=r.d.strftime('%Y-%m'),dia=int(r.d.day),
  de=int(r['D.E'] or 0),mi=round(float(r['% MI']),2),loja=loja(str(r['Filial']))) for _,r in v.iterrows()]
def cat(r):
    st=str(r['ST']); sit=str(r['SIT'])
    if re.match(r'Proposta: \d',st): return 'Vendido não faturado'
    if st.startswith('Proposta:'):
        cli=re.search(r'Cliente: (.*?)Vendedor',st); cli=cli.group(1).upper() if cli else ''
        if 'ACESS' in cli: return 'Disponível' if sit!='TRÂNSITO' else 'Trânsito'
        if 'BLIND' in cli: return 'Em blindagem'
        return 'Bloqueio interno'
    if sit.startswith('DEMO'): return 'Demonstração'
    if st=='TRÂNSITO' or sit=='TRÂNSITO': return 'Trânsito'
    if st=='Disponível' and sit=='ESTOQUE': return 'Disponível'
    return 'Outro'
e['cat']=e.apply(cat,axis=1)
estoque=[dict(cat=r['cat'],fam=fam(r['FAMÍLIA']),versao=up(r['MODELO']),cor_ext=up(r['COR']),cor_int=up(r['COR INTERNA']),de=int(r['D.E'] or 0),
  loja=loja(str(r['FILIAL'])),data_foto=foto) for _,r in e.iterrows()]
json.dump(vendas,open(f'{out}/vendas_hyundai.json','w'),ensure_ascii=False)
json.dump(estoque,open(f'{out}/estoque_hyundai.json','w'),ensure_ascii=False)
print(len(vendas),len(estoque),pd.Series([x['cat'] for x in estoque]).value_counts().to_dict())
