"""Monthly rainfall and soil moisture per corridor, from the Open-Meteo archive API.

The unit is the corridor and the period is 2024-09 … 2026-06 (22 months). A corridor is
assigned to every 1° cell its *centreline path* touches — not to the cell holding its
centroid — because a 800 km corridor crosses several cells and its rainfall is not the
rainfall of one point.

Everything here is built to make a gap visible instead of invisible:

* every cell-month carries ``days_present`` and ``days_expected`` for each variable;
* a null day is excluded and counted, never filled, forward-filled or interpolated;
* the corridor-month value is a path-length-weighted mean over its cells, and the row
  records how many cells contributed and the worst day count among them;
* the manifest records the access date, the licence, the cell count, how many HTTP
  requests were made, and the null counts, so the numbers can be audited later.

Usage::

    python scripts/build_weather.py               # full ingest, cached
    python scripts/build_weather.py --refresh     # ignore the cache, refetch every cell
    python scripts/build_weather.py --spot-check  # independent re-check of one cell
    python scripts/build_weather.py --summary     # read the parquet, print coverage only

Outputs (all under ``data/interim/``):

* ``weather.parquet`` — one row per ``(corridor_id, month)``.
* ``weather_cell_months.parquet`` — one row per ``(cell, month)`` with day coverage.
* ``weather_corridor_cells.json`` — the corridor → cell assignment with weights.
* ``weather_manifest.json`` — provenance and the coverage/null accounting.
* ``weather_cache.json`` — raw API responses, so a re-run costs zero requests.
"""

from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = ("precipitation_sum", "soil_moisture_0_to_7cm_mean")
START_DATE = "2024-09-01"
END_DATE = "2026-06-30"
START_MONTH = START_DATE[:7]
END_MONTH = END_DATE[:7]

#: Weather cells are 1° × 1° — about 110 km, the scale the preflight spec fixed.
CELL_DEG = 1.0
#: Paths are resampled at this spacing so a cell cannot be crossed between two vertices.
SAMPLE_STEP_DEG = 0.02

#: Licence as stated by Open-Meteo's terms and by DATA_LICENSE.md. Recorded per run.
LICENCE = "CC BY 4.0, non-commercial use only (Open-Meteo free tier, ERA5/ERA5-Land reanalysis)"

USER_AGENT = "roadsense-ng/0.1 (corridor weather ingest; non-commercial research)"

CACHE_PATH = INTERIM / "weather_cache.json"
OUT_PARQUET = INTERIM / "weather.parquet"
OUT_CELL_MONTHS = INTERIM / "weather_cell_months.parquet"
OUT_ASSIGNMENT = INTERIM / "weather_corridor_cells.json"
OUT_MANIFEST = INTERIM / "weather_manifest.json"

#: A cell-day null rate above this, or any whole missing cell-month, stops the run.
NULL_DAY_STOP_FRACTION = 0.05


# --------------------------------------------------------------------------- helpers


def month_range(start: str, end: str) -> list[str]:
    """``['2024-09', ..., '2026-06']`` inclusive."""
    year, month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    months: list[str] = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def days_in_month(month: str) -> int:
    year, mon = (int(part) for part in month.split("-"))
    return calendar.monthrange(year, mon)[1]


