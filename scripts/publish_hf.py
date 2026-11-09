"""Stage the published tables and push them to a public Hugging Face dataset.

Usage:
    python scripts/publish_hf.py             # stage only, verify hashes, write README.md
    python scripts/publish_hf.py --upload    # stage, then push to JBZABC/roadsense-nigeria
    python scripts/publish_hf.py --list      # print the remote file list with sizes

Reads (never modifies): data/features/imagery_r10.parquet,
data/interim/{condition,weather,weather_daily_features}.parquet, data/interim/corridors.csv,
the four manifests, docs/dataset-card.md.
Writes: data/publish_staging/**  (gitignored; README.md is the dataset card).

The read path for published data stays anonymous (plain HTTPS, `hf_hub_download` with
`token=False`). Only this script needs a credential, read from HF_TOKEN or the local login;
neither is ever printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "data" / "publish_staging"
REPO_ID = "JBZABC/roadsense-nigeria"

# staged name -> (source path, sha256 recorded in which manifest, record path, rows record)
SOURCES: dict[str, tuple[Path, str | None]] = {
    "imagery_r10.parquet": (ROOT / "data/features/imagery_r10.parquet", "imagery"),
    "condition.parquet": (ROOT / "data/interim/condition.parquet", "condition"),
    "weather.parquet": (ROOT / "data/interim/weather.parquet", None),
    "weather_daily_features.parquet": (
        ROOT / "data/interim/weather_daily_features.parquet",
        None,
    ),
    "corridors.csv": (ROOT / "data/interim/corridors.csv", None),
    "imagery_r10.manifest.json": (ROOT / "data/features/imagery_r10.manifest.json", None),
    "condition.manifest.json": (ROOT / "data/interim/condition.manifest.json", None),
    "weather_manifest.json": (ROOT / "data/interim/weather_manifest.json", None),
    "weather_daily_manifest.json": (ROOT / "data/interim/weather_daily_manifest.json", None),
}

CARD = ROOT / "docs" / "dataset-card.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recorded_hashes() -> dict[str, str]:
    """SHA-256 values the manifests claim, so staging proves the copy is the measured file."""
    imagery = json.loads((ROOT / "data/features/imagery_r10.manifest.json").read_text(encoding="utf-8"))
    condition = json.loads((ROOT / "data/interim/condition.manifest.json").read_text(encoding="utf-8"))
    return {
        "imagery": imagery["output_sha256"],
        "condition": condition["output"]["sha256"],
    }


def manifest_rows() -> dict[str, int]:
    imagery = json.loads((ROOT / "data/features/imagery_r10.manifest.json").read_text(encoding="utf-8"))
    condition = json.loads((ROOT / "data/interim/condition.manifest.json").read_text(encoding="utf-8"))
    weather = json.loads((ROOT / "data/interim/weather_manifest.json").read_text(encoding="utf-8"))
    daily = json.loads((ROOT / "data/interim/weather_daily_manifest.json").read_text(encoding="utf-8"))
    return {
        "imagery_r10.parquet": imagery["rows"],
        "condition.parquet": condition["coverage"]["rows"],
        "weather.parquet": weather["coverage"]["rows_present"],
        "weather_daily_features.parquet": daily["coverage"]["rows_present"],
        "corridors.csv": condition["coverage"]["corridors"],
    }


def stage() -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    claimed = recorded_hashes()

    for name, (source, check) in SOURCES.items():
        if not source.exists():
            raise FileNotFoundError(f"missing {source}")
        target = STAGING / name
        shutil.copy2(source, target)
        actual = sha256(target)
        if check is not None:
            expected = claimed[check]
            status = "matches manifest" if actual == expected else "MISMATCH"
            print(f"  {name:34s} sha256 {actual[:12]}…  {status}")
            if actual != expected:
                raise SystemExit(f"[publish] {name} does not match the manifest hash; refusing")
        else:
            print(f"  {name:34s} sha256 {actual[:12]}…  (no manifest hash recorded)")

    if not CARD.exists():
        raise FileNotFoundError(f"missing {CARD}; the dataset card is written by hand")
    shutil.copy2(CARD, STAGING / "README.md")
    print(f"  {'README.md':34s} (from docs/dataset-card.md)")

    rows = manifest_rows()
    print("\n[publish] rows: staged vs manifest")
    for name, claimed_rows in rows.items():
        path = STAGING / name
        if name.endswith(".parquet"):
            staged_rows = len(pd.read_parquet(path, columns=["corridor_id"]))
        else:
            staged_rows = len(pd.read_csv(path))
        flag = "ok" if staged_rows == claimed_rows else "MISMATCH"
        print(f"  {name:34s} {staged_rows:>7,} vs {claimed_rows:>7,}  {flag}")
        if staged_rows != claimed_rows:
            raise SystemExit(f"[publish] {name} row count disagrees with its manifest")

    total = sum(p.stat().st_size for p in STAGING.iterdir() if p.is_file())
    print(f"\n[publish] staged {len(list(STAGING.iterdir()))} files, {total / 1e6:.2f} MB in "
          f"{STAGING.relative_to(ROOT)}")


def upload() -> None:
    from huggingface_hub import HfApi

    api = HfApi()  # token from HF_TOKEN or the local login; never printed
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="dataset",
        folder_path=str(STAGING),
        commit_message="Publish corridor imagery, condition, weather and the dataset card",
    )
    print(f"\n[publish] uploaded to https://huggingface.co/datasets/{REPO_ID}")
    list_remote(api)


def list_remote(api=None) -> None:
    from huggingface_hub import HfApi

    api = api or HfApi()
    info = api.dataset_info(REPO_ID, files_metadata=True)
    print(f"[publish] private={info.private}  files={len(info.siblings)}")
    for sibling in sorted(info.siblings, key=lambda s: s.rfilename):
        size = sibling.size or 0
        print(f"  {sibling.rfilename:34s} {size:>10,} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true", help="push the staging directory")
    parser.add_argument("--list", action="store_true", help="print the remote file list and exit")
    args = parser.parse_args()

    if args.list:
        list_remote()
        return 0

    stage()
    if args.upload:
        upload()
    else:
        print("\n[publish] staged only — pass --upload to push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
