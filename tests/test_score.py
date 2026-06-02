"""
Tests unitaires src.score — mode complet (8 tests) + mode dégradé (4 tests).
"""
from __future__ import annotations

import pytest

from src.score import (
    Building,
    score_building,
    score_building_degraded,
    status_from_score,
)


def _b(**overrides) -> Building:
    base = dict(
        year_built=1960, floors=4, ratio_parcel_emprise=5.0,
        dist_station_m=300, neighbors_similar=5,
        urban_renewal_active=False,
    )
    base.update(overrides)
    return Building(**base)


# ===========================================================================
# Mode COMPLET — 8 tests existants
# ===========================================================================
def test_ideal_building_scores_100():
    s, st = score_building(_b())
    assert s == 100.0 and st == "TOP"


def test_in_mitcham_excluded():
    s, st = score_building(_b(urban_renewal_active=True))
    assert s == 0.0 and st == "EXCLUDED"


def test_recent_building_no_year_bonus():
    s, _ = score_building(_b(year_built=1995))
    assert s == 70.0


def test_ratio_capped_at_25():
    s, _ = score_building(_b(ratio_parcel_emprise=10.0))
    assert s == 100.0
    s2, _ = score_building(_b(ratio_parcel_emprise=4.0))
    assert s2 == 95.0


def test_distance_tiers():
    s_close, _ = score_building(_b(dist_station_m=300))
    s_mid,   _ = score_building(_b(dist_station_m=800))
    s_far,   _ = score_building(_b(dist_station_m=1500))
    assert s_close - s_mid == 7
    assert s_mid - s_far == 8


def test_missing_year_does_not_inflate():
    s, _ = score_building(_b(year_built=None))
    assert s == 70.0


def test_missing_all_optional_returns_zero_or_few():
    b = Building(year_built=None, floors=None, ratio_parcel_emprise=None,
                 dist_station_m=None, neighbors_similar=0,
                 urban_renewal_active=False)
    s, _ = score_building(b)
    assert s == 0.0


def test_status_thresholds():
    # mode complet — seuils 80/60/40/1
    assert status_from_score(95, degraded=False) == "TOP"
    assert status_from_score(80, degraded=False) == "TOP"
    assert status_from_score(79, degraded=False) == "INVEST"
    assert status_from_score(60, degraded=False) == "INVEST"
    assert status_from_score(50, degraded=False) == "MARGINAL"
    assert status_from_score(40, degraded=False) == "MARGINAL"
    assert status_from_score(20, degraded=False) == "WEAK"
    assert status_from_score(0,  degraded=False) == "WEAK"
    assert status_from_score(0,  excluded=True)  == "EXCLUDED"


# ===========================================================================
# Mode DÉGRADÉ — nouveaux tests
# ===========================================================================
def test_ideal_degraded_scores_75():
    """Mode dégradé : ratio ignoré → 30+20+15+10 = 75."""
    s, st = score_building_degraded(_b())
    assert s == 75.0
    assert st == "TOP"  # ≥60 dans seuils dégradés


def test_degraded_mitcham_excluded():
    """Exclusion mitcham reste absolue en dégradé."""
    s, st = score_building_degraded(_b(urban_renewal_active=True))
    assert s == 0.0
    assert st == "EXCLUDED"


def test_degraded_ratio_ignored():
    """Ratio quelconque (10, 4, None) → même score en dégradé."""
    s10, _ = score_building_degraded(_b(ratio_parcel_emprise=10.0))
    s4,  _ = score_building_degraded(_b(ratio_parcel_emprise=4.0))
    sn,  _ = score_building_degraded(_b(ratio_parcel_emprise=None))
    assert s10 == s4 == sn == 75.0


def test_degraded_status_thresholds():
    """Seuils dégradés : 60/45/30/1."""
    assert status_from_score(70, degraded=True) == "TOP"
    assert status_from_score(60, degraded=True) == "TOP"
    assert status_from_score(59, degraded=True) == "INVEST"
    assert status_from_score(45, degraded=True) == "INVEST"
    assert status_from_score(44, degraded=True) == "MARGINAL"
    assert status_from_score(30, degraded=True) == "MARGINAL"
    assert status_from_score(29, degraded=True) == "WEAK"
    assert status_from_score(0,  degraded=True) == "WEAK"
    assert status_from_score(0,  excluded=True) == "EXCLUDED"
