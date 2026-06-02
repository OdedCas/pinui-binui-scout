"""
Phase 3 — Exports finaux bilingues FR/EN.

3 livrables :
  - outputs/ramat_yosef_nord_phase3.xlsx   (6 onglets)
  - outputs/ramat_yosef_nord_phase3.geojson
  - outputs/ramat_yosef_nord_phase3_carte.html (Folium interactif)
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
from branca.colormap import LinearColormap
from folium.plugins import MarkerCluster
from shapely.geometry import shape

import config
from src.score import DEGRADED_MODE

log = logging.getLogger(__name__)

WGS = "EPSG:4326"
ITM = "EPSG:2039"

STREETVIEW_URL = (
    "https://www.google.com/maps/@{lat},{lon},3a,75y,0h,90t/data=!3m6!1e1"
)

# Mapping des statuts vers couleurs/icônes
STATUS_COLORS = {
    "TOP":      "#1a9641",
    "INVEST":   "#fdae61",
    "MARGINAL": "#f17c46",
    "WEAK":     "#bdbdbd",
    "EXCLUDED": "#d7191c",
}
STATUS_LABEL_FR = {
    "TOP": "🟢 Top opportunité", "INVEST": "🟡 À creuser",
    "MARGINAL": "🟠 Marginal", "WEAK": "⚪ Faible",
    "EXCLUDED": "🔴 Exclu (mitcham actif)",
}
STATUS_LABEL_EN = {
    "TOP": "🟢 Top opportunity", "INVEST": "🟡 To investigate",
    "MARGINAL": "🟠 Marginal", "WEAK": "⚪ Weak",
    "EXCLUDED": "🔴 Excluded (active urban renewal)",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _add_streetview(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Calcul centroïdes en ITM puis reprojection WGS pour précision."""
    # Centroïde en ITM (projection métrique) puis WGS pour le résultat
    centroids_itm = gdf.to_crs(ITM).geometry.centroid
    centroids_wgs = gpd.GeoSeries(centroids_itm, crs=ITM).to_crs(WGS)
    g = gdf.to_crs(WGS).copy()
    g["lat"] = centroids_wgs.y.round(6).values
    g["lon"] = centroids_wgs.x.round(6).values
    g["streetview"] = [STREETVIEW_URL.format(lat=la, lon=lo)
                       for la, lo in zip(g["lat"], g["lon"])]
    return g


