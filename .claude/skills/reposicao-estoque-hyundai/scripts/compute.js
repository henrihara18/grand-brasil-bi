// Modelo de reposição Hyundai — mesmo cálculo da planilha, com pesos por mês editáveis.
window.repoDefaults = {
  pA1: 1, pA2: 1, pA3: 1, pA4: 0,
  pB1: 0, pB2: 0, pB3: 1, pB4: 1,
  dias: 30, transito: true, pondera: true, trava: true, loja: 'Todas'
};
window.repoCompute = function (vendas, estoque, o) {
  const LANC = { i20: '2026-07' };
  const addM = (ym, k) => { const [y, m] = ym.split('-').map(Number); const d = new Date(Date.UTC(y, m - 1 + k, 1)); return d.toISOString().slice(0, 7); };
  const V = vendas.map((r) => ({ ...r, dia: Number(r.dia), de: Number(r.de), mi: Number(r.mi) }));
  const E = estoque.map((r) => ({ ...r, de: Number(r.de) }));
  const cur = V.reduce((a, r) => (r.mes > a ? r.mes : a), '');
  const M = [addM(cur, -3), addM(cur, -2), addM(cur, -1), cur];
  // dia de corte: último dia faturado ou a véspera da foto do estoque, o que for maior (no mesmo mês)
  const foto = (E.find((r) => r.data_foto) || {}).data_foto || '';
  const ultFat = V.filter((r) => r.mes === cur).reduce((a, r) => Math.max(a, r.dia), 0);
  const corte = foto.slice(0, 7) === cur ? Math.max(ultFat, Number(foto.slice(8, 10)) - 1) : ultFat;
  const full = V.filter((r) => M.slice(0, 3).includes(r.mes));
  const curva = full.length ? full.filter((r) => r.dia <= corte).length / full.length : 1;
  const ateCorte = V.filter((r) => r.mes === cur).length;
  const startOf = (fam) => (LANC[fam] && LANC[fam] > M[0] ? LANC[fam] : M[0]);
  const lojaOk = (l) => o.loja === 'Todas' || l === o.loja;
  const P = { A: [o.pA1, o.pA2, o.pA3, o.pA4].map(Number), B: [o.pB1, o.pB2, o.pB3, o.pB4].map(Number) };
  const dias = Number(o.dias) || 30;

  const Vf = V.filter((r) => M.includes(r.mes) && r.mes >= startOf(r.fam) && lojaOk(r.loja));
  const miSum = {}, miN = {};
  Vf.forEach((r) => { miSum[r.versao] = (miSum[r.versao] || 0) + r.mi; miN[r.versao] = (miN[r.versao] || 0) + 1; });
  Vf.forEach((r) => {
    const med = miSum[r.versao] / miN[r.versao];
    r.baixa = r.mi < med - 3 || r.mi < 2 ? 1 : 0;
    r.parado = r.de > 90 ? 1 : 0;
    r.w = o.pondera ? (r.baixa ? 0.5 : 1) * (r.parado ? 0.5 : 1) : 1;
    r.k = M.indexOf(r.mes);
  });
  const Ef = E.filter((r) => lojaOk(r.loja));

  const fator = (fam) => M.map((m, k) => (m < startOf(fam) ? 0 : k === 3 ? curva : 1));
  const demanda = (w, fam, s) => {
    const f = fator(fam); let num = 0, den = 0;
    for (let k = 0; k < 4; k++) { num += P[s][k] * w[k]; den += P[s][k] * f[k]; }
    return den > 0 ? num / den : 0;
  };
  const arred = (x) => (x <= 0 ? 0 : Math.floor(x) + (x - Math.floor(x) >= 0.5 ? 1 : 0));

  function agrupa(keyFn, base) {
    const g = new Map();
    const get = (r) => {
      const key = keyFn(r);
      if (!g.has(key)) g.set(key, { key, fam: r.fam, versao: r.versao, cor_ext: r.cor_ext, cor_int: base === 'int' ? r.cor_int : '',
        v: [0, 0, 0, 0], w: [0, 0, 0, 0], disp: 0, trans: 0, resv: 0, bloq: 0, des: [], q60: 0, q90: 0, mis: [], baixas: 0, nv: 0 });
      return g.get(key);
    };
    Vf.forEach((r) => { const x = get(r); x.v[r.k] += 1; x.w[r.k] += r.w; x.mis.push(r.mi); x.baixas += r.baixa; x.nv += 1; });
    Ef.forEach((r) => {
      const x = get(r);
      if (r.cat === 'Disponível') { x.disp += 1; x.des.push(r.de); if (r.de > 60) x.q60 += 1; if (r.de > 90) x.q90 += 1; }
      else if (r.cat === 'Trânsito') x.trans += 1;
      else if (r.cat === 'Vendido não faturado' || r.cat === 'Reserva cliente') x.resv += 1;
      else x.bloq += 1;
    });
    return [...g.values()];
  }
  function cenario(x, s) {
    const dem = demanda(x.w, x.fam, s);
    const ec = x.disp + (o.transito ? x.trans : 0);
    const pf = Math.max(0, ec - Math.max(0, dem * (1 - curva) - x.resv));
    const meta = dem * dias / 30;
    const nb = meta - pf;
    const fe = !o.trava ? 1 : x.q90 > 0 ? 0 : x.q60 > 0 ? 0.5 : 1;
    return { dem, ec, pf, meta, nb, fe, compra: arred(nb * fe), excesso: Math.max(0, pf - meta), dias_hoje: dem > 0 ? ec / dem * 30 : null };
  }
  const r1 = (x) => Math.round(x * 10) / 10;

  const cores = agrupa((r) => r.versao + ' | ' + r.cor_ext, 'ext').map((x) => {
    const a = cenario(x, 'A'), b = cenario(x, 'B');
    let leitura;
    if (a.dem === 0 && b.dem === 0 && a.ec > 0) leitura = 'Sem venda — não comprar';
    else if (a.compra > 0 && b.compra > 0) leitura = 'Comprar';
    else if (b.compra > 0) leitura = 'Comprar só no recente';
    else if (a.compra > 0) leitura = 'Comprar só no 3 meses';
    else if (a.fe === 0 && Math.max(a.nb, b.nb) >= 0.5) leitura = 'Travado — girar >90d';
    else if (Math.min(a.excesso, b.excesso) >= 1) leitura = 'Excesso';
    else leitura = 'OK';
    return {
      chave: x.key, familia: x.fam, versao: x.versao, cor_ext: x.cor_ext,
      v1: x.v[0], v2: x.v[1], v3: x.v[2], v4: x.v[3],
      disponivel: x.disp, transito: x.trans, reservado: x.resv, bloqueado: x.bloq, estoque: a.ec,
      de_max: x.des.length ? Math.max(...x.des) : null, q90: x.q90,
      mi_medio: x.mis.length ? r1(x.mis.reduce((p, c) => p + c, 0) / x.mis.length) : null,
      dem_a: r1(a.dem), dem_b: r1(b.dem),
      dias_a: a.dias_hoje == null ? null : Math.round(a.dias_hoje), dias_b: b.dias_hoje == null ? null : Math.round(b.dias_hoje),
      compra_a: a.compra, compra_b: b.compra, excesso_a: r1(a.excesso), excesso_b: r1(b.excesso),
      fator: a.fe, leitura,
      _pf_a: a.pf, _pf_b: b.pf, _meta_a: a.meta, _meta_b: b.meta
    };
  });

  // Rateio por cor interna (maior resto), por cenário
  const ints = agrupa((r) => r.versao + ' | ' + r.cor_ext + ' | ' + r.cor_int, 'int').map((x) => {
    const a = cenario(x, 'A'), b = cenario(x, 'B');
    return { chave: x.key, ext: x.versao + ' | ' + x.cor_ext, familia: x.fam, versao: x.versao, cor_ext: x.cor_ext, cor_int: x.cor_int,
      vendas: x.nv, wsum: x.w.reduce((p, c) => p + c, 0), disponivel: x.disp, transito: x.trans,
      def_a: Math.max(0, a.meta - a.pf), def_b: Math.max(0, b.meta - b.pf) };
  });
  const byExt = new Map(cores.map((c) => [c.chave, c]));
  ['a', 'b'].forEach((s) => {
    const grupos = new Map();
    ints.forEach((i) => { if (!grupos.has(i.ext)) grupos.set(i.ext, []); grupos.get(i.ext).push(i); });
    grupos.forEach((lista, ext) => {
      const total = byExt.get(ext)['compra_' + s];
      const sd = lista.reduce((p, i) => p + i['def_' + s], 0), sw = lista.reduce((p, i) => p + i.wsum, 0);
      lista.forEach((i) => { const base = sd > 0 ? i['def_' + s] / sd : sw > 0 ? i.wsum / sw : 1 / lista.length; i._aloc = total * base; i['compra_' + s] = Math.floor(i._aloc + 1e-6); });
      let sobra = total - lista.reduce((p, i) => p + i['compra_' + s], 0);
      [...lista].sort((x, y) => (y._aloc - Math.floor(y._aloc + 1e-6)) - (x._aloc - Math.floor(x._aloc + 1e-6))).forEach((i) => { if (sobra > 0) { i['compra_' + s] += 1; sobra -= 1; } });
    });
  });
  const internas = ints.filter((i) => i.compra_a > 0 || i.compra_b > 0).map((i) => ({
    chave: i.chave, familia: i.familia, versao: i.versao, cor_ext: i.cor_ext, cor_int: i.cor_int,
    vendas: i.vendas, disponivel: i.disponivel, transito: i.transito, compra_a: i.compra_a, compra_b: i.compra_b }));

  const fams = [...new Set(cores.map((c) => c.familia))].sort();
  const familias = fams.map((f) => {
    const cs = cores.filter((c) => c.familia === f);
    const s = (k) => cs.reduce((p, c) => p + (c[k] || 0), 0);
    const da = cs.reduce((p, c) => p + (c.dem_a || 0), 0), db = cs.reduce((p, c) => p + (c.dem_b || 0), 0), ec = s('estoque');
    return { familia: f, vendas_m1: s('v1'), vendas_m2: s('v2'), vendas_m3: s('v3'), vendas_m4: s('v4'), estoque: ec,
      dem_a: r1(da), dem_b: r1(db), dias_a: da > 0 ? Math.round(ec / da * 30) : null, dias_b: db > 0 ? Math.round(ec / db * 30) : null,
      compra_a: s('compra_a'), compra_b: s('compra_b'), excesso_a: r1(s('excesso_a')), q90: s('q90') };
  });
  const T = (k) => cores.reduce((p, c) => p + (c[k] || 0), 0);
  const demA = T('dem_a'), demB = T('dem_b'), est = T('estoque');
  const resumo = [{
    mes_corrente: cur, dia_corte: corte, m1: M[0], m2: M[1], m3: M[2], m4: M[3],
    vendas_ate_corte: ateCorte, curva: Math.round(curva * 1000) / 1000, projecao_mes: Math.round(ateCorte / curva),
    estoque: est, disponivel: T('disponivel'), transito: T('transito'), reservado: T('reservado'), vendido_mes: ateCorte + T('reservado'), data_foto: foto,
    dem_a: r1(demA), dem_b: r1(demB), dias_a: demA > 0 ? Math.round(est / demA * 30) : null, dias_b: demB > 0 ? Math.round(est / demB * 30) : null,
    compra_a: T('compra_a'), compra_b: T('compra_b'), q90: T('q90'), dias_meta: dias
  }];
  const mensal = M.map((m, k) => {
    const n = V.filter((r) => r.mes === m && lojaOk(r.loja)).length;
    return { mes: m, vendas: n, projecao: k === 3 ? Math.max(0, Math.round(n / curva) - n) : 0 };
  });
  const envelhecidos = Ef.filter((r) => r.cat === 'Disponível' && r.de > 60).sort((a, b) => b.de - a.de).map((r, i) => {
    const c = byExt.get(r.versao + ' | ' + r.cor_ext);
    return { id: i + 1, versao: r.versao, cor_ext: r.cor_ext, cor_int: r.cor_int, dias: r.de, loja: r.loja,
      vendas_cor_3m: c ? c.v1 + c.v2 + c.v3 + c.v4 : 0, leitura: c ? c.leitura : '' };
  });
  cores.forEach((c) => { delete c._pf_a; delete c._pf_b; delete c._meta_a; delete c._meta_b; });
  return { resumo, cores, internas, familias, mensal, envelhecidos };
};
