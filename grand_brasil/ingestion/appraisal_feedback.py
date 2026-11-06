"""Appraisal feedback logger — Fase 3 do plano de calibração.

Registra, em CSV append-only, o "valor real pago" pelo veículo após a
avaliação ser fechada (ou marcada como não-fechada). Isso fecha o loop
para calibração contínua: comparando os valores sugeridos pelo motor
com o que foi efetivamente pago, podemos:

  • Medir bias e MAPE em produção (e não só em backtest histórico).
  • Identificar onde o algoritmo erra (modelo, marca, faixa de KM, idade).
  • Recalibrar `buy_ratio`, margens dinâmicas e tabelas de canal.

Não há dashboard ainda — o objetivo dessa primeira versão é só
acumular dados. Depois de 30-60 dias de uso, esses dados alimentam
um relatório de calibração.

Schema (uma linha por registro):
    timestamp           ISO datetime do registro
    plate               Placa (opcional, pode ser anônima)
    brand               Marca usada para casar com vendas
    model_red           model_red usado pelo motor
    fipe_model_name     Nome completo na FIPE
    year_model          Ano modelo
    km                  KM informado
    fipe_price          Valor FIPE
    fipe_code           Código FIPE
    purpose             auto/loja/revenda
    suggested_blended   Valor único recomendado (blended)
    suggested_buy_ratio Valor sugerido pelo buy_ratio (anchor primário)
    suggested_loja      Valor máximo cenário Loja
    suggested_revenda   Valor máximo cenário Revenda
    p_revenda           Probabilidade de Revenda calculada
    brand_tier          SAFE/NEUTRAL/RISKY
    confidence          Nível de confiança da avaliação
    deal_closed         "fechado" / "nao_fechado"
    channel_real        "Loja" / "Revenda" / vazio
    paid_real           Valor efetivamente pago (R$)
    observation         Texto livre do avaliador
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


FEEDBACK_FIELDS: tuple[str, ...] = (
    "timestamp",
    "plate",
    "brand",
    "model_red",
    "fipe_model_name",
    "year_model",
    "km",
    "fipe_price",
    "fipe_code",
    "purpose",
    "suggested_blended",
    "suggested_buy_ratio",
    "suggested_loja",
    "suggested_revenda",
    "p_revenda",
    "brand_tier",
    "confidence",
    "deal_closed",
    "channel_real",
    "paid_real",
    "observation",
)


@dataclass
class FeedbackEntry:
    """One row of feedback. All optional fields default to empty string in CSV."""

    timestamp: str
    plate: str = ""
    brand: str = ""
    model_red: str = ""
    fipe_model_name: str = ""
    year_model: Optional[int] = None
    km: Optional[int] = None
    fipe_price: Optional[float] = None
    fipe_code: str = ""
    purpose: str = ""
    suggested_blended: Optional[float] = None
    suggested_buy_ratio: Optional[float] = None
    suggested_loja: Optional[float] = None
    suggested_revenda: Optional[float] = None
    p_revenda: Optional[float] = None
    brand_tier: str = ""
    confidence: str = ""
    deal_closed: str = ""           # "fechado" | "nao_fechado"
    channel_real: str = ""          # "Loja" | "Revenda" | ""
    paid_real: Optional[float] = None
    observation: str = ""

    def to_row(self) -> dict[str, str]:
        """Serialise to a dict of strings ready for csv.DictWriter."""
        d = asdict(self)
        return {k: ("" if v is None else str(v)) for k, v in d.items()}


def default_log_path() -> Path:
    """Default location of the feedback CSV (relative to project root)."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / "appraisal_feedback.csv"


def append_feedback(
    entry: FeedbackEntry,
    path: Optional[Path] = None,
) -> Path:
    """Append a feedback entry to the CSV log.

    Creates the file with a header row on first use. Subsequent calls
    only append.

    Args:
        entry: The feedback entry to record.
        path: Override the default log location (used by tests).

    Returns:
        The path that was written to.
    """
    log_path = path or default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    needs_header = not log_path.exists() or log_path.stat().st_size == 0

    # newline="" required by csv on all platforms; UTF-8 with BOM so Excel
    # opens the file correctly with PT-BR characters.
    with log_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(FEEDBACK_FIELDS))
        if needs_header:
            writer.writeheader()
        writer.writerow(entry.to_row())

    logger.info(
        "Appraisal feedback logged: plate=%s deal_closed=%s paid_real=%s",
        entry.plate,
        entry.deal_closed,
        entry.paid_real,
    )
    return log_path


def build_entry_from_suggestion(
    suggestion,
    plate: str,
    deal_closed: str,
    channel_real: str,
    paid_real: Optional[float],
    observation: str,
    fipe_price: Optional[float] = None,
    timestamp: Optional[datetime] = None,
) -> FeedbackEntry:
    """Construct a FeedbackEntry from an AppraisalSuggestion + UI inputs.

    Centralises the field mapping so the UI doesn't reach into the
    suggestion structure directly.
    """
    ts = (timestamp or datetime.now()).isoformat(timespec="seconds")

    def _to_float(v) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, Decimal):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return FeedbackEntry(
        timestamp=ts,
        plate=(plate or "").strip().upper(),
        brand=str(suggestion.brand or ""),
        model_red=str(suggestion.model_red or ""),
        fipe_model_name=str(suggestion.fipe_model_name or ""),
        year_model=suggestion.year_model,
        km=suggestion.km,
        fipe_price=_to_float(fipe_price),
        fipe_code=str(suggestion.fipe_code or ""),
        purpose=str(suggestion.purpose or ""),
        suggested_blended=_to_float(suggestion.blended_max_trade_value),
        suggested_buy_ratio=_to_float(suggestion.buy_ratio_price),
        suggested_loja=_to_float(suggestion.loja_max_trade_value),
        suggested_revenda=_to_float(suggestion.revenda_max_trade_value),
        p_revenda=suggestion.p_revenda,
        brand_tier=str(suggestion.brand_tier or ""),
        confidence=str(suggestion.confidence or ""),
        deal_closed=deal_closed,
        channel_real=channel_real,
        paid_real=paid_real,
        observation=(observation or "").strip(),
    )