def _stringify_timestamps(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Folium GeoJson n'accepte pas pd.Timestamp → convertir en str ISO."""
    g = gdf.copy()
    for col in g.columns:
        if col == "geometry":
            continue
        if pd.api.types.is_datetime64_any_dtype(g[col]):
            g[col] = g[col].astype(str).replace({"NaT": None})
    return g


def _govmap_url(lat: float, lon: float) -> str:
    return f"https://www.govmap.gov.il/?c={lon},{lat}&z=10"


# ---------------------------------------------------------------------------
# Excel (6 onglets bilingues)
# ---------------------------------------------------------------------------
def export_xlsx(
    buildings: gpd.GeoDataFrame,
    mitchamim_csv: pd.DataFrame,
    parcels: gpd.GeoDataFrame,
    source: str,
    cadastre_name: str,
    polygon_wgs: dict,
    out_path: Path,
    top_n: int = 25,
) -> None:
    log.info("[EXPORT] xlsx → %s", out_path)
    g = _add_streetview(buildings)

    # --- Top N ---
    top = g.sort_values("score", ascending=False).head(top_n).copy()
    top["validation_age_required_FR_EN"] = "Oui / Yes"
    top["notes_FR_EN"] = ""
    top["lien_govmap"] = [_govmap_url(la, lo) for la, lo in zip(top["lat"], top["lon"])]
    top_cols = [
        "osm_id", "addr", "gush", "helka", "floors",
        "surface_parcelle_m2", "emprise_m2", "ratio_parcel_emprise",
        "dist_station_m", "neighbors_similar", "score", "status",
        "validation_age_required_FR_EN", "streetview", "lien_govmap",
        "lat", "lon", "notes_FR_EN",
    ]
    top_df = top[[c for c in top_cols if c in top.columns]].copy()
    top_df = top_df.rename(columns={
        "osm_id":               "OSM ID",
        "addr":                 "Adresse / Address",
        "gush":                 "Gush",
        "helka":                "Helka",
        "floors":               "Étages / Floors",
        "surface_parcelle_m2":  "Surface parcelle m² / Land area m²",
        "emprise_m2":           "Emprise bâti m² / Footprint m²",
        "ratio_parcel_emprise": "Ratio parcelle/emprise / Land/footprint ratio",
        "dist_station_m":       "Distance station Balfour m / Distance to Balfour station m",
        "neighbors_similar":    "Voisins similaires / Similar neighbors",
        "score":                "Score (/100)",
        "status":               "Statut / Status",
        "validation_age_required_FR_EN": "Validation âge requise / Manual age validation",
        "streetview":           "Google Street View",
        "lien_govmap":          "Lien GovMap / GovMap link",
        "lat":                  "Latitude (WGS84)",
        "lon":                  "Longitude (WGS84)",
        "notes_FR_EN":          "Notes",
    })

    # --- Tous résultats ---
    all_cols = [
        "osm_id", "addr", "gush", "helka", "year_built", "floors", "type",
        "emprise_m2", "surface_parcelle_m2", "ratio_parcel_emprise",
        "dist_station_m", "neighbors_similar", "score", "status",
        "mitcham_name", "urban_renewal_active", "lat", "lon",
    ]
    all_df = g[[c for c in all_cols if c in g.columns]].sort_values(
        "score", ascending=False
    )

    # --- Statistiques ---
    stats_rows: list[dict] = []

    def _stat(name_fr, name_en, value):
        stats_rows.append({
            "Métrique / Metric": f"{name_fr} / {name_en}",
            "Valeur / Value": value,
        })

    n = len(g)
    excluded = (g["status"] == "EXCLUDED").sum() if "status" in g.columns else 0
    _stat("Bâtiments scannés total", "Total buildings scanned", int(n))
    _stat("Bâtiments exclus (mitcham actif)", "Excluded buildings (active mitcham)",
          int(excluded))
    _stat("Bâtiments candidats (hors mitcham)", "Candidate buildings (outside mitcham)",
          int(n - excluded))
    _stat("% match parcelle cadastrale", "% with cadastral parcel match",
          f"{100*g['gush'].notna().sum()/n:.1f}%" if n else "0%")
    if "score" in g.columns and n:
        _stat("Score min", "Score min", float(g["score"].min()))
        _stat("Score max", "Score max", float(g["score"].max()))
        _stat("Score médian", "Score median", float(g["score"].median()))
        _stat("Score moyen", "Score mean", round(float(g["score"].mean()), 1))
    for code in ("TOP", "INVEST", "MARGINAL", "WEAK", "EXCLUDED"):
        if "status" in g.columns:
            cnt = int((g["status"] == code).sum())
            _stat(f"  Statut {STATUS_LABEL_FR[code]}",
                  f"Status {STATUS_LABEL_EN[code]}", cnt)
    if "ratio_parcel_emprise" in g.columns:
        r = pd.to_numeric(g["ratio_parcel_emprise"], errors="coerce").dropna()
        if len(r):
            _stat("Ratio médian (hors NaN)", "Median ratio", float(r.median()))
            _stat("Ratio max", "Max ratio", float(r.max()))
    stats_df = pd.DataFrame(stats_rows)

    # --- Mitchamim actifs Bat Yam ---
    mitch_cols_keep = [c for c in (
        "ShemMitcham", "MisparTochnit", "Status",
        "YachadKayam", "YachadTosafti", "YachadMutza",
        "TaarichHachraza", "Maslul",
    ) if c in mitchamim_csv.columns]
    mitch_df = mitchamim_csv[mitch_cols_keep].rename(columns={
        "ShemMitcham":    "Nom mitcham / Compound name (HE)",
        "MisparTochnit":  "N° TBV / Plan number",
        "Status":         "Statut / Status (HE)",
        "YachadKayam":    "Logements existants / Existing units",
        "YachadTosafti":  "Logements ajoutés / Added units",
        "YachadMutza":    "Logements total / Total units",
        "TaarichHachraza": "Date déclaration / Declaration date",
        "Maslul":         "Filière / Pathway",
    })

    # --- Cover ---
    cover_rows = [
        ("Projet / Project",
         "Pinui-Binui Scout — Ramat Yosef Nord, Bat Yam"),
        ("Date d'exécution / Execution date",
         dt.datetime.now().isoformat(timespec="seconds")),
        ("Périmètre / Scope",
         "Polygone Ramat Yosef Nord 0.85 km² (7 sommets, station Balfour incluse NW)"),
        ("Source bâti / Buildings source", source),
        ("Source cadastre / Cadastre source",
         f"data.gov.il — {cadastre_name} (Mapi)"),
        ("Source mitchamim / Urban renewal source",
         "data.gov.il urban_renewal_mitchamim (Ministry of Housing) + officiallydeclaredprojects.zip"),
        ("Mode scoring / Scoring mode",
         "FULL — tous critères actifs (plafond 100)" if not DEGRADED_MODE
         else "DEGRADED — ratio désactivé (plafond 75)"),
        ("Critères / Criteria",
         "année <1980 (+30) | étages 3-5 (+20) | ratio parcelle/emprise (+25 max) | "
         "<500m station (+15) ou <1000m (+8) | ≥3 voisins similaires (+10) | "
         "EXCLUSION si mitcham actif"),
        ("LIMITATION — year_built",
         "⚠ Tag OSM year_built absent à ~100% à Bat Yam — validation âge à faire "
         "manuellement via Google Street View pour le Top 25. "
         "Plan upgrade : email info@mapi.gov.il pour clé API officielle."),
        ("Filtre outlier appliqué / Outlier filter applied",
         f"Parcelles > {config.PARCEL_OUTLIER_MAX_M2} m² nullifiées "
         "(probablement non-résidentielles : écoles, parcs, équipements publics)"),
    ]
    cover_df = pd.DataFrame(cover_rows, columns=["Champ / Field", "Valeur / Value"])

    # --- Sources & limitations ---
    sources_rows = [
        ("urban_renewal_mitchamim",
         "data.gov.il CKAN datastore_search (resource f65a0daf-…)",
         "weekly", "37 mitchamim Bat Yam"),
        ("officiallydeclaredprojects",
         "data.gov.il bulk SHP via dépôt manuel "
         "(resource ceb7bbb0-…, IAP-protected)",
         "monthly", "~900 mitchamim nationaux"),
        ("helkot (cadastre)",
         f"data.gov.il bulk SHP via dépôt manuel ({cadastre_name})",
         "monthly", f"~3-5M parcelles nationales, {len(parcels)} dans la zone"),
        ("OSM Overpass",
         "https://overpass-api.de/api/interpreter (way[building=*])",
         "live", f"{n} bâtiments retournés"),
        ("Station Balfour",
         "OSM ways triangulation (1187640542, 1189446349, 1187640543)",
         "static", "32.0270 N, 34.7452 E"),
    ]
    sources_df = pd.DataFrame(sources_rows, columns=[
        "Dataset", "URL / Mécanisme", "Refresh", "Couverture / Coverage",
    ])

    # --- Write Excel ---
    with pd.ExcelWriter(out_path, engine="openpyxl") as xl:
        cover_df.to_excel(xl, sheet_name="Cover", index=False)
        top_df.to_excel(xl, sheet_name="Top_25", index=False)
        all_df.to_excel(xl, sheet_name="Tous_resultats", index=False)
        mitch_df.to_excel(xl, sheet_name="Mitchamim_actifs", index=False)
        stats_df.to_excel(xl, sheet_name="Statistiques", index=False)
        sources_df.to_excel(xl, sheet_name="Sources", index=False)

    log.info("[EXPORT] xlsx written (%d sheets)", 6)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
def export_geojson(buildings: gpd.GeoDataFrame, out_path: Path) -> None:
    log.info("[EXPORT] geojson → %s", out_path)
    g = buildings.to_crs(WGS).copy()
    # Cast tous les types non-sérialisables
    for col in g.columns:
        if col == "geometry":
            continue
        if g[col].dtype == "object":
            g[col] = g[col].astype(str).replace({"nan": None, "None": None, "NaT": None})
    if out_path.exists():
        out_path.unlink()
    g.to_file(out_path, driver="GeoJSON")


# ---------------------------------------------------------------------------
# Folium HTML map
# ---------------------------------------------------------------------------
def export_html(
    buildings: gpd.GeoDataFrame,
    mitchamim_polys: gpd.GeoDataFrame,
    polygon_wgs: dict,
    out_path: Path,
    top_n: int = 25,
) -> None:
    log.info("[EXPORT] folium → %s", out_path)
    g = _add_streetview(buildings)
    if g.empty:
        log.warning("Aucun bâtiment à cartographier")
        return

    center = [float(g["lat"].mean()), float(g["lon"].mean())]
    m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")

    # Légende couleurs
    cmap = LinearColormap(
        ["#d7191c", "#bdbdbd", "#f17c46", "#fdae61", "#1a9641"],
        vmin=0, vmax=100,
        caption="Score Pinui-Binui /100 — rouge=exclu, gris=faible, vert=top opportunité",
    )
    cmap.add_to(m)

    # Layer périmètre d'étude
    folium.GeoJson(
        polygon_wgs,
        name="Périmètre d'étude / Study perimeter",
        style_function=lambda _: {
            "color": "#222", "weight": 2,
            "fillOpacity": 0.0, "dashArray": "8 4",
        },
    ).add_to(m)

    # Layer mitchamim (transparent)
    if not mitchamim_polys.empty:
        mitchamim_wgs = _stringify_timestamps(mitchamim_polys.to_crs(WGS))
        folium.GeoJson(
            mitchamim_wgs,
            name="Mitchamim Pinui-Binui actifs / Active urban renewal compounds",
            style_function=lambda _: {
                "color": "#d7191c", "weight": 1.5,
                "fillColor": "#d7191c", "fillOpacity": 0.18,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[c for c in ("ShemMitcha", "MisparProj")
                        if c in mitchamim_wgs.columns],
                aliases=["Nom / Name", "N°"][:len([c for c in ("ShemMitcha", "MisparProj")
                                                  if c in mitchamim_wgs.columns])],
            ),
        ).add_to(m)

    # Layer station Balfour + cercles 300/500/1000m
    lat_s, lon_s = config.BALFOUR_STATION["lat"], config.BALFOUR_STATION["lon"]
    fg_station = folium.FeatureGroup(name="Station Balfour Red Line", show=True)
    folium.Marker(
        [lat_s, lon_s],
        icon=folium.Icon(color="darkblue", icon="train", prefix="fa"),
        tooltip="Station Balfour — Red Line LRT",
    ).add_to(fg_station)
    for radius_m, color, dash in [(300, "#1a9641", "5 5"),
                                  (500, "#fdae61", "5 5"),
                                  (1000, "#f17c46", "5 5")]:
        folium.Circle(
            [lat_s, lon_s], radius=radius_m,
            color=color, weight=2, fill=False, dash_array=dash,
            tooltip=f"{radius_m} m de la station",
        ).add_to(fg_station)
    fg_station.add_to(m)

    # Layer bâtiments — emprise polygonale colorée par status
    fg_buildings = folium.FeatureGroup(
        name="Bâtiments scorés / Scored buildings", show=True,
    )

    top_ids = set(g.sort_values("score", ascending=False).head(top_n)["osm_id"])
    for _, r in g.iterrows():
        color = STATUS_COLORS.get(r.get("status"), "#666")
        is_top = r["osm_id"] in top_ids
        popup_html = (
            f"<b>{r.get('osm_id')}</b>"
            + (f" — <span style='color:#1a9641'><b>TOP {top_n}</b></span>" if is_top else "")
            + "<br>"
            f"<b>Score : {r['score']:.0f}/100</b> "
            f"({STATUS_LABEL_FR.get(r.get('status'), r.get('status'))})<br>"
            f"Adresse / Address : {r.get('addr') or 'N/A'}<br>"
            f"Gush/Helka : {r.get('gush', 'N/A')} / {r.get('helka', 'N/A')}<br>"
            f"Année / Year : {r.get('year_built') or 'N/A (à valider Street View)'}<br>"
            f"Étages / Floors : {r.get('floors') or 'N/A'}<br>"
            f"Emprise / Footprint : {r.get('emprise_m2', 'N/A')} m²<br>"
            f"Parcelle / Parcel : {r.get('surface_parcelle_m2') or 'N/A'} m²<br>"
            f"Ratio : {r.get('ratio_parcel_emprise') or 'N/A'}<br>"
            f"Distance Balfour : {r.get('dist_station_m', 'N/A')} m<br>"
            f"Voisins similaires / Similar neighbors : {int(r.get('neighbors_similar', 0))}<br>"
            f"Mitcham : {r.get('mitcham_name') or '—'}<br>"
            f'<a href="{r["streetview"]}" target="_blank">'
            f'<b>📷 Google Street View</b></a> — '
            f'<a href="{_govmap_url(r["lat"], r["lon"])}" target="_blank">GovMap</a>'
        )
        weight = 3 if is_top else 1
        try:
            folium.GeoJson(
                r.geometry.__geo_interface__,
                style_function=lambda _x, c=color, w=weight: {
                    "fillColor": c, "color": c,
                    "weight": w, "fillOpacity": 0.55,
                },
                popup=folium.Popup(popup_html, max_width=380),
                tooltip=f"Score {r['score']:.0f} — {r.get('status')}",
            ).add_to(fg_buildings)
        except Exception:  # géom invalide → skip
            pass
    fg_buildings.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(out_path))


