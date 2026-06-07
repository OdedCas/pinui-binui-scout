"""
Génère outputs/ramat_yosef_nord_premium.html — carte interactive premium
standalone (Leaflet + CartoDB Dark Matter, dark glassmorphism, 1385 markers
en canvas, panneau slide-in, bilingue FR/EN).

v2 (Day 2 UX/UI) :
  - Gush/Helka cast en int (pas de .0) + bloc GROS dans panel + bouton copier
  - Recherche autocomplete sidebar (Gush, Helka, Gush/Helka, adresse)
  - Panel "TOP CANDIDATS" groupé par Gush + boutons copier-tous / tableau
  - Modal tableau complet : tri, filtre, export CSV, export liste Gush/Helka
  - Note explicative honnête sous la légende (year_built absent)
  - Toast confirmation pour les actions de copie

Seuils de scoring INCHANGÉS — TOP ≥75 reste la grille métier de référence.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

import config
from src.fetch_datagov import fetch_urban_renewal_polygons

log = logging.getLogger(__name__)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    if s in ("nan", "None", "NaT", "<NA>", ""):
        return None
    return s


def _clean_gh(v):
    """Cast Gush/Helka en int-string propre. 7147.0 -> "7147"."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s in ("nan", "None", "NaT", "<NA>", ""):
        return None
    try:
        return str(int(float(s)))
    except (TypeError, ValueError):
        return s