def cell_of(lat: float, lon: float) -> tuple[int, int]:
    """Integer south-west corner of the 1° cell containing the point."""
    # int() truncates toward zero, which is wrong below the equator and west of Greenwich.
    return int(lat // CELL_DEG), int(lon // CELL_DEG)


def cell_key(cell: tuple[int, int]) -> str:
    return f"{cell[0]}/{cell[1]}"


def cell_centre(cell: tuple[int, int]) -> tuple[float, float]:
    return cell[0] * CELL_DEG + CELL_DEG / 2, cell[1] * CELL_DEG + CELL_DEG / 2


def densify(path: list[list[float]], step: float = SAMPLE_STEP_DEG):
    """Yield points along a path, at most ``step`` degrees apart."""
    for index in range(len(path) - 1):
        lon0, lat0 = path[index][0], path[index][1]
        lon1, lat1 = path[index + 1][0], path[index + 1][1]
        span = max(abs(lon1 - lon0), abs(lat1 - lat0))
        steps = max(1, int(span / step) + 1)
        for n in range(steps):
            frac = n / steps
            yield lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac
    if path:
        yield path[-1][1], path[-1][0]


def corridor_names(row: pd.Series) -> list[str]:
    """The corridor's name, then any variant spellings Gate G0 merged into it."""
    names = [str(row["name"]).strip()]
    aliases = row.get("aliases")
    if isinstance(aliases, str) and aliases.strip():
        names.extend(part.strip() for part in aliases.split("|") if part.strip())
    return names


# ----------------------------------------------------------------------- assignment


def assign_corridors() -> tuple[dict[str, dict[str, float]], dict]:
    """Map every corridor to the cells its centreline touches, with length weights."""
    corridors = pd.read_csv(INTERIM / "corridors.csv")
    with gzip.open(INTERIM / "corridor_paths.json.gz", "rt", encoding="utf-8") as handle:
        paths_by_name = json.load(handle)

    assignment: dict[str, dict[str, float]] = {}
    unassigned: list[str] = []
    matched_via_alias: list[str] = []

    for _, row in corridors.iterrows():
        corridor_id = row["corridor_id"]
        chosen = None
        for name in corridor_names(row):
            if paths_by_name.get(name):
                chosen = name
                if name != str(row["name"]).strip():
                    matched_via_alias.append(corridor_id)
                break
        if chosen is None:
            unassigned.append(corridor_id)
            continue

        counts: Counter[str] = Counter()
        for path in paths_by_name[chosen]:
            if len(path) < 2:
                continue
            for lat, lon in densify(path):
                counts[cell_key(cell_of(lat, lon))] += 1
        if not counts:
            unassigned.append(corridor_id)
            continue
        total = sum(counts.values())
        assignment[corridor_id] = {
            key: round(value / total, 6) for key, value in sorted(counts.items())
        }

    claimed = {name for _, row in corridors.iterrows() for name in corridor_names(row)}
    leftovers = sorted(name for name in paths_by_name if name not in claimed)

    facts = {
        "corridors_in_table": int(len(corridors)),
        "path_names_in_file": len(paths_by_name),
        "corridors_assigned": len(assignment),
        "corridors_unassigned": unassigned,
        "corridors_matched_via_alias": matched_via_alias,
        "path_names_not_used_by_any_corridor": leftovers,
    }
    return assignment, facts


# -------------------------------------------------------------------------- fetching


class Fetcher:
    """Fetch one cell at a time, caching every response and counting real requests."""

    def __init__(self, cache: dict, *, refresh: bool = False) -> None:
        self.cache = cache
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.requests_made = 0
        self.from_cache = 0
        self.errors: list[str] = []

    def get(self, cell: tuple[int, int]) -> dict | None:
        key = cell_key(cell)
        cached = self.cache.get(key)
        if cached and not self.refresh:
            self.from_cache += 1
            return cached

        lat, lon = cell_centre(cell)
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "daily": ",".join(DAILY_VARS),
            "timezone": "UTC",
        }
        last_error = ""
        for attempt in range(3):
            self.requests_made += 1
            try:
                response = self.session.get(ARCHIVE_URL, params=params, timeout=90)
            except requests.RequestException as exc:  # network flake, not a licence issue
                last_error = f"{key}: {type(exc).__name__}: {exc}"
                time.sleep(3 * (attempt + 1))
                continue
            if response.status_code == 200:
                payload = response.json()
                entry = {
                    "requested": {"latitude": lat, "longitude": lon},
                    "url": response.url,
                    "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                    "http_status": 200,
                    "response": payload,
                }
                self.cache[key] = entry
                time.sleep(0.2)  # 600 req/min ceiling; stay far below it
                return entry
            last_error = f"{key}: HTTP {response.status_code} {response.text[:160]}"
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            break
        self.errors.append(last_error)
        return {"http_status": None, "requested": {"latitude": lat, "longitude": lon},
                "response": None, "error": last_error}


