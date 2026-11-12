"""Shared settings and the one HTTP helper used by every extractor.

Rules applied here (see docs/DATA_STANDARDS.md):
- official APIs or official download files only;
- low request rate (a pause between calls, retries with back-off on HTTP 429);
- every raw download is saved as a dated snapshot, so a run can be repeated offline.
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
MARTS = ROOT / "data" / "marts"
SEEDS = ROOT / "seeds"
SQL = ROOT / "sql"

START_MONTH = "2018-01"            # first month kept in the tracker
TODAY = date.today().isoformat()   # collection date written next to every observation

USER_AGENT = "materials-price-case-study/1.0 (public-data research; low request rate)"
PAUSE_SECONDS = 1.5                # polite pause between two calls to the same API


def load_env() -> None:
    """Read optional keys (e.g. COMTRADE_KEY) from a local .env file that is never committed."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch(url: str, *, params: dict | None = None, headers: dict | None = None,
          retries: int = 5, timeout: int = 300) -> requests.Response:
    """GET with a polite pause and exponential back-off on rate limits / server errors."""
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    wait = 5
    for attempt in range(retries):
        time.sleep(PAUSE_SECONDS)
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
        except requests.RequestException as exc:  # network hiccup: wait and retry
            print(f"    network error ({exc.__class__.__name__}), retry in {wait}s")
            time.sleep(wait)
            wait *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            print(f"    HTTP {r.status_code}, retry in {wait}s")
            time.sleep(wait)
            wait *= 2
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Giving up after {retries} attempts: {url}")


def snapshot_path(source: str, name: str, ext: str = "csv") -> Path:
    """data/raw/<source>/<name>.<ext>: one file per request, overwritten by each refresh.
    The collection date is stored in data/raw/<source>/_collected_on.txt."""
    folder = RAW / source
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{name}.{ext}"


def stamp(source: str) -> None:
    (RAW / source / "_collected_on.txt").write_text(TODAY + "\n", encoding="utf-8")


def collected_on(source: str) -> str:
    f = RAW / source / "_collected_on.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "unknown"