def _to_num(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    except (TypeError, ValueError):
        return None


def build_buildings_data(gdf: gpd.GeoDataFrame) -> list[dict]:
    g_itm = gdf.to_crs("EPSG:2039")
    centroids_itm = g_itm.geometry.centroid
    centroids_wgs = gpd.GeoSeries(centroids_itm, crs="EPSG:2039").to_crs("EPSG:4326")

    out = []
    for i, b in gdf.reset_index(drop=True).iterrows():
        c = centroids_wgs.iloc[i]
        out.append({
            "id":      str(b.get("osm_id", f"b{i}")),
            "lat":     round(float(c.y), 6),
            "lon":     round(float(c.x), 6),
            "addr":    _clean(b.get("addr")),
            "gush":    _clean_gh(b.get("gush")),
            "helka":   _clean_gh(b.get("helka")),
            "floors":  _to_num(b.get("floors")),
            "year_built": _to_num(b.get("year_built")),
            "surface_parcelle_m2": _to_num(b.get("surface_parcelle_m2")),
            "emprise_m2": _to_num(b.get("emprise_m2")),
            "ratio":   _to_num(b.get("ratio_parcel_emprise")),
            "dist":    _to_num(b.get("dist_station_m")),
            "neighbors": int(b.get("neighbors_similar", 0) or 0),
            "score":   _to_num(b.get("score")) or 0,
            "status":  str(b.get("status", "WEAK")),
            "mitcham": _clean(b.get("mitcham_name")),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    # Top candidat = score > 30 hors mitcham (et top 25 si moins de 25 au-dessus seuil)
    hors_mitcham = [b for b in out if b["status"] != "EXCLUDED"]
    above_30 = [b for b in hors_mitcham if (b["score"] or 0) > 30]
    if len(above_30) >= 25:
        top_ids = {b["id"] for b in above_30}
    else:
        top_ids = {b["id"] for b in hors_mitcham[:25]}
    for b in out:
        b["topCandidate"] = b["id"] in top_ids
        b["top25"] = b["topCandidate"]   # alias rétro-compat
    return out


# Translittérations FR/EN des 37 mitchamim Bat Yam (clé = ShemMitcha hébreu).
# Mapping manuel — règle "zéro fictif" : ne couvre que les noms réellement
# observés. Si un mitcham non listé apparaît, fallback sur ShemMitcha brut.
MITCHAM_TRANSLIT = {
    "חנה סנש":              {"fr": "Hannah Senesh",            "en": "Hannah Senesh"},
    "אילת":                 {"fr": "Eilat",                    "en": "Eilat"},
    "מבצע סיני 25-27":       {"fr": "Opération Sinaï 25-27",    "en": "Operation Sinai 25-27"},
    "בלפור 81":             {"fr": "Balfour 81",               "en": "Balfour 81"},
    "העצמאות בלפור":         {"fr": "Atzma'ut × Balfour",       "en": "Atzma'ut × Balfour"},
    "מתחם התחייה - רהב":     {"fr": "Tehiya — Rahav",           "en": "Tehiya — Rahav"},
    "המבואה הצפונית":        {"fr": "Vestibule Nord",           "en": "Northern Vestibule"},
    "שפרבר":                {"fr": "Schperber",                "en": "Schperber"},
    "הרצל 59-61":            {"fr": "Herzl 59-61",              "en": "Herzl 59-61"},
    "יוספטל מזרח":           {"fr": "Yoseftal Est",             "en": "Yoseftal East"},
    "רוטשילד":              {"fr": "Rothschild",               "en": "Rothschild"},
    "הרב לוי ניסנבוים":      {"fr": "Rav Levi Nissenbaum",      "en": "Rav Levi Nissenbaum"},
    "שינדלר":               {"fr": "Schindler",                "en": "Schindler"},
    'כ"ט בנובמבר (מאוחד)':   {"fr": "29 Novembre (unifié)",     "en": "29 November (Unified)"},
    "הרב מימון - אנה פרנק":   {"fr": "Rav Maimon — Anne Frank",  "en": "Rav Maimon — Anne Frank"},
    "סוקולוב – ירושלים":     {"fr": "Sokolov — Jérusalem",      "en": "Sokolov — Jerusalem"},
    "מגדל הים (רוטשילד 2)":  {"fr": "Migdal HaYam (Rothschild 2)","en": "Migdal HaYam (Rothschild 2)"},
    "השקמה":                {"fr": "HaShikma",                 "en": "HaShikma"},
    "כצנלסון 61-57":         {"fr": "Katznelson 57-61",         "en": "Katznelson 57-61"},
    "החשמונאים/יוספטל":      {"fr": "Hashmonaim / Yoseftal",    "en": "Hashmonaim / Yoseftal"},
    "השבטים":               {"fr": "HaShvatim",                "en": "HaShvatim"},
    "חלמית":                {"fr": "Halamit",                  "en": "Halamit"},
    "דליה":                 {"fr": "Dalia",                    "en": "Dalia"},
    "מצדה":                 {"fr": "Masada",                   "en": "Masada"},
    "קוקיס":                {"fr": "Kokis",                    "en": "Kokis"},
    "הנביאים":              {"fr": "HaNeviim",                 "en": "HaNeviim"},
    "שער צפון העיר":         {"fr": "Porte Nord de la Ville",   "en": "Northern City Gate"},
    "הגיבורים":             {"fr": "HaGiborim",                "en": "HaGiborim"},
    'ביל"ו':                {"fr": "Bilu",                     "en": "Bilu"},
    "שער יוספטל":            {"fr": "Porte Yoseftal",           "en": "Yoseftal Gate"},
    "מטרו דרום":             {"fr": "Métro Sud",                "en": "Metro South"},
    "איילון-יוספטל":         {"fr": "Ayalon — Yoseftal",        "en": "Ayalon — Yoseftal"},
    "בלפור":                {"fr": "Balfour",                  "en": "Balfour"},
    "כצנלסון":              {"fr": "Katznelson",               "en": "Katznelson"},
    "הרב קוקיס":             {"fr": "Rav Kokis",                "en": "Rav Kokis"},
    "הרב מימון - ניסנבוים":   {"fr": "Rav Maimon — Nissenbaum",  "en": "Rav Maimon — Nissenbaum"},
    "הרב מימון":             {"fr": "Rav Maimon",               "en": "Rav Maimon"},
}

TEUR_TRANSLATIONS = {
    "פינוי בינוי":   {"fr": "Pinui-Binui",          "en": "Pinui-Binui"},
    "עיבוי":         {"fr": "Densification (Iboui)", "en": "Densification (Iboui)"},
    'תמ"א 38':       {"fr": "TAMA 38",               "en": "TAMA 38"},
    "תמא 38":        {"fr": "TAMA 38",               "en": "TAMA 38"},
    "מיסוי":         {"fr": "Filière taxation",      "en": "Tax track"},
    "רשויות":        {"fr": "Filière autorités",     "en": "Authorities track"},
    "טרם הוכרז":     {"fr": "Pas encore déclaré",    "en": "Not yet declared"},
}


def _translit_mitcham(shem_he):
    if not shem_he:
        return {"fr": "—", "en": "—"}
    t = MITCHAM_TRANSLIT.get(str(shem_he).strip())
    if t:
        return t
    # Fallback : nom hébreu brut (zéro invention)
    return {"fr": shem_he, "en": shem_he}


def _translit_teur(teur_he):
    if not teur_he or str(teur_he).strip() in ("nan", "None", ""):
        return None
    t = TEUR_TRANSLATIONS.get(str(teur_he).strip())
    return t  # None si pas de mapping


def _mitcham_id(mispar_proj):
    """Normalise MisparProj en string-int : 8001244.0 → '8001244'."""
    if mispar_proj is None:
        return None
    try:
        return str(int(float(mispar_proj)))
    except (TypeError, ValueError):
        return str(mispar_proj).strip() or None


def build_mitchamim_geojson(study_polygon_wgs: dict, buildings_data=None) -> dict:
    gdf = fetch_urban_renewal_polygons(study_polygon_wgs).to_crs("EPSG:4326")

    # Pré-compte des bâtiments dedans chaque mitcham (via mitcham_name)
    counts_by_id = {}
    if buildings_data:
        for b in buildings_data:
            mid = _mitcham_id(b.get("mitcham"))
            if mid:
                counts_by_id[mid] = counts_by_id.get(mid, 0) + 1

    features = []
    for _, m in gdf.iterrows():
        props = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            v = m[col]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                props[col] = None
            elif hasattr(v, "isoformat"):
                props[col] = v.isoformat()
            elif isinstance(v, (int, float, str, bool)):
                props[col] = v
            else:
                props[col] = str(v)

        # Enrichissements user-facing
        mid = _mitcham_id(props.get("MisparProj"))
        props["id_norm"] = mid

        shem_he = props.get("ShemMitcha")
        translit = _translit_mitcham(shem_he)
        props["name_fr"] = translit["fr"]
        props["name_en"] = translit["en"]
        props["name_he"] = shem_he

        maslul  = _translit_teur(props.get("TeurMaslul"))
        sug_mas = _translit_teur(props.get("TeurSugMas"))
        props["maslul_fr"]  = maslul["fr"]  if maslul  else None
        props["maslul_en"]  = maslul["en"]  if maslul  else None
        props["sug_mas_fr"] = sug_mas["fr"] if sug_mas else None
        props["sug_mas_en"] = sug_mas["en"] if sug_mas else None

        props["buildings_inside"] = counts_by_id.get(mid, 0) if mid else 0

        # Lien Mavat : utiliser Kishur direct si présent et valide, sinon None
        kishur = props.get("Kishur")
        if kishur and str(kishur).strip() not in ("nan", "None", "") and "mavat.iplan.gov.il" in str(kishur):
            props["mavat_url"] = str(kishur).strip()
        else:
            props["mavat_url"] = None

        # Centroïde stocké pour positionner label permanent côté JS
        c = m.geometry.centroid
        props["centroid_lat"] = round(float(c.y), 6)
        props["centroid_lon"] = round(float(c.x), 6)

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": mapping(m.geometry),
        })
    return {"type": "FeatureCollection", "features": features}


TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BatYam Pinui Scout — Ramat Yosef Nord</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css">
<style>
:root {
  --bg: #0A0E1A;
  --surface: rgba(19, 25, 41, 0.92);
  --surface-solid: #131929;
  --surface-2: rgba(31, 42, 68, 0.4);
  --border: #1F2A44;
  --text: #FFFFFF;
  --text-muted: #8B9BB4;
  --accent: #00D4FF;
  --accent2: #00FF88;
  --status-top: #00FF88;
  --status-invest: #FFD700;
  --status-marginal: #FF8C42;
  --status-weak: #6B7280;
  --status-excluded: #EF4444;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; width: 100%; overflow: hidden; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  font-size: 14px; line-height: 1.5;
}
#map { position: absolute; inset: 0; z-index: 1; background: var(--bg); }

/* ========== Header ========== */
header {
  position: fixed; top: 0; left: 0; right: 0; height: 60px;
  background: var(--surface);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  z-index: 1000;
  display: flex; align-items: center; padding: 0 20px; gap: 16px;
  transition: opacity 300ms ease;
}
.logo {
  width: 32px; height: 32px;
  background: linear-gradient(135deg, var(--accent) 0%, #0099CC 100%);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700; font-size: 13px;
  color: #000;
  box-shadow: 0 0 12px rgba(0,212,255,0.3);
}
.tool-name { font-size: 16px; font-weight: 600; letter-spacing: -0.2px; }
.tool-name span { color: var(--text-muted); font-weight: 400; margin-left: 4px; }
header .spacer { flex: 1; }
.lang-toggle {
  display: flex; background: rgba(0,0,0,0.4);
  border: 1px solid var(--border); border-radius: 6px; padding: 2px;
}
.lang-toggle button {
  background: none; border: none; color: var(--text-muted);
  font-size: 12px; font-weight: 600; padding: 6px 12px;
  cursor: pointer; border-radius: 4px; transition: all 200ms;
  font-family: inherit;
}
.lang-toggle button.active { background: var(--accent); color: #000; }
.btn-icon {
  background: rgba(0,0,0,0.3); border: 1px solid var(--border);
  color: var(--text); font-size: 13px; padding: 8px 14px;
  border-radius: 6px; cursor: pointer; transition: all 200ms;
  display: flex; align-items: center; gap: 6px;
  font-family: inherit;
}
.btn-icon:hover {
  background: var(--accent); color: #000; border-color: var(--accent);
}

/* ========== Sidebar ========== */
.sidebar {
  position: fixed; top: 60px; bottom: 40px; left: 0;
  width: 340px; padding: 20px; overflow-y: auto;
  background: var(--surface);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-right: 1px solid var(--border);
  z-index: 900;
  transition: opacity 300ms ease, transform 300ms ease;
}
.sidebar::-webkit-scrollbar { width: 6px; }
.sidebar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.sidebar-section { margin-bottom: 24px; }
.sidebar-section h3 {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  color: var(--text-muted); letter-spacing: 1.2px; margin-bottom: 12px;
}

.kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.kpi-card {
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--border); border-radius: 8px; padding: 12px;
}
.kpi-card .value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 22px; font-weight: 600;
  color: var(--accent); line-height: 1;
}
.kpi-card.highlight .value { color: var(--accent2); }
.kpi-card.warn .value { color: var(--status-excluded); }
.kpi-card .label {
  font-size: 11px; color: var(--text-muted);
  margin-top: 6px; line-height: 1.3;
}

/* ========== Search ========== */
.search-box { position: relative; }
.search-box input {
  width: 100%; padding: 10px 12px;
  background: rgba(0,0,0,0.4); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  font-family: inherit; font-size: 13px;
  transition: border-color 200ms;
}
.search-box input:focus { outline: none; border-color: var(--accent); }
.search-results {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0;
  max-height: 280px; overflow-y: auto;
  background: var(--surface-solid);
  border: 1px solid var(--border); border-radius: 6px;
  display: none; z-index: 1500;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.search-results.show { display: block; }
.search-result {
  padding: 8px 12px;
  border-bottom: 1px solid var(--surface-2);
  cursor: pointer;
  display: flex; align-items: center; gap: 8px;
  font-size: 12px;
  transition: background 150ms;
}
.search-result:hover { background: rgba(0,212,255,0.12); }
.search-result:last-child { border-bottom: none; }
.search-result .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.search-result .gh {
  font-family: 'JetBrains Mono', monospace;
  color: var(--accent); font-weight: 600;
  min-width: 80px;
}
.search-result .addr {
  color: var(--text-muted); font-size: 11px; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.search-result .score-mini {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; color: var(--text-muted);
  background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 3px;
}

/* ========== Filters ========== */
.filter-row { margin-bottom: 14px; }
.filter-row label {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 12px; color: var(--text-muted); margin-bottom: 6px;
}
.filter-row label .value {
  color: var(--accent); font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
}
.filter-row input[type="range"] {
  width: 100%; -webkit-appearance: none; appearance: none;
  background: transparent; cursor: pointer;
}
.filter-row input[type="range"]::-webkit-slider-runnable-track {
  background: var(--border); height: 4px; border-radius: 2px;
}
.filter-row input[type="range"]::-moz-range-track {
  background: var(--border); height: 4px; border-radius: 2px;
}
.filter-row input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 14px; height: 14px; border-radius: 50%;
  background: var(--accent); cursor: pointer; margin-top: -5px;
  box-shadow: 0 0 8px var(--accent);
}
.filter-row input[type="range"]::-moz-range-thumb {
  width: 14px; height: 14px; border-radius: 50%; border: none;
  background: var(--accent); cursor: pointer;
  box-shadow: 0 0 8px var(--accent);
}
.toggle-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0; font-size: 13px;
}
.switch { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
.switch input { display: none; }
.switch .slider {
  position: absolute; cursor: pointer; inset: 0;
  background: var(--border); border-radius: 20px; transition: 200ms;
}
.switch .slider::before {
  content: ""; position: absolute; height: 14px; width: 14px;
  left: 3px; top: 3px; background: white; border-radius: 50%;
  transition: 200ms;
}
.switch input:checked + .slider { background: var(--accent); }
.switch input:checked + .slider::before { transform: translateX(16px); }
.filter-row select {
  width: 100%; padding: 8px 10px; font-size: 13px;
  background: rgba(0,0,0,0.4); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  font-family: inherit; cursor: pointer;
}
.filter-row select:focus { outline: none; border-color: var(--accent); }

/* ========== Legend ========== */
.legend-item {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0; font-size: 12px; color: var(--text);
}
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.legend-note {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(255,140,66,0.06);
  border-left: 2px solid var(--status-marginal);
  border-radius: 4px;
  font-size: 11px;
  font-style: italic;
  color: var(--text-muted);
  line-height: 1.4;
}

.live-stat { font-size: 13px; padding: 4px 0; color: var(--text-muted); }
.live-stat .num {
  font-family: 'JetBrains Mono', monospace;
  color: var(--accent); font-weight: 600; margin-right: 4px;
}

/* ========== Top Candidats ========== */
.top-candidates { display: flex; flex-direction: column; gap: 14px; }
.gush-group { }
.gush-group-header {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--accent);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 4px 0;
  border-bottom: 1px solid var(--surface-2);
  margin-bottom: 4px;
}
.gush-group-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 150ms;
  font-size: 12px;
  margin: 1px 0;
}
.gush-group-item:hover {
  background: rgba(0,212,255,0.08);
  transform: translateX(2px);
}
.gush-group-item .dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.gush-group-item .gh-mini {
  font-family: 'JetBrains Mono', monospace;
  color: var(--text); font-weight: 500;
  min-width: 70px;
}
.gush-group-item .addr-mini {
  color: var(--text-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gush-group-item .arrow {
  color: var(--text-muted); opacity: 0.4;
}
.top-actions { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.top-actions .btn-primary,
.top-actions .btn-secondary { margin-bottom: 0; }

/* ========== Building panel ========== */
.building-panel {
  position: fixed; top: 60px; bottom: 40px; right: 0;
  width: 400px; padding: 24px; overflow-y: auto;
  background: var(--surface);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-left: 1px solid var(--border);
  z-index: 950;
  transform: translateX(100%);
  transition: transform 300ms cubic-bezier(0.16, 1, 0.3, 1);
}
.building-panel.open { transform: translateX(0); }
.building-panel::-webkit-scrollbar { width: 6px; }
.building-panel::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.panel-close {
  position: absolute; top: 16px; right: 16px;
  background: rgba(0,0,0,0.4); border: 1px solid var(--border);
  color: var(--text); width: 32px; height: 32px;
  border-radius: 50%; cursor: pointer;
  font-size: 18px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
  transition: all 200ms; font-family: inherit;
}
.panel-close:hover {
  background: var(--status-excluded); border-color: var(--status-excluded);
}

.panel-score {
  font-family: 'JetBrains Mono', monospace;
  font-size: 48px; font-weight: 600;
  line-height: 1; margin-bottom: 4px; margin-top: 8px;
}
.panel-status {
  display: inline-block; font-size: 11px; font-weight: 700;
  padding: 4px 10px; border-radius: 4px; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 8px;
}
.panel-top25 {
  display: inline-block; margin-left: 6px;
  font-size: 11px; font-weight: 700;
  background: rgba(0,255,136,0.15);
  color: var(--accent2);
  border: 1px solid rgba(0,255,136,0.4);
  border-radius: 4px; padding: 4px 8px;
  letter-spacing: 0.5px;
}
.panel-addr {
  font-size: 20px; font-weight: 600; margin-top: 12px; margin-bottom: 6px;
  word-break: break-word; line-height: 1.3;
}
.panel-addr.empty {
  font-style: italic; font-weight: 400;
  color: var(--text-muted); font-size: 16px;
}

/* === Gush/Helka BIG BLOCK === */
.gush-helka-block {
  background: linear-gradient(135deg, rgba(0,212,255,0.10) 0%, rgba(0,212,255,0.04) 100%);
  border: 1px solid rgba(0,212,255,0.35);
  border-radius: 12px;
  padding: 14px 16px;
  margin: 16px 0 20px;
  position: relative;
}
.gush-helka-label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.2px;
  font-weight: 600;
  margin-bottom: 6px;
}
.gush-helka-value {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px;
}
.gh-number {
  font-family: 'JetBrains Mono', monospace;
  font-size: 30px;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: -0.5px;
  line-height: 1.1;
}
.btn-copy-gh {
  background: rgba(0,212,255,0.15);
  border: 1px solid rgba(0,212,255,0.4);
  color: var(--accent);
  width: 36px; height: 36px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 15px;
  display: flex; align-items: center; justify-content: center;
  transition: all 180ms;
  flex-shrink: 0;
  font-family: inherit;
}
.btn-copy-gh:hover {
  background: var(--accent); color: #000;
  box-shadow: 0 0 12px rgba(0,212,255,0.4);
}

.panel-table { width: 100%; border-collapse: collapse; margin: 12px 0; }
.panel-table tr { border-bottom: 1px solid var(--surface-2); }
.panel-table tr:last-child { border-bottom: none; }
.panel-table td { padding: 9px 0; font-size: 13px; }
.panel-table td:first-child { color: var(--text-muted); }
.panel-table td:last-child {
  text-align: right; font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
}
.panel-table td.highlight { color: var(--accent); font-weight: 600; }
.panel-table td.warn { color: var(--status-excluded); font-weight: 600; }

.warning-box {
  background: rgba(255,140,66,0.08);
  border: 1px solid rgba(255,140,66,0.4);
  border-radius: 8px; padding: 12px; margin: 16px 0;
  font-size: 12px; color: var(--text-muted); line-height: 1.4;
}
.warning-box strong {
  color: var(--status-marginal); display: block;
  margin-bottom: 4px; font-size: 13px;
}

.btn-primary {
  display: block; width: 100%; padding: 12px;
  background: var(--accent); color: #000;
  border: none; border-radius: 8px; cursor: pointer;
  font-family: inherit; font-size: 14px; font-weight: 600;
  text-decoration: none; text-align: center;
  transition: all 200ms;
  margin-bottom: 10px;
}
.btn-primary:hover {
  background: var(--accent2); color: #000;
  box-shadow: 0 0 20px rgba(0,255,136,0.4);
  transform: translateY(-1px);
}
.btn-secondary {
  display: block; width: 100%; padding: 10px;
  background: transparent; color: var(--text-muted);
  border: 1px solid var(--border); border-radius: 8px;
  font-family: inherit; font-size: 13px;
  text-decoration: none; text-align: center;
  transition: all 200ms; margin-bottom: 8px; cursor: pointer;
}
.btn-secondary:hover { color: var(--accent); border-color: var(--accent); }

/* ========== Toast ========== */
.toast {
  position: fixed; bottom: 80px; left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: var(--surface-solid);
  border: 1px solid var(--accent2);
  color: var(--accent2);
  padding: 12px 22px;
  border-radius: 8px;
  font-size: 13px; font-weight: 600;
  opacity: 0; pointer-events: none;
  transition: all 300ms cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 2500;
  box-shadow: 0 4px 24px rgba(0,255,136,0.35);
}
.toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* ========== Modal table ========== */
.modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(5, 8, 16, 0.78);
  backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  display: none; align-items: center; justify-content: center;
  z-index: 3000; padding: 24px;
}
.modal-backdrop.open { display: flex; }
.modal {
  background: var(--surface-solid);
  border: 1px solid var(--border);
  border-radius: 14px;
  width: 100%; max-width: 1100px; max-height: 88vh;
  display: flex; flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
}
.modal-header {
  padding: 18px 22px;
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.modal-header h2 { font-size: 17px; font-weight: 600; letter-spacing: -0.2px; }
.modal-toolbar {
  display: flex; gap: 8px; padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  align-items: center;
}
.modal-toolbar input {
  flex: 1; padding: 9px 12px;
  background: rgba(0,0,0,0.4); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  font-family: inherit; font-size: 13px;
}
.modal-toolbar input:focus { outline: none; border-color: var(--accent); }
.modal-btn {
  width: auto !important; padding: 9px 14px !important;
  margin: 0 !important; white-space: nowrap;
}
.modal-table-wrapper { overflow: auto; flex: 1; }
.modal-table {
  width: 100%; border-collapse: collapse;
  font-size: 12px;
}
.modal-table th {
  background: rgba(0,0,0,0.5);
  color: var(--text-muted);
  font-weight: 600;
  padding: 11px 10px;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  position: sticky; top: 0;
  border-bottom: 1px solid var(--border);
  letter-spacing: 0.3px;
  text-transform: uppercase;
  font-size: 10px;
}
.modal-table th:hover { color: var(--accent); }
.modal-table th.sorted { color: var(--accent); }
.modal-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--surface-2);
  font-family: 'JetBrains Mono', monospace;
  vertical-align: middle;
}
.modal-table td.addr-col {
  font-family: 'Inter', sans-serif;
  max-width: 220px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}
.modal-table tbody tr {
  cursor: pointer;
  transition: background 150ms;
}
.modal-table tbody tr:hover { background: rgba(0,212,255,0.08); }
.status-pill {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ========== Red Line stations ========== */
.station-marker {
  display: flex; flex-direction: column; align-items: center;
  pointer-events: auto;
}
.station-icon {
  width: 32px; height: 32px;
  background: #C8102E;
  border: 3px solid #FFFFFF;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #FFFFFF; font-size: 16px; line-height: 1; font-weight: 700;
  box-shadow: 0 2px 10px rgba(0,0,0,0.5), 0 0 0 1px rgba(200,16,46,0.4);
}
.station-icon.secondary {
  width: 22px; height: 22px;
  border-width: 2px;
  font-size: 11px;
  box-shadow: 0 1px 6px rgba(0,0,0,0.5);
}
.station-label {
  background: #FFFFFF;
  color: #C8102E;
  font-family: 'Inter', sans-serif;
  font-size: 10px; font-weight: 700;
  padding: 2px 7px; border-radius: 4px;
  margin-top: 3px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.3);
  white-space: nowrap;
  letter-spacing: 0.2px;
}
.station-label.secondary { font-size: 9px; padding: 1px 5px; }

