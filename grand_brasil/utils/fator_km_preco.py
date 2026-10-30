"""Fatores de depreciação por quilometragem.

Dois modos de cálculo (decidido pelo parâmetro `km_curve`):

  1) LINEAR (legado) — usado quando `km_curve is None` ou `km_curve.enabled=False`.
     Um único fator por marca × canal (FATOR_KM) é multiplicado pela diferença
     de KM em relação à referência. Simples, mas assume que 10k km "valem o mesmo"
     em qualquer faixa de quilometragem.

  2) PIECEWISE (novo) — usado quando `km_curve.enabled=True` (padrão em config.yaml).
     Uma curva piecewise (empírica, calibrada sobre ~3k vendas reais) descreve
     a depreciação marginal por 10k km *do brand default*. O fator de cada marca
     em FATOR_KM é reinterpretado como um multiplicador relativo ao default
     (ex.: BYD Loja = 0.031 / 0.021 = 1.48× o default). A depreciação total é
     o integral da curva entre km_referencia e km_real, escalado pelo multiplicador.

A regra de `km_referencia` (10k × anos de uso) é idêntica nos dois modos.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Importação só para tipo — evita import circular em runtime.
    from grand_brasil.config import KMCurveConfig


# ── Fatores por marca e canal (% depreciação por 10k KM adicionais) ──────────
# No modo LINEAR: aplicado diretamente ao delta de KM.
# No modo PIECEWISE: usado apenas como multiplicador relativo ao default.

FATOR_KM: dict[str, dict[str, float]] = {
    "Loja": {
        "BYD":        0.031,
        "HYUNDAI":    0.013,
        "BMW":        0.027,
        "BMW AUTOS":  0.027,
        "TOYOTA":     0.022,
        "VOLKSWAGEN": 0.013,
        "JEEP":       0.038,
        "HONDA":      0.013,
        "NISSAN":     0.011,
        "CHERY":      0.036,
        "LAND ROVER": 0.046,
        "CHEVROLET":  0.037,
        "FIAT":       0.036,
        "MITSUBISHI": 0.018,
    },
    "Revenda": {
        "HYUNDAI":    0.006,
        "BMW":        0.018,
        "BMW AUTOS":  0.018,
        "VOLKSWAGEN": 0.006,
        "JEEP":       0.011,
        "CHEVROLET":  0.009,
        "CHERY":      0.015,
        "TOYOTA":     0.001,
        "VOLVO":      0.025,
        "HONDA":      0.007,
        "LAND ROVER": 0.019,
        "RENAULT":    0.012,
        "AUDI":       0.062,
        "NISSAN":     0.021,
        "MITSUBISHI": 0.023,
        "FIAT":       0.021,
    },
}

FATOR_KM_DEFAULT: dict[str, float] = {
    "Loja":    0.021,
    "Revenda": 0.011,
}



# ── Funções públicas ──────────────────────────────────────────────────────────

def km_referencia(year_model: int) -> int:
    """Retorna o KM de referência para o ano do modelo.

    Regra: 10.000 km por ano de idade (ano atual − ano modelo).
    Mínimo de 10.000 km (carros zero km ainda têm referência de 10k).

    Exemplos (ano atual = 2026):
        2025 → 10.000 km
        2024 → 20.000 km
        2023 → 30.000 km
    """
    current_year = datetime.now().year
    anos_de_uso = max(current_year - year_model, 1)
    return anos_de_uso * 10_000


def get_fator_km(brand: str, canal: str) -> float:
    """Retorna o fator de depreciação por 10k KM para uma marca e canal.

    Args:
        brand: Nome da marca (ex: "TOYOTA", "BYD"). Case-insensitive.
        canal: "Loja" ou "Revenda".

    Returns:
        Fator decimal (ex: 0.022 = 2.2% por 10k KM).
    """
    canal_norm = canal.strip().title()
    if canal_norm not in FATOR_KM:
        canal_norm = "Loja"

    marca_upper = brand.upper().strip()
    return FATOR_KM[canal_norm].get(marca_upper, FATOR_KM_DEFAULT[canal_norm])


def ajuste_km_pct(
    brand: str,
    canal: str,
    km_real: int,
    year_model: int,
    km_curve: Optional["KMCurveConfig"] = None,
) -> float:
    """Calcula o percentual de ajuste de preço baseado na KM real vs referência.

    Dois modos:

    * LINEAR (km_curve=None ou km_curve.enabled=False):
        ajuste = −fator_km × (km_real − km_ref) / 10.000

    * PIECEWISE (km_curve.enabled=True):
        ajuste = −multiplicador_da_marca × ∫(curva)[km_ref → km_real] / 100
        onde multiplicador_da_marca = get_fator_km(brand, canal)
                                      / FATOR_KM_DEFAULT[canal].

    Sinais:
        Carro com menos KM que referência → ajuste positivo (vale mais).
        Carro com mais KM que referência  → ajuste negativo (vale menos).

    Args:
        brand: Marca do veículo.
        canal: "Loja" ou "Revenda".
        km_real: KM real do veículo a ser avaliado.
        year_model: Ano modelo (para calcular km_referencia).
        km_curve: Configuração opcional da curva piecewise. Quando presente
            e habilitada, substitui o cálculo linear.

    Returns:
        Percentual de ajuste em fração decimal (ex: 0.031 = +3.1%, -0.062 = -6.2%).
    """
    km_ref = km_referencia(year_model)

    # Modo piecewise
    if km_curve is not None and getattr(km_curve, "enabled", False):
        canal_norm = _canal_norm(canal)
        brand_fator = get_fator_km(brand, canal)
        default_fator = FATOR_KM_DEFAULT[canal_norm]
        multiplier = brand_fator / default_fator if default_fator > 0 else 1.0

        # Integral da curva (em pp) entre km_ref e km_real.
        # _piecewise_integral_pp retorna PP positivos quando km_real > km_ref.
        pp_integral = _piecewise_integral_pp(km_curve.segments, km_ref, km_real)
        # Convertemos pp → fração e aplicamos o sinal (mais KM → ajuste negativo).
        return -multiplier * pp_integral / 100.0

    # Modo linear (legado)
    fator = get_fator_km(brand, canal)
    return -fator * (km_real - km_ref) / 10_000


# ── Internals ────────────────────────────────────────────────────────────────

def _canal_norm(canal: str) -> str:
    canal_norm = canal.strip().title()
    return canal_norm if canal_norm in FATOR_KM else "Loja"


def _piecewise_integral_pp(segments, km_start: int, km_end: int) -> float:
    """Integra a curva piecewise entre km_start e km_end.

    Cada segmento declara um `km_max` (limite superior inclusivo) e
    `pp_per_10k` (depreciação marginal dentro do intervalo). O primeiro
    segmento começa em km=0; o segundo começa em segments[0].km_max; etc.

    Retorno em pontos percentuais (pp). Positivo se km_end > km_start,
    negativo se km_end < km_start (simétrico — depreciação "desfeita" quando
    o carro tem MENOS KM que a referência, valorizando o preço).

    Args:
        segments: lista ordenada de segmentos com atributos `km_max` e `pp_per_10k`.
        km_start: KM inicial (ex: km_referencia).
        km_end: KM final (ex: km_real do veículo).
    """
    if km_end == km_start:
        return 0.0

    # Simetria: calculamos o integral no sentido crescente e aplicamos o sinal.
    sign = 1.0 if km_end > km_start else -1.0
    lo = min(km_start, km_end)
    hi = max(km_start, km_end)

    total_pp = 0.0
    prev_boundary = 0
    for seg in segments:
        seg_lo = prev_boundary
        seg_hi = seg.km_max
        prev_boundary = seg_hi

        # Interseção do segmento com [lo, hi]
        overlap_lo = max(seg_lo, lo)
        overlap_hi = min(seg_hi, hi)
        if overlap_hi <= overlap_lo:
            if seg_lo >= hi:
                break
            continue

        overlap_km = overlap_hi - overlap_lo
        total_pp += (overlap_km / 10_000.0) * seg.pp_per_10k

    return sign * total_pp
