"""Daily-resolution rainfall features per corridor-month, from the cached Open-Meteo series.

``data/interim/weather.parquet`` holds monthly totals only. A monthly sum cannot produce a
30-day rolling total, a 7-day maximum or a dry-spell count, so this script reads the *daily*
series that already sits in ``weather_cache.json`` (82 cells x 668 days) and derives the three
features the preflight spec names: ``rain_cum_30d``, ``rain_max_7d``, ``dry_spell_days``.

Definitions (also written into the manifest, because a feature whose definition is not
written down is not a feature):

* **trailing windows.** A window ending on day *d* covers *d - (n-1) … d*, inclusive. No
  window is centred and none looks forward.
* **``rain_mean_trailing30``.** The **mean, over the days of that month, of the trailing
  30-day precipitation total** ending on each day: an average of rolling sums, an
  antecedent-moisture index, *not* a cumulative total.
* **``rain_cum_30d``.** The **total over the trailing 30 days ending on the last day of the
  month** — this, and not the column above, is the quantity the name promises.
* **7-day window.** ``rain_max_7d`` is the **maximum** trailing 7-day total over the days of
  the month.
* **dry day.** A day with ``precipitation_sum < 1.0 mm`` (WMO "dry day"; the archive returns
  0.0 for a rainless day, so a threshold is needed to ignore trace amounts).
* **dry spell.** A run of **>= 5 consecutive dry days**. ``dry_spell_days`` counts the days of
  the month that lie inside such a run. Runs are evaluated on the continuous daily series, so
  a spell may start before the month and still count its in-month days.
* **windows are complete or null.** A 30-day total is only used when all 30 days are present;
  a 7-day total only when all 7 are. Nothing is filled, interpolated or forward-filled. Each
  feature carries the number of contributing days so a short month is visible, not hidden.
* **corridor value.** Path-length-weighted mean over the cells the centreline touches, the
  same weighting ``build_weather.py`` uses. Day-count columns take the **minimum** over
  contributing cells (the worst cell governs), matching the monthly table's convention.

The lookback problem is handled explicitly. The cache starts 2024-09-01, but a 30-day total
for 2024-09-01 needs 2024-08-02. This script may fetch 2024-08-01 … 2024-08-31 — one request
per cell, at most 82 — into a **separate** cache file (``weather_cache_2024-08.json``). The
existing cache is opened read-only. If a cell's August is unavailable, its 2024-09 windows stay
null and the count of affected corridor-months is printed and stored.

Usage::

    python scripts/build_weather_daily.py                # fetch the August lookback if absent
    python scripts/build_weather_daily.py --no-fetch      # offline; 0 requests, 2024-09 partial
    python scripts/build_weather_daily.py --summary       # reprint coverage from the parquet

Outputs (under ``data/interim/``):

* ``weather_daily_cells.parquet`` — one row per ``(cell, date)``: ``precip_mm``,
  ``from_lookback_fetch``.
* ``weather_daily_features.parquet`` — one row per ``(corridor_id, month)``.
* ``weather_daily_manifest.json`` — provenance, definitions and coverage accounting.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
BASE_CACHE = INTERIM / "weather_cache.json"
LOOKBACK_CACHE = INTERIM / "weather_cache_2024-08.json"
ASSIGNMENT = INTERIM / "weather_corridor_cells.json"
OUT_CELLS = INTERIM / "weather_daily_cells.parquet"
OUT_FEATURES = INTERIM / "weather_daily_features.parquet"
OUT_MANIFEST = INTERIM / "weather_daily_manifest.json"

START_MONTH = "2024-09"
END_MONTH = "2026-06"
LOOKBACK_START = "2024-08-01"
LOOKBACK_END = "2024-08-31"
LOOKBACK_MONTH = "2024-08"

#: One request per cell, no retries: the ticket caps the lookback at 82 requests.
MAX_LOOKBACK_REQUESTS = 82

#: A dry day is one below this daily total, in mm.
DRY_MM = 1.0
#: A dry spell is this many consecutive dry days or more.
SPELL_MIN_DAYS = 5
WINDOW_30 = 30
WINDOW_7 = 7

LICENCE = "CC BY 4.0, non-commercial use only (Open-Meteo free tier, ERA5/ERA5-Land reanalysis)"
USER_AGENT = "roadsense-ng/0.1 (corridor daily rainfall features; non-commercial research)"

FEATURES = ("rain_mean_trailing30", "rain_cum_30d", "rain_max_7d", "dry_spell_days")


# --------------------------------------------------------------------------- helpers


def month_range(start: str, end: str) -> list[str]:
    year, month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    months: list[str] = []
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def cell_centre(key: str) -> tuple[float, float]:
    lat, lon = (int(part) for part in key.split("/"))
    return lat + 0.5, lon + 0.5


# ---------------------------------------------------------------------------- caching


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def cache_days(cache: dict, source: str) -> pd.DataFrame:
    """Flatten one cache file into ``(cell, date, precip_mm, source)`` rows."""
    rows: list[dict] = []
    for key, entry in cache.items():
        payload = (entry or {}).get("response") or {}
        daily = payload.get("daily") or {}
        times = daily.get("time") or []
        values = daily.get("precipitation_sum") or []
        for date, value in zip(times, values, strict=False):
            rows.append(
                {
                    "cell": key,
                    "date": date,
                    "precip_mm": pd.to_numeric(value, errors="coerce"),
                    "source": source,
                }
            )
    return pd.DataFrame(rows, columns=["cell", "date", "precip_mm", "source"])


def fetch_lookback(cells: list[str], cache: dict) -> tuple[dict, list[str], int]:
    """One request per cell for 2024-08, no retries. Returns cache, errors, requests made."""
    missing = [cell for cell in cells if cache.get(cell, {}).get("http_status") != 200]
    if not missing:
        return cache, [], 0
    if len(missing) > MAX_LOOKBACK_REQUESTS:
        raise SystemExit(
            f"STOP: lookback needs {len(missing)} requests, cap is {MAX_LOOKBACK_REQUESTS}"
        )

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    errors: list[str] = []
    made = 0
    for index, key in enumerate(missing, start=1):
        if made >= MAX_LOOKBACK_REQUESTS:
            break
        lat, lon = cell_centre(key)
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": LOOKBACK_START,
            "end_date": LOOKBACK_END,
            "daily": "precipitation_sum",
            "timezone": "UTC",
        }
        made += 1
        try:
            response = session.get(ARCHIVE_URL, params=params, timeout=90)
        except requests.RequestException as exc:
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
            continue
        if response.status_code != 200:
            errors.append(f"{key}: HTTP {response.status_code} {response.text[:160]}")
            continue
        cache[key] = {
            "requested": {"latitude": lat, "longitude": lon},
            "url": response.url,
            "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "http_status": 200,
            "response": response.json(),
            "purpose": f"30-day lookback for {START_MONTH}",
        }
        if index % 10 == 0:
            LOOKBACK_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        time.sleep(0.2)
    LOOKBACK_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return cache, errors, made


# --------------------------------------------------------------------------- features


def cell_month_features(daily: pd.DataFrame) -> pd.DataFrame:
    """One row per ``(cell, month)`` for a single cell, from its daily series."""
    frame = daily.set_index(daily["date"].map(pd.Timestamp)).sort_index()
    index = pd.date_range(
        start=min(frame.index.min(), pd.Timestamp(LOOKBACK_START)),
        end=max(frame.index.max(), pd.Timestamp(f"{END_MONTH}-30")),
        freq="D",
    )
    precip = frame["precip_mm"].reindex(index).astype(float)

    t30 = precip.rolling(WINDOW_30, min_periods=WINDOW_30).sum()
    t7 = precip.rolling(WINDOW_7, min_periods=WINDOW_7).sum()
    present = precip.notna()
    # Counts of non-null observations inside each trailing window, so a short window is
    # reported rather than silently averaged.
    n30 = present.astype("int64").rolling(WINDOW_30, min_periods=1).sum()
    n7 = present.astype("int64").rolling(WINDOW_7, min_periods=1).sum()
    n5 = present.astype("int64").rolling(SPELL_MIN_DAYS, min_periods=1).sum()

    dry = present & (precip < DRY_MM)
    run_length = dry.groupby((~dry).cumsum()).cumsum()

    month_end = pd.Series(index.is_month_end, index=index)
    frame_out = pd.DataFrame(
        {
            "month": index.strftime("%Y-%m"),
            "t30": t30.to_numpy(),
            "t30_end": t30.where(month_end).to_numpy(),
            "n30_end": n30.where(month_end).to_numpy(),
            "t7": t7.to_numpy(),
            "n30": n30.to_numpy(),
            "n7": n7.to_numpy(),
            "n5": n5.to_numpy(),
            "in_spell": (run_length >= SPELL_MIN_DAYS).to_numpy(),
            "present": present.to_numpy(),
        }
    )
    frame_out = frame_out[
        frame_out["month"].between(START_MONTH, END_MONTH)
    ]
    grouped = frame_out.groupby("month", sort=True)
    out = pd.DataFrame(
        {
            # An average of rolling 30-day sums: antecedent moisture, not a cumulative total.
            "rain_mean_trailing30": grouped["t30"].mean(),
            "rain_mean_trailing30_days": grouped["t30"].count(),
            # The rolling 30-day sum as at the month's last day: the actual 30-day total.
            "rain_cum_30d": grouped["t30_end"].max(),
            "rain_cum_30d_days": grouped["n30_end"].max(),
            "rain_max_7d": grouped["t7"].max(),
            "rain_max_7d_days": grouped["n7"].min(),
            "dry_spell_days": grouped["in_spell"].sum(),
            "dry_spell_days_days": grouped["n5"].apply(lambda s: int((s == SPELL_MIN_DAYS).sum())),
        }
    ).reset_index()
    # A month with no determinable dry-spell day is null, not a confident zero.
    out.loc[out["dry_spell_days_days"] == 0, "dry_spell_days"] = float("nan")
    out.loc[out["rain_mean_trailing30_days"] == 0, "rain_mean_trailing30"] = float("nan")
    out.loc[out["rain_cum_30d_days"] == 0, "rain_cum_30d"] = float("nan")
    # A month with no complete 7-day window is null; ``t7.max()`` over all-NaN is NaN
    # already, so only the day count needs a guard, and it is reported, not filled.
    return out


def build_cell_months(daily: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for cell, chunk in daily.groupby("cell", sort=True):
        features = cell_month_features(chunk)
        features.insert(0, "cell", cell)
        frames.append(features)
    return pd.concat(frames, ignore_index=True)


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
    cells_total = mapping.groupby("corridor_id")["cell"].nunique().rename("n_cells_total")
    joined = mapping.merge(cell_months, on="cell", how="left")

    records: list[dict] = []
    for (corridor_id, month), block in joined.groupby(["corridor_id", "month"], sort=True):
        record = {"corridor_id": corridor_id, "month": month}
        for feature in FEATURES:
            values = block[feature]
            ok = values.notna()
            weight = block.loc[ok, "weight"].sum()
            record[feature] = (
                float((values[ok] * block.loc[ok, "weight"]).sum() / weight)
                if weight > 0
                else float("nan")
            )
            days = block.loc[ok, f"{feature}_days"]
            record[f"{feature}_days"] = float(days.min()) if len(days) else float("nan")
        record["n_cells"] = int(block[FEATURES[0]].notna().sum())
        records.append(record)

    out = pd.DataFrame.from_records(records)
    out["n_cells_total"] = out["corridor_id"].map(cells_total).astype("int32")
    out["n_cells"] = out["n_cells"].astype("int32")
    month_length = out["month"].map(
        lambda value: calendar.monthrange(int(value[:4]), int(value[5:7]))[1]
    )
    out["full_lookback_30d"] = (out["rain_mean_trailing30_days"] == month_length) & (
        out["n_cells"] == out["n_cells_total"]
    )
    for feature in FEATURES:
        out[f"{feature}_days"] = out[f"{feature}_days"].astype("float")
    # A corridor-month whose 30-day lookback is not complete for every cell is null, not a
    # mean over the days that happened to have a window. Counted in the manifest.
    for feature in FEATURES:
        out.loc[~out["full_lookback_30d"], feature] = float("nan")
    return out.sort_values(["corridor_id", "month"]).reset_index(drop=True)


# ------------------------------------------------------------------------ unit check


def unit_check(features: pd.DataFrame, daily: pd.DataFrame, assignment: dict) -> int:
    """Recompute one corridor-month from the printed daily series and compare."""
    single = sorted(cid for cid, cells in assignment.items() if len(cells) == 1)
    if not single:
        print("unit check: no single-cell corridor available")
        return 1
    corridor_id = single[0]
    cell = next(iter(assignment[corridor_id]))
    # Prefer a month where the dry-spell feature is non-zero: a check that can only return
    # zero cannot fail, so it proves nothing. Fall back to a fixed month if the corridor
    # never has a spell.
    own = features[features["corridor_id"] == corridor_id]
    best = own.sort_values(["dry_spell_days", "month"], ascending=[False, True])
    month = best.iloc[0]["month"] if best.iloc[0]["dry_spell_days"] > 0 else "2025-07"

    stored = features[(features["corridor_id"] == corridor_id) & (features["month"] == month)]
    if stored.empty:
        print(f"unit check: no stored row for {corridor_id} {month}")
        return 1
    stored = stored.iloc[0]

    series = (
        daily[daily["cell"] == cell]
        .assign(date=lambda f: f["date"].map(pd.Timestamp))
        .set_index("date")["precip_mm"]
        .sort_index()
        .astype(float)
    )
    window_start = (pd.Timestamp(f"{month}-01") - pd.Timedelta(days=WINDOW_30 - 1)).date()
    window_end = (pd.Timestamp(f"{month}-01") + pd.offsets.MonthEnd(0)).date()
    window = series.loc[str(window_start): str(window_end)]

    print()
    print("=" * 78)
    print(f"unit check: corridor {corridor_id}  cell {cell}  month {month}")
    print(f"  daily precipitation_sum, {window_start} … {window_end} "
          f"({len(window)} days, for the 30-day windows and the 7-day windows)")
    for start in range(0, len(window), 10):
        chunk = window.iloc[start: start + 10]
        pairs = "  ".join(f"{date}:{value:.1f}" for date, value in chunk.items())
        print(f"  {pairs}")

    day_30 = series.rolling(WINDOW_30, min_periods=WINDOW_30).sum()
    month_days = pd.date_range(f"{month}-01", window_end, freq="D")
    sums_30 = day_30.reindex(month_days)
    print(f"  trailing 30-day totals on each of the {len(month_days)} days of {month}:")
    print("  " + "  ".join(f"{v:.2f}" for v in sums_30.to_numpy()))
    hand_cum = float(sums_30.mean())
    print(f"  mean of those {len(sums_30)} totals = {sums_30.sum():.3f} / {len(sums_30)} "
          f"= {hand_cum:.6f} mm")
    print(f"  stored rain_mean_trailing30 = {stored['rain_mean_trailing30']:.6f} mm  "
          f"delta = {abs(hand_cum - stored['rain_mean_trailing30']):.2e}")
    hand_end = float(sums_30.iloc[-1])
    print(f"  the last of those totals is the trailing 30-day total to month end: "
          f"{hand_end:.3f} mm; stored rain_cum_30d = {stored['rain_cum_30d']:.3f} "
          f"(delta = {abs(hand_end - stored['rain_cum_30d']):.2e})")

    day_7 = series.rolling(WINDOW_7, min_periods=WINDOW_7).sum()
    sums_7 = day_7.reindex(month_days)
    hand_max = float(sums_7.max())
    print(f"  trailing 7-day totals: max over the month = {hand_max:.3f} mm "
          f"(stored rain_max_7d = {stored['rain_max_7d']:.3f}, "
          f"delta = {abs(hand_max - stored['rain_max_7d']):.2e})")

    dry = series < DRY_MM
    run = dry.groupby((~dry).cumsum()).cumsum()
    in_month = run.reindex(month_days).fillna(0)
    spell_days = int((in_month >= SPELL_MIN_DAYS).sum())
    dry_in_month = dry.reindex(month_days)
    print(f"  dry days (< {DRY_MM} mm) in {month}: {int(dry_in_month.sum())} on "
          + ", ".join(str(d.date()) for d in dry_in_month[dry_in_month].index))
    print(f"  longest run of consecutive dry days anywhere in the series: "
          f"{int(run.max())}; days of {month} inside a run of >= {SPELL_MIN_DAYS}: "
          f"{spell_days} (stored dry_spell_days = {stored['dry_spell_days']:.0f})")

    deltas = [
        abs(hand_cum - stored["rain_mean_trailing30"]),
        abs(hand_end - stored["rain_cum_30d"]),
        abs(hand_max - stored["rain_max_7d"]),
        abs(spell_days - stored["dry_spell_days"]),
    ]
    ok = all(delta < 1e-6 for delta in deltas[:3]) and deltas[3] < 1e-9
    print(f"unit check: {'MATCH' if ok else 'MISMATCH'}  "
          f"(max delta {max(deltas):.2e})")
    print("=" * 78)
    return 0 if ok else 1


# --------------------------------------------------------------------------- reporting


def print_coverage(features: pd.DataFrame, facts: dict) -> None:
    corridors = int(features["corridor_id"].nunique())
    months = int(features["month"].nunique())
    expected = facts["corridors_in_table"] * len(month_range(START_MONTH, END_MONTH))
    print()
    print(f"corridors: {corridors} of {facts['corridors_in_table']}   months: {months}   "
          f"expected corridor-months: {expected}")
    print(f"rows present: {len(features)}   rows missing: {expected - len(features)}")
    full = int(features["full_lookback_30d"].sum())
    print(f"corridor-months with a full 30-day lookback: {full}")
    print(f"corridor-months without a full 30-day lookback: {len(features) - full}")
    for month in ("2024-09", "2024-10"):
        block = features[features["month"] == month]
        print(f"  {month}: {int(block['full_lookback_30d'].sum())}/{len(block)} full, "
              f"{int(block['rain_cum_30d'].isna().sum())} null rain_cum_30d")
    for feature in FEATURES:
        print(f"nulls in {feature}: {int(features[feature].isna().sum())}")
    for feature in FEATURES:
        print(f"  {feature}_days  min {features[f'{feature}_days'].min():.0f}  "
              f"median {features[f'{feature}_days'].median():.0f}  "
              f"max {features[f'{feature}_days'].max():.0f}")
    print(f"cell-days in the daily table: {facts['cell_days']}  "
          f"duplicate (cell,date): {facts['duplicate_cell_days']}  "
          f"null precip cell-days: {facts['null_cell_days']}")
    print(f"lookback requests this run: {facts['lookback_requests']}  "
          f"lookback cells cached: {facts['lookback_cells_cached']}/{facts['cells']}")
    print(f"rain_cum_30d summary: min {features['rain_cum_30d'].min():.1f}  "
          f"mean {features['rain_cum_30d'].mean():.1f}  "
          f"max {features['rain_cum_30d'].max():.1f} mm")
    print(f"rain_mean_trailing30 summary: min {features['rain_mean_trailing30'].min():.1f}  "
          f"mean {features['rain_mean_trailing30'].mean():.1f}  "
          f"max {features['rain_mean_trailing30'].max():.1f} mm")
    impossible = int((features["rain_cum_30d"] < features["rain_max_7d"]).sum())
    print(f"corridor-months where rain_cum_30d < rain_max_7d (must be 0): {impossible}")


# ------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-fetch", action="store_true",
                        help="never touch the network; uses whatever is cached")
    parser.add_argument("--no-lookback", action="store_true",
                        help="ignore the August cache as well, showing the partial-lookback "
                             "counterfactual; writes the same files, so re-run afterwards")
    parser.add_argument("--summary", action="store_true",
                        help="reprint coverage from the existing parquet, no recompute")
    parser.add_argument("--no-unit-check", action="store_true", help="skip the hand check")
    args = parser.parse_args(argv)

    if args.summary:
        features = pd.read_parquet(OUT_FEATURES)
        manifest = json.loads(OUT_MANIFEST.read_text(encoding="utf-8"))
        print_coverage(features, manifest["coverage"])
        return 0

    started = datetime.now(UTC)
    assignment_doc = json.loads(ASSIGNMENT.read_text(encoding="utf-8"))
    assignment: dict[str, dict[str, float]] = assignment_doc["assignment"]
    cells = sorted(assignment_doc["cells"])
    corridors_in_table = pd.read_csv(INTERIM / "corridors.csv")["corridor_id"].nunique()

    base = cache_days(load_cache(BASE_CACHE), "base_cache")
    if base.empty:
        print("STOP: weather_cache.json is empty or missing")
        return 2
    if base.duplicated(subset=["cell", "date"]).any():
        dupes = int(base.duplicated(subset=["cell", "date"]).sum())
        print(f"STOP: {dupes} duplicate (cell, date) keys in the base cache")
        return 2
    base_null_days = int(base["precip_mm"].isna().sum())

    lookback_cache = load_cache(LOOKBACK_CACHE)
    lookback_errors: list[str] = []
    lookback_requests = 0
    if args.no_lookback:
        lookback_cache = {}
        print("lookback: ignored on request; 2024-09 windows will be partial")
    elif not args.no_fetch:
        lookback_cache, lookback_errors, lookback_requests = fetch_lookback(
            cells, lookback_cache
        )
        print(f"lookback: {lookback_requests} requests, {len(lookback_errors)} errors")
        for message in lookback_errors:
            print(f"  {message}")

    lookback = cache_days(lookback_cache, "lookback_fetch")
    if not lookback.empty:
        lookback = lookback[lookback["date"].str[:7] == LOOKBACK_MONTH]
    overlap = set(base["cell"] + "|" + base["date"]) & set(
        lookback["cell"] + "|" + lookback["date"]
    )
    if overlap:
        print(f"STOP: {len(overlap)} duplicate (cell, date) keys across the two caches")
        return 2

    daily = pd.concat([base, lookback], ignore_index=True)
    daily["from_lookback_fetch"] = daily["source"] == "lookback_fetch"
    daily = daily.sort_values(["cell", "date"]).reset_index(drop=True)
    duplicate_cell_days = int(daily.duplicated(subset=["cell", "date"]).sum())
    if duplicate_cell_days:
        print(f"STOP: {duplicate_cell_days} duplicate (cell, date) keys after the merge")
        return 2
    if int(daily["precip_mm"].isna().sum()):
        print(f"STOP: {int(daily['precip_mm'].isna().sum())} null daily values "
              "in the series; a window computed over a hole is not a window")
        return 2

    cell_months = build_cell_months(daily)
    features = build_corridor_months(assignment, cell_months)

    cell_out = daily[["cell", "date", "precip_mm", "from_lookback_fetch"]].copy()
    cell_out["precip_mm"] = cell_out["precip_mm"].astype("float32")

    INTERIM.mkdir(parents=True, exist_ok=True)
    cell_out.to_parquet(OUT_CELLS, index=False, compression="zstd")
    features.to_parquet(OUT_FEATURES, index=False, compression="zstd")

    expected = corridors_in_table * len(month_range(START_MONTH, END_MONTH))
    coverage = {
        "corridors_in_table": int(corridors_in_table),
        "months": len(month_range(START_MONTH, END_MONTH)),
        "expected_corridor_months": int(expected),
        "rows_present": int(len(features)),
        "rows_missing": int(expected - len(features)),
        "corridors_covered": int(features["corridor_id"].nunique()),
        "corridors_without_cells": sorted(set(assignment) ^ set(features["corridor_id"])),
        "full_lookback_corridor_months": int(features["full_lookback_30d"].sum()),
        "not_full_lookback_corridor_months": int((~features["full_lookback_30d"]).sum()),
        "lookback_gap_months": sorted(
            features.loc[~features["full_lookback_30d"], "month"].unique().tolist()
        ),
        "nulls": {feature: int(features[feature].isna().sum()) for feature in FEATURES},
        "nulls_by_month_first_five": {
            month: {
                feature: int(
                    features.loc[features["month"] == month, feature].isna().sum()
                )
                for feature in FEATURES
            }
            for month in month_range(START_MONTH, END_MONTH)[:5]
        },
        "cells": len(cells),
        "cell_days": int(len(cell_out)),
        "cell_days_from_lookback_fetch": int(cell_out["from_lookback_fetch"].sum()),
        "duplicate_cell_days": duplicate_cell_days,
        "null_cell_days": base_null_days,
    }
    requests_info = {
        "lookback_requests_this_run": lookback_requests,
        "lookback_errors": lookback_errors,
        "lookback_cache_file": LOOKBACK_CACHE.name,
        "lookback_cells_cached": int(len(lookback_cache)),
        "base_cache_file": BASE_CACHE.name,
        "base_cache_entries": int(len(load_cache(BASE_CACHE))),
    }

    gate_failures: list[str] = []
    if coverage["rows_missing"]:
        gate_failures.append(f"{coverage['rows_missing']} corridor-months absent")
    if coverage["corridors_without_cells"]:
        gate_failures.append("a corridor with cells has no feature row")
    if coverage["nulls"]["rain_cum_30d"] > len(features) * 0.05:
        gate_failures.append(
            f"{coverage['nulls']['rain_cum_30d']} null rain_cum_30d "
            f"({coverage['nulls']['rain_cum_30d'] / len(features):.1%})"
        )

    manifest = {
        "source": {
            "name": "Open-Meteo Historical Weather API (archive)",
            "url": ARCHIVE_URL,
            "variable": "precipitation_sum",
            "unit": "mm/day",
            "timezone": "UTC",
            "daily_span_in_base_cache": [
                str(base["date"].min()),
                str(base["date"].max()),
            ],
            "daily_span_in_lookback_cache": (
                [str(lookback["date"].min()), str(lookback["date"].max())]
                if not lookback.empty
                else None
            ),
            "upstream_manifest": "weather_manifest.json",
            "model_selection": "inherited from the base cache; no re-request with models=",
        },
        "licence": LICENCE,
        "access_date_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "inputs": {
            "base_cache": BASE_CACHE.name,
            "base_cache_untouched": True,
            "lookback_cache": LOOKBACK_CACHE.name if not lookback.empty else None,
            "extra_fetch": (
                {
                    "reason": f"trailing 30-day windows for {START_MONTH} start "
                             f"{LOOKBACK_START}",
                    "range": [LOOKBACK_START, LOOKBACK_END],
                    "variable": "precipitation_sum",
                    "requests_this_run": lookback_requests,
                    "cells_cached": int(len(lookback_cache)),
                    "errors": lookback_errors,
                }
                if not lookback.empty
                else None
            ),
        },
        "definitions": {
            "window_orientation": "trailing: a window ending on day d covers d-(n-1)..d inclusive",
            "rain_mean_trailing30": "mean, over the days of the month, of the trailing 30-day "
                                    "precipitation total ending on each day: an average of "
                                    "rolling sums, not a cumulative total",
            "rain_cum_30d": "precipitation total over the trailing 30 days ending on the last "
                            "day of the month",
            "rain_max_7d": "maximum trailing 7-day precipitation total over the days of the month",
            "dry_day": f"precipitation_sum < {DRY_MM} mm",
            "dry_spell": f"run of >= {SPELL_MIN_DAYS} consecutive dry days",
            "dry_spell_days": f"days of the month lying inside a run of >= {SPELL_MIN_DAYS} "
                              "consecutive dry days; fractional because it is a "
                              "path-length-weighted mean across the corridor's cells",
            "completeness": "a 30-day total needs all 30 days; a 7-day total needs all 7; "
                            "no fill, interpolation or forward-fill",
            "corridor_value": "path-length-weighted mean over the cells the centreline touches",
            "day_count_columns": "minimum over contributing cells (worst cell governs)",
            "lookback": f"days before {START_MONTH} are used only where a window needs them",
            "partial_coverage_policy": "if a corridor-month lacks a complete 30-day lookback for "
                                       "every cell, all three features are null and counted in "
                                       "this manifest rather than computed on a short window",
        },
        "coverage": coverage,
        "requests": requests_info,
        "gate": {"passed": not gate_failures, "failures": gate_failures},
        "outputs": [OUT_CELLS.name, OUT_FEATURES.name],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    facts = dict(coverage)
    facts.update(
        {
            "lookback_requests": lookback_requests,
            "lookback_cells_cached": int(len(lookback_cache)),
        }
    )
    print_coverage(features, facts)
    print(f"wrote {OUT_CELLS.relative_to(ROOT)} ({len(cell_out)} rows), "
          f"{OUT_FEATURES.relative_to(ROOT)} ({len(features)} rows), "
          f"{OUT_MANIFEST.relative_to(ROOT)}")

    status = 0
    if gate_failures:
        print("STOP: coverage gate failed:")
        for failure in gate_failures:
            print(f"  - {failure}")
        status = 2

    if not args.no_unit_check:
        status = max(status, unit_check(features, daily, assignment))
    return status


if __name__ == "__main__":
    sys.exit(main())