/* Ring radius labels */
.ring-label {
  background: rgba(10, 14, 26, 0.8) !important;
  border: 1px solid rgba(0,212,255,0.4) !important;
  color: var(--accent) !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  padding: 2px 6px !important;
  border-radius: 3px !important;
  box-shadow: none !important;
}
.ring-label::before { display: none !important; }

/* Footer Hitchadshut link */
footer a.footer-link {
  color: var(--accent2); text-decoration: none;
  margin-left: 4px; font-weight: 600;
  transition: color 200ms;
}
footer a.footer-link:hover {
  color: #FFFFFF; text-decoration: underline;
}

/* Panel Hitchadshut button — distinct style */
.btn-hitchadshut {
  display: block; width: 100%; padding: 11px;
  background: linear-gradient(135deg, #C8102E 0%, #8B0000 100%);
  color: #FFFFFF !important;
  border: none; border-radius: 8px;
  font-family: inherit; font-size: 13px; font-weight: 600;
  text-decoration: none; text-align: center;
  transition: all 200ms; margin-bottom: 8px; cursor: pointer;
  box-shadow: 0 2px 8px rgba(200,16,46,0.3);
}
.btn-hitchadshut:hover {
  background: linear-gradient(135deg, #E01F3D 0%, #A00000 100%);
  box-shadow: 0 4px 16px rgba(200,16,46,0.45);
  transform: translateY(-1px);
}

/* ========== Pulse halo for top candidates (SVG) ========== */
@keyframes top-pulse {
  0%, 100% { stroke-opacity: 0.85; stroke-width: 2; }
  50%      { stroke-opacity: 0.15; stroke-width: 9; }
}
.top-halo-marker {
  animation: top-pulse 2.2s ease-in-out infinite;
  pointer-events: none;
}

/* ========== Mitcham permanent labels ========== */
.mitcham-label {
  background: rgba(239, 68, 68, 0.92) !important;
  color: #FFFFFF !important;
  border: 1px solid #EF4444 !important;
  border-radius: 5px !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 10px !important;
  letter-spacing: 0.2px;
  padding: 3px 7px !important;
  box-shadow: 0 2px 10px rgba(239,68,68,0.35) !important;
  white-space: nowrap;
  text-align: center;
  line-height: 1.2;
}
.mitcham-label::before { display: none !important; }
.mitcham-label .ml-name { font-weight: 700; }
.mitcham-label .ml-id { font-size: 8px; opacity: 0.7; font-weight: 400; display: block; margin-top: 1px; }

/* Mitchamim sidebar list items */
.mitcham-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  margin: 2px 0;
  border: 1px solid transparent;
  transition: all 150ms;
}
.mitcham-item:hover {
  background: rgba(239,68,68,0.08);
  border-color: rgba(239,68,68,0.3);
  transform: translateX(2px);
}
.mitcham-item .mitcham-flag { font-size: 13px; flex-shrink: 0; }
.mitcham-item .mitcham-name {
  flex: 1;
  color: var(--text);
  font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.mitcham-item .mitcham-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--status-excluded);
  background: rgba(239,68,68,0.15);
  padding: 2px 7px;
  border-radius: 3px;
  flex-shrink: 0;
}
.mitcham-item .arrow { color: var(--text-muted); opacity: 0.5; flex-shrink: 0; }

/* Mitcham popup */
.mitcham-popup .popup-name { font-size: 16px; font-weight: 700; color: var(--status-excluded); margin-bottom: 4px; }
.mitcham-popup .popup-name-he { font-size: 12px; color: var(--text-muted); margin-bottom: 10px; }
.mitcham-popup .popup-row {
  display: flex; justify-content: space-between;
  font-size: 12px; padding: 4px 0;
  border-bottom: 1px solid var(--surface-2);
}
.mitcham-popup .popup-row:last-of-type { border-bottom: none; }
.mitcham-popup .popup-row .lbl { color: var(--text-muted); }
.mitcham-popup .popup-row .val { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
.mitcham-popup .popup-mavat-btn {
  display: block; margin-top: 10px;
  background: var(--accent); color: #000 !important;
  padding: 8px 12px; border-radius: 6px;
  text-decoration: none; text-align: center;
  font-size: 12px; font-weight: 600;
}
.mitcham-popup .popup-mavat-btn:hover { background: var(--accent2); }

/* Hover highlight via gush-group-item */
.marker-hover-highlight { /* class added on path via JS via element manipulation N/A on canvas */ }

/* Legend restructure */
.legend-subtitle {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 600;
  margin: 10px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--surface-2);
}
.legend-item .count {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
}
.legend-square {
  width: 14px; height: 10px; border-radius: 2px;
  border: 1.5px dashed #EF4444;
  background: rgba(239,68,68,0.15);
  flex-shrink: 0;
}

/* ========== Footer + recenter ========== */
footer {
  position: fixed; bottom: 0; left: 0; right: 0; height: 40px;
  background: var(--surface);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--text-muted);
  z-index: 1000;
  transition: opacity 300ms ease;
  padding: 0 20px; text-align: center;
}
footer .num {
  color: var(--accent); font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}
.btn-recenter {
  position: fixed; bottom: 56px; right: 20px; z-index: 800;
  background: var(--accent); color: #000;
  border: none; border-radius: 50%; width: 48px; height: 48px;
  font-size: 20px; cursor: pointer; line-height: 1;
  box-shadow: 0 4px 20px rgba(0,212,255,0.4);
  transition: all 200ms;
  display: flex; align-items: center; justify-content: center;
}
.btn-recenter:hover {
  background: var(--accent2); transform: scale(1.08);
  box-shadow: 0 4px 24px rgba(0,255,136,0.5);
}

body.presenting header,
body.presenting .sidebar,
body.presenting footer { opacity: 0; pointer-events: none; }
body.presenting .btn-recenter { display: none; }

.burger {
  display: none;
  background: rgba(0,0,0,0.3); border: 1px solid var(--border);
  color: white; width: 36px; height: 36px; border-radius: 6px;
  align-items: center; justify-content: center; cursor: pointer;
  font-size: 18px; font-family: inherit;
}

/* ========== Leaflet dark overrides ========== */
.leaflet-container { background: var(--bg); font-family: inherit; }
.leaflet-popup-content-wrapper {
  background: var(--surface-solid); color: var(--text);
  border-radius: 8px; border: 1px solid var(--border);
}
.leaflet-popup-tip { background: var(--surface-solid); border: 1px solid var(--border); }
.leaflet-popup-content { font-family: inherit; }
.leaflet-tooltip {
  background: var(--surface-solid); color: var(--text);
  border: 1px solid var(--border); font-family: inherit;
  font-size: 12px; padding: 6px 10px;
}
.leaflet-tooltip-top:before, .leaflet-tooltip-bottom:before,
.leaflet-tooltip-left:before, .leaflet-tooltip-right:before { border-color: transparent; }
.leaflet-control-attribution {
  background: rgba(0,0,0,0.6) !important; color: var(--text-muted) !important;
  font-size: 10px !important;
}
.leaflet-control-attribution a { color: var(--accent) !important; }
.leaflet-control-zoom a {
  background: var(--surface-solid) !important; color: var(--text) !important;
  border-color: var(--border) !important;
}
.leaflet-control-zoom a:hover { background: var(--accent) !important; color: #000 !important; }

/* ========== Responsive ========== */
@media (max-width: 1199px) {
  .sidebar { width: 300px; }
  .building-panel { width: 360px; }
}
@media (max-width: 799px) {
  .burger { display: flex; }
  .sidebar { width: 100%; max-width: 340px; transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); }
  .building-panel {
    width: 100%; left: 0; right: 0;
    top: auto; bottom: 40px; max-height: 75vh;
    transform: translateY(100%);
    border-left: none; border-top: 1px solid var(--border);
    border-radius: 16px 16px 0 0;
  }
  .building-panel.open { transform: translateY(0); }
  header { padding: 0 12px; gap: 8px; }
  .tool-name span { display: none; }
  .btn-icon span { display: none; }
  .modal { max-height: 95vh; }
  .modal-toolbar { flex-wrap: wrap; }
}
</style>
</head>
<body>

<header>
  <div class="logo">RY</div>
  <div class="tool-name">BatYam <span>Pinui Scout</span></div>
  <button class="burger" onclick="toggleSidebar()" aria-label="Menu">☰</button>
  <div class="spacer"></div>
  <div class="lang-toggle" role="tablist">
    <button id="lang-fr" class="active" onclick="setLang('fr')">FR</button>
    <button id="lang-en" onclick="setLang('en')">EN</button>
  </div>
  <button class="btn-icon" onclick="togglePresentation()" title="Touche P">
    ⛶ <span data-i18n="presentation_mode">Présentation</span>
  </button>
  <button class="btn-icon" id="draw-zone-btn" onclick="toggleDrawZone()" title="Draw a new study zone">
    ✏ <span>Draw Zone</span>
  </button>
</header>

<!-- Draw Zone modal -->
<div id="draw-zone-modal" style="display:none;position:fixed;inset:0;z-index:9000;align-items:center;justify-content:center">
  <div style="position:absolute;inset:0;background:rgba(0,0,0,0.6)" onclick="closeDrawModal()"></div>
  <div style="position:relative;background:var(--surface-solid);border:1px solid var(--border);border-radius:14px;padding:24px;width:540px;max-width:95vw;max-height:90vh;overflow-y:auto;z-index:1">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <h2 style="font-size:16px;font-weight:600;margin:0">New Study Zone</h2>
      <button onclick="closeDrawModal()" style="background:none;border:none;color:var(--text-muted);font-size:20px;cursor:pointer;line-height:1">✕</button>
    </div>

    <!-- Panel A: server available → one-click run -->
    <div id="dz-panel-server" style="display:none">
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 16px">
        Zone drawn. Click the button to fetch buildings, score them, and reload the map automatically.
      </p>
      <button onclick="dzRunPipeline()" style="background:var(--accent);color:#000;border:none;border-radius:8px;padding:12px 20px;font-size:14px;font-weight:700;cursor:pointer;width:100%">
        ▶ Run Pipeline for this zone
      </button>
    </div>

    <!-- Panel B: running → progress log -->
    <div id="dz-panel-progress" style="display:none">
      <pre id="dz-log" style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:14px;font-family:'JetBrains Mono',monospace;font-size:12px;color:#ccc;white-space:pre-wrap;max-height:320px;overflow-y:auto;margin:0 0 12px"></pre>
      <div id="dz-done-msg" style="display:none;color:#4ade80;font-size:13px;font-weight:600;text-align:center">
        Done! Reloading map...
      </div>
      <div id="dz-error-msg" style="display:none;color:#f87171;font-size:13px;font-weight:600;text-align:center">
        Pipeline failed — see log above.
      </div>
    </div>

    <!-- Panel C: no server → copy snippet fallback -->
    <div id="dz-panel-fallback" style="display:none">
      <p style="color:var(--text-muted);font-size:13px;margin:0 0 10px">
        Start <code style="background:var(--surface-2);padding:1px 5px;border-radius:4px">Start Scout.bat</code>
        for one-click runs, or copy this snippet into
        <code style="background:var(--surface-2);padding:1px 5px;border-radius:4px">config.py</code>
        and re-run the pipeline manually.
      </p>
      <pre id="draw-zone-output" style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:14px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--accent);white-space:pre-wrap;word-break:break-all;margin:0 0 14px;user-select:all"></pre>
      <button onclick="copyDrawZone()" style="background:var(--accent);color:#000;border:none;border-radius:8px;padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;width:100%">Copy to clipboard</button>
    </div>
  </div>
</div>

