# NEXT_STEPS — Actions post-MVP v1

## 🧑 Actions humain (toi)

### 1. Validation Street View top 25 — 45 min

- Ouvre `outputs/ramat_yosef_nord_phase3.xlsx` → onglet `Top_25`
- Pour chaque ligne, clique la cellule **Google Street View** (lien direct)
- Critères style années 60-70 : béton brut, 3-5 étages, balcons saillants, sans ascenseur extérieur, façade uniforme
- Annote colonne **Notes** : "années 60 confirmé" ou "trop récent / exclu"
- Procédure détaillée : `outputs/guide_promoteur.md`

**Output attendu** : 5-12 vrais candidats sur 25 (estimation), à présenter en pitch promoteur.

### 2. Email Bat Yam Hitchadshut Ironit — 5 min

**Contact** : à trouver sur `https://b-yam.co.il/`
- Page contact : `https://b-yam.co.il/צור-קשר-התחדשות-עירונית/`
- Probable email : `info@b-yam.co.il` (à confirmer)

**Sujet suggéré FR/EN** :
> Étude foncière Pinui-Binui Ramat Yosef Nord — demande de données complémentaires

**Demande** :
- Données municipales locales bâti Bat Yam avec `year_built` + `floors`
- Liste des copropriétés en cours d'organisation (signal Pinui-Binui amont)
- Coordonnées du responsable technique GIS Bat Yam

### 3. Email Mapi (Survey of Israel) — 5 min

**Contact** : `info@mapi.gov.il`

**Sujet suggéré** :
> Demande de clé API pour couche bâti BNK"L (year_built + floors) — recherche urbaine privée

**Demande** :
- Accès API officielle aux couches bâti nationales avec attributs (year, ms_komot, t_sug_mivne)
- Documentation des endpoints REST
- Conditions d'usage commercial/recherche

Délai typique réponse : 1-3 semaines.

## 🤖 Actions pipeline (automatisables)

### 4. Re-run mensuel

```powershell
# À planifier (Task Scheduler Windows ou cron Linux)
cd C:\Users\moran\Desktop\ramat-yosef-pinui
python -m src.pipeline --label full
```

**Refresh attendu** :
- `mitchamim` (CSV CKAN) — mise à jour hebdo automatique → 37 mitchamim peut évoluer
- `helkot.zip` — refresh manuel mensuel (cf. MANUAL_DOWNLOADS.md)
- `officiallydeclaredprojects.zip` — refresh manuel mensuel
- OSM Overpass — live, capturé à chaque run

**Trigger upgrade nécessaire** : si un mitcham se rajoute qui couvre certains bâtiments du top 25, ils basculeront EXCLUDED automatiquement.

### 5. Extension Bat Yam complet (Phase 3.5)

Quand le MVP v1 sera validé sur 1-2 pitch :

```python
# Dans src/pipeline.py — ajouter polygones par station :
POLYGONS["balfour_north"]   = {...}  # déjà fait via "full"
POLYGONS["rothschild"]      = {...}  # à dessiner sur geojson.io
POLYGONS["jabotinsky"]      = {...}
POLYGONS["atzmaut"]         = {...}
POLYGONS["kommemiyout"]     = {...}

# Run agrégé :
python -m src.pipeline --label all-stations
```

Code de scaling déjà en place — seul ajout = définir 4 nouveaux polygones d'étude.

## 🚧 Quand l'upgrade Mapi arrive

Une fois la clé API reçue :

1. Ajouter `MAPI_API_KEY=...` dans `.env`
2. Implémenter `src/fetch_mapi.py` avec les endpoints fournis
3. Préférer Mapi sur OSM dans `src/fetch_buildings.py` (modifier cascade)
4. Re-flipper `DEGRADED_MODE = False` dans `src/score.py` (déjà fait)
5. Re-run pipeline → scoring 100/100 réel, statuts TOP/INVEST utilisables
6. Re-générer le top 25 v2 → comparer aux validations Street View v1

## 📋 Décisions reportées

| Décision | Raison | Quand reprendre |
|---|---|---|
| F2 — Email Mapi seul puis pause | F1 préféré (livraison rapide) | Maintenant en parallèle |
| F3 — Mavat par gush/helka | Lourd, gain marginal | Si Mapi n'aboutit pas |
| W3 — Reverse govmap.api.js | Hors règles | Jamais |
| Z3 — Vor onoi synthétique parcelles | Interdit « aucune donnée fictive » | Jamais |

## 🎯 Critère de succès MVP v1

- [ ] 5-12 bâtiments validés Street View comme années 60-70 (estimation)
- [ ] 1-2 pitch promoteur amenés à audit terrain (estimation 2-4 semaines)
- [ ] Mapi répond à l'email (estimation 1-3 semaines)

Si OK sur les 2 premiers points → green light Phase 3.5 (extension 5 stations Bat Yam).