def daily_frame(entry: dict) -> pd.DataFrame | None:
    payload = entry.get("response") or {}
    daily = payload.get("daily") or {}
    if not daily.get("time"):
        return None
    frame = pd.DataFrame(
        {
            "date": daily["time"],
            **{var: daily.get(var, [None] * len(daily["time"])) for var in DAILY_VARS},
        }
    )
    frame["month"] = frame["date"].str[:7]
    for var in DAILY_VARS:
        frame[var] = pd.to_numeric(frame[var], errors="coerce")
    return frame


def monthly_cell_frame(cell: tuple[int, int], entry: dict) -> tuple[list[dict], dict]:
    """One row per month for this cell, with day coverage and no filling."""
    rows: list[dict] = []
    meta = {
        "cell": cell_key(cell),
        "requested_lat": round(cell_centre(cell)[0], 4),
        "requested_lon": round(cell_centre(cell)[1], 4),
        "snapped_lat": None,
        "snapped_lon": None,
        "elevation_m": None,
        "days_returned": 0,
        "days_expected_total": 0,
        "error": entry.get("error"),
    }
    frame = daily_frame(entry)
    if frame is None:
        return rows, meta

    payload = entry["response"]
    meta["snapped_lat"] = payload.get("latitude")
    meta["snapped_lon"] = payload.get("longitude")
    meta["elevation_m"] = payload.get("elevation")
    meta["days_returned"] = int(len(frame))
    meta["days_expected_total"] = sum(map(days_in_month, month_range(START_MONTH, END_MONTH)))

    for month, chunk in frame.groupby("month", sort=True):
        if not (START_MONTH <= month <= END_MONTH):
            continue
        expected = days_in_month(month)
        precip = chunk["precipitation_sum"]
        soil = chunk["soil_moisture_0_to_7cm_mean"]
        rows.append(
            {
                "cell": cell_key(cell),
                "month": month,
                "days_in_frame": int(len(chunk)),
                "days_expected": expected,
                "precip_days_present": int(precip.notna().sum()),
                "soil_days_present": int(soil.notna().sum()),
                "precip_mm": round(float(precip.sum()), 3) if precip.notna().any() else None,
                "soil_moisture_mean": (
                    round(float(soil.mean()), 6) if soil.notna().any() else None
                ),
            }
        )
    return rows, meta


# ------------------------------------------------------------------------ reporting


def content_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(frame, index=False)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()[:16]


