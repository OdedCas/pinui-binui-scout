"""
Phase 2 — Enrichissement : spatial joins + ratio + distance + voisins.

Toutes les opérations métriques se font en EPSG:2039 (ITM).
"""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

import config

log = logging.getLogger(__name__)


def ensure_itm(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        log.warning("CRS manquant — suppose EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs.to_epsg() != config.SRID_ITM:
        gdf = gdf.to_crs(config.SRID_ITM)
    return gdf


def join_parcels(
    buildings: gpd.GeoDataFrame, parcels: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """sjoin centroïde-within-parcelle. Si plusieurs matchs, on garde le 1er."""
    buildings = ensure_itm(buildings).copy()
    parcels = ensure_itm(parcels)
    buildings["emprise_m2"] = buildings.geometry.area.round(1)

    if parcels.empty:
        buildings["gush"] = pd.NA
        buildings["helka"] = pd.NA
        buildings["surface_parcelle_m2"] = pd.NA
        buildings["ratio_parcel_emprise"] = pd.NA
        return buildings

    # Champs probables dans helkot_shuma : GUSH_NUM / PARCEL / SHAPE_Area
    # On normalise les noms en testant les variantes les plus courantes.
    fmap = {}
    for canonical, candidates in {
        "gush":  ["GUSH_NUM", "gush_num", "GUSH", "gush"],
        "helka": ["PARCEL", "parcel", "HELKA", "helka"],
    }.items():
        for c in candidates:
            if c in parcels.columns:
                fmap[canonical] = c
                break

    keep = ["geometry"] + list(fmap.values())
    parcels_norm = parcels[keep].rename(columns={v: k for k, v in fmap.items()}).copy()

    pts = buildings.copy()
    pts.geometry = buildings.geometry.centroid
    pts["_bid"] = range(len(pts))

    joined = gpd.sjoin(
        pts[["_bid", "geometry"]], parcels_norm,
        how="left", predicate="within",
    ).drop_duplicates("_bid")

    # Surface parcelle re-calculée depuis la géométrie
    parcels_norm["surface_parcelle_m2"] = parcels_norm.geometry.area.round(1)
    surface_map = parcels_norm.set_index(parcels_norm.index)["surface_parcelle_m2"]
    joined["surface_parcelle_m2"] = joined["index_right"].map(surface_map)

    buildings = buildings.reset_index(drop=True)
    buildings["_bid"] = range(len(buildings))
    out = buildings.merge(
        joined[["_bid", "gush", "helka", "surface_parcelle_m2"]],
        on="_bid", how="left",
    ).drop(columns="_bid")

    # Filtre outlier : parcelles > PARCEL_OUTLIER_MAX_M2 (Phase 3)
    # = probablement non-résidentiel (école, parc, complex sportif).
    # On nullifie le match plutôt que d'exclure le bâtiment (le bâti peut
    # être résidentiel sur une grande parcelle institutionnelle).
    if hasattr(config, "PARCEL_OUTLIER_MAX_M2"):
        outlier = out["surface_parcelle_m2"] > config.PARCEL_OUTLIER_MAX_M2
        n_outlier = int(outlier.sum())
        if n_outlier:
            log.info("[FILTER] %d parcelles > %d m² nullifiées (outlier non-résidentiel)",
                     n_outlier, config.PARCEL_OUTLIER_MAX_M2)
            out.loc[outlier, ["gush", "helka", "surface_parcelle_m2"]] = pd.NA

    out["ratio_parcel_emprise"] = (
        out["surface_parcelle_m2"] / out["emprise_m2"]
    ).round(2)
    return out


def join_mitchamim(
    buildings: gpd.GeoDataFrame, mitchamim: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Flag chaque bâtiment dont le centroïde tombe dans un mitcham."""
    buildings = ensure_itm(buildings).copy()
    if mitchamim is None or mitchamim.empty:
        buildings["mitcham_name"] = None
        buildings["urban_renewal_active"] = False
        return buildings
    mitchamim = ensure_itm(mitchamim)
    # Chercher la colonne nom — varie selon SHP : `ShemMitcham`, `NAME`, etc.
    name_col = next(
        (c for c in ["ShemMitcham", "Name", "name", "shem_mitcha", "MITCHAM_NA"]
         if c in mitchamim.columns),
        mitchamim.columns[0],
    )
    log.info("[JOIN] mitchamim name col = %s", name_col)

    pts = buildings.copy()
    pts.geometry = buildings.geometry.centroid
    pts["_bid"] = range(len(pts))
    j = gpd.sjoin(
        pts[["_bid", "geometry"]], mitchamim[[name_col, "geometry"]],
        how="left", predicate="within",
    )
    agg = j.groupby("_bid")[name_col].agg(
        lambda s: "; ".join(sorted({str(x) for x in s.dropna()})) or None
    )

    buildings = buildings.reset_index(drop=True)
    buildings["mitcham_name"] = agg.reindex(range(len(buildings))).values
    buildings["urban_renewal_active"] = buildings["mitcham_name"].notna()
    return buildings


def add_distance_to_station(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Distance ITM du centroïde du bâtiment au point station."""
    gdf = ensure_itm(gdf).copy()
    station = gpd.GeoSeries(
        [Point(config.BALFOUR_STATION["lon"], config.BALFOUR_STATION["lat"])],
        crs="EPSG:4326",
    ).to_crs(config.SRID_ITM).iloc[0]
    gdf["dist_station_m"] = gdf.geometry.centroid.distance(station).round(1)
    return gdf


def add_neighbor_count(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Compte des voisins "similaires" dans un buffer de NEIGHBOR_BUFFER_M.
    Similaire = même tranche d'âge (avant 1980) et même tranche d'étages (3-5).
    Calcul fait sur l'ensemble (pas seulement bâtiments filtrés) pour cohérence.
    """
    gdf = ensure_itm(gdf).copy()
    if gdf.empty:
        gdf["neighbors_similar"] = 0
        return gdf

    similar = (
        pd.to_numeric(gdf["year_built"], errors="coerce").lt(config.FILTER_YEAR_MAX)
        & pd.to_numeric(gdf["floors"], errors="coerce").between(
            config.FILTER_FLOORS_MIN, config.FILTER_FLOORS_MAX,
        )
    )
    sim_gdf = gdf[similar]
    if sim_gdf.empty:
        gdf["neighbors_similar"] = 0
        return gdf

    buf = gdf.geometry.buffer(config.NEIGHBOR_BUFFER_M)
    buf_gdf = gpd.GeoDataFrame({"_idx": gdf.index, "geometry": buf}, crs=gdf.crs)
    sim_only = sim_gdf[["geometry"]].copy()
    sim_only["_sim_idx"] = sim_gdf.index
    sj = gpd.sjoin(buf_gdf, sim_only, how="left", predicate="intersects")
    # Compte = nombre de similaires dans le buffer, moins soi-même si je suis similaire
    counts = sj.groupby("_idx")["_sim_idx"].count()
    gdf["neighbors_similar"] = counts.reindex(gdf.index).fillna(0).astype(int)
    self_is_similar = similar.reindex(gdf.index).fillna(False)
    gdf.loc[self_is_similar, "neighbors_similar"] -= 1
    gdf["neighbors_similar"] = gdf["neighbors_similar"].clip(lower=0)
    return gdf


def enrich_all(
    buildings: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
    mitchamim: gpd.GeoDataFrame,
    polygon_wgs: dict | None = None,
) -> gpd.GeoDataFrame:
    """Pipeline complet : join parcels → join mitchamim → distance → voisins → Amidar backfill."""
    log.info("[ENRICH] bâtiments d'entrée : %d", len(buildings))
    g = join_parcels(buildings, parcels)
    g = join_mitchamim(g, mitchamim)
    g = add_distance_to_station(g)
    g = add_neighbor_count(g)

    if polygon_wgs is not None:
        from src.fetch_amidar import enrich_from_amidar
        g = enrich_from_amidar(g, polygon_wgs)

    log.info("[ENRICH] enrichi : %d bâtiments, %d dans mitcham, %d avec parcelle",
             len(g),
             int(g["urban_renewal_active"].sum()),
             int(g["gush"].notna().sum()))
    year_filled  = int(g["year_built"].notna().sum())
    floor_filled = int(g["floors"].notna().sum())
    log.info("[ENRICH] year_built=%d/%d  floors=%d/%d",
             year_filled, len(g), floor_filled, len(g))
    return g
