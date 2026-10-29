"""A DuckDB view over the published Parquet tables.

Eighty-six rows of corridors and a couple of thousand events fit comfortably in pandas, so this
module is not about scale. It exists because SQL is the right tool the moment the questions get
relational — "which corridors have an event in 2024 and no event in 2025" is one line here and
several merges in pandas — and because the dbt layer in Phase 4 needs a SQL engine to talk to.

Two connection modes, both free:

* **Local** — read the parquet files in ``dist/dataset`` (or ``data/interim``).
* **Remote** — point DuckDB's ``httpfs`` at the Hugging Face resolve URLs, so a fresh clone can
  query the published data without downloading it first.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from roadsense import config


def local_files(directory: Path | None = None) -> dict[str, Path]:
    """Map each table name to its parquet file, skipping tables that are not built yet."""
    base = directory or config.DIST / "dataset"
    found = {}
    for name, filename in config.PUBLISHED_TABLES.items():
        path = base / filename
        if path.exists():
            found[name] = path
    return found


def connect(
    directory: Path | None = None,
    *,
    remote: bool = False,
    repo_id: str | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open an in-memory database with one view per published table.

    ``remote=True`` creates views over HTTPS instead of local files. It requires the
    ``httpfs`` extension, which DuckDB downloads on first use — the only network access this
    module makes, and only when asked for.
    """
    con = duckdb.connect(database=":memory:")

    if remote:
        con.execute("INSTALL httpfs")
        con.execute("LOAD httpfs")
        from roadsense.hf import resolve_url

        for name, filename in config.PUBLISHED_TABLES.items():
            url = resolve_url(filename, repo_id=repo_id)
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{url}')")
        return con

    for name, path in local_files(directory).items():
        # DuckDB reads forward slashes on every platform; Windows backslashes escape in SQL.
        literal = str(path).replace("\\", "/").replace("'", "''")
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{literal}')")

    return con


def summary(con: duckdb.DuckDBPyConnection) -> dict[str, int | float]:
    """Headline counts, used as a build check and in CI logs."""
    def scalar(sql: str) -> object:
        return con.execute(sql).fetchone()[0]

    return {
        "corridors": int(scalar("SELECT count(*) FROM corridors")),
        "corridors_with_labels": int(
            scalar("SELECT count(*) FROM corridors WHERE label_events > 0")
        ),
        "named_km": round(float(scalar("SELECT sum(length_km) FROM corridors")), 1),
        "events": int(scalar("SELECT count(*) FROM events")),
        "high_confidence_matches": int(
            scalar("SELECT count(*) FROM label_matches WHERE confidence = 'high'")
        ),
    }