def build_corridor_months(
    assignment: dict[str, dict[str, float]], cell_months: pd.DataFrame
) -> pd.DataFrame:
    mapping = pd.DataFrame(
        [
            (corridor_id, cell, weight)
            for corridor_id, cells in assignment.items()
            for cell, weight in cells.items()
        ],
        columns=["corridor_id", "cell", "weight"],
    )
    joined = mapping.merge(cell_months, on="cell", how="left")
    joined["cap_weight"] = joined["weight"].where(joined["precip_mm"].notna())
    joined["soil_weight"] = joined["weight"].where(joined["soil_moisture_mean"].notna())
    joined["w_precip"] = joined["weight"] * joined["precip_mm"]
    joined["w_soil"] = joined["weight"] * joined["soil_moisture_mean"]
    joined["days_present"] = joined[["precip_days_present", "soil_days_present"]].min(axis=1)
    # A cell only counts as contributing if it returned a value for that month.
    joined["_precip_ok"] = joined["precip_mm"].notna().astype("int8")

    grouped = joined.groupby(["corridor_id", "month"], sort=True)
    out = pd.DataFrame(
        {
            "precip_mm": grouped["w_precip"].sum(min_count=1)
            / grouped["cap_weight"].sum(min_count=1),
            "soil_moisture_mean": grouped["w_soil"].sum(min_count=1)
            / grouped["soil_weight"].sum(min_count=1),
            "n_cells": grouped["_precip_ok"].sum(),
            "days_present": grouped["days_present"].min(),
            "days_expected": grouped["days_expected"].min(),
        }
    ).reset_index()
    out["n_cells_total"] = out["corridor_id"].map(
        {cid: len(cells) for cid, cells in assignment.items()}
    )
    out["complete"] = (out["days_present"] >= out["days_expected"]) & (
        out["n_cells"] == out["n_cells_total"]
    )
    out["precip_mm"] = out["precip_mm"].astype(float)
    out["soil_moisture_mean"] = out["soil_moisture_mean"].astype(float)
    out["n_cells"] = out["n_cells"].astype("int32")
    out["n_cells_total"] = out["n_cells_total"].astype("int32")
    out["days_present"] = out["days_present"].astype("Int32")
    out["days_expected"] = out["days_expected"].astype("int32")
    return out.sort_values(["corridor_id", "month"]).reset_index(drop=True)


def print_coverage(
    frame: pd.DataFrame,
    facts: dict,
    cell_months: pd.DataFrame,
    meta_frame: pd.DataFrame | None = None,
) -> None:
    corridors = int(frame["corridor_id"].nunique())
    months = int(frame["month"].nunique())
    expected = int(facts.get("corridors_in_table", corridors)) * months
    print(f"corridors: {corridors}  months: {months}  expected corridor-months: {expected}")
    print(f"rows present: {len(frame)}  missing: {expected - len(frame)}")
    print(f"corridors assigned to >=1 cell: {facts.get('corridors_assigned')}/"
          f"{facts.get('corridors_in_table')}")
    print(f"cells used: {facts.get('cells')}  requests this run: {facts.get('requests_made')}"
          f"  served from cache: {facts.get('from_cache')}")
    if meta_frame is not None and len(meta_frame):
        print(f"cell-days returned: min {int(meta_frame['days_returned'].min())} against "
              f"{int(meta_frame['days_expected_total'].iloc[0])} expected per cell")
    print(f"cell-months with a null precip day: "
          f"{int((cell_months['null_precip_days'] > 0).sum())} of {len(cell_months)}")
    print(f"cell-months with a null soil day: "
          f"{int((cell_months['null_soil_days'] > 0).sum())} of {len(cell_months)}")
    print(f"corridor-months fully covered: {int(frame['complete'].sum())}/{len(frame)} "
          f"({frame['complete'].mean():.2%})")
    print(f"content hash: {content_hash(frame)}")


