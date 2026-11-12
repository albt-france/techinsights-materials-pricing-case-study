"""Tiny helper: run the SQL files of sql/ in a DuckDB database and export tables to CSV."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

from .config import ROOT, SQL

DB_PATH = ROOT / "data" / "materials.duckdb"   # git-ignored, rebuilt by every run


def connect() -> duckdb.DuckDBPyConnection:
    os.chdir(ROOT)                    # SQL files use paths relative to the project root
    return duckdb.connect(str(DB_PATH))


def run_sql(con: duckdb.DuckDBPyConnection, name: str) -> None:
    con.execute((SQL / name).read_text(encoding="utf-8"))
    print(f"  sql {name}")


def export(con: duckdb.DuckDBPyConnection, table: str, path: Path, order: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    q = f"SELECT * FROM {table}" + (f" ORDER BY {order}" if order else "")
    con.execute(f"COPY ({q}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')").fetchall()
    n = con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
    print(f"  export {path.relative_to(ROOT).as_posix():45s} {n:>7,} rows")
