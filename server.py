#!/usr/bin/env python3
"""
Pinui-Binui Scout — local server.
Serves the map and runs the pipeline when you draw a new zone.

Start:  python3 server.py
Then open:  http://localhost:8765
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765

_jobs: dict[str, dict] = {}
_job_counter = 0
_lock = threading.Lock()


def _next_id() -> str:
    global _job_counter
    with _lock:
        _job_counter += 1
        return str(_job_counter)


def _patch_config(polygon: dict) -> None:
    cfg = ROOT / "config.py"
    lines = cfg.read_text(encoding="utf-8").splitlines(keepends=True)

    start = None
    for i, line in enumerate(lines):
        if re.match(r"\s*STUDY_POLYGON_WGS84\s*=", line):
            start = i
            break
    if start is None:
        raise ValueError("STUDY_POLYGON_WGS84 not found in config.py")

    # Walk forward tracking brace depth to find the full assignment block.
    # Handle both one-line and multi-line dict literals safely.
    depth = 0
    seen_open = False
    end = start
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}":
                depth -= 1
        if seen_open and depth == 0:
            end = i
            break

    new_val = "STUDY_POLYGON_WGS84 = " + json.dumps(polygon, ensure_ascii=False) + "\n"
    cfg.write_text("".join(lines[:start] + [new_val] + lines[end + 1:]), encoding="utf-8")


def _run_pipeline(job_id: str, polygon: dict) -> None:
    job = _jobs[job_id]
    try:
        _patch_config(polygon)
        job["log"].append("config.py updated with new zone")
        job["log"].append("Running pipeline (this takes ~30 seconds)...")

        proc = subprocess.Popen(
            [sys.executable, "-m", "src.pipeline", "--label", "full"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            stripped = line.rstrip()
            if stripped:
                job["log"].append(stripped)
        proc.wait()

        if proc.returncode != 0:
            job["status"] = "error"
            job["log"].append(f"Pipeline failed (exit code {proc.returncode})")
            return

        job["log"].append("Regenerating map...")
        r2 = subprocess.run(
            [sys.executable, "-m", "src.export_premium"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if r2.returncode != 0:
            job["status"] = "error"
            job["log"].append("Map generation failed: " + r2.stderr)
            return

        job["status"] = "done"
        job["log"].append("Done! Map is ready.")

    except Exception as exc:
        job["status"] = "error"
        job["log"].append(f"Error: {exc}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence per-request logs
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/map"):
            p = ROOT / "outputs" / "ramat_yosef_nord_premium.html"
            if not p.exists():
                self._json({"error": "map not generated yet"}, 404)
                return
            body = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/ping":
            self._json({"ok": True})

        elif self.path.startswith("/poll/"):
            job_id = self.path[6:]
            job = _jobs.get(job_id)
            if not job:
                self._json({"error": "unknown job"}, 404)
            else:
                self._json({"status": job["status"], "log": job["log"]})

        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/run":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                self._json({"error": "invalid JSON"}, 400)
                return
            polygon = body.get("polygon")
            if not polygon:
                self._json({"error": "missing polygon"}, 400)
                return
            job_id = _next_id()
            _jobs[job_id] = {"status": "running", "log": []}
            threading.Thread(
                target=_run_pipeline, args=(job_id, polygon), daemon=True
            ).start()
            self._json({"job_id": job_id})
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"\n  Pinui-Binui Scout is running at  {url}\n")
    print("  Open that URL in your browser.")
    print("  Press Ctrl+C to stop.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
