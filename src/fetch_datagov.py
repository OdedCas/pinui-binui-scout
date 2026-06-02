"""
Phase 2 — Ingestion data.gov.il.

Deux régimes, suite au diagnostic IAP de Google Cloud Platform sur
`e.data.gov.il` :

  - Catégorie A — CKAN `datastore_search` (sans IAP, automatique)
       → urban_renewal_mitchamim (datastore_active=true)

  - Catégorie B — Bulks SHP sur `e.data.gov.il` (IAP-protected)
       → helkot_shuma.zip, officiallydeclaredprojects.zip
       → téléchargement humain unique via MANUAL_DOWNLOADS.md
       → fichiers déposés dans data/raw/datagov_bulk/

Aucune tentative de contournement OAuth scripté. L'IAP est par design,
on respecte.
"""
from __future__ import annotations

import logging
import tempfile
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

import config

log = logging.getLogger(__name__)

BULK_DIR = config.DATA_RAW / "datagov_bulk"
BULK_DIR.mkdir(parents=True, exist_ok=True)

CKAN_API = config.DATA_GOV_IL_API


# ============================================================================
# Catégorie A — datastore_search (CKAN JSON, sans IAP)
# ============================================================================
def fetch_mitchamim_bat_yam() -> pd.DataFrame:
    """
    Récupère les ~37 mitchamim Bat Yam via `datastore_search` paginé.
    Bypasse complètement le CSV bulk IAP-protected.
    """
    resource_id = config.DATAGOV_DATASETS["urban_renewal_mitchamim"]["resource_id"]
    log.info("[FETCH] datastore_search resource=%s yeshuv=בת ים", resource_id)
    all_records: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        r = requests.get(
            f"{CKAN_API}/datastore_search",
            params={
                "resource_id": resource_id,
                "q":           "בת ים",
                "limit":       page_size,
                "offset":      offset,
            },
            headers={"User-Agent": config.USER_AGENT},
            timeout=30,
        )
        r.raise_for_status()
        result = r.json().get("result", {})
        records = result.get("records", [])
        if not records:
            break
        all_records.extend(records)
        total = result.get("total", 0)
        log.info("[FETCH] +%d (offset=%d / total=%d)", len(records), offset, total)
        offset += page_size
        if offset >= total:
            break

    # Filtre Yeshuv strict (q= est un fulltext qui peut matcher d'autres champs)
    df = pd.DataFrame(all_records)
    if "Yeshuv" in df.columns:
        df = df[df["Yeshuv"].astype(str).str.strip() == "בת ים"].copy()
    log.info("[FETCH] %d mitchamim Bat Yam retenus", len(df))

    out = config.DATA_PROC / "mitchamim_batyam.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    log.info("[WRITE] %s", out)
    return df


# ============================================================================
# Catégorie B — bulks IAP-protected, dépôt manuel
# ============================================================================
class BulkUnavailable(RuntimeError):
    """Levé quand un bulk Cat B n'est pas en local et doit être téléchargé."""

    def __init__(self, filename: str, instructions: str):
        super().__init__(f"Bulk manquant : {filename}\n\n{instructions}")
        self.filename = filename


MANUAL_DOWNLOADS = {
    # Cadastre national COMPLET (zones régularisées) — source primaire
    "helkot.zip": {
        "dataset_page":  "https://data.gov.il/dataset/shape",
        "download_url":  "https://e.data.gov.il/dataset/dff8a168-af6c-4e0f-bbe3-c4bd3646084c/"
                         "resource/c68b4df6-c809-4bb5-a546-61fa1528fed5/download/helkot.zip",
        "size_bytes":    667_592_021,
        "min_size":      500_000_000,
        "format":        "ZIP (SHP cadastre national, ~3-5M parcelles)",
        "ttl_days":      60,    # mensuel mais on tolère 2 mois
    },
    # Cadastre partiel — zones non-régularisées uniquement. Conservé en
    # fallback documentaire. Couvre densément Holon/Petah Tikva mais
    # quasi-vide à Bat Yam Nord. Ne pas utiliser comme source primaire.
    "helkot-shuma.zip": {
        "dataset_page":  "https://data.gov.il/dataset/7a2d683b-10fd-4f39-ba91-efa9db23c663",
        "download_url":  "https://e.data.gov.il/dataset/7a2d683b-10fd-4f39-ba91-efa9db23c663/"
                         "resource/a03a4d39-29d6-4245-b07c-2554d4eab17c/download/helkot-shuma.zip",
        "size_bytes":    11_504_999,
        "min_size":      1_000_000,
        "format":        "ZIP (SHP cadastre partiel zones non-régularisées) — FALLBACK",
        "ttl_days":      30,
    },
    "officiallydeclaredprojects.zip": {
        "dataset_page":  "https://data.gov.il/dataset/1de95a22-576e-4e9c-b7c4-59db01d85290",
        "download_url":  "https://e.data.gov.il/dataset/1de95a22-576e-4e9c-b7c4-59db01d85290/"
                         "resource/ceb7bbb0-e2db-4e87-8a6c-0a250f5de001/download/"
                         "officiallydeclaredprojects.zip",
        "size_bytes":    2_569_754,
        "min_size":      500_000,
        "format":        "ZIP (Shapefile polygones mitchamim)",
        "ttl_days":      30,
    },
}

