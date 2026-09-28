# Working agreement for coding agents in this repo

- Python 3.11, standard library first. New dependencies need a reason in the PR.
- Anything that decides *what is true* (counts, links, thresholds) is code with a test. The LLM only rewrites
  facts from `facts.json` into prose; it never computes numbers or sees user / order IDs.
- SQL in `opsauto/recon.py` must run unchanged on SQLite and PostgreSQL. `PG_DSN=... pytest` checks parity.
- Contract tests in `tests/api/` must also pass against staging (`API_BASE_URL=...`). Don't make them depend on mock internals.
- Masks: user IDs in any file that leaves the job are masked (`report.mask_user`).
- Before finishing: `pytest -q`, then `python -m opsauto.report` and read `reports/<day>/report.md` yourself.
