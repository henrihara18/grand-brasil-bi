"""Webmotors reference section for the Avaliacao page.

Currently in standby mode — the scraper requires ScraperAPI credits due to
the site's PerimeterX anti-bot layer. When SCRAPERAPI_KEY is configured the
full reference UI appears; otherwise the section emits a friendly warning.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from grand_brasil.utils.currency import format_brl


def load_webmotors(brand: str, model: str, year_model: int) -> list[dict]:
    """Fetch Webmotors listings with per-session cache (24h disk cache downstream)."""
    key = f"_wm_{brand}_{model}_{year_model}".lower().replace(" ", "_")
    if key in st.session_state:
        return st.session_state[key]

    try:
        scraperapi_key = st.secrets.get("SCRAPERAPI_KEY", "") or ""
    except Exception:
        scraperapi_key = ""

    try:
        from grand_brasil.ingestion.webmotors_client import search_webmotors
        listings = search_webmotors(
            brand=brand,
            model=model,
            year_model=year_model,
            max_results=100,
            scraperapi_key=scraperapi_key,
        )
        st.session_state[key] = listings
        return listings
    except Exception:
        st.session_state[key] = []
        return []


def render_webmotors(params: dict) -> None:
    """Render the Webmotors reference section — 4 summary cards + full listing table."""
    brand = params["brand"]
    model = params["model"]
    year_model = params["year_model"]
    car_km = params.get("km") or 0

    st.subheader("Referencia Webmotors")

    with st.spinner(f"Buscando anuncios {brand} {model} {year_model} na Webmotors..."):
        listings = load_webmotors(brand, model, year_model)

    if not listings:
        st.warning(
            f"Nenhum anuncio encontrado na Webmotors para {brand} {model} {year_model}. "
            "Verifique a chave SCRAPERAPI_KEY nos secrets ou tente novamente."
        )
        return

    df = pd.DataFrame(listings)
    total = len(df)

    # 4 KPI cards
    conc = df[df["advertiser_type"] == "Concessionaria"].sort_values("price")
    loja_pf = df[df["advertiser_type"].isin(["Loja", "Pessoa Fisica"])].sort_values("price")
    conc_km = conc[conc["km"] <= car_km + 15_000].sort_values("price")
    media = df["price"].mean()

    st.caption(f"{total} anuncios encontrados | {brand} {model} {year_model}")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("**Mais barato — Concessionária**")
        if not conc.empty:
            r = conc.iloc[0]
            st.metric("Preco", format_brl(r["price"]))
            st.caption(f"{r['km']:,} km | {r['advertiser_name'] or r['advertiser_type']}")
            st.markdown(f"[Ver anuncio]({r['url']})", unsafe_allow_html=False)
        else:
            st.info("Sem anuncios de concessionaria")

    with col2:
        st.markdown("**Mais barato — Loja / Pessoa Fisica**")
        if not loja_pf.empty:
            r = loja_pf.iloc[0]
            st.metric("Preco", format_brl(r["price"]))
            st.caption(f"{r['km']:,} km | {r['advertiser_name'] or r['advertiser_type']}")
            st.markdown(f"[Ver anuncio]({r['url']})", unsafe_allow_html=False)
        else:
            st.info("Sem anuncios de loja/PF")

    with col3:
        st.markdown(f"**Conc. mais barata — KM ate {car_km + 15_000:,}**")
        if not conc_km.empty:
            r = conc_km.iloc[0]
            st.metric("Preco", format_brl(r["price"]))
            st.caption(f"{r['km']:,} km | {r['advertiser_name'] or r['advertiser_type']}")
            st.markdown(f"[Ver anuncio]({r['url']})", unsafe_allow_html=False)
        else:
            st.info(f"Sem concessionarias com KM ate {car_km + 15_000:,}")

    with col4:
        st.markdown("**Media Webmotors**")
        st.metric("Preco medio", format_brl(media))
        st.caption(f"Base: {total} anuncios")

    # Full table in an expander
    with st.expander(f"Ver todos os {total} anuncios", expanded=False):
        tbl = df[["price", "km", "year", "version", "advertiser_type",
                  "advertiser_name", "city", "url"]].copy()
        tbl = tbl.rename(columns={
            "price": "Preco",
            "km": "KM",
            "year": "Ano",
            "version": "Versao",
            "advertiser_type": "Tipo",
            "advertiser_name": "Anunciante",
            "city": "Cidade",
            "url": "Link",
        })
        tbl["Preco"] = tbl["Preco"].apply(lambda x: format_brl(x))
        tbl["KM"] = tbl["KM"].apply(lambda x: f"{int(x):,}".replace(",", "."))
        st.dataframe(tbl, use_container_width=True, hide_index=True)