# Ordre de préférence pour le cadastre (cascade) :
CADASTRE_PRIORITY = ["helkot.zip", "helkot-shuma.zip"]

# Signature ZIP officielle : "PK\x03\x04" (local file header) ou "PK\x05\x06"
# (empty zip, rare). On accepte les deux.
ZIP_MAGIC_BYTES = (b"PK\x03\x04", b"PK\x05\x06")


def _is_valid_zip(path: Path, min_size: int) -> tuple[bool, str]:
    """
    Garde-fou complet anti-page IAP :
      - le fichier existe
      - taille > min_size (un HTML d'IAP fait ~3-50 KB)
      - les 4 premiers octets sont une signature ZIP valide

    Retourne (valid, reason). reason est vide si valid=True.
    """
    if not path.exists():
        return False, "fichier absent"
    size = path.stat().st_size
    if size < min_size:
        return False, f"taille {size:,} octets < seuil {min_size:,} (probablement HTML IAP)"
    with open(path, "rb") as fp:
        head = fp.read(4)
    if head not in ZIP_MAGIC_BYTES:
        return False, f"magic bytes inattendus {head!r} (attendu PK\\x03\\x04)"
    return True, ""


def preflight_bulks() -> list[tuple[str, str]]:
    """
    Vérifie les bulks Cat B nécessaires.
    Un seul fichier cadastral suffit (cascade CADASTRE_PRIORITY).
    `officiallydeclaredprojects.zip` est requis.
    Retourne la liste [(filename, reason)] des manquants effectifs.
    """
    missing: list[tuple[str, str]] = []

    # Au moins UN cadastre valide
    cadastre_ok = False
    cadastre_reasons = []
    for filename in CADASTRE_PRIORITY:
        meta = MANUAL_DOWNLOADS[filename]
        ok, reason = _is_valid_zip(BULK_DIR / filename, meta["min_size"])
        if ok:
            cadastre_ok = True
            break
        cadastre_reasons.append(f"{filename}: {reason}")
    if not cadastre_ok:
        missing.append(("cadastre (helkot.zip OU helkot-shuma.zip)",
                        " ; ".join(cadastre_reasons)))

    # Polygones mitchamim — toujours requis
    fn = "officiallydeclaredprojects.zip"
    meta = MANUAL_DOWNLOADS[fn]
    ok, reason = _is_valid_zip(BULK_DIR / fn, meta["min_size"])
    if not ok:
        missing.append((fn, reason))

    return missing


def active_cadastre_path() -> Path | None:
    """Retourne le 1er ZIP cadastral valide selon CADASTRE_PRIORITY, sinon None."""
    for filename in CADASTRE_PRIORITY:
        meta = MANUAL_DOWNLOADS[filename]
        ok, _ = _is_valid_zip(BULK_DIR / filename, meta["min_size"])
        if ok:
            return BULK_DIR / filename
    return None


def ensure_bulk_available(filename: str) -> Path:
    """
    Vérifie qu'un bulk Cat B est présent et valide.
    Lève `BulkUnavailable` avec instructions de dépôt manuel sinon.

    Validation : existence + taille > min_size + magic bytes ZIP `PK\\x03\\x04`.
    """
    meta = MANUAL_DOWNLOADS.get(filename)
    if not meta:
        raise ValueError(f"Bulk inconnu : {filename}")
    path = BULK_DIR / filename

    ok, reason = _is_valid_zip(path, meta["min_size"])
    if ok:
        size_mb = path.stat().st_size / 1e6
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > meta["ttl_days"]:
            log.warning("[BULK] %s : %.0f jours, > TTL %d j (refresh recommandé)",
                        filename, age_days, meta["ttl_days"])
        else:
            log.info("[BULK] ✓ %s (%.1f MB, %.0f j old)",
                     filename, size_mb, age_days)
        return path

    instructions = (
        f"\nLe bulk `{filename}` n'est pas disponible localement.\n"
        f"Raison : {reason}\n\n"
        f"Téléchargement manuel (Google IAP) :\n"
        f"  1. Ouvre {meta['dataset_page']}\n"
        f"  2. Connecte-toi à Google si demandé\n"
        f"  3. Clique sur le bouton 'Download' du resource `{filename}`\n"
        f"  4. Dépose le fichier exact dans : {path}\n"
        f"  5. Vérifie la taille (attendu ~{meta['size_bytes']/1e6:.1f} MB)\n"
        f"  6. Re-lance le pipeline.\n"
        f"\nFormat : {meta['format']}\n"
        f"Refresh recommandé : {meta['ttl_days']} jours."
    )
    raise BulkUnavailable(filename, instructions)