def spot_check() -> int:
    """Re-fetch one cell live and compare it with what is already on disk.

    Independent of the cache on purpose: this is the check a stranger re-runs when they
    doubt the parquet. It uses a corridor that sits in exactly one cell, so the corridor
    figure should equal the cell figure with no weighting in between.
    """
    if not (OUT_PARQUET.exists() and OUT_CELL_MONTHS.exists() and OUT_ASSIGNMENT.exists()):
        print("spot check needs a completed run first; nothing on disk")
        return 2

    frame = pd.read_parquet(OUT_PARQUET)
    cell_months = pd.read_parquet(OUT_CELL_MONTHS)
    assignment = json.loads(OUT_ASSIGNMENT.read_text(encoding="utf-8"))["assignment"]

    counts = Counter(cell for cells in assignment.values() for cell in cells)
    cell = counts.most_common(1)[0][0]
    single = sorted(cid for cid, cells in assignment.items() if list(cells) == [cell])
    month = "2025-07"

    lat_int, lon_int = (int(part) for part in cell.split("/"))
    centre = cell_centre((lat_int, lon_int))
    params = {
        "latitude": f"{centre[0]:.4f}",
        "longitude": f"{centre[1]:.4f}",
        "start_date": f"{month}-01",
        "end_date": f"{month}-{days_in_month(month):02d}",
        "daily": ",".join(DAILY_VARS),
        "timezone": "UTC",
    }
    response = requests.get(ARCHIVE_URL, params=params, timeout=90,
                            headers={"User-Agent": USER_AGENT})
    print(f"spot check: HTTP {response.status_code} in {response.elapsed.total_seconds():.2f}s")
    response.raise_for_status()
    payload = response.json()

    direct = pd.to_numeric(pd.Series(payload["daily"]["precipitation_sum"]), errors="coerce")
    direct_sum = float(direct.sum())
    stored = cell_months[(cell_months["cell"] == cell) & (cell_months["month"] == month)]
    stored_precip = float(stored["precip_mm"].iloc[0])
    stored_days = int(stored["precip_days_present"].iloc[0])

    print(f"cell {cell}: requested ({params['latitude']}, {params['longitude']}), "
          f"returned ({payload.get('latitude')}, {payload.get('longitude')})")
    print(f"direct API {month} precipitation_sum: {len(direct)} days, "
          f"{int(direct.notna().sum())} non-null, sum {direct_sum:.3f} mm")
    print(f"parquet cell-month: {stored_precip:.3f} mm over {stored_days} non-null days")
    print(f"delta: {abs(direct_sum - stored_precip):.6f} mm")

    if not single:
        print("no single-cell corridor for this cell; cell comparison only")
        return 0 if abs(direct_sum - stored_precip) < 5e-4 else 1

    corridor_id = single[0]
    row = frame[(frame["corridor_id"] == corridor_id) & (frame["month"] == month)]
    corridor_precip = float(row["precip_mm"].iloc[0])
    print(f"corridor {corridor_id} sits in cell {cell} only; "
          f"parquet precip_mm = {corridor_precip:.3f}, "
          f"delta vs direct {abs(corridor_precip - direct_sum):.6f} mm")
    ok = abs(direct_sum - stored_precip) < 5e-4 and abs(corridor_precip - direct_sum) < 5e-4
    print("spot check: " + ("MATCH" if ok else "MISMATCH"))
    return 0 if ok else 1


