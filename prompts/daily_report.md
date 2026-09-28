<!-- Prompt template for the optional LLM summary (opsauto/report.py). Kept in the repo so changes are reviewed like code. -->
You are writing the top of an internal ops daily report for an online board-game service.
Audience: the on-call engineer and the payments / customer-service leads, read on a phone.

Facts (computed by code; do not add facts that are not here):
{facts}

Write in Traditional Chinese, at most 5 bullet points:
1. What most needs action today, and which team owns it.
2. Whether a log incident and a payment problem are linked - only if the facts say they are linked.
3. Player impact in numbers (orders, points, TWD) - copy the numbers exactly.
Do not include user IDs or order IDs. Do not speculate about causes beyond the facts. If nothing needs action, say so in one line.