def _read_shp_from_zip(
    zip_path: Path, bbox_itm: tuple[float, float, float, float] | None = None
) -> gpd.GeoDataFrame:
    """
    Lit un SHP depuis un ZIP.
    Si bbox_itm fourni (xmin,ymin,xmax,ymax en EPSG:2039) → filtre natif
    via GDAL `/vsizip/` + pyogrio, charge SEULEMENT les features dans la
    bbox. Mémoire-friendly pour gros ZIPs (667 MB→~5 MB RAM).
    """
    # Inspecter le ZIP sans extraire — récupère le nom du .shp interne
    with zipfile.ZipFile(zip_path) as zf:
        shp_internal = next(
            (n for n in zf.namelist() if n.lower().endswith(".shp")),
            None,
        )
    if shp_internal is None:
        raise RuntimeError(f"Aucun .shp dans {zip_path}")
    log.info("[PARSE] SHP interne : %s", shp_internal)

    # Chemin GDAL virtual : /vsizip/<zip>/<internal.shp>
    vsi_path = f"/vsizip/{zip_path.as_posix()}/{shp_internal}"

    if bbox_itm is not None:
        log.info("[PARSE] lecture filtrée bbox=%s", bbox_itm)
        gdf = gpd.read_file(vsi_path, bbox=bbox_itm)
    else:
        log.info("[PARSE] lecture complète (sans bbox)")
        gdf = gpd.read_file(vsi_path)

    if gdf.crs is None:
        log.warning("SHP sans CRS — suppose EPSG:2039 (ITM)")
        gdf.set_crs(2039, inplace=True)
    log.info("[PARSE] %d features, CRS=%s, columns=%s",
             len(gdf), gdf.crs, list(gdf.columns))
    return gdf


def _clip_to_polygon(
    gdf: gpd.GeoDataFrame, polygon_wgs: dict
) -> gpd.GeoDataFrame:
    study = gpd.GeoSeries(
        [shape(polygon_wgs)], crs="EPSG:4326"
    ).to_crs(gdf.crs).iloc[0]
    return gdf[gdf.geometry.intersects(study)].copy()


def _polygon_bbox_itm(
    polygon_wgs: dict, padding_m: float = 500,
) -> tuple[float, float, float, float]:
    """Bbox du polygone d'étude en EPSG:2039 + padding (mètres)."""
    g = gpd.GeoSeries([shape(polygon_wgs)], crs="EPSG:4326").to_crs(2039)
    minx, miny, maxx, maxy = g.total_bounds
    return (minx - padding_m, miny - padding_m,
            maxx + padding_m, maxy + padding_m)


def fetch_cadastre(polygon_wgs: dict) -> gpd.GeoDataFrame:
    """
    Cadastre Mapi (cascade) — `helkot.zip` complet en priorité,
    `helkot-shuma.zip` partiel en fallback documentaire.

    Lecture mémoire-friendly via bbox filter natif `/vsizip/` :
      - 667 MB ZIP → ~5-10 MB RAM en lecture filtrée
      - bbox = polygone d'étude reprojeté ITM + padding 500m
    """
    zp = active_cadastre_path()
    if zp is None:
        # Lève BulkUnavailable explicitement sur la source primaire
        ensure_bulk_available("helkot.zip")
    source = zp.name
    log.info("[CADASTRE] source active : %s", source)

    bbox = _polygon_bbox_itm(polygon_wgs, padding_m=500)
    gdf = _read_shp_from_zip(zp, bbox_itm=bbox)
    if gdf.empty:
        log.warning("[CADASTRE] 0 parcelle dans la bbox ITM %s", bbox)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2039")
    # Clip plus fin au polygone exact
    clipped = _clip_to_polygon(gdf, polygon_wgs)
    log.info("[CADASTRE] %d parcelles clippées au polygone (depuis %d en bbox)",
             len(clipped), len(gdf))
    clipped = clipped.to_crs(config.SRID_ITM)
    clipped["surface_m2"] = clipped.geometry.area.round(1)
    return clipped


# Alias rétro-compat
fetch_helkot_shuma = fetch_cadastre
fetch_helkot       = fetch_cadastre


def fetch_urban_renewal_polygons(polygon_wgs: dict) -> gpd.GeoDataFrame:
    """Polygones des mitchamim déclarés — bbox filter natif aussi."""
    zp = ensure_bulk_available("officiallydeclaredprojects.zip")
    bbox = _polygon_bbox_itm(polygon_wgs, padding_m=500)
    gdf = _read_shp_from_zip(zp, bbox_itm=bbox)
    clipped = _clip_to_polygon(gdf, polygon_wgs)
    log.info("[MITCHAMIM] %d dans la zone (depuis %d en bbox)",
             len(clipped), len(gdf))
    return clipped.to_crs(config.SRID_ITM)
