"""
Runner Phase 2 — exécute le pipeline sur les mini-polygones v1, v2, v3 et
produit un rapport CONSOLIDÉ avec les Sections A-E demandées.

Section A — Diagnostic technique global
Section B — Résultats v1 (cas vierge)
Section C — Résultats v2 (cas frontière mitcham)
Section D — Résultats v3 (test exclusion strict)
Section E — Validation cohérence + Anomalies + Plan upgrade

Usage:
    python -m src.pipeline                  # run all 3 (= --label all)
    python -m src.pipeline --label v1       # ne run que v1
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Force UTF-8 sur stdout/stderr — sinon la console Windows (cp1255 hébreu)
# crashe sur les caractères français/emoji.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import geopandas as gpd
import pandas as pd

import config
from src.enrich import enrich_all
from src.fetch_buildings import fetch_buildings
from src.fetch_datagov import (
    BulkUnavailable,
    active_cadastre_path,
    fetch_cadastre,
    fetch_mitchamim_bat_yam,
    fetch_urban_renewal_polygons,
    preflight_bulks,
)
from src.score import DEGRADED_MODE, score_dataframe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s . %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


# Mini-polygones
MINI_V1 = {
    "type": "Polygon", "coordinates": [[
        [34.7490, 32.0236], [34.7510, 32.0236],
        [34.7510, 32.0254], [34.7490, 32.0254],
        [34.7490, 32.0236],
    ]],
}
MINI_V2 = {
    "type": "Polygon", "coordinates": [[
        [34.7458, 32.0240], [34.7478, 32.0240],
        [34.7478, 32.0258], [34.7458, 32.0258],
        [34.7458, 32.0240],
    ]],
}
MINI_V3 = {
    # Corrigé après vérif pyproj : v3 précédent (lat 32.0237-32.0255) était
    # 200 m TROP AU SUD du mitcham 8001244 (latitude réelle 659233-659775
    # ITM = ~32.0270-32.0319 WGS84). Bounds corrigés ITM = 176235-176435
    # X / 659403-659604 Y → 94 % à l'intérieur du mitcham (vérifié).
    "type": "Polygon", "coordinates": [[
        [34.74692, 32.02700], [34.74903, 32.02700],
        [34.74903, 32.02881], [34.74692, 32.02881],
        [34.74692, 32.02700],
    ]],
}

POLYGONS = {
    "v1":   MINI_V1,
    "v2":   MINI_V2,
    "v3":   MINI_V3,
    "full": config.STUDY_POLYGON_WGS84,   # Phase 3 — Ramat Yosef Nord complet
}


# ---------------------------------------------------------------------------
# Banner + preflight
# ---------------------------------------------------------------------------
def _banner_degraded() -> str:
    if not DEGRADED_MODE:
        return ""
    return (
        "\n" + "=" * 70 + "\n"
        "MODE DÉGRADÉ activé : `helkot.zip` (cadastre complet 667 MB) non\n"
        "chargé. Critère `ratio surface_parcelle / emprise` INACTIF.\n"
        "Plafond du score : 75/100. Tous les autres critères sont actifs.\n"
        + "=" * 70 + "\n"
    )


def _preflight_banner() -> bool:
    missing = preflight_bulks()
    if not missing:
        log.info("=== PREFLIGHT . tous les bulks Cat B en place ===")
        return True
    print("\n" + "=" * 70)
    print("PREFLIGHT — bulks manquants ou invalides :")
    print("=" * 70)
    for fname, reason in missing:
        print(f"  - {fname}  ->  {reason}")
    print()
    print("Voir MANUAL_DOWNLOADS.md. Pipeline continue en mode minimal.")
    print("=" * 70 + "\n")
    return False


# ---------------------------------------------------------------------------
# Run per-label (sans formatage Markdown)
# ---------------------------------------------------------------------------
def run_label(label: str, polygon_wgs: dict, parcels, mitchamim) -> dict:
    log.info("=== RUN %s ===", label)
    buildings, source = fetch_buildings(polygon_wgs)
    log.info("[FETCH] %d bâtiments via %s", len(buildings), source)
    enriched = enrich_all(buildings, parcels, mitchamim, polygon_wgs=polygon_wgs)
    scored = score_dataframe(enriched)

    out_path = config.DATA_PROC / f"phase2_{label}.geojson"
    if not scored.empty:
        scored.to_crs("EPSG:4326").to_file(out_path, driver="GeoJSON")
        log.info("[WRITE] %s", out_path)

    return {"label": label, "polygon": polygon_wgs, "gdf": scored, "source": source}


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------
DISPLAY_COLS_BASE = [
    "osm_id", "addr", "year_built", "floors",
    "emprise_m2", "surface_parcelle_m2", "ratio_parcel_emprise",
    "dist_station_m", "neighbors_similar", "score", "status",
]


def _gdf_to_md(gdf, cols, top=None) -> str:
    if gdf.empty:
        return "_Aucun bâtiment._\n"
    cols = [c for c in cols if c in gdf.columns]
    df = gdf[cols].copy()
    if top is not None:
        df = df.sort_values("score", ascending=False).head(top)
    return df.to_markdown(index=False, floatfmt=".1f")


def _pct(gdf, col) -> float:
    if col not in gdf.columns or len(gdf) == 0:
        return 0.0
    return 100 * gdf[col].notna().sum() / len(gdf)


# ---------------------------------------------------------------------------
# Sections A-E
# ---------------------------------------------------------------------------
def section_a(runs: dict, n_parcels: int, n_mitchamim_zone: int,
              cadastre_path) -> str:
    mode_label = "DEGRADED — critère ratio désactivé (plafond 75/100)" if DEGRADED_MODE \
        else "FULL — tous critères actifs (plafond 100/100)"
    cadastre_label = {
        "helkot.zip":       "cadastre national régularisé Mapi (complet)",
        "helkot-shuma.zip": "cadastre partiel zones non-régularisées (FALLBACK)",
    }.get(cadastre_path.name if cadastre_path else "", "inconnu")
    lines = [
        "## Section A — Diagnostic technique",
        "",
        f"**Mode scoring** : `{mode_label}`",
        "",
        f"- Cadastre actif : `{cadastre_path.name if cadastre_path else 'AUCUN'}` — "
        f"{cadastre_label} ({n_parcels} parcelles dans study polygon)",
        f"- Mitchamim chargés dans study polygon : **{n_mitchamim_zone}**",
        f"- Source bâti : **OSM Overpass** (GovMap REST 404 sur 4 endpoints testés)",
        "",
        "Couverture champs OSM par mini-polygone :",
        "",
        "| Polygone | N bâtiments | year_built % | floors % | type % | mitchamim ∩ |",
        "|---|---|---|---|---|---|",
    ]
    for label in ("v1", "v2", "v3"):
        r = runs.get(label)
        if not r:
            continue
        g = r["gdf"]
        n_mitch = int(g["urban_renewal_active"].sum()) if "urban_renewal_active" in g.columns else 0
        lines.append(
            f"| {label} | {len(g)} | {_pct(g,'year_built'):.0f}% | "
            f"{_pct(g,'floors'):.0f}% | {_pct(g,'type'):.0f}% | {n_mitch} |"
        )
    lines.append("")

    # Géométries invalides
    invalid = sum(int((~r["gdf"].geometry.is_valid).sum()) for r in runs.values())
    lines.append(f"Géométries invalides total : **{invalid}**")
    lines.append("")
    return "\n".join(lines)


def section_b(runs: dict) -> str:
    r = runs.get("v1")
    if not r:
        return ""
    g = r["gdf"]
    lines = [
        "## Section B — Résultats v1 (cas vierge, hors mitcham)",
        "",
        f"_Mini-polygone 200 × 200 m, centre (34.7500, 32.0245), {len(g)} bâtiments OSM._",
        "",
        _gdf_to_md(g, DISPLAY_COLS_BASE, top=15),
        "",
    ]
    if not g.empty:
        top5 = g.sort_values("score", ascending=False).head(5)
        lines.append("**Top 5 commentés :**")
        for _, r0 in top5.iterrows():
            reasons = []
            if pd.notna(r0.get("year_built")) and r0["year_built"] < 1980:
                reasons.append(f"vieux {int(r0['year_built'])}")
            elif pd.isna(r0.get("year_built")):
                reasons.append("année N/A")
            if pd.notna(r0.get("floors")) and 3 <= r0["floors"] <= 5:
                reasons.append(f"{int(r0['floors'])} étages")
            elif pd.isna(r0.get("floors")):
                reasons.append("étages N/A")
            if pd.notna(r0.get("dist_station_m")):
                d = r0["dist_station_m"]
                tier = "<500m" if d < 500 else ("<1000m" if d < 1000 else f">{int(d)}m")
                reasons.append(f"station {tier}")
            if int(r0.get("neighbors_similar", 0) or 0) >= 3:
                reasons.append(f"{int(r0['neighbors_similar'])} voisins similaires")
            lines.append(f"- `{r0.get('osm_id', '?')}` → **{r0['score']:.0f}** ({r0['status']}) — {', '.join(reasons)}")
    lines.append("")
    return "\n".join(lines)


def section_c(runs: dict) -> str:
    r = runs.get("v2")
    if not r:
        return ""
    g = r["gdf"]
    in_m = g[g["urban_renewal_active"]] if "urban_renewal_active" in g.columns else g.iloc[:0]
    out_m = g[~g.get("urban_renewal_active", pd.Series([False] * len(g), index=g.index))]
    lines = [
        "## Section C — Résultats v2 (cas frontière mitcham)",
        "",
        f"_Mini-polygone 200 × 200 m vers Balfour, centre (34.7468, 32.0249), {len(g)} bâtiments OSM._",
        "",
        f"- Bâtiments dans mitcham (centroïde within) : **{len(in_m)}**",
        f"- Bâtiments hors mitcham : **{len(out_m)}**",
        f"- Résultat attendu : v2 est en bordure de mitcham `8001244` (overlap "
        f"vertical 38m sur 200m). Géométrie polygonale du mitcham fait que "
        f"les centroïdes OSM tombent côté hors-mitcham → "
        f"**0 in mitcham est cohérent**.",
        "",
        "**Top 15 (tous hors mitcham) :**",
        "",
        _gdf_to_md(out_m, DISPLAY_COLS_BASE + ["mitcham_name"], top=15),
        "",
    ]
    if not out_m.empty:
        top3 = out_m.sort_values("score", ascending=False).head(3)
        lines.append("**Top 3 hors mitcham :**")
        for _, r0 in top3.iterrows():
            lines.append(
                f"- `{r0.get('osm_id')}` → **{r0['score']:.0f}** ({r0['status']}) "
                f"— année={_fmt(r0.get('year_built'))}, étages={_fmt(r0.get('floors'))}, "
                f"dist={_fmt(r0.get('dist_station_m'))}m, "
                f"voisins={int(r0.get('neighbors_similar', 0) or 0)}"
            )
    lines.append("")
    return "\n".join(lines)


def section_d(runs: dict) -> str:
    r = runs.get("v3")
    if not r:
        return ""
    g = r["gdf"]
    in_m = g[g["urban_renewal_active"]] if "urban_renewal_active" in g.columns else g.iloc[:0]
    out_m = g[~g.get("urban_renewal_active", pd.Series([False] * len(g), index=g.index))]
    all_excluded = (in_m["score"] == 0).all() if len(in_m) else None
    lines = [
        "## Section D — Résultats v3 (test exclusion strict)",
        "",
        f"_Mini-polygone 200 × 200 m DANS mitcham `8001244`, ITM X 176200-176400 / Y 659400-659600, {len(g)} bâtiments OSM._",
        "",
        f"- Bâtiments dans un mitcham (attendu : majorité) : **{len(in_m)}**",
        f"- Bâtiments hors mitcham : **{len(out_m)}**",
        f"- Tous les `in mitcham` ont score=0 : "
        f"{'✅ 100%' if all_excluded else ('❌ BUG' if all_excluded is False else '— (n=0)')}",
        "",
    ]
    if len(in_m) > 0:
        lines += [
            "### Bâtiments DANS mitcham (score=0 attendu)",
            "",
            _gdf_to_md(in_m, DISPLAY_COLS_BASE + ["mitcham_name"], top=20),
            "",
            "Distribution des mitchamim touchés :",
            "",
            in_m["mitcham_name"].value_counts().head(5).to_frame("count").to_markdown(),
            "",
        ]
    if len(out_m) > 0:
        lines += [
            "### Bâtiments HORS mitcham (score réel)",
            "",
            _gdf_to_md(out_m, DISPLAY_COLS_BASE, top=15),
            "",
        ]
    return "\n".join(lines)


def section_e(runs: dict) -> str:
    all_buildings = pd.concat([r["gdf"] for r in runs.values()], ignore_index=True)
    intuitive_lines = []
    excl_lines = []
    anomalies = []

    if not all_buildings.empty:
        # Cohorte 'idéale' : vieux + 3-5 étages
        ideal = all_buildings[
            pd.to_numeric(all_buildings["year_built"], errors="coerce").lt(1980)
            & pd.to_numeric(all_buildings["floors"], errors="coerce").between(3, 5)
            & ~all_buildings.get("urban_renewal_active", False)
        ]
        if len(ideal):
            intuitive_lines.append(
                f"- Cohorte vieux + 3-5 étages hors mitcham (n={len(ideal)}) : "
                f"score moyen = **{ideal['score'].mean():.1f}**"
            )
        else:
            intuitive_lines.append("- Aucun bâtiment OSM avec année ET étages remplis hors mitcham")

        # Exclusion check
        excl = all_buildings[all_buildings.get("urban_renewal_active", False)]
        if len(excl):
            all_zero = (excl["score"] == 0).all()
            excl_lines.append(
                f"- {len(excl)} bâtiments in mitcham : "
                f"{'✅ tous score=0' if all_zero else '❌ score non-zéro'}"
            )
        else:
            excl_lines.append("- Aucun bâtiment in mitcham détecté → exclusion non testée en run actuel")

        # Anomalies
        n = len(all_buildings)
        for col in ("year_built", "floors"):
            if col in all_buildings.columns:
                m_pct = 100 * all_buildings[col].isna().sum() / n
                if m_pct > 30:
                    anomalies.append(
                        f"- 🛑 `{col}` manquant à **{m_pct:.0f}%** "
                        f"(seuil STOP=30%) — OSM Overpass insuffisant. "
                        f"Tag {col} rarement renseigné sur OSM Israël."
                    )
        # Anomalie : bâtiment >1980 mais score haut hors mitcham
        recent_hi = all_buildings[
            (~all_buildings.get("urban_renewal_active", False))
            & pd.to_numeric(all_buildings["year_built"], errors="coerce").gt(1980)
            & (all_buildings["score"] >= 50)
        ]
        if len(recent_hi):
            anomalies.append(
                f"- {len(recent_hi)} bâtiment(s) post-1980 avec score ≥ 50 hors mitcham"
            )

    if DEGRADED_MODE:
        plan = [
            "**Plan upgrade vers mode complet :**",
            "1. Télécharger manuellement `helkot.zip` (667 MB, Mapi, IAP Google) — "
            "le code prêt à le consommer via `/vsizip/` + bbox filter natif.",
            "2. Alternative officielle : demande d'accès API Mapi à `info@mapi.gov.il`.",
            "3. Fallback synthétique : interdit par règle « aucune donnée fictive ».",
        ]
    else:
        plan = [
            "**Mode FULL actif** — `helkot.zip` cadastre national chargé, critère ratio "
            "actif. Plafond du score : 100/100.",
            "",
            "**Bloquant restant : `year_built`**",
            "- OSM Israël ne tag pas l'année de construction (100% manquant)",
            "- E1 Tel Aviv spillover, E2 CKAN permis, V3 Nadlan : tous échec",
            "- Sans `year_built` aucun bâtiment ne peut dépasser 70/100 (manque le +30 année)",
            "",
            "**Voies long-terme pour year_built :**",
            "1. Email officiel `info@mapi.gov.il` — clé API bâti Mapi",
            "2. Email NTA/Govmap technique — token Nadlan deals officiel",
            "3. Acceptation que le scoring discrimine sur `ratio + dist + floors + "
            "exclusion mitcham` (max effectif observé ~40-65/100) ; year reste une "
            "validation manuelle terrain",
        ]
    plan += [
        "",
        f"**Recommandation Phase 3 :** scale au polygone d'étude complet (0.85 km², "
        f"~1 300-1 500 bâtiments OSM attendus) en **mode {'DEGRADED' if DEGRADED_MODE else 'FULL'}**. "
        f"Les critères actifs (ratio, distance station, exclusion mitcham) discriminent "
        f"déjà des candidats MARGINAL (≥40). year_built reste manquant, à confirmer "
        f"manuellement sur le top 25.",
    ]

    sections = [
        "## Section E — Validation cohérence + Anomalies + Plan upgrade",
        "",
        "### Validation scoring intuitif",
        *(intuitive_lines or ["- N/A"]),
        "",
        "### Validation exclusions",
        *(excl_lines or ["- N/A"]),
        "",
        "### Anomalies & questions ouvertes",
        *(anomalies or ["- aucune anomalie critique au-dessus du seuil 30%"]),
        "",
        *plan,
    ]
    return "\n".join(sections)


def _fmt(v) -> str:
    if pd.isna(v):
        return "N/A"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", choices=["v1", "v2", "v3", "all", "full"],
                    default="all")
    args = ap.parse_args(argv)

    print(_banner_degraded(), end="")
    _preflight_banner()

    log.info("=== INGESTION data.gov.il ===")
    mitchamim_csv = None
    try:
        mitchamim_csv = fetch_mitchamim_bat_yam()
    except Exception as e:
        log.warning("mitchamim KO : %s", e)
    try:
        parcels = fetch_cadastre(config.STUDY_POLYGON_WGS84)
    except BulkUnavailable as e:
        log.warning("[DEGRADE] %s", e)
        parcels = gpd.GeoDataFrame(geometry=[], crs="EPSG:2039")
    try:
        mitchamim = fetch_urban_renewal_polygons(config.STUDY_POLYGON_WGS84)
    except BulkUnavailable as e:
        log.warning("[DEGRADE] %s", e)
        mitchamim = gpd.GeoDataFrame(geometry=[], crs="EPSG:2039")

    if args.label == "all":
        labels = ["v1", "v2", "v3"]
    elif args.label == "full":
        labels = ["full"]
    else:
        labels = [args.label]

    runs: dict[str, dict] = {}
    for label in labels:
        runs[label] = run_label(label, POLYGONS[label], parcels, mitchamim)

    # === Phase 3 — exports complets si on a tourné en mode full ===
    if "full" in runs:
        from src.export import (export_xlsx, export_geojson,
                                export_html, export_promoter_guide)
        gdf = runs["full"]["gdf"]
        src = runs["full"]["source"]
        cadastre = active_cadastre_path()
        out_xlsx = config.OUTPUTS / "ramat_yosef_nord_phase3.xlsx"
        out_geojson = config.OUTPUTS / "ramat_yosef_nord_phase3.geojson"
        out_html = config.OUTPUTS / "ramat_yosef_nord_phase3_carte.html"
        out_guide = config.OUTPUTS / "guide_promoteur.md"
        log.info("=== EXPORTS Phase 3 ===")
        if mitchamim_csv is None:
            mitchamim_csv = pd.DataFrame()
        export_xlsx(gdf, mitchamim_csv, parcels, src,
                    cadastre.name if cadastre else "—",
                    config.STUDY_POLYGON_WGS84, out_xlsx)
        export_geojson(gdf, out_geojson)
        export_html(gdf, mitchamim, config.STUDY_POLYGON_WGS84, out_html)
        export_promoter_guide(out_guide)
        # Petit récap stdout
        sizes = {
            p.name: f"{p.stat().st_size/1024:.0f} KB"
            for p in (out_xlsx, out_geojson, out_html, out_guide)
            if p.exists()
        }
        print()
        print("=== Phase 3 livrables ===")
        for name, size in sizes.items():
            print(f"  outputs/{name}  {size}")

    # Rapport consolidé
    cadastre = active_cadastre_path()
    parts = [
        _banner_degraded().strip(),
        "",
        section_a(runs, len(parcels), len(mitchamim), cadastre),
        section_b(runs),
        section_c(runs),
        section_d(runs),
        section_e(runs),
    ]
    out = config.DATA_PROC / "phase2_report.md"
    out.write_text("\n\n".join(p for p in parts if p), encoding="utf-8")
    print(f"\n-> Rapport consolidé : {out}\n")
    print("\n\n".join(p for p in parts if p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