# ---------------------------------------------------------------------------
# Plan promoteur (intégré au xlsx via Cover ; aussi écrit en MD séparé)
# ---------------------------------------------------------------------------
def export_promoter_guide(out_path: Path, top_n: int = 25) -> None:
    log.info("[EXPORT] guide promoteur → %s", out_path)
    content = f"""# Guide promoteur — Top {top_n} Ramat Yosef Nord, Bat Yam
# Promoter's guide — Top {top_n} Ramat Yosef Nord, Bat Yam

## Comment lire le top {top_n} / How to read the Top {top_n}

Chaque ligne = 1 bâtiment candidat Pinui-Binui, classé par score décroissant.
Each row = 1 candidate Pinui-Binui building, ranked by descending score.

## Méthode de validation âge en 30 sec / 30-sec age validation method

1. **Ouvre l'onglet `Top_{top_n}`** dans Excel (xlsx)
2. Pour chaque bâtiment du Top {top_n} :
   - Clique sur la cellule **`Google Street View`** → ouvre la rue
   - Tourne la vue vers le bâtiment correspondant
   - Estime visuellement : style années 60/70 ? béton brut, balcons saillants,
     3-5 étages, sans ascenseur visible = profil Pinui-Binui
3. **Annote la colonne `Notes`** : "années 60s OK" ou "trop récent, exclu"

## Interprétation des scores / Score interpretation

| Score | Statut FR | Status EN | Action |
|---|---|---|---|
| ≥ 80 | 🟢 Top opportunité | Top opportunity | Validation Street View + visite terrain |
| 60-79 | 🟡 À creuser | To investigate | Validation Street View, intérêt secondaire |
| 40-59 | 🟠 Marginal | Marginal | Probable seulement si combo géographique intéressant |
| 1-39 | ⚪ Faible | Weak | À exclure sauf opportunité unique |
| 0 | 🔴 Exclu | Excluded | Déjà dans mitcham Pinui-Binui actif — laisser tomber |

⚠ En l'absence de `year_built` (Phase 2 limitation), même un Top peut être
un bâtiment récent. La validation Street View est OBLIGATOIRE.

In the absence of `year_built` (Phase 2 limitation), even a Top can be
a recent building. Street View validation is MANDATORY.

## Critères à croiser pour décision finale / Final decision criteria

1. **Validation âge Street View** (manuel) : ≤ 1980 confirmé
2. **Score Pinui-Binui** ≥ 60 (cf. table ci-dessus)
3. **Densité voisinage** : ≥ 3 bâtiments similaires dans 50 m
   (donne du levier pour assembler un mitcham)
4. **Distance LRT Balfour** ≤ 500 m (valorisation transit immédiat)
5. **Statut copropriétaire** : à enquêter hors-pipeline (Tabu officiel)

## Phase upgrade en cours / Upgrade phase in progress

Email envoyé à `info@mapi.gov.il` pour clé API officielle bâti avec
attributs `year` + `floors` complets. Délai estimé 1-3 semaines.

Quand reçue, le pipeline génère un Top {top_n} v2 avec scoring discriminant
sur 100/100 au lieu de ~40/100 maximum observé en MVP v1.
"""
    out_path.write_text(content, encoding="utf-8")