<aside class="sidebar" id="sidebar">

  <!-- KPIs -->
  <div class="sidebar-section">
    <h3 data-i18n="section_overview">Vue d'ensemble</h3>
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="value" id="kpi-total">—</div>
        <div class="label" data-i18n="kpi_total">Bâtiments scannés</div>
      </div>
      <div class="kpi-card">
        <div class="value" id="kpi-candidates">—</div>
        <div class="label" data-i18n="kpi_candidates">Candidats actifs</div>
      </div>
      <div class="kpi-card highlight">
        <div class="value" id="kpi-top">—</div>
        <div class="label" data-i18n="kpi_top">Top candidats</div>
      </div>
      <div class="kpi-card warn">
        <div class="value" id="kpi-excluded">—</div>
        <div class="label" data-i18n="kpi_buildings_excluded">Bâtiments exclus</div>
      </div>
    </div>
  </div>

  <!-- Search -->
  <div class="sidebar-section">
    <h3 data-i18n="section_search">Recherche</h3>
    <div class="search-box">
      <input type="text" id="search-input" placeholder="🔍 Gush/Helka ou adresse..." data-i18n-placeholder="search_placeholder" autocomplete="off">
      <div class="search-results" id="search-results"></div>
    </div>
  </div>

  <!-- Filters -->
  <div class="sidebar-section">
    <h3 data-i18n="section_filters">Filtres</h3>
    <div class="filter-row">
      <label>
        <span data-i18n="filter_score">Score</span> ≥
        <span class="value" id="score-val">0</span>
      </label>
      <input type="range" id="score-min" min="0" max="100" step="1" value="0">
    </div>
    <div class="filter-row">
      <label>
        <span data-i18n="filter_distance">Distance station max</span>
        <span class="value" id="dist-val">2000 m</span>
      </label>
      <input type="range" id="dist-max" min="100" max="2000" step="50" value="2000">
    </div>
    <div class="toggle-row">
      <span data-i18n="filter_mitchamim">Afficher mitchamim</span>
      <label class="switch">
        <input type="checkbox" id="show-mitchamim" checked>
        <span class="slider"></span>
      </label>
    </div>
    <div class="toggle-row">
      <span data-i18n="filter_top25">Top candidats seulement</span>
      <label class="switch">
        <input type="checkbox" id="top25-only">
        <span class="slider"></span>
      </label>
    </div>
    <div class="toggle-row">
      <span><span data-i18n="filter_highlight_top">Mettre en évidence top candidats</span></span>
      <label class="switch">
        <input type="checkbox" id="highlight-top" checked>
        <span class="slider"></span>
      </label>
    </div>
    <div class="toggle-row">
      <span><span data-i18n="filter_show_excluded">Afficher bâtiments exclus</span></span>
      <label class="switch">
        <input type="checkbox" id="show-excluded">
        <span class="slider"></span>
      </label>
    </div>
    <div class="toggle-row">
      <span><span data-i18n="filter_show_redline">Afficher Red Line</span></span>
      <label class="switch">
        <input type="checkbox" id="show-redline" checked>
        <span class="slider"></span>
      </label>
    </div>
    <div class="filter-row" style="margin-top: 12px;">
      <label><span data-i18n="filter_status">Statut</span></label>
      <select id="status-filter">
        <option value="all" data-i18n="status_all">Tous</option>
        <option value="TOP">TOP</option>
        <option value="INVEST">INVEST</option>
        <option value="MARGINAL">MARGINAL</option>
        <option value="WEAK">WEAK</option>
        <option value="EXCLUDED">EXCLUDED</option>
      </select>
    </div>
  </div>

  <!-- Legend -->
  <div class="sidebar-section">
    <h3 data-i18n="section_legend">Légende</h3>

    <div class="legend-subtitle" data-i18n="legend_markers_title">Markers bâtiment</div>
    <div class="legend-item"><span class="legend-dot" style="background:#00FF88"></span><span data-i18n="legend_top">Top opportunité</span><span class="count" id="lc-top">—</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:#FFD700"></span><span data-i18n="legend_invest">À investiguer</span><span class="count" id="lc-invest">—</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:#FF8C42"></span><span data-i18n="legend_marginal">Marginal</span><span class="count" id="lc-marginal">—</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:#6B7280"></span><span data-i18n="legend_weak">Faible</span><span class="count" id="lc-weak">—</span></div>
    <div class="legend-item"><span class="legend-dot" style="background:#EF4444"></span><span data-i18n="legend_excluded_in_mitcham">Exclu (dans mitcham actif)</span><span class="count" id="lc-excluded">—</span></div>

    <div class="legend-subtitle" data-i18n="legend_zones_title">Zones sur la carte</div>
    <div class="legend-item"><span class="legend-square"></span><span data-i18n="legend_mitcham_zone">Zone mitcham actif</span><span class="count" id="lc-zones">—</span></div>

    <div class="legend-note" data-i18n="legend_note">ℹ Aucun TOP/INVEST actuellement — year_built indisponible limite le score max. Validation Street View requise pour les MARGINAL.</div>
  </div>

  <!-- Mitchamim actifs (déclarés) -->
  <div class="sidebar-section">
    <h3>
      <span data-i18n="section_active_mitchamim">Mitchamim actifs</span>
      <span style="color: var(--status-excluded); margin-left: 4px;" id="mitchamim-count-badge"></span>
    </h3>
    <div id="mitchamim-list"></div>
  </div>

  <!-- Top Candidats groupé par Gush -->
  <div class="sidebar-section">
    <h3 data-i18n="section_top_candidates">Top candidats</h3>
    <div class="top-candidates" id="top-candidates-list"></div>
    <div class="top-actions">
      <button class="btn-primary" onclick="copyAllGH()" data-i18n="btn_copy_all_gh">📋 Copier tous les Gush/Helka</button>
      <button class="btn-secondary" onclick="openTableModal()" data-i18n="btn_view_table">📊 Voir le tableau complet</button>
    </div>
  </div>

  <!-- Live stats -->
  <div class="sidebar-section">
    <h3 data-i18n="section_live">Stats live</h3>
    <div class="live-stat">
      <span class="num" id="stat-shown">0</span><span data-i18n="showing_buildings">bâtiments affichés</span>
    </div>
    <div class="live-stat">
      <span class="num" id="stat-top25">0</span><span data-i18n="in_top25">dans le top</span>
    </div>
    <div class="live-stat">
      <span class="num" id="stat-mitcham">0</span><span data-i18n="in_mitcham">dans un mitcham</span>
    </div>
  </div>

</aside>

<div id="map"></div>

<aside class="building-panel" id="panel" aria-hidden="true">
  <button class="panel-close" onclick="closePanel()" aria-label="Close" title="Echap">×</button>
  <div id="panel-content"></div>
</aside>

<button class="btn-recenter" title="Recentrer" onclick="recenterMap()">⌖</button>

<footer>
  <span>📊 <span class="num" id="footer-total">—</span> <span data-i18n="kpi_total">bâtiments</span>
  &middot; <span class="num" id="footer-top">—</span> <span data-i18n="footer_top">top candidats</span>
  &middot; <span class="num" id="footer-mitchamim">—</span> <span data-i18n="footer_excluded">mitchamim</span>
  &middot; <span data-i18n="footer_updated">MAJ</span> __GENERATED_DATE__
  &middot; <a href="https://b-yam.co.il" target="_blank" rel="noopener" class="footer-link" data-i18n="footer_hitchadshut" title="Bat Yam Urban Renewal Authority">🏛 Hitchadshut Ironit Bat Yam ↗</a>
  </span>
</footer>

<!-- Toast -->
<div class="toast" id="toast"></div>

<!-- Modal tableau complet -->
<div class="modal-backdrop" id="modal-backdrop" onclick="modalBackdropClick(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h2 data-i18n="modal_title">Top candidats — Liste complète</h2>
      <button class="panel-close" onclick="closeTableModal()">×</button>
    </div>
    <div class="modal-toolbar">
      <input type="text" id="modal-search" placeholder="Rechercher..." data-i18n-placeholder="modal_search">
      <button class="btn-secondary modal-btn" onclick="exportCSV()" data-i18n="modal_export_csv">↓ Export CSV</button>
      <button class="btn-secondary modal-btn" onclick="exportGHList()" data-i18n="modal_export_gh">📋 Export Gush/Helka</button>
    </div>
    <div class="modal-table-wrapper">
      <table class="modal-table" id="modal-table">
        <thead></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
<script>
"use strict";

// =============== Embedded data ===============
const buildings = __BUILDINGS__;
const mitchamimGeoJSON = __MITCHAMIM__;
const station = __STATION__;
const studyPolygon = __STUDY_POLYGON__;

// =============== i18n ===============
const i18n = {
  fr: {
    section_overview: "Vue d'ensemble",
    section_search: "Recherche",
    section_filters: "Filtres",
    section_legend: "Légende",
    section_top_candidates: "Top candidats",
    section_live: "Stats live",
    search_placeholder: "🔍 Gush/Helka ou adresse...",
    kpi_total: "Bâtiments scannés",
    kpi_candidates: "Candidats actifs",
    kpi_top: "Top candidats",
    kpi_mitchamim: "Mitchamim actifs",
    filter_score: "Score",
    filter_distance: "Distance station max",
    filter_mitchamim: "Afficher mitchamim",
    filter_top25: "Top candidats seulement",
    filter_status: "Statut",
    status_all: "Tous",
    legend_top: "Top opportunité",
    legend_invest: "À investiguer",
    legend_marginal: "Marginal",
    legend_weak: "Faible",
    legend_excluded: "Exclu (mitcham actif)",
    legend_excluded_in_mitcham: "Exclu (dans mitcham actif)",
    legend_markers_title: "Markers bâtiment",
    legend_zones_title: "Zones sur la carte",
    legend_mitcham_zone: "Zone mitcham actif",
    legend_currently: "actuellement",
    legend_in_mitcham: "dans mitcham actif",
    legend_note: "ℹ Aucun TOP/INVEST actuellement — year_built indisponible limite le score max. Validation Street View requise pour les MARGINAL.",
    kpi_mitchamim_zones: "Zones mitchamim",
    kpi_buildings_excluded: "Bâtiments exclus",
    filter_show_excluded: "Afficher bâtiments exclus",
    filter_highlight_top: "Mettre en évidence top candidats",
    mitcham_label_prefix: "🚫 Mitcham",
    filter_show_redline: "Afficher stations Red Line",
    station_balfour: "Station Balfour",
    station_tooltip: "🚊 Station Balfour — Red Line (LRT Tel Aviv-Yafo)",
    redline_label: "Ligne Rouge — Tram Tel Aviv-Yafo (tracé approximatif)",
    link_hitchadshut: "🏛 Démarrer dossier Pinui-Binui (Hitchadshut Ironit Bat Yam) ↗",
    hitchadshut_tooltip: "Autorité officielle Bat Yam pour Pinui-Binui et TAMA 38",
    footer_hitchadshut: "🏛 Hitchadshut Ironit Bat Yam ↗",
    ring_300: "300 m",
    ring_500: "500 m",
    ring_1000: "1 km",
    section_active_mitchamim: "Mitchamim actifs",
    mitchamim_in_zone: "dans la zone",
    mitcham_buildings_inside: "bât. à l'intérieur",
    mitcham_status: "Statut",
    mitcham_track: "Filière",
    mitcham_sug_mas: "Voie",
    mitcham_id_tbv: "ID TBV",
    mitcham_id_proj: "ID Projet",
    mitcham_he_name: "Nom hébreu",
    view_on_mavat: "📋 Voir sur Mavat ↗",
    no_address: "sans adresse",
    validation_required: "Validation visuelle requise",
    validation_note: "year_built non disponible — vérifiez l'âge via Street View.",
    btn_streetview: "🔍 Ouvrir Street View",
    btn_govmap: "Voir sur GovMap",
    btn_mavat: "Voir sur Mavat",
    btn_copy_all_gh: "📋 Copier tous les Gush/Helka",
    btn_view_table: "📊 Voir le tableau complet",
    btn_copy: "📋 Copier",
    copied_toast: "Gush/Helka copié !",
    copied_all_toast: "Liste copiée dans le presse-papier !",
    modal_title: "Top candidats — Liste complète",
    modal_search: "Rechercher...",
    modal_export_csv: "↓ Export CSV",
    modal_export_gh: "📋 Export Gush/Helka",
    presentation_mode: "Présentation",
    floors: "Étages",
    year_built: "Année construction",
    land_area: "Surface parcelle",
    footprint: "Emprise bâti",
    ratio: "Ratio terrain/bâti",
    dist_balfour: "Distance Balfour",
    neighbors: "Voisins similaires",
    gush_helka: "Gush / Helka",
    mitcham_label: "Mitcham actif",
    top25_badge: "★ TOP",
    showing_buildings: "bâtiments affichés",
    in_top25: "dans le top",
    in_mitcham: "dans un mitcham",
    footer_top: "top candidats",
    footer_excluded: "mitchamim exclus",
    footer_updated: "MAJ",
    col_rank: "#",
    col_score: "Score",
    col_status: "Statut",
    col_gush: "Gush",
    col_helka: "Helka",
    col_address: "Adresse",
    col_floors: "Étages",
    col_land: "Surf. parcelle",
    col_footprint: "Emprise",
    col_ratio: "Ratio",
    col_dist: "Dist. Balfour",
  },
  en: {
    section_overview: "Overview",
    section_search: "Search",
    section_filters: "Filters",
    section_legend: "Legend",
    section_top_candidates: "Top candidates",
    section_live: "Live stats",
    search_placeholder: "🔍 Gush/Helka or address...",
    kpi_total: "Buildings scanned",
    kpi_candidates: "Active candidates",
    kpi_top: "Top candidates",
    kpi_mitchamim: "Active mitchamim",
    filter_score: "Score",
    filter_distance: "Max station distance",
    filter_mitchamim: "Show mitchamim",
    filter_top25: "Top candidates only",
    filter_status: "Status",
    status_all: "All",
    legend_top: "Top opportunity",
    legend_invest: "To investigate",
    legend_marginal: "Marginal",
    legend_weak: "Weak",
    legend_excluded: "Excluded (active mitcham)",
    legend_excluded_in_mitcham: "Excluded (in active mitcham)",
    legend_markers_title: "Building markers",
    legend_zones_title: "Map zones",
    legend_mitcham_zone: "Active mitcham zone",
    legend_currently: "currently",
    legend_in_mitcham: "in active mitcham",
    legend_note: "ℹ No TOP/INVEST currently — year_built unavailable limits max score. Visual Street View validation required for MARGINAL.",
    kpi_mitchamim_zones: "Mitchamim zones",
    kpi_buildings_excluded: "Excluded buildings",
    filter_show_excluded: "Show excluded buildings",
    filter_highlight_top: "Highlight top candidates",
    mitcham_label_prefix: "🚫 Mitcham",
    filter_show_redline: "Show Red Line stations",
    station_balfour: "Balfour Station",
    station_tooltip: "🚊 Balfour Station — Red Line (Tel Aviv-Yafo LRT)",
    redline_label: "Red Line — Tel Aviv-Yafo LRT (approximate trace)",
    link_hitchadshut: "🏛 Start Pinui-Binui application (Bat Yam Urban Renewal Authority) ↗",
    hitchadshut_tooltip: "Official Bat Yam authority for Pinui-Binui and TAMA 38",
    footer_hitchadshut: "🏛 Bat Yam Urban Renewal ↗",
    ring_300: "300 m",
    ring_500: "500 m",
    ring_1000: "1 km",
    section_active_mitchamim: "Active mitchamim",
    mitchamim_in_zone: "in zone",
    mitcham_buildings_inside: "buildings inside",
    mitcham_status: "Status",
    mitcham_track: "Track",
    mitcham_sug_mas: "Mode",
    mitcham_id_tbv: "TBV ID",
    mitcham_id_proj: "Project ID",
    mitcham_he_name: "Hebrew name",
    view_on_mavat: "📋 View on Mavat ↗",
    no_address: "no address",
    validation_required: "Visual validation required",
    validation_note: "year_built unavailable — verify age via Street View.",
    btn_streetview: "🔍 Open Street View",
    btn_govmap: "View on GovMap",
    btn_mavat: "View on Mavat",
    btn_copy_all_gh: "📋 Copy all Gush/Helka",
    btn_view_table: "📊 View full table",
    btn_copy: "📋 Copy",
    copied_toast: "Gush/Helka copied!",
    copied_all_toast: "List copied to clipboard!",
    modal_title: "Top candidates — Full list",
    modal_search: "Search...",
    modal_export_csv: "↓ Export CSV",
    modal_export_gh: "📋 Export Gush/Helka",
    presentation_mode: "Presentation",
    floors: "Floors",
    year_built: "Year built",
    land_area: "Land area",
    footprint: "Footprint",
    ratio: "Land/building ratio",
    dist_balfour: "Distance to Balfour",
    neighbors: "Similar neighbors",
    gush_helka: "Gush / Helka",
    mitcham_label: "Active mitcham",
    top25_badge: "★ TOP",
    showing_buildings: "buildings shown",
    in_top25: "in top",
    in_mitcham: "in a mitcham",
    footer_top: "top candidates",
    footer_excluded: "excluded mitchamim",
    footer_updated: "Updated",
    col_rank: "#",
    col_score: "Score",
    col_status: "Status",
    col_gush: "Gush",
    col_helka: "Helka",
    col_address: "Address",
    col_floors: "Floors",
    col_land: "Land area",
    col_footprint: "Footprint",
    col_ratio: "Ratio",
    col_dist: "Dist. Balfour",
  }
};

