"""
Bat Yam GIS — API discovery via Playwright.

Opens the Bat Yam GIS portal in a real Chromium browser, pans to the
Ramat Yosef Nord study area, and records every network request made.
Saves a report to  outputs/batyam_gis_apis.json  for inspection.

Run from Windows:
    python playwright_discover.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Request

ROOT    = Path(__file__).resolve().parent
OUT     = ROOT / "outputs" / "batyam_gis_apis.json"

# Study area centre (Ramat Yosef Nord)
LAT, LON = 32.024, 34.753

# Candidate GIS URLs to try — script will try each until one loads
GIS_CANDIDATES = [
    "https://www.batyam.muni.il",          # main site — look for GIS link
    "https://iview2.malam-team.com/iview2/?mun=6300",   # Malam IView2 (Bat Yam code)
    "https://iview.batyam.muni.il",
    "https://gis.batyam.muni.il",
    "https://batyam.maps.arcgis.com",
]

KEYWORDS = [
    "gis", "map", "mapa", "מפה", "iview", "arcgis", "feature",
    "layer", "buildings", "מבנים", "שנת", "קומות", "parcel", "helka",
]


def is_interesting(url: str) -> bool:
    low = url.lower()
    return any(k in low for k in KEYWORDS)


def run():
    captured: list[dict] = []

    def on_request(req: Request):
        url = req.url
        if any(ext in url for ext in [".png", ".jpg", ".woff", ".css", ".gif", ".ico"]):
            return
        if is_interesting(url) or req.resource_type in ("xhr", "fetch"):
            captured.append({
                "url":    url,
                "method": req.method,
                "type":   req.resource_type,
                "post":   req.post_data[:300] if req.post_data else None,
            })

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=300)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.on("request", on_request)

        # ── Step 1: find the GIS portal ──────────────────────────────────
        gis_url = None
        for candidate in GIS_CANDIDATES:
            print(f"Trying: {candidate}")
            try:
                page.goto(candidate, wait_until="domcontentloaded", timeout=12000)
                time.sleep(2)

                # If it's the main site, hunt for a GIS/map link
                if "batyam.muni.il" in candidate and "iview" not in candidate and "gis." not in candidate:
                    links = page.evaluate("""() =>
                        [...document.querySelectorAll('a')].map(a => ({
                            text: a.innerText.trim(),
                            href: a.href
                        })).filter(a => a.href && /gis|map|מפה|iview|geo/i.test(a.href + a.text))
                    """)
                    if links:
                        print("Found GIS links on main site:")
                        for l in links[:8]:
                            print(f"  {l['text'][:40]}  →  {l['href'][:80]}")
                        gis_url = links[0]["href"]
                        break
                else:
                    title = page.title()
                    print(f"  Loaded: {title[:60]}")
                    if page.url and "error" not in page.url.lower():
                        gis_url = page.url
                        break
            except Exception as e:
                print(f"  failed: {e}")

        if not gis_url:
            print("Could not find GIS portal. Trying govmap as fallback...")
            gis_url = f"https://www.govmap.gov.il/?c={LON},{LAT}&z=14"

        # ── Step 2: navigate to GIS and pan to study area ─────────────────
        print(f"\nOpening GIS: {gis_url}")
        page.goto(gis_url, wait_until="networkidle", timeout=30000)
        time.sleep(3)
        print(f"Page title: {page.title()}")

        # Interact — try to click around to trigger data loads
        for _ in range(3):
            try:
                page.mouse.move(700, 450)
                page.mouse.click(700, 450)
                time.sleep(1)
                page.mouse.wheel(0, -300)   # zoom in
                time.sleep(1)
            except Exception:
                pass

        time.sleep(4)

        # ── Step 3: save screenshot + requests ───────────────────────────
        screenshot = ROOT / "outputs" / "batyam_gis_screenshot.png"
        try:
            page.screenshot(path=str(screenshot), full_page=False)
            print(f"Screenshot saved: {screenshot}")
        except Exception as e:
            print(f"Screenshot failed: {e}")

        browser.close()

    # ── Report ────────────────────────────────────────────────────────────
    print(f"\nCaptured {len(captured)} requests total")

    # Deduplicate by domain+path (ignore query params for grouping)
    unique: dict[str, dict] = {}
    for req in captured:
        p = urlparse(req["url"])
        key = p.scheme + "://" + p.netloc + p.path
        if key not in unique:
            unique[key] = req

    print(f"Unique endpoints: {len(unique)}")

    # Flag ones that look like they return building attributes
    building_candidates = [
        r for r in unique.values()
        if any(k in r["url"].lower() for k in [
            "building", "mivne", "binyan", "shnat", "year", "floor", "koma",
            "FeatureServer", "MapServer", "query", "wfs", "mivna",
        ])
    ]

    report = {
        "gis_url": gis_url,
        "total_captured": len(captured),
        "unique_endpoints": list(unique.values()),
        "building_candidates": building_candidates,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved: {OUT}")
    print("\n=== BUILDING CANDIDATES ===")
    for r in building_candidates:
        print(f"  {r['method']} {r['url'][:120]}")
    if not building_candidates:
        print("  (none found — check outputs/batyam_gis_apis.json for all endpoints)")


if __name__ == "__main__":
    run()
