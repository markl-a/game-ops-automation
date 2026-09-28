"""Log triage: group lines into templates, then compare today with a baseline day.

Template extraction is the masking step Drain-style parsers start with: replace ids, numbers and durations with
<*> so "table=T12 player=u000123 reconnect attempt=2" and "... T88 ... u009876 ... attempt=1" become one template.
It is deliberately simple - explainable in a code review, and good enough for service logs we control.

Two things are worth a human's attention:
  new      - a WARN/ERROR template that never appeared in the baseline
  spike    - a known template whose hourly count is far above the baseline for that hour (Poisson tail)
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

LINE = re.compile(r"^(?P<ts>\S+)\s+(?P<level>[A-Z]+)\s+\[(?P<svc>[\w-]+)\]\s+(?P<msg>.*)$")
MASKS = [
    (re.compile(r"GPA\.\d{4}-\d{4}-\d{4}-\d{5}"), "<order>"),
    (re.compile(r"\b(order=)\S+"), r"\1<order>"),
    (re.compile(r"\bu\d{6}\b"), "<user>"),
    (re.compile(r"\bT\d+\b"), "<table>"),
    (re.compile(r"\b\d+ms\b"), "<dur>"),
    (re.compile(r"(?<=[=:(])\d+\b"), "<*>"),
    (re.compile(r"\b\d{3,}\b"), "<*>"),
]
SEVERE = {"WARN", "ERROR", "FATAL"}


def template(msg: str) -> str:
    for rx, rep in MASKS:
        msg = rx.sub(rep, msg)
    return msg


@dataclass
class Line:
    hour: int
    ts: str
    level: str
    svc: str
    msg: str
    tpl: str


def parse(path: Path) -> list[Line]:
    out = []
    for raw in path.read_text().splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        ts = m["ts"]
        out.append(Line(int(ts[11:13]), ts, m["level"], m["svc"], m["msg"], template(m["msg"])))
    return out


def poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam), computed in log space for stability."""
    if k <= 0:
        return 1.0
    lam = max(lam, 0.5)                               # a template seen 0 times at that hour is not "impossible"
    log_p = -lam
    cdf = math.exp(log_p)
    for i in range(1, k):
        log_p += math.log(lam) - math.log(i)
        cdf += math.exp(log_p)
    return max(0.0, 1.0 - cdf)


@dataclass
class Incident:
    kind: str                       # new | spike
    level: str
    svc: str
    tpl: str
    count: int
    first_seen: str
    peak_hour: int
    peak_count: int
    baseline_at_peak: float
    samples: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.svc}|{self.tpl}"


def triage(today: list[Line], baseline: list[Line], p_threshold: float = 1e-6, min_ratio: float = 3.0) -> list[Incident]:
    base_hour = Counter((l.svc, l.tpl, l.hour) for l in baseline)
    base_tpls = {(l.svc, l.tpl) for l in baseline}
    groups: dict[tuple, list[Line]] = defaultdict(list)
    for l in today:
        groups[(l.svc, l.tpl)].append(l)

    incidents = []
    for (svc, tpl), lines in groups.items():
        level = max((l.level for l in lines), key=["DEBUG", "INFO", "WARN", "ERROR", "FATAL"].index)
        per_hour = Counter(l.hour for l in lines)
        peak_hour, peak = per_hour.most_common(1)[0]
        base_peak = base_hour.get((svc, tpl, peak_hour), 0)
        samples = [l.ts[11:19] + " " + l.msg for l in lines[:: max(1, len(lines) // 3)][:3]]
        common = dict(level=level, svc=svc, tpl=tpl, count=len(lines), first_seen=lines[0].ts, samples=samples)
        if (svc, tpl) not in base_tpls:
            if level in SEVERE:
                incidents.append(Incident("new", peak_hour=peak_hour, peak_count=peak, baseline_at_peak=0, **common))
            continue
        # spike: the worst hour, judged against the same hour yesterday (traffic has a strong daily shape)
        worst = min(per_hour, key=lambda h: poisson_sf(per_hour[h], base_hour.get((svc, tpl, h), 0)))
        k, lam = per_hour[worst], base_hour.get((svc, tpl, worst), 0)
        if level in SEVERE and poisson_sf(k, lam) < p_threshold and k >= min_ratio * max(lam, 1):
            incidents.append(Incident("spike", peak_hour=worst, peak_count=k, baseline_at_peak=lam, **common))
    order = {"ERROR": 0, "FATAL": 0, "WARN": 1}
    return sorted(incidents, key=lambda i: (order.get(i.level, 2), i.kind != "new", -i.count))


def level_counts(lines: list[Line]) -> dict[str, int]:
    return dict(Counter(l.level for l in lines))
