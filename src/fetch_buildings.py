"""
Phase 2 — Ingestion bâti.

Tente GovMap REST en premier (si joignable depuis la machine), bascule
automatiquement sur OSM Overpass si KO.

Schéma canonique de sortie (GeoDataFrame en EPSG:2039) :
    osm_id | name | year_built | floors | type | source | geometry
"""
from __future__ import annotations

import json
import logging
import time

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

import config
from src.http_client import HttpError, get_json

log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------------------
# OSM Overpass (fallback)
# ---------------------------------------------------------------------------
_OVERPASS_TEMPLATE = """
[out:json][timeout:60];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
);
out center geom tags;
"""


def fetch_osm_buildings(polygon_wgs: dict) -> gpd.GeoDataFrame:
    """OSM Overpass — retourne tous building=* dans le bbox du polygone."""
    coords = polygon_wgs["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    s, w, n, e = min(lats), min(lons), max(lats), max(lons)
    q = _OVERPASS_TEMPLATE.format(s=s, w=w, n=n, e=e)
    log.info("[FETCH] OSM Overpass bbox=%s,%s,%s,%s", s, w, n, e)
    r = requests.post(
        OVERPASS_URL,
        data={"data": q},
        timeout=120,
        headers={"User-Agent": config.USER_AGENT},
    )
    r.raise_for_status()
    elements = r.json().get("elements", [])
    log.info("[FETCH] OSM → %d éléments", len(elements))

    records = []
    geoms = []
    for el in elements:
        tags = el.get("tags", {})
        # Géométrie
        if el["type"] == "way" and "geometry" in el:
            ring = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(ring) >= 3 and ring[0] != ring[-1]:
                ring.append(ring[0])
            if len(ring) < 4:
                continue
            geom = shape({"type": "Polygon", "coordinates": [ring]})
        else:
            # relations multipolygones — on prend le center pour l'instant
            c = el.get("center")
            if not c:
                continue
            geom = shape({"type": "Point", "coordinates": [c["lon"], c["lat"]]})

        # Mapping canonique
        year = tags.get("building:start_date") or tags.get("start_date") or tags.get("year_of_construction")
        floors = tags.get("building:levels")
        btype = tags.get("building", "yes")
        addr = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")]))
        records.append({
            "osm_id": f"{el['type']}/{el['id']}",
            "name": tags.get("name"),
            "addr": addr or None,
            "year_built": pd.to_numeric(year, errors="coerce") if year else None,
            "floors":     pd.to_numeric(floors, errors="coerce") if floors else None,
            "type":       btype,
            "source":     "osm",
        })
        geoms.append(geom)

    if not records:
        return gpd.GeoDataFrame(
            columns=["osm_id", "name", "addr", "year_built", "floors",
                     "type", "source", "geometry"],
            geometry="geometry", crs="EPSG:4326",
        )

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    # Garder uniquement les polygones (les Points = relations non résolues)
    gdf = gdf[gdf.geometry.geom_type == "Polygon"].copy()
    log.info("[FETCH] OSM polygones retenus : %d", len(gdf))
    return gdf.to_crs(config.SRID_ITM)


# ---------------------------------------------------------------------------
# GovMap REST (à activer quand joignable)
# ---------------------------------------------------------------------------
_GOVMAP_PROBED = False  # cache d'échec à la 1re tentative — évite 4 retries × N runs


def fetch_govmap_buildings(polygon_wgs: dict) -> gpd.GeoDataFrame | None:
    """Tente GovMap. Cache l'échec après le 1er run pour gagner du temps."""
    global _GOVMAP_PROBED
    if _GOVMAP_PROBED:
        log.info("[FETCH] GovMap déjà sondé KO — skip retry")
        return None
    _GOVMAP_PROBED = True

    for root in config.GOVMAP_REST_CANDIDATES:
        try:
            meta = get_json(root, params={"f": "json"}, subdir="govmap_probe")
        except (HttpError, requests.RequestException) as e:
            log.warning("[FETCH] GovMap %s → KO (%s)", root, str(e)[:80])
            continue
        log.info("[FETCH] GovMap joignable : %s", root)
        # Phase 3 : parcourir folders/services pour trouver la couche bâti
        # officielle. Pour l'instant on retourne None pour basculer sur OSM.
        log.info("[FETCH] GovMap : couche bâti à identifier — fallback OSM pour l'instant")
        return None
    return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def fetch_buildings(polygon_wgs: dict) -> tuple[gpd.GeoDataFrame, str]:
    """Retourne (gdf, source) avec source ∈ {'govmap','osm'}."""
    gdf = fetch_govmap_buildings(polygon_wgs)
    if gdf is not None and len(gdf) > 0:
        return gdf, "govmap"
    log.warning("[FALLBACK] GovMap KO → OSM Overpass")
    return fetch_osm_buildings(polygon_wgs), "osm"
