"""Synthetic but realistic ops data for an online board-game service (mahjong / card tables).

Writes data/:
  logs/2026-09-27.log  baseline day
  logs/2026-09-28.log  incident day: Apple payment callbacks start failing signature checks at 20:00,
                       and a network blip at 21:00-21:30 causes a wave of table reconnects
  payments.csv         payment-provider export (Google Play / App Store / convenience-store codes)
  grants.csv           game-side point grants
  catalog.csv          sku -> points

Deterministic (seeded). The incident on the 28th leaves traces in *both* the logs and the payment data, which is
the point: the daily report should connect them.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TZ = timezone(timedelta(hours=8))
CATALOG = {"pts_100": (100, 30), "pts_350": (350, 90), "pts_1200": (1200, 290), "pts_4000": (4000, 890), "vip_month": (3000, 490)}


def order_id(rng: random.Random, provider: str) -> str:
    if provider == "google":
        return "GPA.%04d-%04d-%04d-%05d" % tuple(rng.randrange(10 ** k) for k in (4, 4, 4, 5))
    if provider == "apple":
        return "%d" % rng.randrange(10 ** 14, 10 ** 15)
    return "CVS%010d" % rng.randrange(10 ** 10)


def log_day(day: datetime, rng: random.Random, incident: bool) -> list[str]:
    lines = []

    def emit(t: datetime, level: str, svc: str, msg: str):
        lines.append((t, f"{t.isoformat(timespec='milliseconds')} {level:5} [{svc}] {msg}"))

    for minute in range(24 * 60):
        t0 = day + timedelta(minutes=minute)
        hour = t0.hour
        load = 0.3 + (1.2 if 19 <= hour <= 23 else 0.6 if 12 <= hour <= 18 else 0.2)   # evening peak
        for _ in range(int(rng.expovariate(1 / (8 * load))) + 1):
            t = t0 + timedelta(seconds=rng.random() * 60)
            u, tb = f"u{rng.randrange(10 ** 6):06d}", f"T{rng.randrange(1, 4000)}"
            r = rng.random()
            if r < 0.55:
                emit(t, "INFO", "room-svc", f"table={tb} player={u} joined seat={rng.randrange(1, 5)}")
            elif r < 0.80:
                emit(t, "INFO", "game-svc", f"table={tb} hand={rng.randrange(10 ** 7)} settled in {rng.randrange(40, 400)}ms")
            elif r < 0.93:
                emit(t, "INFO", "pay-svc", f"provider={rng.choice(['google', 'apple', 'cvs'])} order={order_id(rng, 'google')} granted user={u}")
            elif r < 0.985:
                emit(t, "WARN", "room-svc", f"table={tb} player={u} reconnect attempt={rng.randrange(1, 3)}")
            elif r < 0.995:
                emit(t, "WARN", "pay-svc", f"provider=google order={order_id(rng, 'google')} callback slow {rng.randrange(1500, 4000)}ms")
            else:
                emit(t, "ERROR", "match-svc", f"NullPointerException at MatchQueue.pop(MatchQueue.java:{rng.choice([118, 118, 131])})")
        if incident and 21 * 60 <= minute < 21 * 60 + 30:                                  # network blip
            for _ in range(rng.randrange(25, 45)):
                t = t0 + timedelta(seconds=rng.random() * 60)
                emit(t, "WARN", "room-svc", f"table=T{rng.randrange(1, 4000)} player=u{rng.randrange(10 ** 6):06d} reconnect attempt={rng.randrange(1, 6)}")
        if incident and minute >= 20 * 60 and rng.random() < 0.35:                          # Apple callbacks broken
            t = t0 + timedelta(seconds=rng.random() * 60)
            emit(t, "ERROR", "pay-svc", f"provider=apple order={order_id(rng, 'apple')} signature verify failed: x5c chain expired")
    return [s for _, s in sorted(lines)]


def payments_and_grants(rng: random.Random):
    pays, grants = [], []
    start = datetime(2026, 9, 27, tzinfo=TZ)
    gid = 1
    for i in range(1800):
        t = start + timedelta(seconds=rng.random() * 2 * 86400)
        provider = rng.choices(["google", "apple", "cvs"], [0.55, 0.35, 0.10])[0]
        sku = rng.choice(list(CATALOG))
        pts, twd = CATALOG[sku]
        oid, uid = order_id(rng, provider), f"u{rng.randrange(10 ** 6):06d}"
        status = "REFUNDED" if rng.random() < 0.01 else "PAID"
        pays.append({"order_id": oid, "provider": provider, "user_id": uid, "sku": sku, "amount_twd": twd, "status": status,
                     "paid_at": t.isoformat()})
        broken = provider == "apple" and t >= datetime(2026, 9, 28, 20, tzinfo=TZ)        # callbacks failing → never granted
        if broken or status == "REFUNDED" and rng.random() < 0.7:
            continue
        g = {"grant_id": gid, "order_id": oid, "user_id": uid, "points": pts, "granted_at": (t + timedelta(seconds=rng.randrange(2, 90))).isoformat()}
        grants.append(g); gid += 1
    # a few classic data problems
    for g in rng.sample(grants[:1500], 2):                                              # double grant (retry without idempotency)
        grants.append({**g, "grant_id": gid, "granted_at": g["granted_at"]}); gid += 1
    g = rng.choice(grants[:1500]); g["points"] = g["points"] * 10                        # wrong points (catalog bug)
    grants.append({"grant_id": gid, "order_id": "GPA.0000-0000-0000-00000", "user_id": "u000001", "points": 4000,
                   "granted_at": "2026-09-28T03:12:00+08:00"})                              # orphan (manual GM grant, no order)
    return pays, grants


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def main():
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    rng = random.Random(28)
    for day, incident in ((datetime(2026, 9, 27, tzinfo=TZ), False), (datetime(2026, 9, 28, tzinfo=TZ), True)):
        (DATA / "logs" / f"{day:%Y-%m-%d}.log").write_text("\n".join(log_day(day, rng, incident)) + "\n")
    pays, grants = payments_and_grants(rng)
    write_csv(DATA / "payments.csv", pays)
    write_csv(DATA / "grants.csv", grants)
    write_csv(DATA / "catalog.csv", [{"sku": k, "points": v[0], "price_twd": v[1]} for k, v in CATALOG.items()])


if __name__ == "__main__":
    main()
