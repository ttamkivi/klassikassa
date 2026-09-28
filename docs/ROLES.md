# Who does what: treasurer and helper

Most class funds run on two people, whatever they are called: the one whose name is on
the account (**laekur**, klassipankur) and the one who does most of the talking and the
buying (**laekuri abi**). Often they live in the same house. This page is how the work
splits, and which commands take which chore off whom. It comes from five years of one
real class's mail, anonymised.

## The helper's recurring work, and what the tool does with it

| Chore, done by hand | What it took | With klassikassa |
|---|---|---|
| Add up the coming costs, divide by the class, round, decide the ask | a spreadsheet and a calculator, every time | `propose --item ...` shows the breakdown and the rounded ask |
| Write the collection mail (what for, how much, where, by when) | 20 minutes of wording | `announce <id>` writes it; you adjust tone |
| Enter each incoming payment in the class table | an evening per collection | `ingest` + automatic matching; only real puzzles reach `review` |
| Work out who is still missing | scanning the table | `status` |
| Chase the missing ones | a mail to the list, or awkward private messages | `remind`: one private draft per family, spaced out, capped |
| Pay for gifts and materials herself, then get it back | remembering, and a note somewhere | `advance`, `reimburse`, `owed` |
| Check an organiser's list for a trip | cross-reading two tables | `check-list` |
| Report to parents what was spent | a long mail with an itemised list | `report` |
| Answer "have I paid?" | look it up, reply | `status`, or a shared table if the class agreed |

## What stays human

- Deciding what the class spends on, with the teacher.
- The tone of the messages and the relationship with the parents.
- Anything involving a family that cannot pay: that conversation is private and personal.
- Confirming that a payment belongs to a child when the tool is not sure.

## A good rhythm

- **Start of year:** roster, reference numbers, first collection announced.
- **Each collection:** propose, announce, then one `ingest` + `status` a few days after
  the due date. Reminders only after that.
- **End of each term:** `report` to the parents' list, before the next ask. Trust in the
  next collection is built by the last report.
