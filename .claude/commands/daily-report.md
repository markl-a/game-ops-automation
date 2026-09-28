Run the ops daily report for $ARGUMENTS (default: the latest day in data/logs) and review it before anyone else does.

1. `python -m opsauto.report --day <day> --baseline <previous day>`
2. Read `reports/<day>/report.md` and `facts.json`.
3. Check that every number in the summary appears in facts.json. List any that don't.
4. For each new or spiking template, open 3 raw lines from data/logs/<day>.log around the peak hour and say whether
   the template grouping looks right, or whether two different problems were merged by the masking.
5. Do not post anywhere. Reply with: the summary as-is, anything you'd change, and why.
