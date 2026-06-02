"""
Phase 1 — Exploration des endpoints/datasets.

Sondes :
1. data.gov.il (CKAN) avec queries hébreu — datasets renouvellement urbain,
   cadastre helkot-shuma, bâtiments à préserver, etc.
2. Pour chaque dataset retenu : `package_show` + `datastore_search` filtrant
   Bat Yam (50 lignes max).
3. GovMap REST national — re-sondage (peut échouer depuis sandbox).
4. iplan ArcGIS (Xplan + arcgis) — re-sondage.
5. Mavat — HEAD only + ping de l'API REST partielle.

⚠ Aucune référence Complot v5.gis-net.co.il — abandonné définitivement (WAF).

Output : `data/processed/explore_results.md`

Usage :
    python -m src.explore
    python -m src.explore --only-datagov
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import config
from src.http_client import HttpError, get_json, head_ok

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("explore")


# ---------------------------------------------------------------------------
# data.gov.il (CKAN)
# ---------------------------------------------------------------------------
@dataclass
class CkanDataset:
    id: str
    name: str
    title: str
    organization: str
    resources: list[dict] = field(default_factory=list)


def ckan_search(query: str, rows: int = 20) -> list[CkanDataset]:
    try:
        data = get_json(
            f"{config.DATA_GOV_IL_API}/package_search",
            params={"q": query, "rows": rows},
            subdir="datagov_search",
        )
    except HttpError as e:
        log.warning("ckan search %r failed: %s", query, e)
        return []
    results = (data.get("result") or {}).get("results", [])
    out: list[CkanDataset] = []
    for r in results:
        out.append(CkanDataset(
            id=r.get("id", ""),
            name=r.get("name", ""),
            title=r.get("title", ""),
            organization=(r.get("organization") or {}).get("title", ""),
            resources=[
                {"id": x.get("id"), "name": x.get("name"),
                 "format": x.get("format"), "url": x.get("url"),
                 "datastore_active": x.get("datastore_active", False)}
                for x in r.get("resources", [])
            ],
        ))
    log.info("ckan q=%r → %d datasets", query, len(out))
    return out


def ckan_show(package_id: str) -> dict | None:
    try:
        data = get_json(
            f"{config.DATA_GOV_IL_API}/package_show",
            params={"id": package_id},
            subdir="datagov_show",
        )
    except HttpError as e:
        log.warning("package_show %s failed: %s", package_id, e)
        return None
    return data.get("result")


def ckan_sample(resource_id: str, q: str = "", limit: int = 50) -> dict | None:
    """Tente un datastore_search pour récupérer N lignes (échoue si la
    ressource n'est pas datastore_active — auquel cas il faut télécharger
    le ZIP/CSV directement)."""
    try:
        data = get_json(
            f"{config.DATA_GOV_IL_API}/datastore_search",
            params={"resource_id": resource_id, "q": q, "limit": limit} if q
                  else {"resource_id": resource_id, "limit": limit},
            subdir="datagov_sample",
        )
    except HttpError as e:
        log.warning("datastore_search %s failed: %s", resource_id, e)
        return None
    return data.get("result")


# ---------------------------------------------------------------------------
# GovMap / iplan ArcGIS re-sondage
# ---------------------------------------------------------------------------
def probe_url(url: str) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url}
    try:
        data = get_json(url, params={"f": "json"}, subdir="arcgis_probe")
        result["reachable"] = True
        result["has_services"] = "services" in data or "layers" in data
        result["folders"] = data.get("folders", [])
        result["services"] = [s.get("name") for s in data.get("services", [])]
        result["layers"] = [
            {"id": l.get("id"), "name": l.get("name")}
            for l in data.get("layers", []) or []
        ]
    except (HttpError, requests.RequestException) as e:
        result["reachable"] = False
        result["error"] = str(e)[:160]
    return result


# ---------------------------------------------------------------------------
# Mavat
# ---------------------------------------------------------------------------
def probe_mavat() -> dict[str, Any]:
    return {
        "root_reachable": head_ok(config.MAVAT_ROOT),
        "rest_api_base":  config.MAVAT_API_REST,
        "note": "API publique partielle, schémas non documentés. "
                "Endpoint /rest/api/Attacments confirmé via SERP. "
                "planSearch privé — fallback : data.gov.il/urban_renewal_mitchamim "
                "+ master plans ZIP couvrent déjà Pinui-Binui actifs.",
    }


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def render_report(state: dict, out_path: Path) -> None:
    lines: list[str] = []
    lines += [
        "# Explore results — Phase 1 v2",
        "",
        f"_Généré le {datetime.now().isoformat(timespec='seconds')}_",
        "",
        "## TL;DR",
        "",
    ]
    n_pkg = sum(len(v) for v in state["datagov"]["searches"].values())
    n_active = len([d for d in state["datagov"]["confirmed"].values() if d])
    govmap_ok = any(p["reachable"] for p in state["govmap"])
    iplan_ok  = any(p["reachable"] for p in state["iplan"])
    lines += [
        f"- data.gov.il : {n_pkg} datasets trouvés, **{n_active} confirmés exploitables**",
        f"- GovMap REST joignable : **{govmap_ok}**",
        f"- iplan ArcGIS joignable : **{iplan_ok}**",
        f"- Mavat root joignable : **{state['mavat']['root_reachable']}**",
        f"- Bat Yam Complot : **abandonné** (WAF, voir CHANGELOG)",
        "",
    ]

    # ---- Datasets data.gov.il retenus ----
    lines += [
        "## Datasets data.gov.il retenus",
        "",
        "| Slug | Resource ID | Format | Bat Yam ? | Description |",
        "|---|---|---|---|---|",
    ]
    for slug, info in state["datagov"]["confirmed"].items():
        if not info:
            continue
        r = info["resource"]
        coverage = info["coverage"]
        lines.append(
            f"| `{slug}` | `{r.get('id','?')}` | {r.get('format','?')} | "
            f"{coverage} | {info.get('description','')} |"
        )
    lines.append("")

    # ---- Sample columns ----
    for slug, info in state["datagov"]["confirmed"].items():
        if not info or not info.get("columns"):
            continue
        lines += [
            f"### `{slug}` — schéma",
            "",
            "| Field | Description |",
            "|---|---|",
        ]
        for col, desc in info["columns"].items():
            lines.append(f"| `{col}` | {desc} |")
        lines.append("")

    # ---- GovMap / iplan ----
    lines += ["## GovMap REST", ""]
    lines += ["| URL | Joignable | Services |", "|---|---|---|"]
    for p in state["govmap"]:
        services = ", ".join((p.get("services") or [])[:5]) or "—"
        lines.append(
            f"| `{p['url']}` | {'✅' if p['reachable'] else '❌ ' + p.get('error','')[:80]} | {services} |"
        )
    lines += ["", "## iplan ArcGIS (Xplan)", ""]
    lines += ["| URL | Joignable | Services |", "|---|---|---|"]
    for p in state["iplan"]:
        services = ", ".join((p.get("services") or [])[:5]) or "—"
        lines.append(
            f"| `{p['url']}` | {'✅' if p['reachable'] else '❌ ' + p.get('error','')[:80]} | {services} |"
        )
    lines += ["", "## Mavat", "", f"- root reachable : {state['mavat']['root_reachable']}",
              f"- REST partielle : `{state['mavat']['rest_api_base']}`",
              f"- note : {state['mavat']['note']}", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("rapport partiel écrit : %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-datagov", action="store_true")
    ap.add_argument("--only-arcgis",  action="store_true")
    args = ap.parse_args(argv)

    state: dict[str, Any] = {
        "datagov": {"searches": {}, "confirmed": {}},
        "govmap": [],
        "iplan":  [],
        "mavat":  {},
    }

    if not args.only_arcgis:
        log.info("=== data.gov.il searches (hébreu) ===")
        for q in config.DATAGOV_QUERIES_HE:
            state["datagov"]["searches"][q] = [asdict(d) for d in ckan_search(q)]

        log.info("=== data.gov.il datasets confirmés (package_show + sample) ===")
        for slug, meta in config.DATAGOV_DATASETS.items():
            pkg = ckan_show(meta["package_id"])
            if not pkg:
                state["datagov"]["confirmed"][slug] = None
                continue
            resources = pkg.get("resources", [])
            target = (
                next((r for r in resources if r["id"] == meta.get("resource_id")), None)
                if meta.get("resource_id") else (resources[0] if resources else None)
            )
            coverage = "?"
            columns: dict[str, str] = {}
            if target and target.get("datastore_active"):
                sample = ckan_sample(target["id"],
                                     q=meta.get("filter_yeshuv", ""), limit=50)
                if sample:
                    total = sample.get("total", "?")
                    coverage = f"{total} lignes"
                    columns = {
                        f.get("id"): f.get("info", {}).get("notes", "")
                        for f in sample.get("fields", [])
                    }
            state["datagov"]["confirmed"][slug] = {
                "resource": target or {},
                "coverage": coverage,
                "columns": columns,
                "description": pkg.get("title", ""),
            }

    if not args.only_datagov:
        log.info("=== GovMap REST re-sondage ===")
        state["govmap"] = [probe_url(u) for u in config.GOVMAP_REST_CANDIDATES]
        log.info("=== iplan ArcGIS re-sondage ===")
        state["iplan"] = [probe_url(u) for u in (
            config.IPLAN_ARCGIS_REST, config.IPLAN_XPLAN_REST,
        )]
        log.info("=== Mavat ===")
        state["mavat"] = probe_mavat()

    out = config.DATA_PROC / "explore_results.md"
    render_report(state, out)
    print(f"\n→ Rapport : {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
