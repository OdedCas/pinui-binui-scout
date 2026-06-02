"""
Enrichissement Amidar — année de construction + nombre de comptages.

Source : GovMap WFS `govmap:layer_amidarbuildings` (Amidar public housing).
Chaque ligne = un appartement ; on agrège par גוש/חלקה :
  - year_built  = min(שנת_בניה)   → année la plus ancienne = construction initiale
  - floors      = max(מספר_קומות) → nombre de niveaux du bâtiment

Join clé : (gush, helka) — disponible après join_parcels dans le pipeline.
Ne remplace PAS les valeurs déjà renseignées par OSM.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

import config

log = logging.getLogger(__name__)

GOVMAP_WFS = "https://www.govmap.gov.il/api/geoserver/wfs"
LAYER      = "govmap:layer_amidarbuildings"
HEADERS    = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin":     "https://www.govmap.gov.il",
    "Referer":    "https://www.govmap.gov.il/",
}


def _wgs84_bbox_to_mercator(
    polygon_wgs: dict,
    padding_m: float = 500,
) -> tuple[float, float, float, float]:
    """Convert WGS84 polygon bbox → EPSG:3857 (Web Mercator) with padding."""
    g = gpd.GeoSeries([shape(polygon_wgs)], crs="EPSG:4326").to_crs("EPSG:3857")
    minx, miny, maxx, maxy = g.total_bounds
    return minx - padding_m, miny - padding_m, maxx + padding_m, maxy + padding_m


def fetch_amidar_buildings(polygon_wgs: dict) -> pd.DataFrame:
    """
    Fetch Amidar apartment rows inside polygon bbox, aggregate to building level.
    Returns DataFrame with columns: gush, helka, year_built_amidar, floors_amidar.
    Empty DataFrame if WFS unreachable.
    """
    minx, miny, maxx, maxy = _wgs84_bbox_to_mercator(polygon_wgs)
    bbox_str = f"{minx:.0f},{miny:.0f},{maxx:.0f},{maxy:.0f}"

    try:
        r = requests.get(
            GOVMAP_WFS,
            params={
                "service":      "WFS",
                "version":      "2.0.0",
                "request":      "GetFeature",
                "typeNames":    LAYER,
                "outputFormat": "application/json",
                "bbox":         bbox_str,
                "count":        "5000",
            },
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as exc:
        log.warning("[AMIDAR] WFS request failed: %s — skipping enrichment", exc)
        return pd.DataFrame(columns=["gush", "helka", "year_built_amidar", "floors_amidar"])

    if not feats:
        log.info("[AMIDAR] 0 features in bbox")
        return pd.DataFrame(columns=["gush", "helka", "year_built_amidar", "floors_amidar"])

    rows: list[dict[str, Any]] = []
    for f in feats:
        p = f["properties"]
        g = p.get("גוש")
        h = p.get("חלקה")
        y = p.get("שנת_בניה")
        fl = p.get("מספר_קומות")
        if g is None or h is None:
            continue
        try:
            rows.append({"gush": int(g), "helka": int(h),
                         "year_built_amidar": int(y) if y is not None else None,
                         "floors_amidar":     int(fl) if fl is not None else None})
        except (TypeError, ValueError):
            continue

    if not rows:
        log.info("[AMIDAR] no rows with gush/helka")
        return pd.DataFrame(columns=["gush", "helka", "year_built_amidar", "floors_amidar"])

    df = pd.DataFrame(rows)

    # Aggregate per building: earliest year, max floors
    agg = df.groupby(["gush", "helka"]).agg(
        year_built_amidar=("year_built_amidar", "min"),
        floors_amidar=("floors_amidar",     "max"),
    ).reset_index()

    log.info("[AMIDAR] %d buildings fetched (from %d apartment rows)", len(agg), len(rows))
    return agg


def enrich_from_amidar(
    buildings: gpd.GeoDataFrame,
    polygon_wgs: dict,
) -> gpd.GeoDataFrame:
    """
    Backfill year_built and floors from Amidar where OSM has nulls.
    Requires buildings to already have gush/helka columns (from join_parcels).
    """
    amidar = fetch_amidar_buildings(polygon_wgs)
    if amidar.empty:
        return buildings

    buildings = buildings.copy()

    # Normalise gush/helka to int for join
    def _to_int(s: pd.Series) -> pd.Series:
        return pd.to_numeric(s, errors="coerce").astype("Int64")

    buildings["_gush_i"]  = _to_int(buildings["gush"])
    buildings["_helka_i"] = _to_int(buildings["helka"])
    amidar["gush"]  = amidar["gush"].astype("Int64")
    amidar["helka"] = amidar["helka"].astype("Int64")

    merged = buildings.merge(
        amidar.rename(columns={"gush": "_gush_i", "helka": "_helka_i"}),
        on=["_gush_i", "_helka_i"],
        how="left",
    )

    # Backfill only where OSM is missing
    yb = pd.to_numeric(merged.get("year_built"), errors="coerce")
    fl = pd.to_numeric(merged.get("floors"),     errors="coerce")

    filled_year   = yb.isna() & merged["year_built_amidar"].notna()
    filled_floors = fl.isna() & merged["floors_amidar"].notna()

    merged.loc[filled_year,   "year_built"] = merged.loc[filled_year,   "year_built_amidar"]
    merged.loc[filled_floors, "floors"]     = merged.loc[filled_floors, "floors_amidar"]

    log.info(
        "[AMIDAR] backfilled year_built=%d  floors=%d  buildings",
        int(filled_year.sum()), int(filled_floors.sum()),
    )

    return merged.drop(columns=["_gush_i", "_helka_i",
                                 "year_built_amidar", "floors_amidar"])
