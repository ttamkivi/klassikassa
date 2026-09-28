"""klassikassa command line. Run `klassikassa --help` for the list of commands."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import collect, core


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="klassikassa", description="Class-fund treasurer: who paid, what was spent, gentle reminders.")
    p.add_argument("--dir", default=os.environ.get("KLASSIKASSA_DIR"), help="class data directory (or $KLASSIKASSA_DIR)")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (testing, back-dating)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    a = sub.add_parser

    # setup
    a("init", help="create a class directory from the demo class")
    a("refs", help="print each child's reference number (viitenumber)")
    s = a("infer-roster", help="propose children + payers from an account's payment history")
    s.add_argument("--since"); s.add_argument("--kids", help="class list file, one name per line")
    s.add_argument("--stale", help="flag children whose last payment is before YYYY-MM-DD")

    # money in and out
    s = a("ingest", help="add bank statement file(s): LHV JSON, camt.053 XML, CSV, XLSX")
    s.add_argument("files", nargs="+")
    a("review", help="payments and spends that need a human")
    s = a("assign", help="payment -> child"); s.add_argument("txid"); s.add_argument("kid"); s.add_argument("--note")
    s = a("split", help="one payment for siblings: split TXID 03=30 04=30")
    s.add_argument("txid"); s.add_argument("parts", nargs="+"); s.add_argument("--note")
    s = a("income", help="money in that is no family's: fair, refund, leftover")
    s.add_argument("txid"); s.add_argument("--activity", required=True); s.add_argument("--note")
    s = a("spend", help="bank spend -> activity"); s.add_argument("txid"); s.add_argument("--activity", required=True); s.add_argument("--receipt")
    s = a("ignore", help="row that must not count at all (a loan in and out)"); s.add_argument("txid"); s.add_argument("--note", required=True)
    s = a("cash", help="cash that never touched the bank")
    s.add_argument("direction", choices=["in", "out"]); s.add_argument("amount")
    for f in ("--kid", "--activity", "--who", "--note", "--date"):
        s.add_argument(f)
    s = a("advance", help="a parent paid something out of pocket (gift, materials)")
    s.add_argument("amount"); s.add_argument("--who", required=True); s.add_argument("--activity", required=True)
    s.add_argument("--note"); s.add_argument("--date")
    s = a("reimburse", help="bank transfer paying a parent back"); s.add_argument("txid"); s.add_argument("--who", required=True); s.add_argument("--note")
    a("owed", help="what the class still owes parents who paid out of pocket")

    # collections
    s = a("propose", help="per-child amount from a list of costs")
    s.add_argument("--item", action="append", required=True, help="'Teater=35/laps' or 'Buss=180/klass'")
    s.add_argument("--kids", type=int); s.add_argument("--round", type=int, default=5); s.add_argument("--buffer", default="0")
    s.add_argument("--from-balance", default="0", help="money already on the account to put toward this")
    s.add_argument("--id", default="kogumine"); s.add_argument("--label", default="Klassiraha"); s.add_argument("--due", default="")
    s.add_argument("--add", action="store_true", help="append the collection to config.toml")
    s = a("announce", help="draft the collection mail to the parents' list"); s.add_argument("id")

    # who paid
    a("status", help="each family, what is paid and overdue, balance")
    a("balance", help="income, spend, balance")
    s = a("table", help="payment table as CSV (shareable only if the class agreed)")
    s.add_argument("--treasurer", action="store_true"); s.add_argument("--out")
    s = a("check-list", help="an organiser's name list against the account")
    s.add_argument("file"); s.add_argument("--since"); s.add_argument("--match", help="description must contain this")
    s.add_argument("--amount", help="amount each should have paid")
    s = a("remind", help="reminder drafts for overdue families (never sends)"); s.add_argument("--force", action="store_true")
    s = a("mark-reminded", help="record reminders you actually sent"); s.add_argument("kids", nargs="+"); s.add_argument("--channel", default="email")
    s = a("report", help="report for parents (markdown); --treasurer adds names")
    s.add_argument("--treasurer", action="store_true"); s.add_argument("--out")
    return p


COMMANDS = {
    "refs": core.cmd_refs, "infer-roster": core.cmd_infer_roster, "ingest": core.cmd_ingest,
    "review": core.cmd_review, "assign": core.cmd_assign, "split": core.cmd_split,
    "income": core.cmd_income, "spend": core.cmd_spend, "ignore": core.cmd_ignore, "cash": core.cmd_cash,
    "advance": collect.cmd_advance, "reimburse": collect.cmd_reimburse, "owed": collect.cmd_owed,
    "propose": collect.cmd_propose, "announce": collect.cmd_announce,
    "status": core.cmd_status, "balance": core.cmd_balance, "table": collect.cmd_table,
    "check-list": collect.cmd_check_list, "remind": core.cmd_remind,
    "mark-reminded": core.cmd_mark_reminded, "report": core.cmd_report,
}


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if not args.dir:
        p.error("set --dir or KLASSIKASSA_DIR")
    if args.cmd == "init":
        return core.cmd_init(args)
    COMMANDS[args.cmd](core.Kassa(Path(args.dir)), args)


if __name__ == "__main__":
    main()
