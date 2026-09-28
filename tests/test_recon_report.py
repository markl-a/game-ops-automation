import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opsauto import report
from opsauto.recon import load, reconcile

DATA = Path(__file__).resolve().parent.parent / "data"
TZ = timezone(timedelta(hours=8))


@pytest.fixture(scope="module")
def recon():
    return reconcile(load(DATA), datetime(2026, 9, 29, tzinfo=TZ))


def test_injected_problems_are_found(recon):
    c = recon.counts()
    assert c["duplicate_grant"] == 2 and c["points_mismatch"] == 1 and c["orphan_grant"] == 1
    assert c["missing_grant"] > 0 and all(r["provider"] == "apple" for r in recon.findings["missing_grant"])


def test_recent_unpaid_grants_are_in_flight_not_alarms():
    early = reconcile(load(DATA), datetime(2026, 9, 28, 20, 10, tzinfo=TZ))
    assert early.counts()["missing_grant"] == 0 and early.in_flight > 0


def test_report_links_payment_incident_to_missing_grants_and_masks_users(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)          # deterministic summary
    report.main(["--out", str(tmp_path)])
    out = tmp_path / "2026-09-28"
    md = (out / "report.md").read_text()
    assert "## 關聯" in md and "apple" in md
    rows = list(csv.DictReader((out / "missing_grant.csv").open()))
    assert rows and all("***" in r["user_id"] for r in rows)
    assert "u0" not in md.split("## 日誌")[0]          # no raw user ids in the summary


@pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="needs PostgreSQL (CI service or PG_DSN)")
def test_same_sql_gives_same_answer_on_postgres(recon):
    from opsauto.recon import load_pg, reconcile_pg
    con = load_pg(os.environ["PG_DSN"], DATA)
    assert reconcile_pg(con, datetime(2026, 9, 29, tzinfo=TZ)) == recon.counts()