let currentLang = "fr";
function t(key) { return i18n[currentLang][key] || key; }

function setLang(lang) {
  currentLang = lang;
  document.getElementById("lang-fr").classList.toggle("active", lang === "fr");
  document.getElementById("lang-en").classList.toggle("active", lang === "en");
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (i18n[lang][key] != null) el.textContent = i18n[lang][key];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (i18n[lang][key] != null) el.placeholder = i18n[lang][key];
  });
  if (selectedBuilding) showBuilding(selectedBuilding);
  renderTopCandidates();
  if (document.getElementById("modal-backdrop").classList.contains("open")) renderModalTable();
  // Re-render station labels + ring labels qui contiennent du texte i18n
  if (typeof renderStations === "function") renderStations();
  if (typeof renderRings === "function") renderRings();
  if (typeof refreshMitchamimI18n === "function") refreshMitchamimI18n();
}

// =============== Status palette ===============
const STATUS_COLORS = {
  TOP: "#00FF88",
  INVEST: "#FFD700",
  MARGINAL: "#FF8C42",
  WEAK: "#6B7280",
  EXCLUDED: "#EF4444",
};
const STATUS_LABEL_KEY = {
  TOP: "legend_top",
  INVEST: "legend_invest",
  MARGINAL: "legend_marginal",
  WEAK: "legend_weak",
  EXCLUDED: "legend_excluded",
};

// =============== Helpers ===============
function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function escapeAttr(s) { return escapeHtml(s).replace(/\\/g, "\\\\"); }

function fmt(v, suffix) {
  if (v == null || v === "" || (typeof v === "number" && isNaN(v))) return "N/A";
  const out = (typeof v === "number" && !Number.isInteger(v)) ? v.toFixed(2) : v;
  return out + (suffix || "");
}

// =============== Map init ===============
const canvasRenderer = L.canvas({ padding: 0.5 });
const meanLat = buildings.length ? buildings.reduce((s, b) => s + b.lat, 0) / buildings.length : station.lat;
const meanLon = buildings.length ? buildings.reduce((s, b) => s + b.lon, 0) / buildings.length : station.lon;

const map = L.map("map", {
  renderer: canvasRenderer, zoomControl: true, attributionControl: true, preferCanvas: true,
}).setView([meanLat, meanLon], 16);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap &copy; CARTO",
  subdomains: "abcd", maxZoom: 20,
}).addTo(map);

const studyLayer = L.geoJSON(studyPolygon, {
  style: { color: "#FFFFFF", weight: 1.5, fillOpacity: 0, dashArray: "6 6", opacity: 0.4 },
  interactive: false,
}).addTo(map);

// ===== Red Line stations (markers seulement — tracé retiré v6 car approximatif) =====
const redLineStations = __RED_LINE_STATIONS__;
const stationsLayer = L.layerGroup().addTo(map);

// Marqueurs stations — Balfour grosse + autres secondaires
function makeStationIcon(stn, isPrimary) {
  const cls = isPrimary ? "station-icon" : "station-icon secondary";
  const labelCls = isPrimary ? "station-label" : "station-label secondary";
  const labelText = currentLang === "en" ? stn.name_en : stn.name_fr;
  return L.divIcon({
    className: "station-divicon",
    html:
      '<div class="station-marker">'
      + '<div class="' + cls + '">🚊</div>'
      + '<div class="' + labelCls + '">' + labelText + '</div>'
      + '</div>',
    iconSize: [80, isPrimary ? 56 : 44],
    iconAnchor: [40, isPrimary ? 16 : 11],
  });
}

function renderStations() {
  stationsLayer.clearLayers();
  redLineStations.forEach(stn => {
    const isPrimary = !!stn.primary;
    const icon = makeStationIcon(stn, isPrimary);
    const labelKey = isPrimary ? "station_tooltip" : null;
    const tipBase = (currentLang === "en" ? stn.name_en : stn.name_fr);
    const tip = isPrimary ? t("station_tooltip") : ("🚊 " + tipBase);
    const m = L.marker([stn.lat, stn.lon], {
      icon: icon,
      zIndexOffset: isPrimary ? 1000 : 700,
    }).bindTooltip(tip, { direction: "top", offset: [0, -16], sticky: true });
    stationsLayer.addLayer(m);
  });
}
renderStations();

// Cercles concentriques recalibrés + labels positionnés à 3h
const RING_CONFIG = [
  { r: 300,  opacity: 0.40, weight: 1.5, dash: "4 4",  labelKey: "ring_300"  },
  { r: 500,  opacity: 0.30, weight: 1.5, dash: "6 4",  labelKey: "ring_500"  },
  { r: 1000, opacity: 0.20, weight: 1,   dash: "8 6",  labelKey: "ring_1000" },
];
const ringLabelsLayer = L.layerGroup().addTo(map);

function renderRings() {
  // Cleanup
  if (window._ringCircles) window._ringCircles.forEach(c => map.removeLayer(c));
  window._ringCircles = [];
  ringLabelsLayer.clearLayers();

  RING_CONFIG.forEach(cfg => {
    const c = L.circle([station.lat, station.lon], {
      radius: cfg.r, color: "#C8102E", fillOpacity: 0, weight: cfg.weight,
      dashArray: cfg.dash, opacity: cfg.opacity, interactive: false,
    }).addTo(map);
    window._ringCircles.push(c);

    // Label à 3h = est du centre, décalé du rayon (1m ≈ 1/111000 ° lat, lon scaled by cos(lat))
    const lonOffset = cfg.r / (111320 * Math.cos(station.lat * Math.PI / 180));
    const labelLatLng = [station.lat, station.lon + lonOffset];
    L.tooltip({
      permanent: true, direction: "right",
      className: "ring-label", offset: [4, 0],
    }).setLatLng(labelLatLng).setContent(t(cfg.labelKey)).addTo(ringLabelsLayer);
  });
}
renderRings();

// Layer pour les labels permanents mitchamim
const mitchamLabelsLayer = L.layerGroup().addTo(map);

function buildMitchamTooltipHtml(p) {
  const name = p["name_" + currentLang] || p.name_he || "—";
  return '<b>🚫 ' + escapeHtml(name) + '</b><br>'
    + '#' + escapeHtml(String(p.id_norm || p.MisparProj || "?")) + ' · '
    + escapeHtml(String(p["maslul_" + currentLang] || p.TeurMaslul || ""));
}

function buildMitchamPopupHtml(p) {
  const name      = p["name_" + currentLang] || p.name_he || "—";
  const nameHe    = p.name_he && p.name_he !== name ? p.name_he : null;
  const maslul    = p["maslul_" + currentLang];
  const sug       = p["sug_mas_" + currentLang];
  const tbv       = (p.plan_name && String(p.plan_name).trim() !== "nan") ? p.plan_name : null;
  const count     = p.buildings_inside || 0;
  const mavatUrl  = p.mavat_url;

  let html = '<div class="mitcham-popup">';
  html += '<div class="popup-name">🚫 ' + escapeHtml(name) + '</div>';
  if (nameHe) html += '<div class="popup-name-he">' + escapeHtml(nameHe) + '</div>';

  html += '<div class="popup-row"><span class="lbl">' + t("mitcham_id_proj") + '</span><span class="val">#' + escapeHtml(String(p.id_norm)) + '</span></div>';
  if (tbv) html += '<div class="popup-row"><span class="lbl">' + t("mitcham_id_tbv") + '</span><span class="val">' + escapeHtml(String(tbv)) + '</span></div>';
  if (maslul) html += '<div class="popup-row"><span class="lbl">' + t("mitcham_track") + '</span><span class="val">' + escapeHtml(maslul) + '</span></div>';
  if (sug) html += '<div class="popup-row"><span class="lbl">' + t("mitcham_sug_mas") + '</span><span class="val">' + escapeHtml(sug) + '</span></div>';
  html += '<div class="popup-row"><span class="lbl">' + t("mitcham_buildings_inside") + '</span><span class="val">' + count + '</span></div>';

  if (mavatUrl) {
    html += '<a href="' + escapeAttr(mavatUrl) + '" target="_blank" rel="noopener" class="popup-mavat-btn">' + t("view_on_mavat") + '</a>';
  }
  html += '</div>';
  return html;
}

const mitchamimLayer = L.geoJSON(mitchamimGeoJSON, {
  style: {
    fillColor: "#EF4444", fillOpacity: 0.12,
    color: "#EF4444", weight: 3, dashArray: "6 4", opacity: 0.85,
  },
  onEachFeature: (feature, layer) => {
    const p = feature.properties || {};
    layer.bindTooltip(buildMitchamTooltipHtml(p), { sticky: true });
    layer.bindPopup(buildMitchamPopupHtml(p), { maxWidth: 320, className: "mitcham-popup-wrap" });
  },
}).addTo(map);

function renderMitchamimLabels() {
  mitchamLabelsLayer.clearLayers();
  mitchamimGeoJSON.features.forEach(f => {
    const p = f.properties || {};
    const name = p["name_" + currentLang] || p.name_he || "—";
    const labelHtml = '<span class="ml-name">🚫 ' + escapeHtml(name) + '</span>'
                    + '<span class="ml-id">#' + escapeHtml(String(p.id_norm || p.MisparProj || "?")) + '</span>';
    const lat = p.centroid_lat, lon = p.centroid_lon;
    if (lat == null || lon == null) return;
    L.tooltip({
      permanent: true, direction: "center",
      className: "mitcham-label", offset: [0, 0],
    }).setLatLng([lat, lon]).setContent(labelHtml).addTo(mitchamLabelsLayer);
  });
}

function refreshMitchamimI18n() {
  // Re-bind tooltips / popups au lang change
  mitchamimLayer.eachLayer(layer => {
    const p = layer.feature && layer.feature.properties;
    if (!p) return;
    layer.unbindTooltip();
    layer.unbindPopup();
    layer.bindTooltip(buildMitchamTooltipHtml(p), { sticky: true });
    layer.bindPopup(buildMitchamPopupHtml(p), { maxWidth: 320 });
  });
  renderMitchamimLabels();
  renderMitchamimList();
}

renderMitchamimLabels();

// Sidebar : liste des mitchamim actifs triés par nombre de bâtiments dedans
function renderMitchamimList() {
  const features = mitchamimGeoJSON.features.slice().sort((a, b) => {
    return (b.properties.buildings_inside || 0) - (a.properties.buildings_inside || 0);
  });
  const html = features.map(f => {
    const p = f.properties || {};
    const name  = p["name_" + currentLang] || p.name_he || "—";
    const count = p.buildings_inside || 0;
    const id = p.id_norm || p.MisparProj || "";
    const heTitle = (p.name_he && p.name_he !== name) ? p.name_he : name;
    return '<div class="mitcham-item" onclick="zoomToMitcham(\'' + escapeAttr(String(id)) + '\')" title="' + escapeAttr(String(heTitle)) + '">'
      + '<span class="mitcham-flag">🚫</span>'
      + '<span class="mitcham-name">' + escapeHtml(name) + '</span>'
      + '<span class="mitcham-count">' + count + '</span>'
      + '<span class="arrow">→</span>'
      + '</div>';
  }).join("");
  const listEl = document.getElementById("mitchamim-list");
  if (listEl) listEl.innerHTML = html;
  const badge = document.getElementById("mitchamim-count-badge");
  if (badge) badge.textContent = "(" + features.length + " " + t("mitchamim_in_zone") + ")";
}

