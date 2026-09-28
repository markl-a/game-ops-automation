"""Daily ops report: log triage + payment reconciliation, linked, as Markdown (+ CSVs for the teams that act on them).

python -m opsauto.report --day 2026-09-28 --baseline 2026-09-27 [--post]
  --post   send the summary to $OPS_WEBHOOK_URL (Slack / Teams incoming webhook); otherwise just write files.
The optional LLM summary runs only if ANTHROPIC_API_KEY is set; the report is complete without it.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .logtriage import Incident, level_counts, parse, triage
from .recon import by_provider_hour, load, reconcile

ROOT = Path(__file__).resolve().parent.parent
TZ = timezone(timedelta(hours=8))


def mask_user(uid: str) -> str:
    return uid[:3] + "***" + uid[-1:] if len(uid) > 4 else "***"


def link(incidents: list[Incident], missing: list[dict]) -> list[dict]:
    """A payment-service incident naming provider X is linked to missing grants for X that start in or after
    the incident's first hour. Code decides links; the LLM only gets told about them."""
    links = []
    for inc in incidents:
        m = re.search(r"provider=(\w+)", inc.tpl)
        if inc.svc != "pay-svc" or not m:
            continue
        start = inc.first_seen[:13]
        hits = [r for r in missing if r["provider"] == m.group(1) and r["paid_at"][:13] >= start]
        if hits:
            links.append({"incident": inc.tpl, "provider": m.group(1), "since": inc.first_seen[:16],
                          "orders": len(hits), "twd": sum(int(r["amount_twd"]) for r in hits)})
    return links


def facts(day, incidents, recon, links) -> dict:
    missing = recon.findings["missing_grant"]
    return {
        "day": day,
        "log_incidents": [{"kind": i.kind, "level": i.level, "service": i.svc, "template": i.tpl, "count": i.count,
                           "peak_hour": i.peak_hour, "peak_count": i.peak_count, "baseline_same_hour": i.baseline_at_peak}
                          for i in incidents],
        "payments": {**recon.counts(), "missing_grant_twd": sum(int(r["amount_twd"]) for r in missing),
                     "in_flight_within_sla": recon.in_flight},
        "linked": links,
    }


