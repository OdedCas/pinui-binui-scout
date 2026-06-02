"""
Bat Yam GIS — API discovery via Playwright.

Strategy:
  1. Open GovMap focused on Ramat Yosef Nord — enable building layers,
     click buildings to trigger identify/query requests.
  2. Also visit www.batyam.muni.il to find their GIS link.

Saves report to outputs/batyam_gis_apis.json.

Run: python playwright_discover.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "outputs" / "batyam_gis_apis.json"

# Ramat Yosef Nord — GovMap URL centred on study area, zoom 16
GOVMAP_URL = "https://www.govmap.gov.il/?c=34.752,32.024&z=16&lang=1"
BATYAM_URL = "https://www.batyam.muni.il"


def snap(page, name):
    path = ROOT / "outputs" / f"discover_{name}.png"
    try:
        page.screenshot(path=str(path))
        print(f"  screenshot → {path.name}")
    except Exception as e:
        print(f"  screenshot failed: {e}")


def run():
    captured: list[dict] = []

    def on_request(req):
        url = req.url
        if any(url.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".woff", ".woff2", ".ttf", ".gif", ".ico", ".svg"]):
            return
        if "/tile/" in url or "/tiles/" in url:
            return
        captured.append({
            "url":    url,
            "method": req.method,
            "type":   req.resource_type,
            "post":   req.post_data[:500] if req.post_data else None,
        })

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=150)
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="he-IL",
        )
        page = ctx.new_page()
        page.on("request", on_request)

        # ═══════════════════════════════════════════════════════════════
        # PHASE 1 — GovMap building layers
        # ═══════════════════════════════════════════════════════════════
        print(f"\n[1] GovMap → {GOVMAP_URL}")
        try:
            page.goto(GOVMAP_URL, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            print(f"  nav warning: {e}")

        time.sleep(6)
        print(f"  title: {page.title()}")
        snap(page, "govmap_initial")

        cx, cy = 700, 450

        # Zoom in further
        print("  zooming in...")
        for _ in range(4):
            page.mouse.wheel(0, -500)
            time.sleep(0.8)
        time.sleep(3)
        snap(page, "govmap_zoomed")

        # Click buildings on the map to trigger identify requests
        print("  clicking buildings...")
        for dx, dy in [(0,0), (60,0), (-60,0), (0,60), (0,-60), (40,40), (-40,40), (80,30), (-80,30)]:
            page.mouse.click(cx+dx, cy+dy)
            time.sleep(2)

        # Try to find and click layer panel / buildings toggle
        print("  looking for layer controls...")
        for sel in [
            "button[title*='שכב']", "button[aria-label*='layer']",
            "[class*='layer-btn']", "[class*='layers']",
            "button[title*='Layer']", "[data-layer*='building']",
            "button[title*='מבנ']",
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    time.sleep(2)
                    print(f"    clicked: {sel}")
            except Exception:
                pass

        # More clicks after potential layer activation
        for dx, dy in [(0,0), (50,20), (-50,20), (20,-50), (-20,-50)]:
            page.mouse.click(cx+dx, cy+dy)
            time.sleep(2)

        time.sleep(3)
        snap(page, "govmap_after_clicks")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 2 — Bat Yam municipality website → find GIS link
        # ═══════════════════════════════════════════════════════════════
        print(f"\n[2] Bat Yam site → {BATYAM_URL}")
        try:
            page.goto(BATYAM_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(4)
            print(f"  title: {page.title()}")
            snap(page, "batyam_main")

            # Extract all GIS/map links
            links = page.evaluate("""() =>
                [...document.querySelectorAll('a[href]')].map(a => ({
                    text: (a.innerText || a.title || '').trim().slice(0,60),
                    href: a.href
                })).filter(a =>
                    /gis|map|מפה|iview|geo|מיפוי|שכב/i.test(a.href + ' ' + a.text)
                )
            """)
            print(f"  GIS links found: {len(links)}")
            for l in links[:10]:
                print(f"    {l['text']:<40} → {l['href'][:80]}")

            # Navigate to the first GIS link found
            if links:
                gis_href = links[0]["href"]
                print(f"\n  Navigating to: {gis_href}")
                try:
                    page.goto(gis_href, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(8)
                    print(f"  title: {page.title()}")
                    snap(page, "batyam_gis")
                    # Interact
                    for dx, dy in [(0,0), (60,30), (-60,30), (30,-60)]:
                        page.mouse.click(cx+dx, cy+dy)
                        time.sleep(2)
                except Exception as e:
                    print(f"  GIS nav failed: {e}")

        except Exception as e:
            print(f"  Bat Yam site failed: {e}")

        time.sleep(3)
        browser.close()

    # ── Build report ─────────────────────────────────────────────────────
    unique: dict[str, dict] = {}
    for req in captured:
        p = urlparse(req["url"])
        key = p.scheme + "://" + p.netloc + p.path
        if key not in unique:
            unique[key] = req

    building_kw = [
        "feature", "query", "identify", "getfeature", "getmap",
        "mapserver", "featureserver", "wfs", "wms",
        "mivne", "binyan", "shnat", "floor", "koma", "building",
        "entitiesbypoint", "getlayerdata", "layerdata",
    ]
    candidates = [
        r for r in unique.values()
        if r["type"] in ("xhr", "fetch")
        and any(k in r["url"].lower() for k in building_kw)
        and "cdn" not in r["url"]
        and "googleapis" not in r["url"]
    ]

    xhr_all = [r for r in unique.values() if r["type"] in ("xhr", "fetch")]

    report = {
        "total_captured": len(captured),
        "unique_endpoints": list(unique.values()),
        "xhr_fetch": xhr_all,
        "building_candidates": candidates,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"Report: {OUT}")
    print(f"\n=== BUILDING CANDIDATES ({len(candidates)}) ===")
    for r in candidates:
        print(f"  {r['method']} {r['url'][:130]}")
        if r.get("post"):
            print(f"     POST: {r['post'][:120]}")
    print(f"\n=== ALL XHR/FETCH ({len(xhr_all)}) ===")
    for r in xhr_all:
        print(f"  {r['method']} {r['url'][:120]}")
        if r.get("post"):
            print(f"     POST: {r['post'][:100]}")


if __name__ == "__main__":
    run()