function zoomToMitcham(id) {
  let target = null;
  mitchamimLayer.eachLayer(layer => {
    const pid = String(layer.feature.properties.id_norm || layer.feature.properties.MisparProj || "");
    if (pid === String(id)) target = layer;
  });
  if (!target) return;
  map.flyToBounds(target.getBounds(), { padding: [60, 60], duration: 0.6 });
  setTimeout(() => target.openPopup(), 600);
}

const buildingsLayer = L.layerGroup().addTo(map);
const markerById = new Map();
const haloLayer = L.layerGroup().addTo(map);
const haloRenderer = L.svg({ padding: 0.5 });

// Hiérarchie visuelle par statut (radius / opacity / stroke)
function getMarkerRadius(b) {
  switch (b.status) {
    case "TOP":      return 11;
    case "INVEST":   return 9;
    case "MARGINAL": return 7;
    case "WEAK":     return 3;
    case "EXCLUDED": return 3;
    default:         return 4;
  }
}
function getMarkerOpacity(b) {
  switch (b.status) {
    case "TOP":      return 0.95;
    case "INVEST":   return 0.90;
    case "MARGINAL": return 0.85;
    case "WEAK":     return 0.45;
    case "EXCLUDED": return 0.30;
    default:         return 0.50;
  }
}
function getMarkerStrokeWeight(b) {
  switch (b.status) {
    case "TOP":      return 2;
    case "INVEST":   return 2;
    case "MARGINAL": return 1.5;
    case "WEAK":     return 0.5;
    case "EXCLUDED": return 0;
    default:         return 1;
  }
}

let selectedBuilding = null;

buildings.forEach(b => {
  const color = STATUS_COLORS[b.status] || "#6B7280";
  const baseRadius  = getMarkerRadius(b);
  const baseOpacity = getMarkerOpacity(b);
  const baseWeight  = getMarkerStrokeWeight(b);
  const m = L.circleMarker([b.lat, b.lon], {
    renderer: canvasRenderer,
    radius: baseRadius,
    fillColor: color, fillOpacity: baseOpacity,
    color: "#FFFFFF",
    weight: baseWeight,
    opacity: baseOpacity,
  });
  m._data = b;
  m._baseRadius  = baseRadius;
  m._baseOpacity = baseOpacity;
  m._baseWeight  = baseWeight;
  m.on("click", () => showBuilding(b));
  m.on("mouseover", e => {
    e.target.setRadius(e.target._baseRadius * 1.8);
    e.target.setStyle({ fillOpacity: 1, opacity: 1, weight: 2 });
    const label = b.addr || (b.score.toFixed(0) + " · " + t(STATUS_LABEL_KEY[b.status] || "legend_weak"));
    e.target.bindTooltip(label, { direction: "top", offset: [0, -6], sticky: true }).openTooltip();
  });
  m.on("mouseout", e => {
    e.target.setRadius(e.target._baseRadius);
    e.target.setStyle({
      fillOpacity: e.target._baseOpacity,
      opacity:     e.target._baseOpacity,
      weight:      e.target._baseWeight,
    });
    e.target.closeTooltip();
  });
  buildingsLayer.addLayer(m);
  markerById.set(b.id, m);
});

// =============== Filters ===============
const state = {
  scoreMin: 0, distMax: 2000,
  showMitchamim: true, top25Only: false, statusFilter: "all",
  showExcluded: false,   // EXCLUDED markers cachés par défaut
  highlightTop: true,    // pulse halo sur top candidats par défaut
};

function applyFilters() {
  let shown = 0, shownTop25 = 0, shownInMitcham = 0;
  buildings.forEach(b => {
    const m = markerById.get(b.id);
    const dist = b.dist == null ? 0 : b.dist;
    const isExcluded = b.status === "EXCLUDED";
    const pass = (
      (b.score || 0) >= state.scoreMin
      && dist <= state.distMax
      && (!state.top25Only || b.topCandidate)
      && (state.statusFilter === "all" || b.status === state.statusFilter)
      && (state.showExcluded || !isExcluded)
    );
    if (pass) {
      if (!buildingsLayer.hasLayer(m)) buildingsLayer.addLayer(m);
      shown++;
      if (b.topCandidate) shownTop25++;
      if (isExcluded) shownInMitcham++;
    } else {
      buildingsLayer.removeLayer(m);
    }
  });
  document.getElementById("stat-shown").textContent = shown;
  document.getElementById("stat-top25").textContent = shownTop25;
  document.getElementById("stat-mitcham").textContent = shownInMitcham;
  renderTopHalos();
}

function initKPIs() {
  const total = buildings.length;
  const candidates = buildings.filter(b => b.status !== "EXCLUDED").length;
  const topCount = getTopCandidatesList().length;
  const mitchamimZones = mitchamimGeoJSON.features.length;
  const excludedCount = buildings.filter(b => b.status === "EXCLUDED").length;

  // KPI cards
  document.getElementById("kpi-total").textContent = total;
  document.getElementById("kpi-candidates").textContent = candidates;
  document.getElementById("kpi-top").textContent = topCount;
  document.getElementById("kpi-excluded").textContent = excludedCount;

  // Footer
  document.getElementById("footer-total").textContent = total;
  document.getElementById("footer-top").textContent = topCount;
  document.getElementById("footer-mitchamim").textContent = mitchamimZones;

  // Legend counts (real counts par status)
  const setCount = (id, n) => {
    const el = document.getElementById(id);
    if (el) el.textContent = "(" + n + ")";
  };
  const byStatus = (st) => buildings.filter(b => b.status === st).length;
  setCount("lc-top",      byStatus("TOP"));
  setCount("lc-invest",   byStatus("INVEST"));
  setCount("lc-marginal", byStatus("MARGINAL"));
  setCount("lc-weak",     byStatus("WEAK"));
  setCount("lc-excluded", excludedCount);
  setCount("lc-zones",    mitchamimZones);
}

// =============== Top candidates halo (pulse) ===============
function renderTopHalos() {
  haloLayer.clearLayers();
  if (!state.highlightTop) return;
  // Halos only on top candidates that are also visible (post-filter)
  const visibleTops = buildings.filter(b => {
    if (!b.topCandidate) return false;
    if (b.status === "EXCLUDED" && !state.showExcluded) return false;
    const dist = b.dist == null ? 0 : b.dist;
    return (b.score || 0) >= state.scoreMin
        && dist <= state.distMax
        && (state.statusFilter === "all" || b.status === state.statusFilter);
  });
  visibleTops.forEach(b => {
    const baseR = getMarkerRadius(b) + 5;
    const halo = L.circleMarker([b.lat, b.lon], {
      renderer: haloRenderer,
      radius: baseR,
      fillOpacity: 0,
      color: "#FFA500",
      weight: 2,
      opacity: 0.85,
      className: "top-halo-marker",
      interactive: false,
    });
    haloLayer.addLayer(halo);
  });
}

// =============== Hover from sidebar list ===============
function highlightMarkerOnHover(id) {
  const m = markerById.get(id);
  if (!m) return;
  m.bringToFront();
  m.setStyle({ weight: 3, color: "#00D4FF", fillOpacity: 1, opacity: 1 });
  m.setRadius(m._baseRadius * 1.8);
}
function unhighlightMarker(id) {
  const m = markerById.get(id);
  if (!m) return;
  m.setStyle({
    weight:      m._baseWeight,
    color:       "#FFFFFF",
    fillOpacity: m._baseOpacity,
    opacity:     m._baseOpacity,
  });
  m.setRadius(m._baseRadius);
}

document.getElementById("score-min").addEventListener("input", e => {
  state.scoreMin = parseFloat(e.target.value);
  document.getElementById("score-val").textContent = state.scoreMin;
  applyFilters();
});
document.getElementById("dist-max").addEventListener("input", e => {
  state.distMax = parseFloat(e.target.value);
  document.getElementById("dist-val").textContent = state.distMax + " m";
  applyFilters();
});
document.getElementById("show-mitchamim").addEventListener("change", e => {
  state.showMitchamim = e.target.checked;
  if (state.showMitchamim) {
    if (!map.hasLayer(mitchamimLayer)) mitchamimLayer.addTo(map);
    if (!map.hasLayer(mitchamLabelsLayer)) mitchamLabelsLayer.addTo(map);
  } else {
    if (map.hasLayer(mitchamimLayer)) map.removeLayer(mitchamimLayer);
    if (map.hasLayer(mitchamLabelsLayer)) map.removeLayer(mitchamLabelsLayer);
  }
});
document.getElementById("show-excluded").addEventListener("change", e => {
  state.showExcluded = e.target.checked;
  applyFilters();
});
document.getElementById("highlight-top").addEventListener("change", e => {
  state.highlightTop = e.target.checked;
  renderTopHalos();
});
document.getElementById("show-redline").addEventListener("change", e => {
  const on = e.target.checked;
  if (on) {
    if (!map.hasLayer(stationsLayer)) stationsLayer.addTo(map);
  } else {
    if (map.hasLayer(stationsLayer)) map.removeLayer(stationsLayer);
  }
});
document.getElementById("top25-only").addEventListener("change", e => {
  state.top25Only = e.target.checked;
  applyFilters();
});
document.getElementById("status-filter").addEventListener("change", e => {
  state.statusFilter = e.target.value;
  applyFilters();
});

// =============== Search ===============
function buildSearchIndex() {
  return buildings.map(b => ({
    b: b,
    searchable: [
      b.gush || "",
      b.helka || "",
      (b.gush && b.helka) ? (b.gush + "/" + b.helka) : "",
      b.addr || ""
    ].join(" ").toLowerCase()
  }));
}
const searchIndex = buildSearchIndex();

// Gush/Helka pattern: "6158/402", "6158 402", "6158-402"
const GH_RE = /^(\d+)\s*[\/\-\s]\s*(\d+)$/;

let _nominatimDebounce = null;
let _geocodeMarker = null;

function performSearch(query) {
  const box = document.getElementById("search-results");
  if (!query || query.trim().length < 2) {
    box.classList.remove("show");
    clearTimeout(_nominatimDebounce);
    return;
  }
  const q = query.toLowerCase().trim();
  const exactGH = q.match(GH_RE);

  // --- local search ---
  let localResults;
  if (exactGH) {
    const g = exactGH[1], h = exactGH[2];
    localResults = searchIndex.filter(it => it.b.gush === g && it.b.helka === h);
  } else {
    localResults = searchIndex.filter(it => it.searchable.includes(q));
  }
  localResults.sort((a, b) => (b.b.score || 0) - (a.b.score || 0));
  localResults = localResults.slice(0, 8);

  if (localResults.length > 0) {
    renderLocalSearchResults(localResults);
    clearTimeout(_nominatimDebounce);
    return;
  }

  // --- no local match → live lookup ---
  box.innerHTML = '<div class="search-result" style="cursor:default;color:var(--text-muted)">🔍 Searching...</div>';
  box.classList.add("show");
  clearTimeout(_nominatimDebounce);
  _nominatimDebounce = setTimeout(() => {
    if (exactGH) {
      showGHNotInZone(exactGH[1], exactGH[2]);
    } else {
      geocodeNominatim(query.trim());
    }
  }, 400);
}

function renderLocalSearchResults(results) {
  const box = document.getElementById("search-results");
  box.innerHTML = results.map(r => {
    const b = r.b;
    const color = STATUS_COLORS[b.status] || "#6B7280";
    const gh = (b.gush && b.helka) ? (b.gush + "/" + b.helka) : "—";
    const addr = b.addr ? escapeHtml(b.addr) : '<i style="opacity:0.5">' + t("no_address") + '</i>';
    return '<div class="search-result" onclick="searchResultClick(\'' + escapeAttr(b.id) + '\')">'
      + '<span class="dot" style="background:' + color + '"></span>'
      + '<span class="gh">' + gh + '</span>'
      + '<span class="addr">' + addr + '</span>'
      + '<span class="score-mini">' + b.score.toFixed(0) + '</span>'
      + '</div>';
  }).join("");
  box.classList.add("show");
}