def llm_summary(f: dict) -> str | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic                                                     # optional dependency
    prompt = (ROOT / "prompts" / "daily_report.md").read_text().split("-->", 1)[1].replace("{facts}", json.dumps(f, ensure_ascii=False, indent=1))
    msg = anthropic.Anthropic().messages.create(model=os.environ.get("OPS_LLM_MODEL", "claude-sonnet-5"), max_tokens=600,
                                                messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text


def rule_summary(f: dict) -> str:
    """Deterministic summary - used when no LLM is configured, and as the reference the LLM text is checked against."""
    out = []
    for l in f["linked"]:
        out.append(f"- **金流組**：{l['provider']} 自 {l['since'][11:]} 起付款回調失敗，{l['orders']} 筆已付款未入點（NT${l['twd']:,}）。"
                   f"先修回調，再依清單補點；客服可先用 `missing_grant.csv` 回覆玩家。")
    p = f["payments"]
    if p["duplicate_grant"] or p["points_mismatch"]:
        out.append(f"- **遊戲後端**：重複入點 {p['duplicate_grant']} 筆、點數與商品不符 {p['points_mismatch']} 筆，需檢查入點冪等與商品設定。")
    if p["granted_but_refunded"]:
        out.append(f"- **金流＋營運**：已退款仍有點數 {p['granted_but_refunded']} 筆，需人工決定是否扣回（點數可能已花掉）。")
    if p["orphan_grant"]:
        out.append(f"- **稽核**：無對應訂單的入點 {p['orphan_grant']} 筆（可能是 GM 手動發放），逐筆確認。")
    for i in f["log_incidents"]:
        if i["kind"] == "spike":
            out.append(f"- **維運**：{i['service']} `{i['template']}` 在 {i['peak_hour']}:00 達 {i['peak_count']} 次（昨日同時段 {i['baseline_same_hour']:.0f}），確認當時網路／機房事件。")
    return "\n".join(out) or "- 今日無需處理事項。"


def render(day, lines_today, incidents, recon, links, summary) -> str:
    lc = level_counts(lines_today)
    md = [f"# 維運日報 {day}", "", "## 摘要", summary, "",
          f"## 日誌（{sum(lc.values()):,} 行；ERROR {lc.get('ERROR', 0)}、WARN {lc.get('WARN', 0)}）", "",
          "| 類型 | 等級 | 服務 | 樣板 | 次數 | 高峰 | 昨日同時段 |", "|---|---|---|---|---|---|---|"]
    for i in incidents:
        md.append(f"| {'新出現' if i.kind == 'new' else '暴增'} | {i.level} | {i.svc} | `{i.tpl}` | {i.count} | {i.peak_hour}:00 ({i.peak_count}) | {i.baseline_at_peak:.0f} |")
    for i in incidents:
        md += ["", f"<details><summary>{i.svc}: {i.tpl}</summary>", "", "```", *i.samples, "```", "</details>"]
    c = recon.counts()
    md += ["", "## 金流對帳", "", "| 檢查 | 筆數 | 說明 |", "|---|---|---|",
           f"| 已付款未入點（超過 SLA 30 分） | {c['missing_grant']} | 玩家付了錢沒拿到點數 |",
           f"| 仍在 SLA 內 | {recon.in_flight} | 回調處理中，不告警 |",
           f"| 重複入點 | {c['duplicate_grant']} | 同一訂單入點多次 |",
           f"| 點數與商品不符 | {c['points_mismatch']} | |",
           f"| 已退款仍有點數 | {c['granted_but_refunded']} | 需人工決定是否扣回 |",
           f"| 無訂單的入點 | {c['orphan_grant']} | |", ""]
    clusters = by_provider_hour(recon.findings["missing_grant"])
    if clusters:
        md += ["未入點分布（金流商 × 小時）：" + "、".join(f"{k} {v} 筆" for k, v in list(clusters.items())[:6]), ""]
    if links:
        md += ["## 關聯", ""] + [f"- `{l['incident']}` ↔ {l['provider']} 未入點 {l['orders']} 筆（NT${l['twd']:,}），自 {l['since']}" for l in links] + [""]
    md += ["明細 CSV 在同目錄（玩家 ID 已遮罩）。本報告由 `python -m opsauto.report` 產生。"]
    return "\n".join(md) + "\n"


def write_csvs(out: Path, recon) -> None:
    for name, rows in recon.findings.items():
        if not rows:
            continue
        rows = [{**r, "user_id": mask_user(r["user_id"])} if "user_id" in r else r for r in rows]
        with (out / f"{name}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)


def post(text: str) -> None:
    url = os.environ.get("OPS_WEBHOOK_URL")
    if not url:
        print("OPS_WEBHOOK_URL not set; not posting")
        return
    import httpx
    httpx.post(url, json={"text": text}, timeout=10).raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-09-28")
    ap.add_argument("--baseline", default="2026-09-27")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--post", action="store_true")
    a = ap.parse_args(argv)
    data, out = Path(a.data), Path(a.out) / a.day
    out.mkdir(parents=True, exist_ok=True)
    today, base = parse(data / "logs" / f"{a.day}.log"), parse(data / "logs" / f"{a.baseline}.log")
    incidents = triage(today, base)
    as_of = datetime.fromisoformat(a.day).replace(tzinfo=TZ) + timedelta(days=1)
    recon = reconcile(load(data), as_of)
    links = link(incidents, recon.findings["missing_grant"])
    f = facts(a.day, incidents, recon, links)
    summary = llm_summary(f) or rule_summary(f)
    (out / "facts.json").write_text(json.dumps(f, ensure_ascii=False, indent=1))
    (out / "report.md").write_text(render(a.day, today, incidents, recon, links, summary))
    write_csvs(out, recon)
    print(summary)
    if a.post:
        post(f"維運日報 {a.day}\n{summary}")


if __name__ == "__main__":
    main()
