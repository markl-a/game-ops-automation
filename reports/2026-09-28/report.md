# 維運日報 2026-09-28

## 摘要
- **金流組**：apple 自 20:01 起付款回調失敗，40 筆已付款未入點（NT$12,860）。先修回調，再依清單補點；客服可先用 `missing_grant.csv` 回覆玩家。
- **遊戲後端**：重複入點 2 筆、點數與商品不符 1 筆，需檢查入點冪等與商品設定。
- **金流＋營運**：已退款仍有點數 5 筆，需人工決定是否扣回（點數可能已花掉）。
- **稽核**：無對應訂單的入點 1 筆（可能是 GM 手動發放），逐筆確認。
- **維運**：room-svc `table=<table> player=<user> reconnect attempt=<*>` 在 21:00 達 1135 次（昨日同時段 29），確認當時網路／機房事件。

## 日誌（11,818 行；ERROR 130、WARN 1783）

| 類型 | 等級 | 服務 | 樣板 | 次數 | 高峰 | 昨日同時段 |
|---|---|---|---|---|---|---|
| 新出現 | ERROR | pay-svc | `provider=apple order=<order> signature verify failed: x5c chain expired` | 75 | 22:00 (21) | 0 |
| 暴增 | WARN | room-svc | `table=<table> player=<user> reconnect attempt=<*>` | 1681 | 21:00 (1135) | 29 |

<details><summary>pay-svc: provider=apple order=<order> signature verify failed: x5c chain expired</summary>

```
20:01:04 provider=apple order=739643493162077 signature verify failed: x5c chain expired
21:17:36 provider=apple order=142221803073485 signature verify failed: x5c chain expired
22:34:28 provider=apple order=395159027489079 signature verify failed: x5c chain expired
```
</details>

<details><summary>room-svc: table=<table> player=<user> reconnect attempt=<*></summary>

```
00:00:54 table=T2959 player=u094594 reconnect attempt=2
21:02:53 table=T982 player=u987356 reconnect attempt=3
21:18:18 table=T387 player=u138077 reconnect attempt=2
```
</details>

## 金流對帳

| 檢查 | 筆數 | 說明 |
|---|---|---|
| 已付款未入點（超過 SLA 30 分） | 40 | 玩家付了錢沒拿到點數 |
| 仍在 SLA 內 | 12 | 回調處理中，不告警 |
| 重複入點 | 2 | 同一訂單入點多次 |
| 點數與商品不符 | 1 | |
| 已退款仍有點數 | 5 | 需人工決定是否扣回 |
| 無訂單的入點 | 1 | |

未入點分布（金流商 × 小時）：apple 2026-09-28T20:00 15 筆、apple 2026-09-28T22:00 12 筆、apple 2026-09-28T21:00 8 筆、apple 2026-09-28T23:00 5 筆

## 關聯

- `provider=apple order=<order> signature verify failed: x5c chain expired` ↔ apple 未入點 40 筆（NT$12,860），自 2026-09-28T20:01

明細 CSV 在同目錄（玩家 ID 已遮罩）。本報告由 `python -m opsauto.report` 產生。