function showGHNotInZone(gush, helka) {
  const box = document.getElementById("search-results");
  const gmUrl = 'https://www.govmap.gov.il/?c=34.75,32.02&z=10&lay=200720';
  const mvUrl = 'https://mavat.iplan.gov.il/SV3?gush=' + encodeURIComponent(gush) + '&helka=' + encodeURIComponent(helka);
  const tabuUrl = 'https://www.tabu.justice.gov.il/LandRegistrationPortal/ShowCase.aspx?sType=1&SubjectType=2&ScrollAmount=4&Gush=' + encodeURIComponent(gush) + '&Helka=' + encodeURIComponent(helka);
  box.innerHTML =
    '<div class="search-result" style="cursor:default">'
    + '<span class="dot" style="background:#6B7280"></span>'
    + '<span class="gh" style="color:var(--text-muted)">גוש ' + escapeHtml(gush) + '</span>'
    + '<span class="addr" style="color:var(--text-muted)">חלקה ' + escapeHtml(helka) + ' — not in study zone</span>'
    + '</div>'
    + '<div class="search-result" onclick="window.open(\'' + escapeAttr(mvUrl) + '\',\'_blank\')">'
    + '<span class="dot" style="background:#FF8C42"></span>'
    + '<span class="gh" style="color:#FF8C42">Mavat</span>'
    + '<span class="addr">View plans on Mavat (iplan.gov.il) ↗</span>'
    + '</div>'
    + '<div class="search-result" onclick="window.open(\'' + escapeAttr(gmUrl) + '\',\'_blank\')">'
    + '<span class="dot" style="background:#00D4FF"></span>'
    + '<span class="gh" style="color:var(--accent)">GovMap</span>'
    + '<span class="addr">View parcel on GovMap ↗</span>'
    + '</div>'
    + '<div class="search-result" onclick="window.open(\'' + escapeAttr(tabuUrl) + '\',\'_blank\')">'
    + '<span class="dot" style="background:#A78BFA"></span>'
    + '<span class="gh" style="color:#A78BFA">Tabu</span>'
    + '<span class="addr">Ownership records (Tabu) ↗</span>'
    + '</div>';
  box.classList.add("show");
}

function geocodeNominatim(query) {
  const box = document.getElementById("search-results");
  // Append Israel if not already there to focus results
  const qFull = /israel|ישראל/i.test(query) ? query : query + ', Israel';
  fetch(
    'https://nominatim.openstreetmap.org/search?q=' + encodeURIComponent(qFull)
    + '&format=json&limit=5&countrycodes=il&accept-language=he,en',
    { headers: { 'User-Agent': 'PinuiBinuiScout/1.0 (research)' } }
  )
  .then(r => r.json())
  .then(data => {
    if (!data || !data.length) {
      box.innerHTML = '<div class="search-result" style="cursor:default;color:var(--text-muted)">No results found</div>';
      box.classList.add("show");
      return;
    }
    box.innerHTML = data.slice(0, 5).map(item => {
      const lat = parseFloat(item.lat), lon = parseFloat(item.lon);
      const shortName = item.display_name.split(',').slice(0, 3).join(',');
      const latE = escapeAttr(String(lat)), lonE = escapeAttr(String(lon));
      const nameE = escapeAttr(item.display_name);
      return '<div class="search-result" onclick="gotoGeocode(' + lat + ',' + lon + ',\'' + nameE + '\')">'
        + '<span class="dot" style="background:#00D4FF;border:1.5px solid #fff"></span>'
        + '<span class="gh" style="color:var(--accent)">📍</span>'
        + '<span class="addr">' + escapeHtml(shortName) + '</span>'
        + '</div>';
    }).join("");
    box.classList.add("show");
  })
  .catch(() => {
    box.innerHTML = '<div class="search-result" style="cursor:default;color:var(--text-muted)">Search failed — check internet connection</div>';
    box.classList.add("show");
  });
}

function gotoGeocode(lat, lon, fullName) {
  map.flyTo([lat, lon], 17, { duration: 0.6 });
  if (_geocodeMarker) { map.removeLayer(_geocodeMarker); _geocodeMarker = null; }
  const shortName = escapeHtml(fullName.split(',').slice(0, 2).join(','));
  const gmUrl = 'https://www.govmap.gov.il/?c=' + lon + ',' + lat + '&z=10';
  _geocodeMarker = L.circleMarker([lat, lon], {
    radius: 12, fillColor: "#00D4FF", fillOpacity: 0.85,
    color: "#FFFFFF", weight: 2, opacity: 1,
  }).addTo(map).bindPopup(
    '<b>📍 ' + shortName + '</b>'
    + '<br><small style="color:#8B9BB4">Nominatim geocode result</small>'
    + '<br><a href="' + escapeAttr(gmUrl) + '" target="_blank" rel="noopener" style="color:#00D4FF">View on GovMap ↗</a>',
    { maxWidth: 300 }
  );
  setTimeout(() => { if (_geocodeMarker) _geocodeMarker.openPopup(); }, 650);
  document.getElementById("search-input").value = "";
  document.getElementById("search-results").classList.remove("show");
}

function searchResultClick(id) {
  const b = buildings.find(x => x.id === id);
  if (!b) return;
  // Remove any geocode pin when clicking a local result
  if (_geocodeMarker) { map.removeLayer(_geocodeMarker); _geocodeMarker = null; }
  map.flyTo([b.lat, b.lon], 18, { duration: 0.5 });
  setTimeout(() => showBuilding(b), 400);
  document.getElementById("search-input").value = "";
  document.getElementById("search-results").classList.remove("show");
}

document.addEventListener("click", e => {
  if (!e.target.closest(".search-box")) {
    document.getElementById("search-results").classList.remove("show");
  }
});
document.getElementById("search-input").addEventListener("input", e => performSearch(e.target.value));
document.getElementById("search-input").addEventListener("focus", e => {
  if (e.target.value.trim()) performSearch(e.target.value);
});

// =============== Top Candidats ===============
function getTopCandidatesList() {
  const sorted = [...buildings].filter(b => b.status !== "EXCLUDED").sort((a, b) => (b.score || 0) - (a.score || 0));
  const aboveThreshold = sorted.filter(b => (b.score || 0) > 30);
  if (aboveThreshold.length >= 25) return aboveThreshold;
  return sorted.slice(0, 25);
}

function renderTopCandidates() {
  const items = getTopCandidatesList();
  const groups = {};
  items.forEach(b => {
    const g = b.gush || "N/A";
    if (!groups[g]) groups[g] = [];
    groups[g].push(b);
  });
  const sortedGushes = Object.keys(groups).sort((a, b) => {
    const bestA = Math.max.apply(null, groups[a].map(x => x.score || 0));
    const bestB = Math.max.apply(null, groups[b].map(x => x.score || 0));
    return bestB - bestA;
  });
  const html = sortedGushes.map(g => {
    const arr = groups[g].sort((a, b) => (b.score || 0) - (a.score || 0));
    const header = '<div class="gush-group-header">Gush ' + escapeHtml(g) + '</div>';
    const itemsHtml = arr.map(b => {
      const color = STATUS_COLORS[b.status] || "#6B7280";
      const gh = (b.gush && b.helka) ? (b.gush + "/" + b.helka) : "—";
      const addr = b.addr ? escapeHtml(b.addr) : '<i style="opacity:0.45">(' + t("no_address") + ')</i>';
      const idAttr = escapeAttr(b.id);
      return '<div class="gush-group-item"'
        + ' onclick="searchResultClick(\'' + idAttr + '\')"'
        + ' onmouseenter="highlightMarkerOnHover(\'' + idAttr + '\')"'
        + ' onmouseleave="unhighlightMarker(\'' + idAttr + '\')">'
        + '<span class="dot" style="background:' + color + '"></span>'
        + '<span class="gh-mini">' + gh + '</span>'
        + '<span class="addr-mini">' + addr + '</span>'
        + '<span class="arrow">→</span></div>';
    }).join("");
    return '<div class="gush-group">' + header + itemsHtml + '</div>';
  }).join("");
  document.getElementById("top-candidates-list").innerHTML = html;
}

function copyAllGH() {
  const items = getTopCandidatesList();
  const list = items.filter(b => b.gush && b.helka)
    .map(b => b.gush + "/" + b.helka).join(", ");
  copyToClipboard(list, t("copied_all_toast"));
}

function copyGH(gh) { copyToClipboard(gh, t("copied_toast")); }

function copyToClipboard(text, toastMsg) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => showToast(toastMsg));
  } else {
    // Fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); showToast(toastMsg); } catch (e) {}
    document.body.removeChild(ta);
  }
}

function showToast(msg) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove("show"), 2200);
}

// =============== Building panel ===============
function showBuilding(b) {
  selectedBuilding = b;
  const color = STATUS_COLORS[b.status] || "#6B7280";
  const statusLabel = t(STATUS_LABEL_KEY[b.status] || "legend_weak");
  const hasGushHelka = b.gush && b.helka;
  const ghStr = hasGushHelka ? (b.gush + "/" + b.helka) : "";

  const sv = "https://www.google.com/maps/@" + b.lat + "," + b.lon + ",3a,75y,0h,90t/data=!3m6!1e1";
  const gm = "https://www.govmap.gov.il/?c=" + b.lon + "," + b.lat + "&z=10";
  const mv = hasGushHelka ? ("https://mavat.iplan.gov.il/SV3?gush=" + b.gush + "&helka=" + b.helka) : null;

  const addrHtml = b.addr
    ? '<div class="panel-addr">' + escapeHtml(b.addr) + '</div>'
    : '<div class="panel-addr empty"><i>' + t("no_address") + '</i></div>';

  const ghBlock = hasGushHelka ? (
    '<div class="gush-helka-block">'
    + '<div class="gush-helka-label">' + t("gush_helka") + '</div>'
    + '<div class="gush-helka-value">'
    +   '<span class="gh-number">' + b.gush + ' / ' + b.helka + '</span>'
    +   '<button class="btn-copy-gh" onclick="copyGH(\'' + ghStr + '\')" title="' + t("btn_copy") + '">📋</button>'
    + '</div></div>'
  ) : "";

  const html = ''
    + '<div class="panel-score" style="color:' + color + '">' + b.score.toFixed(1) + '</div>'
    + '<span class="panel-status" style="background:' + color + '20;color:' + color + ';border:1px solid ' + color + '">' + statusLabel + '</span>'
    + (b.top25 ? '<span class="panel-top25">' + t("top25_badge") + '</span>' : '')
    + addrHtml
    + ghBlock
    + '<table class="panel-table">'
    + '<tr><td>' + t("floors") + '</td><td>' + fmt(b.floors) + '</td></tr>'
    + '<tr><td>' + t("year_built") + '</td><td' + (b.year_built ? '' : ' class="warn"') + '>' + fmt(b.year_built) + '</td></tr>'
    + '<tr><td>' + t("land_area") + '</td><td>' + fmt(b.surface_parcelle_m2, " m²") + '</td></tr>'
    + '<tr><td>' + t("footprint") + '</td><td>' + fmt(b.emprise_m2, " m²") + '</td></tr>'
    + '<tr><td>' + t("ratio") + '</td><td class="highlight">' + fmt(b.ratio) + '</td></tr>'
    + '<tr><td>' + t("dist_balfour") + '</td><td>' + fmt(b.dist, " m") + '</td></tr>'
    + '<tr><td>' + t("neighbors") + '</td><td>' + b.neighbors + '</td></tr>'
    + (b.mitcham ? '<tr><td>' + t("mitcham_label") + '</td><td class="warn">' + escapeHtml(b.mitcham) + '</td></tr>' : '')
    + '</table>'
    + (b.year_built ? '' : (
        '<div class="warning-box">'
        + '<strong>⚠ ' + t("validation_required") + '</strong>'
        + t("validation_note")
        + '</div>'))
    + '<a href="' + sv + '" target="_blank" rel="noopener" class="btn-primary">' + t("btn_streetview") + '</a>'
    + '<a href="' + gm + '" target="_blank" rel="noopener" class="btn-secondary">' + t("btn_govmap") + '</a>'
    + (mv ? '<a href="' + mv + '" target="_blank" rel="noopener" class="btn-secondary">' + t("btn_mavat") + '</a>' : '')
    + '<a href="https://b-yam.co.il" target="_blank" rel="noopener" class="btn-hitchadshut" title="' + t("hitchadshut_tooltip") + '">' + t("link_hitchadshut") + '</a>';

  document.getElementById("panel-content").innerHTML = html;
  const panel = document.getElementById("panel");
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
  map.panTo([b.lat, b.lon], { animate: true });
}

function closePanel() {
  const panel = document.getElementById("panel");
  panel.classList.remove("open");
  panel.setAttribute("aria-hidden", "true");
  selectedBuilding = null;
}

// =============== Modal tableau ===============
let modalSortKey = "score";
let modalSortDesc = true;
let modalFilter = "";

function openTableModal() {
  document.getElementById("modal-backdrop").classList.add("open");
  renderModalTable();
}
function closeTableModal() {
  document.getElementById("modal-backdrop").classList.remove("open");
}
function modalBackdropClick(event) {
  if (event.target.id === "modal-backdrop") closeTableModal();
}

