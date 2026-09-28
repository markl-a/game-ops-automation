from pathlib import Path

from opsauto.logtriage import Line, parse, poisson_sf, template, triage

DATA = Path(__file__).resolve().parent.parent / "data" / "logs"


def test_template_masks_variables_but_keeps_meaning():
    a = template("table=T12 player=u000123 reconnect attempt=2")
    b = template("table=T3999 player=u987654 reconnect attempt=5")
    assert a == b == "table=<table> player=<user> reconnect attempt=<*>"
    assert "signature verify failed" in template("provider=apple order=739643493162077 signature verify failed: x5c chain expired")


def test_poisson_tail():
    assert poisson_sf(0, 3) == 1.0
    assert poisson_sf(30, 3) < 1e-15
    assert 0.3 < poisson_sf(3, 3) < 0.7


def test_incident_day_finds_new_payment_error_and_reconnect_spike():
    inc = triage(parse(DATA / "2026-09-28.log"), parse(DATA / "2026-09-27.log"))
    kinds = {(i.kind, i.svc) for i in inc}
    assert ("new", "pay-svc") in kinds and ("spike", "room-svc") in kinds
    assert len(inc) == 2                              # nothing else on a normal-looking evening peak


def test_quiet_day_against_itself_has_no_incidents():
    day = parse(DATA / "2026-09-27.log")
    assert triage(day, day) == []


def test_info_lines_never_become_incidents():
    today = [Line(10, "2026-09-28T10:00:00", "INFO", "x", "hello", "hello")] * 500
    assert triage(today, []) == []
