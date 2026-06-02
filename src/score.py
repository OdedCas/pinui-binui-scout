"""
Scoring /100 — mode COMPLET et mode DÉGRADÉ.

Le drapeau `DEGRADED_MODE` est `True` par défaut tant que le cadastre
complet `helkot.zip` (667 MB Mapi) n'est pas chargé localement. Dans ce
mode, le critère `ratio surface_parcelle / emprise_au_sol` (25 pts max)
est INACTIF : faute de cadastre exhaustif à Bat Yam Nord, la surface
parcelle est inconnue et on refuse d'inventer une valeur.

Plafond du score en mode dégradé : 75/100.
Plafond du score en mode complet : 100/100 (inchangé).

Tous les autres critères (année, étages, distance station, voisinage,
exclusion mitcham) sont actifs dans les deux modes.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config


# ---------------------------------------------------------------------------
# Drapeau de mode
# ---------------------------------------------------------------------------
def _detect_degraded() -> bool:
    try:
        from src.fetch_datagov import active_cadastre_path
        return active_cadastre_path() is None
    except Exception:
        return False

DEGRADED_MODE = _detect_degraded()
"""
True tant que `helkot.zip` (cadastre complet Mapi) n'est pas en local.
Flippé à False après dépôt manuel de helkot.zip 667 MB → ratio actif.
"""


# Seuils statuts ajustés au plafond 75 du mode dégradé.
STATUS_THRESHOLDS_DEGRADED = [
    (60, "TOP",      "🟢 Top opportunité",      "🟢 Top opportunity",   "#1a9641"),
    (45, "INVEST",   "🟡 À creuser",            "🟡 To investigate",    "#fdae61"),
    (30, "MARGINAL", "🟠 Marginal",             "🟠 Marginal",          "#f17c46"),
    ( 1, "WEAK",     "⚪ Faible",               "⚪ Weak",              "#bdbdbd"),
    ( 0, "EXCLUDED", "🔴 Exclu (Pinui actif)",  "🔴 Excluded",          "#d7191c"),
]


@dataclass
class Building:
    """Vue minimale d'un bâtiment pour le scoring."""
    year_built: int | None
    floors: int | None
    ratio_parcel_emprise: float | None
    dist_station_m: float | None
    neighbors_similar: int
    urban_renewal_active: bool


# ---------------------------------------------------------------------------
# Helpers statut
# ---------------------------------------------------------------------------
def status_from_score(score: float, *, excluded: bool = False,
                       degraded: bool | None = None) -> str:
    if excluded:
        return "EXCLUDED"
    if degraded is None:
        degraded = DEGRADED_MODE
    thresholds = STATUS_THRESHOLDS_DEGRADED if degraded else config.STATUS_THRESHOLDS
    for threshold, code, *_ in thresholds:
        if code == "EXCLUDED":
            continue
        if score >= threshold:
            return code
    return "WEAK"


# ---------------------------------------------------------------------------
# Scoring — mode COMPLET (avec ratio actif)
# ---------------------------------------------------------------------------
def score_building(b: Building) -> tuple[float, str]:
    """Mode complet — ratio parcelle/emprise actif (25 pts max). Plafond 100."""
    if b.urban_renewal_active:
        return 0.0, "EXCLUDED"
    w = config.SCORE_WEIGHTS
    s = 0.0
    if b.year_built is not None and b.year_built < config.FILTER_YEAR_MAX:
        s += w["old_building"]
    if b.floors is not None and config.FILTER_FLOORS_MIN <= b.floors <= config.FILTER_FLOORS_MAX:
        s += w["floors_range"]
    if b.ratio_parcel_emprise is not None and b.ratio_parcel_emprise > 0:
        s += min(w["ratio_cap"], b.ratio_parcel_emprise * w["ratio_mult"])
    if b.dist_station_m is not None:
        if b.dist_station_m < config.DIST_CLOSE_M:
            s += w["dist_close"]
        elif b.dist_station_m < config.DIST_MID_M:
            s += w["dist_mid"]
    if b.neighbors_similar >= config.NEIGHBOR_MIN_COUNT:
        s += w["neighbors"]
    s = min(100.0, s)
    return float(s), status_from_score(s, degraded=False)


# ---------------------------------------------------------------------------
# Scoring — mode DÉGRADÉ (ratio désactivé)
# ---------------------------------------------------------------------------
def score_building_degraded(b: Building) -> tuple[float, str]:
    """
    Mode dégradé — `ratio_parcel_emprise` IGNORÉ.
    Plafond effectif : 30 + 20 + 15 + 10 = 75/100.
    """
    if b.urban_renewal_active:
        return 0.0, "EXCLUDED"
    w = config.SCORE_WEIGHTS
    s = 0.0
    if b.year_built is not None and b.year_built < config.FILTER_YEAR_MAX:
        s += w["old_building"]
    if b.floors is not None and config.FILTER_FLOORS_MIN <= b.floors <= config.FILTER_FLOORS_MAX:
        s += w["floors_range"]
    # ratio_parcel_emprise volontairement ignoré
    if b.dist_station_m is not None:
        if b.dist_station_m < config.DIST_CLOSE_M:
            s += w["dist_close"]
        elif b.dist_station_m < config.DIST_MID_M:
            s += w["dist_mid"]
    if b.neighbors_similar >= config.NEIGHBOR_MIN_COUNT:
        s += w["neighbors"]
    s = min(75.0, s)
    return float(s), status_from_score(s, degraded=True)


# ---------------------------------------------------------------------------
# Application au DataFrame
# ---------------------------------------------------------------------------
def score_dataframe(gdf) -> pd.DataFrame:
    """Dispatche sur le scoring actif selon `DEGRADED_MODE`."""
    fn = score_building_degraded if DEGRADED_MODE else score_building
    scores, statuses = [], []
    for _, row in gdf.iterrows():
        b = Building(
            year_built=_safe_int(row.get("year_built")),
            floors=_safe_int(row.get("floors")),
            ratio_parcel_emprise=_safe_float(row.get("ratio_parcel_emprise")),
            dist_station_m=_safe_float(row.get("dist_station_m")),
            neighbors_similar=int(row.get("neighbors_similar", 0) or 0),
            urban_renewal_active=bool(row.get("urban_renewal_active", False)),
        )
        s, st = fn(b)
        scores.append(s)
        statuses.append(st)
    gdf = gdf.copy()
    gdf["score"] = scores
    gdf["status"] = statuses
    gdf["mode"] = "degraded" if DEGRADED_MODE else "full"
    return gdf


def _safe_int(v) -> int | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _safe_float(v) -> float | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