function renderModalTable() {
  const cols = [
    { key: "rank",   labelKey: "col_rank",     fmt: (b, i) => "#" + (i + 1) },
    { key: "score",  labelKey: "col_score",    fmt: b => b.score.toFixed(1) },
    { key: "status", labelKey: "col_status",   fmt: b => {
        const c = STATUS_COLORS[b.status] || "#6B7280";
        return '<span class="status-pill" style="background:' + c + '20;color:' + c + '">' + b.status + '</span>';
    } },
    { key: "gush",   labelKey: "col_gush",     fmt: b => b.gush || "—" },
    { key: "helka",  labelKey: "col_helka",    fmt: b => b.helka || "—" },
    { key: "addr",   labelKey: "col_address",  fmt: b => escapeHtml(b.addr || ""), cls: "addr-col" },
    { key: "floors", labelKey: "col_floors",   fmt: b => b.floors == null ? "—" : b.floors },
    { key: "surface_parcelle_m2", labelKey: "col_land", fmt: b => b.surface_parcelle_m2 == null ? "—" : b.surface_parcelle_m2 },
    { key: "emprise_m2", labelKey: "col_footprint",     fmt: b => b.emprise_m2 == null ? "—" : b.emprise_m2 },
    { key: "ratio",  labelKey: "col_ratio",    fmt: b => b.ratio == null ? "—" : b.ratio },
    { key: "dist",   labelKey: "col_dist",     fmt: b => b.dist == null ? "—" : b.dist.toFixed(0) },
  ];

  // Header
  const thead = "<tr>" + cols.map(c => {
    const arrow = c.key === modalSortKey ? (modalSortDesc ? " ▼" : " ▲") : "";
    const cls = c.key === modalSortKey ? "sorted" : "";
    return '<th class="' + cls + '" onclick="sortModalTable(\'' + c.key + '\')">' + t(c.labelKey) + arrow + '</th>';
  }).join("") + "</tr>";
  document.querySelector("#modal-table thead").innerHTML = thead;

  // Filter
  const q = modalFilter.toLowerCase();
  let rows = q ? buildings.filter(b => {
    const s = [b.gush, b.helka, b.gush && b.helka ? b.gush + "/" + b.helka : "",
               b.addr, b.status].join(" ").toLowerCase();
    return s.includes(q);
  }) : [...buildings];

  // Sort (rank is a virtual column, sort by score desc instead)
  const sortKeyEffective = modalSortKey === "rank" ? "score" : modalSortKey;
  rows.sort((a, b) => {
    let va = a[sortKeyEffective], vb = b[sortKeyEffective];
    if (sortKeyEffective === "gush" || sortKeyEffective === "helka") {
      va = va ? parseInt(va, 10) : -1;
      vb = vb ? parseInt(vb, 10) : -1;
    }
    if (va == null) va = -Infinity;
    if (vb == null) vb = -Infinity;
    if (typeof va === "string" && typeof vb === "string") {
      return modalSortDesc ? vb.localeCompare(va) : va.localeCompare(vb);
    }
    return modalSortDesc ? (vb - va) : (va - vb);
  });

  const tbody = rows.map((b, i) => {
    return '<tr onclick="modalRowClick(\'' + escapeAttr(b.id) + '\')">'
      + cols.map(c => '<td class="' + (c.cls || "") + '">' + c.fmt(b, i) + '</td>').join("")
      + '</tr>';
  }).join("");
  document.querySelector("#modal-table tbody").innerHTML = tbody;
}

function sortModalTable(key) {
  if (modalSortKey === key) modalSortDesc = !modalSortDesc;
  else { modalSortKey = key; modalSortDesc = true; }
  renderModalTable();
}

function modalRowClick(id) {
  const b = buildings.find(x => x.id === id);
  if (!b) return;
  closeTableModal();
  map.flyTo([b.lat, b.lon], 18, { duration: 0.5 });
  setTimeout(() => showBuilding(b), 400);
}

function exportCSV() {
  const cols = ["rank", "score", "status", "gush", "helka", "addr",
                "floors", "year_built", "surface_parcelle_m2",
                "emprise_m2", "ratio", "dist", "neighbors", "mitcham",
                "lat", "lon"];
  const sorted = [...buildings].sort((a, b) => (b.score || 0) - (a.score || 0));
  const header = cols.join(",");
  const rows = sorted.map((b, i) => cols.map(c => {
    if (c === "rank") return i + 1;
    let v = b[c];
    if (v == null) return "";
    v = String(v).replace(/"/g, '""');
    return /[",\n]/.test(v) ? '"' + v + '"' : v;
  }).join(","));
  const csv = [header].concat(rows).join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "ramat_yosef_nord_export.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function exportGHList() {
  const list = buildings
    .filter(b => b.gush && b.helka && b.status !== "EXCLUDED")
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .map(b => b.gush + "/" + b.helka)
    .join(", ");
  copyToClipboard(list, t("copied_all_toast"));
}

document.getElementById("modal-search").addEventListener("input", e => {
  modalFilter = e.target.value;
  renderModalTable();
});

// =============== Draw Zone ===============
const DZ_SERVER = window.location.protocol === "file:"
  ? "http://127.0.0.1:8765"
  : window.location.origin;
let _drawControl = null;
let _drawnItems  = null;
let _drawActive  = false;
let _dzPolygon   = null;  // GeoJSON polygon from last draw

function dzFetchWithTimeout(url, options = {}, timeoutMs = 1500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const merged = { ...options, signal: controller.signal };
  return fetch(url, merged).finally(() => clearTimeout(timer));
}

function toggleDrawZone() {
  const btn = document.getElementById("draw-zone-btn");
  if (_drawActive) {
    if (_drawControl) { map.removeControl(_drawControl); _drawControl = null; }
    if (_drawnItems)  { map.removeLayer(_drawnItems);   _drawnItems  = null; }
    _drawActive = false;
    btn.style.background = "";
    btn.style.color = "";
    return;
  }
  _drawActive = true;
  btn.style.background = "var(--accent)";
  btn.style.color = "#000";

  _drawnItems = new L.FeatureGroup();
  map.addLayer(_drawnItems);

  _drawControl = new L.Control.Draw({
    draw: {
      polygon: {
        allowIntersection: false,
        shapeOptions: { color: "#00D4FF", fillOpacity: 0.12 },
        showArea: true,
      },
      polyline: false, rectangle: false, circle: false,
      circlemarker: false, marker: false,
    },
    edit: { featureGroup: _drawnItems, remove: false },
  });
  map.addControl(_drawControl);
  new L.Draw.Polygon(map, _drawControl.options.draw.polygon).enable();

  map.once(L.Draw.Event.CREATED, function(e) {
    _drawnItems.addLayer(e.layer);
    if (_drawControl) { map.removeControl(_drawControl); _drawControl = null; }
    _drawActive = false;
    btn.style.background = "";
    btn.style.color = "";

    const latlngs = e.layer.getLatLngs()[0];
    const coords = latlngs.map(p => [
      parseFloat(p.lng.toFixed(6)),
      parseFloat(p.lat.toFixed(6))
    ]);
    coords.push(coords[0]);
    _dzPolygon = { type: "Polygon", coordinates: [coords] };

    // Populate fallback snippet
    document.getElementById("draw-zone-output").textContent =
      "STUDY_POLYGON_WGS84 = {\n"
      + '    "type": "Polygon",\n'
      + '    "coordinates": [[\n'
      + coords.map(c => "        [" + c[0] + ", " + c[1] + "],").join("\n")
      + "\n    ]],\n}";

    // Show modal, then check if server is running
    ["server","progress","fallback"].forEach(p =>
      document.getElementById("dz-panel-" + p).style.display = "none"
    );
    document.getElementById("draw-zone-modal").style.display = "flex";
    dzCheckServer();
  });
}

function dzCheckServer() {
  dzFetchWithTimeout(DZ_SERVER + "/ping")
    .then(r => r.ok ? dzShowPanel("server") : dzShowPanel("fallback"))
    .catch(() => dzShowPanel("fallback"));
}

function dzShowPanel(name) {
  ["server","progress","fallback"].forEach(p =>
    document.getElementById("dz-panel-" + p).style.display = p === name ? "block" : "none"
  );
}

function dzRunPipeline() {
  dzShowPanel("progress");
  document.getElementById("dz-log").textContent = "";
  document.getElementById("dz-done-msg").style.display = "none";
  document.getElementById("dz-error-msg").style.display = "none";

  fetch(DZ_SERVER + "/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ polygon: _dzPolygon }),
  })
  .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
  .then(({ job_id, error }) => {
    if (!job_id) {
      throw new Error(error || "Server did not return a job id");
    }
    dzPoll(job_id);
  })
  .catch(err => {
    document.getElementById("dz-log").textContent = "Could not reach server: " + err;
    document.getElementById("dz-error-msg").style.display = "block";
  });
}

function dzPoll(jobId) {
  const logEl = document.getElementById("dz-log");
  const iv = setInterval(() => {
    fetch(DZ_SERVER + "/poll/" + jobId)
      .then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)))
      .then(({ status, log }) => {
        logEl.textContent = log.join("\n");
        logEl.scrollTop = logEl.scrollHeight;
        if (status === "done") {
          clearInterval(iv);
          document.getElementById("dz-done-msg").style.display = "block";
          setTimeout(() => location.reload(), 1800);
        } else if (status === "error") {
          clearInterval(iv);
          document.getElementById("dz-error-msg").style.display = "block";
        }
      })
      .catch(err => {
        clearInterval(iv);
        logEl.textContent += (logEl.textContent ? "\n" : "") + "Polling failed: " + err;
        document.getElementById("dz-error-msg").style.display = "block";
      });
  }, 1000);
}

function closeDrawModal() {
  document.getElementById("draw-zone-modal").style.display = "none";
  if (_drawnItems) { map.removeLayer(_drawnItems); _drawnItems = null; }
}

function copyDrawZone() {
  const text = document.getElementById("draw-zone-output").textContent;
  navigator.clipboard.writeText(text).then(() => showToast("Copied!"));
}

// =============== Presentation mode + keyboard ===============
let presenting = false;
function togglePresentation() {
  presenting = !presenting;
  document.body.classList.toggle("presenting", presenting);
  setTimeout(() => map.invalidateSize(), 350);
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (document.getElementById("draw-zone-modal").style.display === "flex") {
      closeDrawModal(); return;
    }
    if (document.getElementById("modal-backdrop").classList.contains("open")) {
      closeTableModal();
      return;
    }
    if (presenting) { togglePresentation(); return; }
    closePanel();
  } else if ((e.key === "p" || e.key === "P")
             && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    togglePresentation();
  }
});

function recenterMap() {
  map.fitBounds(studyLayer.getBounds(), { padding: [40, 40] });
}
function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
}

// =============== Boot ===============
setLang("fr");
initKPIs();
applyFilters();
renderTopCandidates();
renderMitchamimList();
setTimeout(() => recenterMap(), 100);
</script>
</body>
</html>
"""


def render(out_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"[PREMIUM] loading geojson...")
    gj_path = config.OUTPUTS / "ramat_yosef_nord_phase3.geojson"
    if not gj_path.exists():
        raise FileNotFoundError(
            f"{gj_path} introuvable. Lancez d'abord :\n  python -m src.pipeline --label full")
    buildings = gpd.read_file(gj_path)
    print(f"[PREMIUM] {len(buildings)} buildings loaded")

    buildings_data = build_buildings_data(buildings)
    mitchamim_gj = build_mitchamim_geojson(config.STUDY_POLYGON_WGS84, buildings_data)
    print(f"[PREMIUM] {len(mitchamim_gj['features'])} mitchamim loaded")

    station = {
        "lat": config.BALFOUR_STATION["lat"],
        "lon": config.BALFOUR_STATION["lon"],
        "name_fr": config.BALFOUR_STATION["name_fr"],
        "name_en": config.BALFOUR_STATION["name_en"],
    }

    # Red Line Bat Yam — 9 stations + tracé approximatif (Overpass bloqué
    # côté sandbox, hardcoded fallback). Balfour ancrée sur ses coords OSM
    # confirmées (32.0270, 34.7452) ; autres stations approximées sur le
    # tracé NTA officiel rue Rothschild → Balfour → Yoseftal → Kommemiyout.
    red_line_stations = [
        {"lat": 32.0297, "lon": 34.7409, "name_he": "העצמאות",
         "name_fr": "Atzma'ut",    "name_en": "Atzma'ut"},
        {"lat": 32.0283, "lon": 34.7445, "name_he": "רוטשילד",
         "name_fr": "Rothschild",  "name_en": "Rothschild"},
        {"lat": 32.0278, "lon": 34.7450, "name_he": "ז'בוטינסקי",
         "name_fr": "Jabotinsky",  "name_en": "Jabotinsky"},
        {"lat": 32.0270, "lon": 34.7452, "name_he": "בלפור",
         "name_fr": "Balfour",     "name_en": "Balfour", "primary": True},
        {"lat": 32.0244, "lon": 34.7480, "name_he": "בנימין",
         "name_fr": "Binyamin",    "name_en": "Binyamin"},
        {"lat": 32.0210, "lon": 34.7530, "name_he": "יוספטל",
         "name_fr": "Yoseftal",    "name_en": "Yoseftal"},
        {"lat": 32.0173, "lon": 34.7580, "name_he": "כ\"ט בנובמבר",
         "name_fr": "29 Novembre", "name_en": "29 November"},
        {"lat": 32.0135, "lon": 34.7625, "name_he": "העמל",
         "name_fr": "Amal",        "name_en": "Amal"},
        {"lat": 32.0095, "lon": 34.7670, "name_he": "הקוממיות",
         "name_fr": "Kommemiyout", "name_en": "Kommemiyout"},
    ]
    # v6 : polyline retirée (tracé approximatif), on ne garde que les
    # markers des 9 stations. Le placeholder __RED_LINE_PATH__ reste
    # défini pour rétrocompat mais n'est plus utilisé côté JS.
    red_line_path = []

    html = (TEMPLATE
            .replace("__BUILDINGS__", json.dumps(buildings_data, ensure_ascii=False))
            .replace("__MITCHAMIM__", json.dumps(mitchamim_gj, ensure_ascii=False))
            .replace("__STATION__", json.dumps(station, ensure_ascii=False))
            .replace("__RED_LINE_STATIONS__", json.dumps(red_line_stations, ensure_ascii=False))
            .replace("__RED_LINE_PATH__", json.dumps(red_line_path))
            .replace("__STUDY_POLYGON__", json.dumps(config.STUDY_POLYGON_WGS84))
            .replace("__GENERATED_DATE__", dt.datetime.now().strftime("%Y-%m-%d")))

    out_path.write_text(html, encoding="utf-8")
    print(f"[PREMIUM] written {out_path} ({len(html)/1024:.0f} KB)")


def main() -> int:
    out = config.OUTPUTS / "ramat_yosef_nord_premium.html"
    render(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