# ----------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="ignore the response cache")
    parser.add_argument("--spot-check", action="store_true",
                        help="re-check one cell against a direct API call, then exit")
    parser.add_argument("--summary", action="store_true",
                        help="print coverage from the existing parquet only, no network")
    args = parser.parse_args(argv)

    started = datetime.now(UTC)
    months = month_range(START_MONTH, END_MONTH)

    if args.summary:
        frame = pd.read_parquet(OUT_PARQUET)
        cell_months = pd.read_parquet(OUT_CELL_MONTHS)
        manifest = json.loads(OUT_MANIFEST.read_text(encoding="utf-8"))
        facts = dict(manifest["coverage"])
        facts["requests_made"] = manifest["requests"]["made_this_run"]
        facts["from_cache"] = manifest["requests"]["served_from_cache"]
        print_coverage(frame, facts, cell_months)
        return 0

    if args.spot_check:
        return spot_check()

    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    assignment, facts = assign_corridors()
    cells = sorted(
        {cell for cell_map in assignment.values() for cell in cell_map},
        key=lambda key: (int(key.split("/")[0]), int(key.split("/")[1])),
    )
    facts["cells"] = len(cells)

    fetcher = Fetcher(cache, refresh=args.refresh)
    cell_rows: list[dict] = []
    meta_rows: list[dict] = []

    for index, key in enumerate(cells, start=1):
        lat_int, lon_int = (int(part) for part in key.split("/"))
        entry = fetcher.get((lat_int, lon_int))
        rows, meta = monthly_cell_frame((lat_int, lon_int), entry or {})
        cell_rows.extend(rows)
        meta_rows.append(meta)
        if index % 25 == 0 or index == len(cells):
            print(f"  fetched {index}/{len(cells)} cells, "
                  f"{sum(1 for r in cell_rows if r['precip_mm'] is None)} null cell-months",
                  flush=True)
            CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")

    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")

    if fetcher.errors:
        print("STOP: cell fetches failed:")
        for message in fetcher.errors:
            print(f"  {message}")
        return 2

    cell_months = pd.DataFrame(cell_rows)
    meta_frame = pd.DataFrame(meta_rows)

    # Every cell must have a row for every month, or the gap is the finding.
    expected_cell_months = len(cells) * len(months)
    missing_cell_months = expected_cell_months - len(cell_months)

    # Snapping: the API returns its own grid point. Two cells landing on the same point
    # means the grid is coarser than 1° and the cells are not independent.
    snapped = meta_frame.dropna(subset=["snapped_lat", "snapped_lon"])
    duplicate_snaps = snapped.duplicated(subset=["snapped_lat", "snapped_lon"], keep=False)
    snap_offset = (
        (snapped["snapped_lat"] - snapped["requested_lat"]).abs().max(),
        (snapped["snapped_lon"] - snapped["requested_lon"]).abs().max(),
    )

    cell_months["null_precip_days"] = cell_months["days_expected"] - cell_months["precip_days_present"]
    cell_months["null_soil_days"] = cell_months["days_expected"] - cell_months["soil_days_present"]

    corridor_months = build_corridor_months(assignment, cell_months)
    corridor_months = corridor_months[
        corridor_months["month"].between(START_MONTH, END_MONTH)
    ].reset_index(drop=True)

    frame = corridor_months[[
        "corridor_id", "month", "precip_mm", "soil_moisture_mean",
        "n_cells", "n_cells_total", "days_present", "days_expected", "complete",
    ]]

    INTERIM.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT_PARQUET, index=False, compression="zstd")
    cell_months.sort_values(["cell", "month"]).to_parquet(
        OUT_CELL_MONTHS, index=False, compression="zstd"
    )
    OUT_ASSIGNMENT.write_text(
        json.dumps(
            {
                "cell_deg": CELL_DEG,
                "sample_step_deg": SAMPLE_STEP_DEG,
                "cells": sorted({cell for cells_map in assignment.values() for cell in cells_map}),
                "assignment": assignment,
            },
            indent=None,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    total_days = int(cell_months["days_expected"].sum())
    null_precip_days = int(cell_months["null_precip_days"].sum())
    null_soil_days = int(cell_months["null_soil_days"].sum())
    null_fraction = max(null_precip_days, null_soil_days) / total_days if total_days else 1.0

    gate_failures: list[str] = []
    if missing_cell_months:
        gate_failures.append(f"{missing_cell_months} cell-months absent entirely")
    if facts["corridors_unassigned"]:
        gate_failures.append(f"{len(facts['corridors_unassigned'])} corridors in no cell")
    if null_fraction > NULL_DAY_STOP_FRACTION:
        gate_failures.append(f"null cell-days {null_fraction:.2%} > "
                             f"{NULL_DAY_STOP_FRACTION:.0%}")
    if bool(duplicate_snaps.any()):
        gate_failures.append("two cells snapped to the same API grid point")

    coverage = {
        "corridors_in_table": facts["corridors_in_table"],
        "months_expected": len(months),
        "expected_corridor_months": facts["corridors_in_table"] * len(months),
        "rows_present": int(len(frame)),
        "rows_missing": facts["corridors_in_table"] * len(months) - int(len(frame)),
        "corridors_assigned": facts["corridors_assigned"],
        "corridors_unassigned": facts["corridors_unassigned"],
        "corridors_matched_via_alias": facts["corridors_matched_via_alias"],
        "path_names_not_used_by_any_corridor": facts["path_names_not_used_by_any_corridor"],
        "cells": facts["cells"],
        "cell_months_present": int(len(cell_months)),
        "cell_months_expected": expected_cell_months,
        "cell_months_missing": missing_cell_months,
        "cell_days_expected": total_days,
        "null_days": {"precipitation_sum": null_precip_days,
                      "soil_moisture_0_to_7cm_mean": null_soil_days},
        "null_day_fraction": round(null_fraction, 6),
        "cell_months_with_any_null_precip_day": int((cell_months["null_precip_days"] > 0).sum()),
        "cell_months_with_any_null_soil_day": int((cell_months["null_soil_days"] > 0).sum()),
        "fully_covered_corridor_months": int(frame["complete"].sum()),
        "corridor_months_with_no_value": int(frame["precip_mm"].isna().sum()),
        "days_present_min": int(cell_months["precip_days_present"].min()),
        "snap_offset_max_deg": [round(float(snap_offset[0]), 6),
                                round(float(snap_offset[1]), 6)],
        "cells_sharing_a_grid_point": int(duplicate_snaps.sum()),
        "content_hash": content_hash(frame),
    }

    manifest = {
        "source": {
            "name": "Open-Meteo Historical Weather API (archive)",
            "url": ARCHIVE_URL,
            "variables": list(DAILY_VARS),
            "units": {"precipitation_sum": "mm/day", "soil_moisture_0_to_7cm_mean": "m3/m3"},
            "start_date": START_DATE,
            "end_date": END_DATE,
            "cell_deg": CELL_DEG,
            "sample_step_deg": SAMPLE_STEP_DEG,
            "timezone": "UTC",
            "parameters": ["latitude", "longitude", "start_date", "end_date", "daily",
                           "timezone"],
            "model_selection": "API default (best_match); no models= parameter was pinned",
        },
        "licence": LICENCE,
        "access_date_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "requests": {
            "made_this_run": fetcher.requests_made,
            "served_from_cache": fetcher.from_cache,
            "cache_entries": len(cache),
            "first_fetch_utc": min(
                (entry["fetched_utc"] for entry in cache.values()
                 if entry.get("fetched_utc")),
                default=None,
            ),
            "cache_file": CACHE_PATH.name,
        },
        "transform": {
            "rainfall": "sum of daily precipitation_sum over non-null days in the month",
            "soil_moisture": "mean of daily soil_moisture_0_to_7cm_mean over non-null days",
            "corridor_month": "path-length-weighted mean over the cells the centreline touches",
            "null_policy": "excluded and counted; no fill, forward-fill or interpolation",
        },
        "coverage": coverage,
        "gate": {"passed": not gate_failures, "failures": gate_failures},
        "outputs": [OUT_PARQUET.name, OUT_CELL_MONTHS.name, OUT_ASSIGNMENT.name],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print_coverage(
        frame,
        {
            "corridors_in_table": facts["corridors_in_table"],
            "corridors_assigned": facts["corridors_assigned"],
            "cells": facts["cells"],
            "requests_made": fetcher.requests_made,
            "from_cache": fetcher.from_cache,
        },
        cell_months,
        meta_frame,
    )
    print(f"snap: max offset {coverage['snap_offset_max_deg']} deg, "
          f"{coverage['cells_sharing_a_grid_point']} cells share a grid point")
    print(f"wrote {OUT_PARQUET.relative_to(ROOT)} ({len(frame)} rows), "
          f"{OUT_CELL_MONTHS.relative_to(ROOT)}, {OUT_ASSIGNMENT.relative_to(ROOT)}, "
          f"{OUT_MANIFEST.relative_to(ROOT)}")

    if gate_failures:
        print("STOP: coverage gate failed:")
        for failure in gate_failures:
            print(f"  - {failure}")
        return 2
    print("gate: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
