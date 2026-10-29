"""Thin, dependency-free I/O helpers.

Deliberately stdlib-only: Gate G0 must run on a bare interpreter with pandas and
nothing else, so the go/no-go test cannot be blocked by a geospatial install.
"""

from __future__ import annotations

import json
import shutil
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "roadsense-ng/0.1 (+https://github.com/; research project)"


def fetch_bytes(url: str, *, timeout: int = 120, retries: int = 4) -> bytes:
    """GET ``url`` and return the body, retrying transient failures with backoff."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised after
            last_error = exc
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def fetch_json(url: str, *, timeout: int = 120) -> Any:
    """GET ``url`` and parse the response as JSON."""
    return json.loads(fetch_bytes(url, timeout=timeout))


def download(url: str, dest: Path, *, force: bool = False, timeout: int = 300) -> Path:
    """Download ``url`` to ``dest`` unless it already exists.

    Caching matters here: the OCDS bundle is ~23 MB and the GRID3 pull is ~41 MB, and
    neither should be re-fetched on every run or on every CI job that can avoid it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        return dest
    payload = fetch_bytes(url, timeout=timeout)
    dest.write_bytes(payload)
    return dest


def extract_tarball(archive: Path, dest_dir: Path, *, force: bool = False) -> Path:
    """Extract ``archive`` into ``dest_dir`` unless it has already been extracted."""
    marker = dest_dir / ".extracted"
    if marker.exists() and not force:
        return dest_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest_dir, filter="data")
    marker.write_text("ok", encoding="utf-8")
    return dest_dir


def write_manifest(dest: Path, entries: dict[str, str]) -> Path:
    """Record source URLs and retrieval timestamps for provenance."""
    payload = {
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": entries,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def quote(value: str) -> str:
    """URL-encode a query value."""
    return urllib.parse.quote(value, safe="")


def copytree(src: Path, dst: Path) -> None:
    """Copy a directory tree, replacing the destination."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
