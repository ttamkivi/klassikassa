---
name: klassikassa
description: >
  Class-fund treasurer for a school class: reads the class bank statement, matches
  payments to children, proposes per-child collection amounts from real costs, drafts
  announcements and private reminders (never sends), tracks money parents paid out of
  pocket, and writes the report for parents. Trigger for "klassiraha", "klassikassa",
  "klassipankur", "laekur", "who hasn't paid", "kes pole maksnud", "class money",
  "collect money for the class", "class fund report".
---

Read [AGENT.md](AGENT.md) and follow it. The command is `klassikassa` (or
`python -m klassikassa` from this repository). The class directory comes from
`$KLASSIKASSA_DIR` or `--dir`; ask which class if there is more than one.
