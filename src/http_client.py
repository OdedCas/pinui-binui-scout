"""
HTTP client maison : rate-limit, retry exponentiel, cache local sur disque.

Utilisé par tous les modules `fetch_*.py` et `explore.py`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter (token bucket simple, mono-thread).
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, hz: float) -> None:
        self.min_interval = 1.0 / hz if hz > 0 else 0.0
        self.last_call = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self.last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self.last_call = time.monotonic()


_LIMITER = _RateLimiter(config.RATE_LIMIT_HZ)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
@dataclass
class CacheEntry:
    path: Path
    fresh: bool


def _cache_key(url: str, params: dict | None) -> str:
    payload = url + (urlencode(sorted((params or {}).items())))
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _cache_lookup(url: str, params: dict | None, subdir: str) -> CacheEntry:
    key = _cache_key(url, params)
    root = config.DATA_RAW / subdir
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{key}.json"
    if not config.CACHE_ENABLED or not path.exists():
        return CacheEntry(path=path, fresh=False)
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return CacheEntry(path=path, fresh=age_h < config.CACHE_TTL_HOURS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
class HttpError(RuntimeError):
    pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, HttpError)),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _do_request(
    url: str, params: dict | None, timeout: int, headers: dict
) -> requests.Response:
    _LIMITER.wait()
    log.debug("GET %s params=%s", url, params)
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    if r.status_code >= 500:
        raise HttpError(f"HTTP {r.status_code} on {url}")
    return r


def get_json(
    url: str,
    *,
    params: dict | None = None,
    subdir: str = "misc",
    use_cache: bool | None = None,
) -> dict[str, Any]:
    """
    GET → JSON avec cache, rate-limit, retry. Lève HttpError sur 4xx/5xx final.

    Le payload est stocké pretty-printed dans `data/raw/<subdir>/<sha>.json`
    avec un sidecar `.meta.json` (url, params, timestamp, http_status).
    """
    cache = _cache_lookup(url, params, subdir)
    if cache.fresh and (use_cache if use_cache is not None else True):
        log.info("cache hit: %s (%s)", url, cache.path.name)
        return json.loads(cache.path.read_text(encoding="utf-8"))

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    r = _do_request(url, params, config.HTTP_TIMEOUT, headers)
    if r.status_code >= 400:
        raise HttpError(f"HTTP {r.status_code} on {url}: {r.text[:200]}")
    try:
        data = r.json()
    except ValueError as e:
        raise HttpError(f"non-JSON response from {url}: {e}") from e

    cache.path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = {
        "url": url,
        "params": params,
        "timestamp": time.time(),
        "http_status": r.status_code,
        "bytes": len(r.content),
    }
    cache.path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def head_ok(url: str) -> bool:
    """Test simple : retourne True si HEAD répond < 400."""
    try:
        _LIMITER.wait()
        r = requests.head(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
            allow_redirects=True,
        )
        return r.status_code < 400
    except requests.RequestException:
        return False
