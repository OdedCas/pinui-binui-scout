# MANUAL_DOWNLOADS — fichiers IAP-protected à déposer manuellement

## Contexte technique

Le sous-domaine **`e.data.gov.il`** (qui sert les bulks téléchargeables) est
derrière un **Google Cloud Identity-Aware Proxy (IAP)** depuis 2025-2026.
Symptômes live :

- Header `X-Goog-IAP-Generated-Response: true`
- HTTP 302 → `accounts.google.com/o/oauth2/v2/auth?client_id=534789…`

L'API CKAN principale sur `data.gov.il/api/3/action/...` est libre d'IAP.
Le UA officiel `datagov-external-client` ne bypasse pas l'IAP sur `e.data.gov.il`
(testé 2026-05-25, redirect 302 identique aux UA génériques).

## Catégorisation des sources

| Dataset | Catégorie | Mécanisme | Refresh | Statut |
|---|---|---|---|---|
| `urban_renewal_mitchamim` (CSV) | A | CKAN `datastore_search` paginé | hebdo auto | ✅ live, 37/37 Bat Yam |
| **`helkot.zip` — cadastre COMPLET national** | B | dépôt manuel `data/raw/datagov_bulk/` | mensuel manuel | ⭐ **source primaire** |
| `helkot-shuma.zip` — cadastre partiel (zones non-régularisées) | B | dépôt manuel | mensuel manuel | fallback documentaire |
| `officiallydeclaredprojects.zip` | B | dépôt manuel | mensuel manuel | requis pour exclusion |
| OSM Overpass (bâti) | A | requête publique | live | fallback bâti |

## Fichiers à déposer

Dépose chaque fichier dans `data/raw/datagov_bulk/<filename>` exact.

### ⭐ `helkot.zip` — cadastre national COMPLET (Mapi, BNK"L)

| Champ | Valeur |
|---|---|
| Dataset page | https://data.gov.il/dataset/shape |
| Resource id | `c68b4df6-c809-4bb5-a546-61fa1528fed5` |
| Download URL (IAP) | https://e.data.gov.il/dataset/dff8a168-af6c-4e0f-bbe3-c4bd3646084c/resource/c68b4df6-c809-4bb5-a546-61fa1528fed5/download/helkot.zip |
| Taille attendue | **667 592 021 octets** (~667.6 MB) |
| Plancher acceptable | 500 MB (anti-page-IAP) |
| Format | ZIP contenant `.shp` + `.shx` + `.dbf` + `.prj` (~3-5M parcelles) |
| Dépôt local | `data/raw/datagov_bulk/helkot.zip` |
| Refresh recommandé | 60 jours |

**Lecture mémoire-friendly** : `fetch_cadastre` ouvre via GDAL `/vsizip/`
avec bbox filter natif. 667 MB ZIP → ~5-10 MB RAM en lecture filtrée
sur la zone d'étude.

### `helkot-shuma.zip` — cadastre PARTIEL (fallback)

Note importante : ce dataset ne couvre que les **zones non régularisées**
(`שטח לא מוסדר`). Bat Yam Nord étant urbain régularisé depuis longtemps,
quasi-vide ici. Conservé comme fallback documentaire.

| Champ | Valeur |
|---|---|
| Dataset page | https://data.gov.il/dataset/7a2d683b-10fd-4f39-ba91-efa9db23c663 |
| Download URL (IAP) | https://e.data.gov.il/dataset/.../helkot-shuma.zip |
| Taille | ~11.5 MB |
| Dépôt local | `data/raw/datagov_bulk/helkot-shuma.zip` |

### `officiallydeclaredprojects.zip` — polygones mitchamim Pinui-Binui

| Champ | Valeur |
|---|---|
| Dataset page | https://data.gov.il/dataset/1de95a22-576e-4e9c-b7c4-59db01d85290 |
| Download URL (IAP) | https://e.data.gov.il/dataset/.../officiallydeclaredprojects.zip |
| Taille | **2 569 754 octets** (~2.6 MB) |
| Plancher acceptable | 500 KB |
| Dépôt local | `data/raw/datagov_bulk/officiallydeclaredprojects.zip` |

## Procédure utilisateur

1. Ouvre le **Dataset page** dans Chrome (utilisateur Google connecté idéalement)
2. Si IAP demande sign-in → connecte-toi
3. Sur la page du dataset, clique sur le bouton **Download** du resource
4. Vérifie la taille à ±5 % du `Taille attendue`
5. Si le fichier fait < `Plancher acceptable` ou s'ouvre en HTML → IAP a redirigé, refais connecté
6. Dépose le `.zip` à l'emplacement exact ci-dessus

## Cascade cadastre

Le code utilise `CADASTRE_PRIORITY = ["helkot.zip", "helkot-shuma.zip"]` :
si `helkot.zip` est présent et valide, il est utilisé. Sinon, fallback sur
`helkot-shuma.zip`. Si aucun n'est valide → `BulkUnavailable` levée.

## Validation à l'ouverture

`preflight_bulks()` vérifie au démarrage :
- ✅ Au moins UN cadastre valide (`helkot.zip` OU `helkot-shuma.zip`)
- ✅ `officiallydeclaredprojects.zip` valide
- ✅ Tailles > `min_size` (plancher anti-page-IAP)
- ✅ Magic bytes ZIP `PK\x03\x04`

## Comportement en mode dégradé

- Sans `helkot.zip` MAIS avec `helkot-shuma.zip` → `ratio_parcel_emprise`
  sera NaN pour la quasi-totalité des bâtiments à Bat Yam Nord. Score
  plafonne à 75.
- Sans `officiallydeclaredprojects.zip` → `urban_renewal_active=False`
  partout → **EXCLUSION DÉSACTIVÉE**, scoring NON FIABLE. À ne pas
  utiliser en production.
