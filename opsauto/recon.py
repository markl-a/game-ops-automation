"""Payment <-> point-grant reconciliation.

Loads the provider export and the game's grant table into a database and runs plain SQL checks. The SQL sticks to
what SQLite and PostgreSQL both accept (no FULL OUTER JOIN, no vendor functions) so the same queries run against
the real Postgres replica. Timestamps are ISO-8601 text with the same offset, so string comparison is time order.

A paid order without a grant is only a problem once it is older than the callback SLA; newer ones are in flight.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE payments (order_id TEXT PRIMARY KEY, provider TEXT, user_id TEXT, sku TEXT, amount_twd INTEGER, status TEXT, paid_at TEXT);
CREATE TABLE grants   (grant_id INTEGER PRIMARY KEY, order_id TEXT, user_id TEXT, points INTEGER, granted_at TEXT);
CREATE TABLE catalog  (sku TEXT PRIMARY KEY, points INTEGER, price_twd INTEGER);
CREATE INDEX ix_grants_order ON grants(order_id);
"""

CHECKS = {
    # paid, not refunded, no grant, older than the SLA -> player paid and got nothing
    "missing_grant": """
        SELECT p.order_id, p.provider, p.user_id, p.sku, p.amount_twd, p.paid_at
        FROM payments p LEFT JOIN grants g ON g.order_id = p.order_id
        WHERE p.status = 'PAID' AND g.grant_id IS NULL AND p.paid_at < :sla_cutoff
        ORDER BY p.paid_at""",
    # same order granted more than once -> usually a retried callback without an idempotency check
    "duplicate_grant": """
        SELECT g.order_id, g.user_id, COUNT(*) AS grants, SUM(g.points) AS points_total
        FROM grants g JOIN payments p ON p.order_id = g.order_id
        GROUP BY g.order_id, g.user_id HAVING COUNT(*) > 1""",
    # points granted differ from the catalog for the SKU paid for
    "points_mismatch": """
        SELECT g.order_id, p.sku, c.points AS expected, g.points AS granted
        FROM grants g JOIN payments p ON p.order_id = g.order_id JOIN catalog c ON c.sku = p.sku
        WHERE g.points <> c.points""",
    # refunded but points still granted -> needs a clawback decision (not automatic: points may be spent)
    "granted_but_refunded": """
        SELECT p.order_id, p.provider, p.user_id, g.points, p.paid_at
        FROM payments p JOIN grants g ON g.order_id = p.order_id WHERE p.status = 'REFUNDED'""",
    # grants with no payment behind them -> manual GM grants or worse; someone should confirm each
    "orphan_grant": """
        SELECT g.grant_id, g.order_id, g.user_id, g.points, g.granted_at
        FROM grants g LEFT JOIN payments p ON p.order_id = g.order_id WHERE p.order_id IS NULL""",
}


def load(data: Path, db: str = ":memory:") -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table in ("payments", "grants", "catalog"):
        with (data / f"{table}.csv").open() as f:
            rows = list(csv.DictReader(f))
        cols = list(rows[0])
        con.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    con.commit()
    return con


@dataclass
class ReconResult:
    findings: dict[str, list[dict]]
    in_flight: int
    as_of: str

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.findings.items()}


def reconcile(con: sqlite3.Connection, as_of: datetime, sla: timedelta = timedelta(minutes=30)) -> ReconResult:
    cutoff = (as_of - sla).isoformat()
    findings = {name: [dict(r) for r in con.execute(sql, {"sla_cutoff": cutoff})] for name, sql in CHECKS.items()}
    in_flight = con.execute("""SELECT COUNT(*) FROM payments p LEFT JOIN grants g ON g.order_id = p.order_id
                               WHERE p.status = 'PAID' AND g.grant_id IS NULL AND p.paid_at >= :c""", {"c": cutoff}).fetchone()[0]
    return ReconResult(findings, in_flight, as_of.isoformat())


def by_provider_hour(rows: list[dict]) -> dict[str, int]:
    """Missing grants bucketed by provider and hour - a cluster points at an integration, not at players."""
    out: dict[str, int] = {}
    for r in rows:
        key = f'{r["provider"]} {r["paid_at"][:13]}:00'
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def load_pg(dsn: str, data: Path):
    """Same tables and CHECKS on PostgreSQL (CI runs this against a postgres:16 service)."""
    import psycopg
    con = psycopg.connect(dsn, autocommit=True)
    con.execute("DROP TABLE IF EXISTS payments, grants, catalog")
    for stmt in filter(str.strip, SCHEMA.split(";")):
        con.execute(stmt)
    for table in ("payments", "grants", "catalog"):
        with (data / f"{table}.csv").open() as f, con.cursor().copy(f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
            cp.write(f.read())
    return con


def reconcile_pg(con, as_of: datetime, sla: timedelta = timedelta(minutes=30)) -> dict[str, int]:
    cutoff = (as_of - sla).isoformat()
    out = {}
    for name, sql in CHECKS.items():
        out[name] = len(con.execute(sql.replace(":sla_cutoff", "%(sla_cutoff)s"), {"sla_cutoff": cutoff}).fetchall())
    return out
