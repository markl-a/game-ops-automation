# game-ops-automation

**Turns an online board-game service's overnight logs and payment data into one morning report. Each report says what broke, who owns it, and how many players paid without receiving points. It also includes API contract tests that stop the same class of bug from coming back.**

This is a portfolio demo from September 2026. The logs and payments are **synthetic** (`opsauto/simulate.py`, seeded) for a mahjong / card-table style service. They contain one planted incident, which leaves traces in both the logs and the money.

## The morning report (`python -m opsauto.report`)

Real output on the sample day (`reports/2026-09-28/report.md`):

> - **金流組**：apple 自 20:01 起付款回調失敗，40 筆已付款未入點（NT$12,860）。先修回調，再依清單補點；客服可先用 `missing_grant.csv` 回覆玩家。
> - **遊戲後端**：重複入點 2 筆、點數與商品不符 1 筆，需檢查入點冪等與商品設定。
> - **金流＋營運**：已退款仍有點數 5 筆，需人工決定是否扣回（點數可能已花掉）。
> - **稽核**：無對應訂單的入點 1 筆（可能是 GM 手動發放），逐筆確認。
> - **維運**：room-svc `table=<table> player=<user> reconnect attempt=<*>` 在 21:00 達 1135 次（昨日同時段 29），確認當時網路／機房事件。

How it gets there:

| Step | What | Why this way |
|---|---|---|
| **Log triage** (`logtriage.py`) | Mask IDs, numbers and durations, which turns 11,818 lines into 9 templates. Flag WARN/ERROR templates that are **new** versus the baseline day, or that **spike** above the same hour yesterday (Poisson tail, p < 1e-6 and ≥3×) | Traffic has a strong evening peak, so comparing to the daily average would alert every night. The same hour yesterday is the right baseline |
| **Reconciliation** (`recon.py`) | Plain SQL checks for missing grants, duplicate grants, points ≠ catalog, refunded-but-granted, and grants with no order | The same SQL runs on SQLite and PostgreSQL; CI proves parity. Unpaid orders inside the 30-min callback SLA are "in flight", not alarms |
| **Linking** (`report.link`) | A `pay-svc` incident naming provider X is linked to X's missing grants from that hour onward | Code decides links; the LLM is only told about them |
| **Summary** | Deterministic Chinese summary by default. With `ANTHROPIC_API_KEY` set, an LLM rewrites `facts.json` using [prompts/daily_report.md](prompts/daily_report.md) | The LLM gets aggregated numbers only, never user or order IDs, and is told not to add facts |
| **Outputs** | `report.md`, `facts.json`, one CSV per finding (player IDs masked), optional post to a Slack/Teams webhook | Customer service gets a list to answer players from; payments gets a list to re-grant from |

Scheduling example: [.github/workflows/daily-report.yml](.github/workflows/daily-report.yml) (08:30 Taipei, uploads the report as an artifact, and posts only if the webhook secret exists).

## API contract tests (`tests/api/`)

Every case maps to a finding the report can produce:

| Report finding | Contract test |
|---|---|
| Duplicate grant | Retry with the same `Idempotency-Key` returns the same result, and the balance doesn't move |
| | The same order with a *new* key returns 409, because the order is the real unit of idempotency |
| Points ≠ catalog | A top-up grants exactly the catalog points |
| Grants for bad input | Unknown SKU, malformed user or missing key: 422, and the balance doesn't move |

They run in-process against a small FastAPI mock by default. The **same tests run against a real environment** with `API_BASE_URL=https://staging…`, because they only use the public API.

## Working with coding agents

- [CLAUDE.md](CLAUDE.md) sets the rules the agent follows here. Numbers come from code with tests, the LLM never sees IDs, and SQL must stay portable.
- [.claude/commands/daily-report.md](.claude/commands/daily-report.md) is a reusable `/daily-report` command. It runs the report and then **audits it**: every number in the summary must appear in `facts.json`, and each template grouping is spot-checked against raw lines. This is the kind of reusable AI workflow and operating template I'd hand to a non-engineering team.

## Run

```bash
pip install -r requirements.txt
python -m opsauto.simulate                     # regenerate sample data (already committed)
python -m opsauto.report                       # → reports/2026-09-28/
pytest -q                                      # 18 tests; set PG_DSN=postgresql://... to include the Postgres parity test
API_BASE_URL=https://staging.example pytest tests/api -q
```

## Limits

- The masking parser is tuned for logs whose format we control. For third-party or free-text logs, I'd switch to a real Drain implementation and review the templates it learns.
- The spike test assumes yesterday is a normal day. In production, the baseline would be the same weekday over several weeks, with holidays and events excluded.
- The data is synthetic. The planted incident is intentionally clean, and real incidents overlap.

MIT License.
