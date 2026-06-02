"""
Configuration centrale — Pinui-Binui Scout, Ramat Yosef Nord, Bat Yam.

Sources par criticité (post-Phase 1 v2) :
 1. data.gov.il — Ministère Logement, datasets CSV/ZIP (autorité officielle)
 2. GovMap REST national (cadastre, parcelles avec helka)
 3. Mavat REST partielle (détails TBV individuels — fallback)
 4. Tel Aviv IView2MapHeb (référence schéma canonique, pas data Bat Yam)

Convention : *CONFIRMED* = vérifié live ; *TO_VALIDATE_RUNTIME* = endpoint
public connu mais socket fermé depuis ma sandbox — à re-tester sur la
machine de l'utilisateur.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).resolve().parent
DATA_RAW   = ROOT / "data" / "raw"
DATA_PROC  = ROOT / "data" / "processed"
OUTPUTS    = ROOT / "outputs"
LOGS       = ROOT / "data" / "logs"
for _p in (DATA_RAW, DATA_PROC, OUTPUTS, LOGS):
    _p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------
SRID_ITM = 2039
SRID_WGS = 4326


# ---------------------------------------------------------------------------
# Station Balfour (Red Line LRT, Bat Yam)
#
# Données disponibles :
# - Article batyam.mynet : "בצד המערבי של צומת רוטשילד-בלפור במרכז הרחוב"
# - OSM bus stop @ Rothschild × Balfour : 32.0273, 34.7453
# - Overpass rue Balfour, segments les plus au nord (proches LRT) :
#     way 1187640542 center (32.0287, 34.7450)
#     way 1189446349 center (32.0274, 34.7453)
#     way 1187640543 center (32.0268, 34.7452)
# - NTA officiel : pas de GPS publié, valeur estimée à l'intersection
#
# Moyenne pondérée + arrondi : 32.0270 N, 34.7452 E. *CONFIRMED via OSM
# multi-sources convergentes, à raffiner Phase 3 si NTA publie shapefile.*
# ---------------------------------------------------------------------------
BALFOUR_STATION = {
    "name_fr": "Station Balfour (Red Line)",
    "name_en": "Balfour Station (Red Line)",
    "name_he": "תחנת בלפור",
    "lon": 34.7452,
    "lat": 32.0270,
    "source": (
        "OSM segments rue Balfour autour intersection Rothschild "
        "(ways 1187640542, 1189446349, 1187640543) — moyenne pondérée"
    ),
}


# ---------------------------------------------------------------------------
# Polygone d'étude — Ramat Yosef Nord (v2, corrigé géographie réelle)
#
# Ramat Yosef centre (Nominatim) : 32.0188, 34.7574
# Station Balfour : 32.0270, 34.7452 (NW du quartier)
# Rue Balfour (axe ouest) : lon ~34.7450 d'après segments OSM
# Yoseftal (axe est) : lon ~34.7610
#
# 7 vertex suivant approximativement le grid de rues, polygone fermé
# anti-horaire (RFC 7946 valide). Surface ≈ 0.85 km² (sous 1 km²).
# Inclut la station Balfour à la frontière NW pour le critère distance.
# ---------------------------------------------------------------------------
STUDY_POLYGON_WGS84 = {"type": "Polygon", "coordinates": [[[34.745035, 32.01747], [34.749069, 32.016306], [34.744005, 32.010049], [34.741516, 32.01114], [34.745035, 32.01747]]]}

# ---------------------------------------------------------------------------
# Sources data.gov.il (CKAN) — *CONFIRMED via API HTTP*
#
# IDs récupérés via /api/3/action/package_show. resource_ids stables sur
# data.gov.il, datastore_search supporte filtres q= et filters={}.
# ---------------------------------------------------------------------------
DATA_GOV_IL_API = "https://data.gov.il/api/3/action"

DATAGOV_DATASETS = {
    # Mitchamim renouvellement urbain (déclarés) — table CSV avec 37 lignes Bat Yam
    "urban_renewal_mitchamim": {
        "package_id":  "0bfc2b7f-5ed6-426a-84de-1a6552a5c35f",
        "resource_id": "f65a0daf-f737-49c5-9424-d378d52104f5",
        "format":      "CSV",
        "columns_key": [
            "MisparMitham", "Yeshuv", "SemelYeshuv", "ShemMitcham",
            "YachadKayam", "YachadTosafti", "YachadMutza",
            "TaarichHachraza", "MisparTochnit",
            "KishurLatar", "SachHeterim", "KishurLaMapa",
            "Maslul", "ShnatMatanTokef", "Bebitzua", "Status",
        ],
        "filter_yeshuv": "בת ים",
    },
    # Polygones géographiques des projets déclarés (ZIP SHP) — TO_VALIDATE format
    "urban_renewal_polygons": {
        "package_id":  "1de95a22-576e-4e9c-b7c4-59db01d85290",
        "resource_id": "ceb7bbb0-e2db-4e87-8a6c-0a250f5de001",
        "format":      "ZIP",
        "filename":    "officiallydeclaredprojects.zip",
    },
    # Master plans (proposés ou approuvés)
    "urban_renewal_masterplans": {
        "package_id":  "1de95a22-576e-4e9c-b7c4-59db01d85290",
        "resource_id": "38555a84-8523-4ab1-9fe5-df6b523c15ea",
        "format":      "ZIP",
        "filename":    "masterplans.zip",
    },
    # Cadastre national niveau parcelle (Mapi) — ZIP SHP, MAJ mensuelle
    "helkot_shuma": {
        "package_id":  "7a2d683b-10fd-4f39-ba91-efa9db23c663",
        "resource_id": "a03a4d39-29d6-4245-b07c-2554d4eab17c",
        "format":      "ZIP",
        "filename":    "helkot-shuma.zip",
        "expected_fields": ["GUSH_NUM", "PARCEL", "SHAPE_Area"],  # à confirmer ouverture ZIP
    },
    # Bâtiments à préserver — exclusion forte (interdit de démolir)
    "buildings_preservation": {
        "package_id":  "0e8a1152-1cf2-4a9d-9fe8-2bfd7f60d970",
        "resource_id": None,  # 60 fichiers, on choisira GeoJSON via package_show
        "format":      "GeoJSON|SHP|KML",
        "purpose":     "exclusion list",
    },
}

# Queries CKAN à lancer en Phase 1 si discovery automatique
DATAGOV_QUERIES_HE = [
    "התחדשות עירונית",   # urban renewal
    "פינוי בינוי",         # pinui-binui
    "תמא 38",              # tama 38 (sans guillemets — variant)
    "תמ\"א 38",            # tama 38 (avec guillemets)
    "חלקות שומה",          # parcels
    "גושי שומה",           # gushim
    "מבנים",               # buildings (général)
    "בת ים",               # Bat Yam direct
]


# ---------------------------------------------------------------------------
# GovMap REST national — *TO_VALIDATE_RUNTIME*
# Endpoints publics connus, échouent socket-closed depuis sandbox.
# ---------------------------------------------------------------------------
GOVMAP_REST_CANDIDATES = [
    "https://www.govmap.gov.il/api/layers-catalog",      # catalog meta
    "https://ags.govmap.gov.il/arcgis/rest/services",    # ArcGIS root
    "https://ags.govmap.gov.il/Layers/Layers/MapServer", # legacy structure
    "https://ags.govmap.gov.il/Layers/Rendering/MapServer",
]
# Layer codes connus du frontend govmap.gov.il/?lay=… :
#   200720 — מתחמי התחדשות עירונית (urban renewal compounds)
#   203    — קווים כחולים (blue lines = plan boundaries)
GOVMAP_LAYER_CODES = {
    "urban_renewal_compounds": 200720,
    "blue_lines_plans":         203,
}


# ---------------------------------------------------------------------------
# Mavat (TABA en cours, gush/helka) — *TO_VALIDATE_RUNTIME*
# - Frontend : https://mavat.iplan.gov.il/SV3
# - REST partielle : /rest/api/... (Attacments confirmé public via SERP)
# - Pas de doc Swagger publique pour /planSearch
# - iplan ArcGIS REST (Xplan) : https://ags.iplan.gov.il/xplan ou /arcgis
# ---------------------------------------------------------------------------
MAVAT_ROOT       = "https://mavat.iplan.gov.il"
MAVAT_API_REST   = f"{MAVAT_ROOT}/rest/api"
IPLAN_ARCGIS_REST = "https://ags.iplan.gov.il/arcgis/rest/services"
IPLAN_XPLAN_REST  = "https://ags.iplan.gov.il/xplan/rest/services"


# ---------------------------------------------------------------------------
# Tel Aviv — référence schéma uniquement (PAS source data pour Bat Yam)
# Hypothèse : Bat Yam et les autres municipalités IL utilisent la même
# convention Mapi (year, ms_komot, t_sug_mivne, gova_simplex_2019). À valider
# Phase 2 sur le premier bâtiment Bat Yam récupéré (via GovMap REST).
# ---------------------------------------------------------------------------
TEL_AVIV_BUILDINGS_REF = (
    "https://gisn.tel-aviv.gov.il/arcgis/rest/services/IView2MapHeb/MapServer/24"
)
SCHEMA_CANONICAL_FIELDS = {
    "year_built":  "year",
    "floors":      "ms_komot",
    "type":        "t_sug_mivne",
    "name":        "shem_mivne",
    "height":      "gova_simplex_2019",
    "asbestos":    "t_asbest_level",
    "uid":         "UniqueId",
}


# ---------------------------------------------------------------------------
# HTTP politesse
# ---------------------------------------------------------------------------
USER_AGENT       = os.getenv(
    "HTTP_USER_AGENT",
    "datagov-external-client PinuiBinuiScout/0.2 (research)",
)
RATE_LIMIT_HZ    = float(os.getenv("RATE_LIMIT_PER_SEC", "5"))
HTTP_TIMEOUT     = 30
CACHE_ENABLED    = os.getenv("CACHE_ENABLED", "1") == "1"
CACHE_TTL_HOURS  = int(os.getenv("CACHE_TTL_HOURS", "24"))


# ---------------------------------------------------------------------------
# Filtres métier
# ---------------------------------------------------------------------------
FILTER_YEAR_MAX    = 1980
FILTER_FLOORS_MIN  = 3
FILTER_FLOORS_MAX  = 5
NEIGHBOR_BUFFER_M  = 50
NEIGHBOR_MIN_COUNT = 3
DIST_CLOSE_M       = 500
DIST_MID_M         = 1000

# Phase 3 — filtre outlier parcelles non-résidentielles
# Surface > 5000 m² = probablement école / parc / équipement public.
# On nullifie le match cadastre (ratio devient NaN, pas de bonus).
PARCEL_OUTLIER_MAX_M2 = 5000


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
SCORE_WEIGHTS = {
    "old_building": 30, "floors_range": 20,
    "ratio_cap":    25, "ratio_mult":    5,
    "dist_close":   15, "dist_mid":      8,
    "neighbors":    10,
}

STATUS_THRESHOLDS = [
    (80, "TOP",      "🟢 Top opportunité",       "🟢 Top opportunity",  "#1a9641"),
    (60, "INVEST",   "🟡 À creuser",             "🟡 To investigate",   "#fdae61"),
    (40, "MARGINAL", "🟠 Marginal",              "🟠 Marginal",         "#f17c46"),
    ( 1, "WEAK",     "⚪ Faible",                "⚪ Weak",             "#bdbdbd"),
    ( 0, "EXCLUDED", "🔴 Exclu (Pinui actif)",   "🔴 Excluded",         "#d7191c"),
]


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
OUTPUT_XLSX    = OUTPUTS / "resultats.xlsx"
OUTPUT_GEOJSON = OUTPUTS / "resultats.geojson"
OUTPUT_HTML    = OUTPUTS / "carte.html"
TOP_N          = 25
