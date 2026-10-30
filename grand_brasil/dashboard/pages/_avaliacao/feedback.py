"""Feedback form rendered after every appraisal result.

Captures the actual paid price (or "deal not closed") and writes it
to a CSV log. The intent is to build a calibration dataset over time
that can be cross-referenced against the algorithm's suggestions.

This is a lightweight collector — there is no in-app dashboard yet.
"""

from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from grand_brasil.ingestion.appraisal_feedback import (
    append_feedback,
    build_entry_from_suggestion,
)
from grand_brasil.utils.currency import format_brl

logger = logging.getLogger(__name__)


def render_feedback_form(result, fipe_price: Optional[float] = None) -> None:
    """Render the "valor real pago" form below the appraisal result."""
    # Stable key per appraisal (so re-runs / new evaluations reset the form)
    eval_key = f"{result.brand}-{result.model_red}-{result.year_model}-{result.km}"
    submitted_key = f"feedback_submitted_{eval_key}"

    if st.session_state.get(submitted_key):
        st.success(
            "✅ Feedback registrado. Obrigado! "
            "Os dados serao usados para calibrar o algoritmo."
        )
        return

    with st.expander("📝 Registrar valor real pago (calibração)", expanded=False):
        st.caption(
            "Após fechar (ou recusar) o negócio, registre aqui o valor "
            "efetivamente pago. Esses dados alimentam a calibração do "
            "algoritmo."
        )

        col_p, col_d = st.columns([2, 2])
        with col_p:
            plate = st.text_input(
                "Placa (opcional)",
                key=f"feedback_plate_{eval_key}",
                placeholder="ABC1D23",
                max_chars=10,
            )
        with col_d:
            deal_status = st.radio(
                "Status do negócio",
                options=["Fechado", "Não fechado"],
                horizontal=True,
                key=f"feedback_status_{eval_key}",
            )

        deal_closed = "fechado" if deal_status == "Fechado" else "nao_fechado"

        col_c, col_v = st.columns([2, 2])
        with col_c:
            channel_real = st.radio(
                "Canal real",
                options=["", "Loja", "Revenda"],
                format_func=lambda x: "(não definido)" if x == "" else x,
                horizontal=True,
                key=f"feedback_channel_{eval_key}",
            )
        with col_v:
            paid_real_input = st.number_input(
                "Valor pago real (R$)",
                min_value=0,
                max_value=10_000_000,
                value=0,
                step=500,
                key=f"feedback_paid_{eval_key}",
                help=(
                    "Apenas se Status='Fechado'. Se ainda nao fechou, "
                    "deixe em 0 e marque como 'Nao fechado'."
                ),
            )

        observation = st.text_area(
            "Observação (opcional)",
            key=f"feedback_obs_{eval_key}",
            placeholder=(
                "Ex: cliente comparou com Webmotors / desconto por troca / "
                "carro chegou com avaria adicional, etc."
            ),
            max_chars=500,
        )

        submit = st.button(
            "💾 Salvar feedback",
            key=f"feedback_submit_{eval_key}",
            type="primary",
        )

        if not submit:
            return

        # Validation
        if deal_closed == "fechado" and paid_real_input <= 0:
            st.error(
                "Para negócios fechados, informe o valor pago real (> 0)."
            )
            return

        paid_real = float(paid_real_input) if paid_real_input > 0 else None

        try:
            entry = build_entry_from_suggestion(
                suggestion=result,
                plate=plate,
                deal_closed=deal_closed,
                channel_real=channel_real,
                paid_real=paid_real,
                observation=observation,
                fipe_price=fipe_price,
            )
            log_path = append_feedback(entry)
        except Exception as exc:
            logger.exception("Failed to log appraisal feedback")
            st.error(f"Erro ao salvar feedback: {exc}")
            return

        st.session_state[submitted_key] = True
        success_msg = (
            f"✅ Feedback registrado em `{log_path.name}`."
        )
        if paid_real is not None and result.blended_max_trade_value:
            blended = float(result.blended_max_trade_value)
            delta = paid_real - blended
            delta_pct = (delta / blended) * 100 if blended else 0
            direction = "acima" if delta >= 0 else "abaixo"
            success_msg += (
                f"  \nValor pago: **{format_brl(paid_real)}** — "
                f"{abs(delta_pct):.1f}% {direction} do recomendado "
                f"({format_brl(blended)})."
            )
        st.success(success_msg)
