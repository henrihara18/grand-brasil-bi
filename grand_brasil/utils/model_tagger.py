"""Normalização de MODELO -> SHORTNAME (família comercial do veículo).

Ordem de resolução:
 1. match exato na base Tag_Modelos.xlsx
 2. família com trim (CRETA, COROLLA, COROLLA CROSS): família + trim conhecido
 3. maior prefixo de token que bata com uma família conhecida da base
 4. heurística: tokens até a primeira especificação técnica

Modelos resolvidos pelos passos 2-4 ficam em `Tagger.novos` para confirmação
e incorporação na próxima versão da base.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_TAG_PATH = Path(__file__).resolve().parent.parent / "assets" / "Tag_Modelos.xlsx"

SPEC_RE = re.compile(
    r"^("
    r"\d[\.,]\d+L?"
    r"|KW|CV|V\d+|\d+V|\d+P"
    r"|TURBO|FLEX|GASOLINA|DIESEL|ELETRICO|ELÉTRICO|HIBRIDO|HÍBRIDO|IFLEX"
    r"|TSI|TGDI|TDI|MPFI|TFSI|CGI|MSI|THP|SCE|MIVEC|VVT-I|VVT-IE|ECOBOOST"
    r"|DM-I|PHEV\d*|MHEV|EV|AWD|4X4|4X2|4WD|DSL|D-4D|16V|8V|12V|24V"
    r")$"
)

TRIM_FAMILIES = ("COROLLA CROSS", "COROLLA", "CRETA")

# Famílias confirmadas que ainda não estão na base Tag_Modelos
EXTRA_FAMILIES = ("YARIS CROSS",)

LETTER_NUM = re.compile(r"^[A-Z]{1,3}$")

BRAND_PREFIX = re.compile(
    r"^(I/)?(ALL NEW |NEW |JEEP |CHEV |CHEVROLET |AUDI |TOYOTA |VW |FIAT |HONDA |"
    r"HYUNDAI |NISSAN |RENAULT |PEUGEOT |CITROEN |FORD |BYD |KIA |MITSUBISHI )+"
)


def clean(s) -> str:
    s = str(s).upper().strip()
    s = s.replace("I/", "")
    s = re.sub(r"\s+", " ", s)
    return s


def strip_brand(m: str) -> str:
    out = BRAND_PREFIX.sub("", m).strip()
    return out if out else m


class Tagger:
    def __init__(self, tag_path: Optional[Path | str] = None):
        tag = pd.read_excel(tag_path or DEFAULT_TAG_PATH, header=1)
        tag = tag[["Modelo", "Shortname"]].dropna()
        tag["Modelo"] = tag["Modelo"].map(clean)
        tag["Shortname"] = tag["Shortname"].astype(str).str.upper().str.strip()
        self.map = dict(zip(tag["Modelo"], tag["Shortname"]))
        self.shortnames = sorted(set(tag["Shortname"]))

        self.trims: dict[str, list[str]] = {}
        for fam in TRIM_FAMILIES:
            ts = {sn[len(fam) + 1:] for sn in self.shortnames if sn.startswith(fam + " ")}
            self.trims[fam] = sorted(ts, key=lambda x: -len(x.split()))

        fams = set()
        for sn in self.shortnames:
            base = sn
            for fam in TRIM_FAMILIES:
                if sn == fam or sn.startswith(fam + " "):
                    base = fam
                    break
            fams.add(base)
        fams.update(EXTRA_FAMILIES)
        self.families = sorted(fams, key=lambda x: -len(x.split()))
        self.novos: dict[str, str] = {}

    def _trim_family(self, m: str) -> Optional[str]:
        for fam in TRIM_FAMILIES:
            if m == fam or m.startswith(fam + " "):
                rest = m[len(fam):].strip()
                for t in self.trims.get(fam, []):
                    if re.search(r"(?:^|\s)" + re.escape(t) + r"(?:\s|$)", rest):
                        return f"{fam} {t}"
                return fam
        return None

    def _prefix_family(self, m: str) -> Optional[str]:
        toks = m.split()
        for fam in self.families:
            ft = fam.split()
            if toks[:len(ft)] == ft:
                return fam
        return None

    def _heuristic(self, m: str) -> str:
        toks = m.split()
        fam: list[str] = []
        for i, t in enumerate(toks):
            if SPEC_RE.match(t):
                break
            if i == 1 and fam and LETTER_NUM.match(fam[0]) and re.match(r"^\d+$", t):
                fam.append(t)
                continue
            if re.match(r"^\d", t):
                break
            fam.append(t)
        if not fam:
            fam = toks[:1]
        return " ".join(fam[:3])

    def resolve(self, modelo) -> str:
        m = clean(modelo)
        if m in self.map:
            return self.map[m]
        b = strip_brand(m)
        r = self._trim_family(b)
        if r is None:
            r = self._prefix_family(b)
        if r is None:
            r = self._heuristic(b)
        self.novos[m] = r
        return r

    def apply(self, series: pd.Series) -> pd.Series:
        return series.map(self.resolve)
