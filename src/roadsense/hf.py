"""Read and write the published dataset on Hugging Face.

Why Hugging Face rather than object storage: it is the only option tested here that keeps the
project's no-payment-method rule. Cloudflare R2 requires a card on the account to enable, even
on the free tier (findings F5).

Reads are anonymous — a plain HTTPS GET against the ``resolve`` URL, no token, no client
library. Only publishing needs ``HF_TOKEN``. That asymmetry is deliberate: a stranger cloning
this repo must be able to fetch the data without creating anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from roadsense import config
from roadsense.io import download

TOKEN_ENV = "HF_TOKEN"


def resolve_url(filename: str, *, repo_id: str | None = None, revision: str | None = None) -> str:
    """Build the anonymous download URL for one file in the dataset repo."""
    repo = repo_id or config.HF_DATASET_REPO
    rev = revision or config.HF_DATASET_REVISION
    return f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{filename}"


def local_path(filename: str, *, dest_dir: Path | None = None) -> Path:
    """Where a published file is cached locally."""
    return (dest_dir or config.DATA_RAW / "published") / filename


def fetch(
    filename: str,
    *,
    dest_dir: Path | None = None,
    force: bool = False,
    repo_id: str | None = None,
    revision: str | None = None,
) -> Path:
    """Download one published file once, then reuse the cache."""
    dest = local_path(filename, dest_dir=dest_dir)
    url = resolve_url(filename, repo_id=repo_id, revision=revision)
    return download(url, dest, force=force)


def load(
    filename: str,
    *,
    dest_dir: Path | None = None,
    force: bool = False,
    repo_id: str | None = None,
) -> pd.DataFrame:
    """Load one published parquet table, fetching it if needed."""
    path = fetch(filename, dest_dir=dest_dir, force=force, repo_id=repo_id)
    return pd.read_parquet(path)


def token() -> str:
    """Read the publish token, failing with an actionable message if absent."""
    value = os.environ.get(TOKEN_ENV, "").strip()
    if not value:
        raise RuntimeError(
            f"{TOKEN_ENV} is not set. Publishing needs a Hugging Face write token; reading the "
            "dataset does not. Create one at https://huggingface.co/settings/tokens"
        )
    return value


def publish(
    folder: Path,
    *,
    repo_id: str | None = None,
    commit_message: str = "Update RoadSense Nigeria derived tables",
) -> str:
    """Upload a prepared folder to the dataset repo, creating the repo if needed.

    ``huggingface_hub`` is imported lazily so that reading the dataset by URL never depends
    on it being installed.
    """
    from huggingface_hub import HfApi

    repo = repo_id or config.HF_DATASET_REPO
    api = HfApi(token=token())
    api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        repo_id=repo,
        repo_type="dataset",
        folder_path=str(folder),
        commit_message=commit_message,
    )
    return f"https://huggingface.co/datasets/{repo}"


def describe() -> dict:
    """Machine-readable description of where the data lives, for the README and CI logs."""
    return {
        "repo": config.HF_DATASET_REPO,
        "revision": config.HF_DATASET_REVISION,
        "files": {
            name: {
                "file": filename,
                "url": resolve_url(filename),
            }
            for name, filename in config.PUBLISHED_TABLES.items()
        },
    }


def write_description(dest: Path) -> Path:
    """Write the JSON manifest next to the repo so docs never hardcode a URL by hand."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(describe(), indent=2), encoding="utf-8")
    return dest
