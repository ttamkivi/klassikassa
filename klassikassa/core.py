#!/usr/bin/env python3
"""klassikassa: class-fund treasurer ledger.

Who has paid, who has not, where the money went, and who needs a (soft) reminder.
All arithmetic happens here, in Decimal and SQLite; the agent only judges the result.

Data lives in one directory per class (default $KLASSIKASSA_DIR), never in git:

    config.toml      class, account, collections, reminder policy
    roster.csv       kids + parents' contacts            (sensitive)
    statements/      bank statements: LHV MCP JSON, camt.053 XML, CSV or XLSX
    decisions.csv    manual assign / ignore / spend decisions (the only
                     hand-made state; everything else is re-derived)
    manual.csv       cash in / cash out that never touched the bank
    reminders.csv    reminders actually sent (appended by mark-reminded)
    drafts/          generated reminder drafts, one file per family

The ledger is rebuilt from these files on every run, so there is no cache to go stale.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tomllib
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "examples" / "demo-class"
CENT = Decimal("0.01")


# ── helpers ──────────────────────────────────────────────────────────────────

def D(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def fold(s: str) -> str:
    """Lowercase, strip diacritics and punctuation: 'Õnne-Liis Kägu' -> 'onne liis kagu'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ref_731(base: str) -> str:
    """Estonian reference number (viitenumber): base digits + 7-3-1 check digit.
    Every Estonian bank validates this checksum in the reference field, so a typo
    is rejected at the payer's end instead of landing as an unmatched payment."""
    weights = [7, 3, 1]
    total = sum(int(d) * weights[i % 3] for i, d in enumerate(reversed(base)))
    return base + str((10 - total % 10) % 10)


def today(args) -> dt.date:
    return dt.date.fromisoformat(args.today) if getattr(args, "today", None) else dt.date.today()


def eur(x: Decimal) -> str:
    return f"{x:,.2f} €".replace(",", " ")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


# ── LHV statement adapter ────────────────────────────────────────────────────
# The LHV MCP returns JSON whose exact envelope is not documented. Known for sure
# (21.09.2026): each transfer carries paymentData.creditor / .debtor with name AND
# iban, and card purchases have paymentData = null. Everything else is read with
# fallbacks, and `ingest` refuses a file it cannot find transactions in.

def _first(d: dict, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def _find_tx_list(obj):
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        if any(_first(x, "amount", "transactionAmount") is not None for x in obj):
            return obj
    if isinstance(obj, dict):
        for k in ("transactions", "entries", "items", "data", "statement", "booked"):
            if k in obj:
                found = _find_tx_list(obj[k])
                if found is not None:
                    return found
        for v in obj.values():
            found = _find_tx_list(v)
            if found is not None:
                return found
    return None


def local_date(v) -> str:
    """LHV gives settlementDtime in UTC ("...T21:30:00Z"); a payment at 00:30 Tallinn
    time belongs to the next day. Plain dates pass through."""
    v = str(v or "")
    if "T" not in v:
        return v[:10]
    from zoneinfo import ZoneInfo
    t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    return t.astimezone(ZoneInfo("Europe/Tallinn")).date().isoformat()


# Bank's own entries: not a family, not a class purchase. Classified, never "review".
BANK_ENTRIES = {"INTR": "pangaintress", "TAXE": "tulumaks intressilt"}


def normalise_tx(raw: dict) -> dict:
    amt = _first(raw, "amount", "transactionAmount")
    cur = raw.get("currency", "EUR")
    if isinstance(amt, dict):
        cur = amt.get("currency", cur)
        amt = _first(amt, "amount", "value")
    amount = D(amt)
    direction = str(_first(raw, "direction", "creditDebitIndicator", "type") or "").upper()
    if direction.startswith("D") and amount > 0:
        amount = -amount
    elif not direction:
        direction = "CREDIT" if amount >= 0 else "DEBIT"
    incoming = amount >= 0

    pd = raw.get("paymentData") or {}
    party = pd.get("debtor" if incoming else "creditor") or {}
    name = _first(party, "name", "fullName") or _first(
        raw, "debtorName" if incoming else "creditorName", "counterpartyName", "merchantName") or ""
    acct = _first(party, "iban", "accountNo", "account", "accountNumber")
    if isinstance(acct, dict):
        acct = acct.get("iban")
    if not acct:
        side = raw.get("debtorAccount" if incoming else "creditorAccount") or {}
        acct = side.get("iban") if isinstance(side, dict) else side
    desc = _first(raw, "description", "remittanceInformation",
                  "remittanceInformationUnstructured", "details", "explanation") \
        or _first(pd, "remittanceInformation", "description") or ""
    ref = _first(raw, "referenceNumber", "reference", "creditorReference", "customerReference") \
        or _first(pd, "referenceNumber", "reference") or ""
    date = local_date(_first(raw, "bookingDate", "valueDate", "date", "transactionDate",
                             "settlementDtime", "createdAt"))
    ttype = raw.get("transactionType") or {}
    ttype = ttype.get("subfamily", "") if isinstance(ttype, dict) else str(ttype)

    # LHV's bankReference is NOT unique: interest and the tax withheld on it share one
    # (61 of 797 rows on one real account, checked 28.09.2026). Keying on it alone drops them.
    native = _first(raw, "transactionId", "id", "entryReference", "archiveId", "bankReference")
    key = f"{native}|{date}|{amount}|{direction}" if native else f"{date}|{amount}|{name}|{acct}|{desc}|{ref}"
    return {
        "txid": hashlib.sha1(str(key).encode()).hexdigest()[:8],
        "date": date, "amount": amount, "currency": cur,
        "name": str(name), "iban": str(acct or ""),
        "description": str(desc), "reference": re.sub(r"\D", "", str(ref)),
        "source": "bank", "ttype": ttype,
    }


# ── loading ──────────────────────────────────────────────────────────────────

class Kassa:
    def __init__(self, root: Path):
        self.root = root
        cfg_path = root / "config.toml"
        if not cfg_path.exists():
            sys.exit(f"No config.toml in {root}. Run: klassikassa.py init {root}")
        self.cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        self.cls = self.cfg["class"]
        self.collections = sorted(self.cfg.get("collection", []), key=lambda c: c["due"])
        self.kids = {r["kid_id"]: r for r in read_csv(root / "roster.csv") if r.get("kid_id")}
        prefix = str(self.cls.get("ref_prefix", "10"))
        for k in self.kids.values():
            k["ref"] = ref_731(prefix + k["kid_id"].zfill(2))
        self.decisions = read_csv(root / "decisions.csv")
        self.reminders = read_csv(root / "reminders.csv")
        self.txs = self._load_txs()
        self._apply()

    # transactions: bank statements + manual cash rows, de-duplicated by txid
    def _load_txs(self) -> dict[str, dict]:
        txs: dict[str, dict] = {}
        own = fold(self.cls.get("account_iban", "")).replace(" ", "")
        from .banks import load_file
        for f in sorted((self.root / "statements").iterdir()) if (self.root / "statements").exists() else []:
            if f.name.startswith(".") or f.suffix.lower() not in (".json", ".xml", ".csv", ".xlsx"):
                continue
            for t in load_file(f):
                # multi-account dumps: keep only rows whose own account is the class account
                acct = fold(t.pop("own_account", "") or "").replace(" ", "")
                if own and acct and acct != own:
                    continue
                if t["date"] < self.cls.get("start", "0000"):
                    continue
                txs.setdefault(t["txid"], t)
        for i, r in enumerate(read_csv(self.root / "manual.csv")):
            amt = D(r["amount"])
            t = {"txid": "c" + hashlib.sha1(f"{i}{r}".encode()).hexdigest()[:7],
                 "date": r["date"], "amount": amt if r["direction"] == "in" else -abs(amt),
                 "currency": "EUR", "name": r.get("who", "") or "sularaha", "iban": "",
                 "description": r.get("note", ""), "reference": "", "source": "cash"}
            if r.get("kid_id"):
                t["kid_id"], t["how"] = r["kid_id"], "cash"
            if r.get("activity"):
                t["activity"] = r["activity"]
            txs[t["txid"]] = t
        return txs

    def _match(self, t: dict) -> tuple[str | None, str]:
        """Return (kid_id, how) for an incoming payment, or (None, reason)."""
        by_ref = {k["ref"]: kid for kid, k in self.kids.items()}
        if t["reference"] in by_ref:
            return by_ref[t["reference"]], "viitenumber"
        for r, kid in by_ref.items():
            if re.search(rf"(?<!\d){r}(?!\d)", t["description"]):
                return kid, "viitenumber selgituses"
        desc, payer = fold(t["description"]), fold(t["name"])
        hits = {kid for kid, k in self.kids.items() if fold(k["kid_name"]) and fold(k["kid_name"]) in desc}
        if len(hits) == 1:
            return hits.pop(), "lapse nimi selgituses"
        if len(hits) > 1:
            return None, "mitu lapse nime selgituses"
        payer_hits = set()
        for kid, k in self.kids.items():
            names = [k.get("parent1_name"), k.get("parent2_name")] + (k.get("payer_aliases") or "").split(";")
            if payer and any(fold(n) == payer for n in names if n and n.strip()):
                payer_hits.add(kid)
        if len(payer_hits) == 1:
            kid = payer_hits.pop()
            # A parent paying for siblings in two classes: accept only if the first
            # name in the description does not point at another kid.
            return kid, "maksja nimi"
        if len(payer_hits) > 1:
            first = {kid for kid in payer_hits
                     if fold(self.kids[kid]["kid_name"]).split()[0] in desc.split()}
            if len(first) == 1:
                return first.pop(), "maksja nimi + eesnimi"
            return None, "sama vanem mitmel lapsel"
        return None, "tundmatu maksja"

    def _apply(self) -> None:
        dec = {d["txid"]: d for d in self.decisions}  # last decision per tx wins
        for t in self.txs.values():
            d = dec.get(t["txid"])
            if d and d["action"] == "ignore":
                t["ignored"] = d.get("note", "ignored")
                continue
            if t.get("ttype") in BANK_ENTRIES and not d:
                t["activity"] = BANK_ENTRIES[t["ttype"]]
                continue
            if t["amount"] >= 0:
                if d and d["action"] == "assign":
                    t["kid_id"], t["how"] = d["value"], "käsitsi"
                elif d and d["action"] == "income":
                    t["activity"] = d["value"]  # class income that is no family's payment
                elif d and d["action"] == "split":
                    t["split"] = {kid: D(a) for kid, a in (x.split("=") for x in d["value"].split(";"))}
                    t["how"] = "käsitsi jagatud"
                elif "kid_id" not in t and "activity" not in t:
                    kid, how = self._match(t)
                    if kid:
                        t["kid_id"], t["how"] = kid, how
                    else:
                        t["unmatched"] = how
            else:
                if d and d["action"] == "reimburse":
                    # paying a parent back for an advance: not a new expense (the advance was)
                    t["reimburse"] = d["value"]
                    t["activity"] = f"tagasimakse: {d['value']}"
                elif d and d["action"] == "spend":
                    t["activity"] = d["value"]
                    t["receipt"] = d.get("note", "")
                elif "activity" not in t:
                    t["activity"] = self._suggest_activity(t)
                    t["uncategorised"] = True

    def _suggest_activity(self, t: dict) -> str:
        """Same creditor as an already-categorised spend -> same activity (suggestion only)."""
        for d in self.decisions:
            if d["action"] == "spend":
                other = self.txs.get(d["txid"])
                if other and fold(other["name"]) == fold(t["name"]) and other["name"]:
                    return d["value"] + " (?)"
        return ""

    # ── what each family owes ──
    def owed(self, kid: str, as_of: dt.date, include_future=True) -> list[tuple[dict, Decimal]]:
        out = []
        for c in self.collections:
            applies = c.get("applies", "all")
            if applies != "all" and kid not in applies:
                continue
            if kid in c.get("exempt", []):
                continue
            if not include_future and dt.date.fromisoformat(c["due"]) > as_of:
                continue
            amt = D(c.get("overrides", {}).get(kid, c["amount"]))
            if amt > 0:
                out.append((c, amt))
        return out

    def db(self) -> sqlite3.Connection:
        """Load everything into in-memory SQLite so sums are done by a database, not by eye."""
        con = sqlite3.connect(":memory:")
        con.execute("create table tx(txid, date, cents int, name, iban, description, reference, "
                    "source, kid_id, how, activity, receipt, state)")
        for t in self.txs.values():
            state = ("ignored" if "ignored" in t else "unmatched" if "unmatched" in t
                     else "uncategorised" if t.get("uncategorised") else "ok")
            parts = t.get("split") or {t.get("kid_id"): t["amount"]}
            for kid, amt in parts.items():
                con.execute("insert into tx values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    t["txid"], t["date"], int(amt * 100), t["name"], t["iban"], t["description"],
                    t["reference"], t["source"], kid, t.get("how") or t.get("unmatched"),
                    t.get("activity"), t.get("receipt"), state))
        return con

    def paid(self, con, kid) -> Decimal:
        (c,) = con.execute("select coalesce(sum(cents),0) from tx where kid_id=? and cents>0 "
                           "and state!='ignored'", (kid,)).fetchone()
        return D(Decimal(c) / 100)

    def family_status(self, con, kid: str, as_of: dt.date) -> dict:
        """Allocate what a family paid to its collections oldest-due-first."""
        left = self.paid(con, kid)
        rows, due_now = [], Decimal(0)
        for c, amt in self.owed(kid, as_of):
            got = min(left, amt)
            left -= got
            is_due = dt.date.fromisoformat(c["due"]) <= as_of
            state = "makstud" if got == amt else ("osaliselt" if got > 0 else "maksmata")
            if not is_due and got < amt:
                state += " (tähtaeg ees)"
            if is_due:
                due_now += amt - got
            rows.append({"collection": c, "amount": amt, "got": got, "state": state, "is_due": is_due})
        return {"kid": kid, "rows": rows, "due_now": due_now, "credit": left,
                "paid": self.paid(con, kid)}

    def reminder_log(self, kid: str) -> list[dict]:
        return [r for r in self.reminders if r["kid_id"] == kid]


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_init(args):
    root = Path(args.dir)
    if (root / "config.toml").exists():
        sys.exit(f"{root} already has a config.toml; not overwriting.")
    root.mkdir(parents=True, exist_ok=True)
    (root / "statements").mkdir(exist_ok=True)
    shutil.copy(EXAMPLE / "config.toml", root / "config.toml")
    shutil.copy(EXAMPLE / "roster.csv", root / "roster.csv")
    print(f"Created {root}. Now edit config.toml and replace roster.csv with the real class list.")


def cmd_refs(k: Kassa, args):
    print(f"Viitenumbrid, {k.cls['name']} (üks lapse kohta, kehtib kõigile kogumistele)\n")
    for kid, r in sorted(k.kids.items()):
        print(f"  {kid:>3}  {r['ref']:<10} {r['kid_name']}")


def cmd_ingest(k: Kassa, args):
    dest = k.root / "statements"
    dest.mkdir(exist_ok=True)
    before = set(k.txs)
    from .banks import load_file
    for f in args.files:
        try:
            rows = load_file(Path(f))
        except ValueError as e:
            sys.exit(str(e))
        name = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + Path(f).name
        shutil.copy(f, dest / name)
        print(f"{f}: {len(rows)} rows read, stored as statements/{name}")
    k2 = Kassa(k.root)
    new = [t for tid, t in k2.txs.items() if tid not in before]
    print(f"{len(new)} new transactions after de-duplication.")
    unm = [t for t in new if "unmatched" in t]
    unc = [t for t in new if t.get("uncategorised")]
    if unm or unc:
        print(f"Needs a human: {len(unm)} unmatched payments, {len(unc)} uncategorised spends. Run: review")


def cmd_status(k: Kassa, args):
    con, as_of = k.db(), today(args)
    print(f"{k.cls['name']}  ·  seis {as_of}  ·  {len(k.kids)} last\n")
    tot_due = Decimal(0)
    lines = []
    for kid in sorted(k.kids):
        s = k.family_status(con, kid, as_of)
        tot_due += s["due_now"]
        cells = "  ".join(f"{r['collection']['id']}:{r['state']}" for r in s["rows"])
        rem = k.reminder_log(kid)
        remtxt = f"  meeldetuletusi {len(rem)}, viimane {rem[-1]['date']}" if rem else ""
        extra = f"  ülemakse {eur(s['credit'])}" if s["credit"] > 0 else ""
        flag = "⚠" if s["due_now"] > 0 else "✓"
        lines.append(f"{flag} {kid:>3} {k.kids[kid]['kid_name']:<22} makstud {eur(s['paid']):>10}  "
                     f"võlg {eur(s['due_now']):>9}  {cells}{extra}{remtxt}")
    print("\n".join(lines))
    print()
    cmd_balance(k, args, con=con)
    print(f"Tähtaja ületanud võlg kokku: {eur(tot_due)}")
    (n_unm,) = con.execute("select count(*) from tx where state='unmatched'").fetchone()
    (n_unc,) = con.execute("select count(*) from tx where state='uncategorised'").fetchone()
    if n_unm or n_unc:
        print(f"⚠ Ülevaatust vajab: {n_unm} tundmatut laekumist, {n_unc} kategoriseerimata kulu (review).")


def cmd_balance(k: Kassa, args, con=None):
    con = con or k.db()
    q = lambda sql: D(Decimal(con.execute(sql).fetchone()[0] or 0) / 100)
    inc = q("select sum(cents) from tx where cents>0 and state!='ignored'")
    out = q("select sum(cents) from tx where cents<0 and state!='ignored'")
    print(f"Laekunud {eur(inc)}  ·  kulutatud {eur(-out)}  ·  kassas {eur(inc + out)}")
    opening = k.cls.get("opening_balance")
    if opening is not None:
        print(f"(Algsaldo {eur(D(opening))} on eraldi; pangasaldo peaks olema {eur(D(opening) + inc + out)}.)")


def cmd_review(k: Kassa, args):
    con = k.db()
    rows = con.execute("select txid,date,cents,name,description,reference,how from tx "
                       "where state='unmatched' order by date").fetchall()
    print(f"Tundmatud laekumised ({len(rows)}):  assign TXID KID · split · income TXID --activity ... · ignore (ainult vead)")
    for r in rows:
        print(f"  {r[0]}  {r[1]}  {eur(D(Decimal(r[2]) / 100)):>10}  {r[3]!r:28} {r[4]!r}  ref={r[5] or '-'}  [{r[6]}]")
    rows = con.execute("select txid,date,cents,name,description,activity from tx "
                       "where state='uncategorised' order by date").fetchall()
    print(f"\nKategoriseerimata kulud ({len(rows)}):  spend TXID --activity '...' [--receipt ...]")
    for r in rows:
        sug = f"  soovitus: {r[5]}" if r[5] else ""
        print(f"  {r[0]}  {r[1]}  {eur(D(Decimal(r[2]) / 100)):>10}  {r[3]!r:28} {r[4]!r}{sug}")
    print("\nAutomaatsed seosed (kontrolli nime järgi sobitatud):")
    for r in con.execute("select txid,date,cents,name,kid_id,how from tx where how in "
                         "('maksja nimi','maksja nimi + eesnimi','lapse nimi selgituses') order by date"):
        print(f"  {r[0]}  {r[1]}  {eur(D(Decimal(r[2]) / 100)):>10}  {r[3]!r:28} → {r[4]} "
              f"{k.kids.get(r[4], {}).get('kid_name', '?')}  [{r[5]}]")


def _decide(k: Kassa, txid: str, action: str, value: str, note: str):
    if txid not in k.txs:
        sys.exit(f"No transaction {txid}.")
    append_csv(k.root / "decisions.csv", ["txid", "action", "value", "note", "at"],
               {"txid": txid, "action": action, "value": value, "note": note,
                "at": dt.datetime.now().isoformat(timespec="seconds")})
    t = k.txs[txid]
    print(f"{action}: {txid} {t['date']} {eur(t['amount'])} {t['name']!r} → {value or note}")


def cmd_assign(k, args):
    if args.kid not in k.kids:
        sys.exit(f"No kid {args.kid} in roster.")
    _decide(k, args.txid, "assign", args.kid, args.note or "")


def cmd_split(k, args):
    parts = dict(x.split("=") for x in args.parts)
    bad = [kid for kid in parts if kid not in k.kids]
    if bad:
        sys.exit(f"Not in roster: {', '.join(bad)}")
    total = sum((D(a) for a in parts.values()), Decimal(0))
    if args.txid not in k.txs or total != k.txs[args.txid]["amount"]:
        sys.exit(f"Parts add up to {eur(total)}, the payment is "
                 f"{eur(k.txs[args.txid]['amount']) if args.txid in k.txs else '?'}.")
    _decide(k, args.txid, "split", ";".join(f"{kid}={D(a)}" for kid, a in parts.items()), args.note or "")


def cmd_ignore(k, args):
    _decide(k, args.txid, "ignore", "", args.note)


def cmd_income(k, args):
    if args.txid not in k.txs:
        sys.exit(f"No transaction {args.txid}.")
    if k.txs[args.txid]["amount"] <= 0:
        sys.exit("income is for incoming money (fair proceeds, refunds, leftovers returned).")
    _decide(k, args.txid, "income", args.activity, args.note or "")


def cmd_spend(k, args):
    _decide(k, args.txid, "spend", args.activity, args.receipt or "")


def cmd_cash(k, args):
    if args.kid and args.kid not in k.kids:
        sys.exit(f"No kid {args.kid} in roster.")
    row = {"date": args.date or dt.date.today().isoformat(), "direction": args.direction,
           "amount": str(D(args.amount)), "kid_id": args.kid or "", "activity": args.activity or "",
           "who": args.who or "", "note": args.note or ""}
    append_csv(k.root / "manual.csv", list(row), row)
    print(f"cash {args.direction} {eur(D(args.amount))} recorded.")


WORDS = {"et": {"partly": " (osaliselt tasutud)", "due": "tähtaeg", "and": " ja ", "subject": "klassiraha"},
         "en": {"partly": " (partly paid)", "due": "due", "and": " and ", "subject": "class money"}}


def template(k: "Kassa", name: str) -> str:
    """Class override (<class dir>/templates/<name>.txt) wins over the shipped template."""
    own = k.root / "templates" / f"{name}.txt"
    shipped = HERE / "templates" / k.cls.get("language", "et") / f"{name}.txt"
    return (own if own.exists() else shipped).read_text(encoding="utf-8")


def cmd_remind(k: Kassa, args):
    con, as_of = k.db(), today(args)
    pol = k.cfg.get("reminders", {})
    grace = int(pol.get("first_after_days", 3))
    every = int(pol.get("repeat_every_days", 10))
    cap = int(pol.get("max_reminders", 3))
    (n_unm,) = con.execute("select count(*) from tx where state='unmatched'").fetchone()
    if n_unm and not args.force:
        sys.exit(f"{n_unm} incoming payments are still unmatched. One of them may be a family you are "
                 f"about to remind. Resolve them first (review), or pass --force.")
    out_dir = k.root / "drafts" / as_of.isoformat()
    manifest, talk = [], []
    W = WORDS.get(k.cls.get("language", "et"), WORDS["et"])
    for kid in sorted(k.kids):
        s = k.family_status(con, kid, as_of)
        open_rows = [r for r in s["rows"] if r["is_due"] and r["got"] < r["amount"]
                     and dt.date.fromisoformat(r["collection"]["due"]) + dt.timedelta(days=grace) <= as_of]
        if not open_rows:
            continue
        log = k.reminder_log(kid)
        if len(log) >= cap:
            talk.append(kid)
            continue
        if log and (as_of - dt.date.fromisoformat(log[-1]["date"])).days < every:
            continue
        r = k.kids[kid]
        first = r["kid_name"].split()[0]
        # Estonian genitive is irregular (Tanel -> Taneli, Rait -> Raidu), so it comes
        # from the roster, not from a suffix rule. Without it the name stays nominative.
        gen = r.get("kid_genitive") or first
        parents = [p for p in (r.get("parent1_name"), r.get("parent2_name")) if p]
        emails = [e for e in (r.get("parent1_email"), r.get("parent2_email")) if e]
        phones = [p for p in (r.get("parent1_phone"), r.get("parent2_phone")) if p]
        lines = "".join(f"  · {x['collection']['label']}: {eur(x['amount'] - x['got'])}"
                        f"{W['partly'] if x['got'] else ''}, {W['due']} {x['collection']['due']}\n"
                        for x in open_rows)
        total = sum((x["amount"] - x["got"] for x in open_rows), Decimal(0))
        openings = [l for l in template(k, "remind-openings").splitlines() if l.strip()]
        body = template(k, "remind").format(
            greeting=(", " + W["and"].join(p.split()[0] for p in parents)) if parents else "",
            opening=openings[min(len(log), len(openings) - 1)].format(cls=k.cls["name"], kid_gen=gen),
            lines=lines, total=eur(total), holder=k.cls["account_holder"], iban=k.cls["account_iban"],
            ref=r["ref"], kid_gen=gen,
            signature=k.cls.get("signature", k.cls.get("treasurer", "")))
        subject = f"{k.cls['name']} {W['subject']}: {first}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{kid}.txt").write_text(
            f"To: {', '.join(emails)}\nPhone: {', '.join(phones)}\nSubject: {subject}\n\n{body}", encoding="utf-8")
        manifest.append({"kid_id": kid, "to": emails, "phones": phones, "subject": subject,
                         "body": body, "reminder_no": len(log) + 1, "total": str(total),
                         "collections": [x["collection"]["id"] for x in open_rows]})
    if manifest:
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(manifest)} reminder drafts in {out_dir if manifest else '(none)'}. Nothing was sent.")
    for m in manifest:
        print(f"  {m['kid_id']:>3} {k.kids[m['kid_id']]['kid_name']:<22} {eur(D(m['total'])):>9}  "
              f"#{m['reminder_no']}  → {', '.join(m['to']) or 'NO EMAIL: ' + ', '.join(m['phones'])}")
    for kid in talk:
        print(f"  {kid:>3} {k.kids[kid]['kid_name']:<22} {cap} reminders already. Stop writing; talk in person.")
    if manifest:
        print("After sending, record each one:  mark-reminded KID [--channel email|sms|ekool|stuudium]")


def cmd_mark_reminded(k: Kassa, args):
    for kid in args.kids:
        if kid not in k.kids:
            sys.exit(f"No kid {kid}.")
        append_csv(k.root / "reminders.csv", ["kid_id", "date", "channel"],
                   {"kid_id": kid, "date": today(args).isoformat(), "channel": args.channel})
    print(f"Recorded reminder for {', '.join(args.kids)}.")


def cmd_report(k: Kassa, args):
    con, as_of = k.db(), today(args)
    q = lambda sql, *p: D(Decimal(con.execute(sql, p).fetchone()[0] or 0) / 100)
    inc = q("select sum(cents) from tx where cents>0 and state!='ignored'")
    out = -q("select sum(cents) from tx where cents<0 and state!='ignored'")
    st = [k.family_status(con, kid, as_of) for kid in k.kids]
    L = [f"# {k.cls['name']} klassikassa, seis {as_of}", ""]
    L += ["## Kogumised", "", "| Kogumine | Summa lapse kohta | Tähtaeg | Tasutud peresid | Laekunud |",
          "|---|---|---|---|---|"]
    for c in k.collections:
        rows = [(s, r) for s in st for r in s["rows"] if r["collection"]["id"] == c["id"]]
        full = sum(1 for _, r in rows if r["got"] == r["amount"])
        got = sum((r["got"] for _, r in rows), Decimal(0))
        L.append(f"| {c['label']} | {eur(D(c['amount']))} | {c['due']} | {full} / {len(rows)} | {eur(got)} |")
    other = con.execute("select activity, sum(cents) from tx where cents>0 and kid_id is null "
                        "and activity is not null and state!='ignored' group by 1 order by 2 desc").fetchall()
    if other:
        L += ["", "## Muud tulud", "", "| Allikas | Summa |", "|---|---|"]
        L += [f"| {a} | {eur(D(Decimal(c) / 100))} |" for a, c in other]
    L += ["", "## Kulud tegevuste kaupa", "", "| Tegevus | Summa |", "|---|---|"]
    exp: dict[str, Decimal] = {}
    for t in k.txs.values():
        if t["amount"] < 0 and "ignored" not in t and not t.get("reimburse"):
            a = t.get("activity") or "kategoriseerimata"
            exp[a] = exp.get(a, Decimal(0)) - t["amount"]
    adv = read_csv(k.root / "advances.csv")
    for a in adv:  # paid out of a parent's pocket: an expense of the class all the same
        exp[a["activity"]] = exp.get(a["activity"], Decimal(0)) + D(a["amount"])
    for act, amt in sorted(exp.items(), key=lambda kv: -kv[1]):
        L.append(f"| {act} | {eur(amt)} |")
    out = sum(exp.values(), Decimal(0))
    back = sum((-t["amount"] for t in k.txs.values() if t.get("reimburse")), Decimal(0))
    owed = sum((D(a["amount"]) for a in adv), Decimal(0)) - back
    if owed:
        L += ["", f"_Vanemate ettemakstud ja veel tagastamata: {eur(owed)}_"]
    opening = D(k.cls.get("opening_balance", 0))
    if opening:
        L += ["", f"Algsaldo {k.cls.get('start', '')}: {eur(opening)}"]
    L += ["", f"**Laekunud {eur(inc)} · kulud kokku {eur(out)} · kontol {eur(opening + inc - out + owed)}"
          f"{' (millest ' + eur(owed) + ' kuulub tagastamisele)' if owed else ''}**", ""]
    if args.treasurer:
        L += ["## Laekurile (ei lähe vanematele)", "", "| Laps | Makstud | Võlg | Meeldetuletusi |", "|---|---|---|---|"]
        for s in st:
            if s["due_now"] > 0 or s["credit"] > 0:
                L.append(f"| {k.kids[s['kid']]['kid_name']} | {eur(s['paid'])} | {eur(s['due_now'])}"
                         f"{' (ülemakse ' + eur(s['credit']) + ')' if s['credit'] else ''} | {len(k.reminder_log(s['kid']))} |")
        L.append("")
    else:
        L += ["_Pere-põhiseid võlgnevusi siin ei avaldata. Iga pere saab oma seisu eraldi._", ""]
    text = "\n".join(L)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Written {args.out}")
    else:
        print(text)


# ── roster inference from payment history ────────────────────────────────────
# For a class account that already has history (inherited from the previous
# treasurer, or old statements): parents write the child's name in the description
# ("Mari Kask 6.b teatriraha"), so the history is a draft roster. The script only
# proposes; every kid-parent link is confirmed by a human before it goes to roster.csv.

NOT_NAMES = set("""
klassiraha klassi klass raha teatriraha teater teatri teatrisse pilet piletid ekskursioon
ekskursiooni reis reisi reisiraha osamakse makse kokku lisa lisaks oppekaik oppekaigu
kingitus kink kingiks jõulukink joulukink jõulud joulud sünnipäev sunnipaev laager laagri
annetus eest ja ning ka kevad sugis talv suvi poolaasta tasu opetaja opetajale kool kooli
tallinna reaalkool reaalkooli rk uleanne ulekanne arve viitenumber jaanuar veebruar marts
aprill mai juuni juuli august september oktoober november detsember matk matka pidu
lopupidu lopuraamat kontsert kino muuseum muuseumi buss bussi toit sook suusapaev
klassireis klassiekskursioon lopuraha lopureis tagasimakse teatripiletid joulutrall vat ii iii
osa osamakse1 osamakse2 esimene teine kolmas
""".split())
COMPANY = re.compile(r"\b(ou|as|mtu|sa|fie|oü|uab|sia|oy|ab)\b", re.I)
WORD = re.compile(r"[A-Za-zÀ-ÿŠšŽžÕõÄäÖöÜü][A-Za-zÀ-ÿŠšŽžÕõÄäÖöÜü'-]+")


def _runs(desc: str) -> list[list[str]]:
    """Consecutive capitalised non-keyword words, split at keywords and at "ja"/"&".
    Returns runs plus markers: ["&"] between two runs joined by "ja"."""
    runs, cur = [], []
    words = []
    for w in re.findall(WORD.pattern + r"|&", desc):
        parts = w.split("-")
        if len(parts) > 1 and any(fold(x) in NOT_NAMES for x in parts):
            words += [x.capitalize() for x in parts if x and fold(x) not in NOT_NAMES]
        else:
            words.append(w)
    for w in words:
        f = fold(w)
        if w == "&" or f in ("ja", "ning"):
            if cur:
                runs.append(cur); cur = []
            runs.append(["&"])
        elif not w or f in NOT_NAMES or not w[0].isupper() or len(w) < 2:
            if cur:
                runs.append(cur); cur = []
        else:
            cur.append(w)
    if cur:
        runs.append(cur)
    return runs


def _kid_candidates(desc: str, payer: str) -> list[tuple[str, str]]:
    """(candidate kid name, how) pairs from one description, strongest first."""
    payer_is_person = not COMPANY.search(payer)
    surname = fold(payer).split()[-1] if payer_is_person and fold(payer) else ""
    runs = _runs(desc)
    out = []
    for i, r in enumerate(runs):
        if r == ["&"]:
            continue
        if len(r) >= 2:  # "Mari Kask", "Mari-Liis Kask", "Anna Maria Kask"
            how = "täisnimi, sama perenimi" if surname and fold(r[-1]) == surname else "täisnimi selgituses"
            out.append((" ".join(r), how))
        elif i + 2 < len(runs) and runs[i + 1] == ["&"] and len(runs[i + 2]) >= 2:
            # "Kaspar ja Eva Mänd": siblings sharing the surname written once
            out.append((f"{r[0]} {runs[i + 2][-1]}", "õde/vend samas makses"))
    if out:
        return out
    # lowercase descriptions: "mari kask klassiraha"
    words = [w for w in WORD.findall(desc) if fold(w) not in NOT_NAMES]
    for a, b in zip(words, words[1:]):
        if surname and fold(b) == surname and fold(a) != surname:
            out.append((f"{a.capitalize()} {b.capitalize()}", "täisnimi, sama perenimi"))
    if out:
        return out
    firsts = [w for w in words if fold(w) != surname and fold(w) not in ("ja", "ning")]
    if len(firsts) == 1 and surname:
        return [(f"{firsts[0].capitalize()} {surname.capitalize()}", "eesnimi + maksja perenimi (oletus)")]
    return []


def _consolidate(kids: dict) -> dict:
    """Merge noisy one-off candidates into names confirmed by 2+ payments:
    "Mari Kask Kihnu" -> "Mari Kask" (trip name glued on), "Taneli Tamm" ->
    "Tanel Tamm" (genitive). A candidate is only merged when exactly one core name fits."""
    core = {k: e for k, e in kids.items() if len(e["evidence"]) >= 2}
    def fits(cand: list[str], name: list[str]) -> bool:
        n = len(name)
        if any(cand[i:i + n] == name for i in range(len(cand) - n + 1)):
            return True
        # genitive / typo on the first name only: "taneli tamm" vs "tanel tamm"
        return (len(cand) == n and cand[1:] == name[1:] and
                (cand[0] == name[0] + "i" or cand[0] + "i" == name[0] or cand[0].rstrip("i") == name[0].rstrip("i")))
    out = {k: e for k, e in core.items()}
    for key, e in kids.items():
        if key in core:
            continue
        targets = [c for c in core if c != key and fits(key.split(), c.split())]
        # longest-evidence core wins a genitive tie ("taneli tamm" is itself core if paid twice)
        if len(targets) == 1:
            t = out[targets[0]]
            t["evidence"] += [x + "  [liidetud: " + e["name"] + "]" for x in e["evidence"]]
            for pk, p in e["payers"].items():
                q = t["payers"].setdefault(pk, {"name": p["name"], "ibans": set(), "n": 0, "sum": Decimal(0), "how": set()})
                q["ibans"] |= p["ibans"]; q["n"] += p["n"]; q["sum"] += p["sum"]; q["how"] |= p["how"]
        else:
            out[key] = e
    # genitive pairs where BOTH forms are core: keep the one with more payments
    for key in list(out):
        for other in list(out):
            if key != other and key in out and other in out and fits(key.split(), other.split()) \
                    and len(key.split()) == len(other.split()) and len(out[key]["evidence"]) <= len(out[other]["evidence"]):
                t, e = out[other], out.pop(key)
                t["evidence"] += [x + "  [liidetud: " + e["name"] + "]" for x in e["evidence"]]
                for pk, p in e["payers"].items():
                    q = t["payers"].setdefault(pk, {"name": p["name"], "ibans": set(), "n": 0, "sum": Decimal(0), "how": set()})
                    q["ibans"] |= p["ibans"]; q["n"] += p["n"]; q["sum"] += p["sum"]; q["how"] |= p["how"]
    return out


def cmd_infer_roster(k: Kassa, args):
    since = args.since or "0000"
    txs = {}
    from .banks import load_file
    for f in sorted((k.root / "statements").iterdir()):
        if f.suffix.lower() not in (".json", ".xml", ".csv", ".xlsx"):
            continue
        for t in load_file(f):
            if t["amount"] > 0 and t["date"] >= since and t.get("ttype") not in BANK_ENTRIES:
                txs.setdefault(t["txid"], t)
    NOT_NAMES.update(fold(w) for w in k.cfg.get("infer", {}).get("not_names", []))
    known = [fold(n) for n in (Path(args.kids).read_text(encoding="utf-8").splitlines()
                               if args.kids else []) if n.strip()]
    kids: dict[str, dict] = {}      # folded kid name -> {name, payers{payer:{...}}, evidence}
    orphans = []
    for t in sorted(txs.values(), key=lambda t: t["date"]):
        cands = _kid_candidates(t["description"], t["name"])
        if known:  # a class list beats any heuristic
            hit = [n for n in known if n in fold(t["description"])]
            if hit:
                cands = [(" ".join(w.capitalize() for w in hit[0].split()), "klassinimekirjast")]
        if not cands:
            orphans.append(t)
            continue
        for name, how in cands:
            key = fold(name)
            e = kids.setdefault(key, {"name": name, "payers": {}, "evidence": []})
            p = e["payers"].setdefault(" ".join(sorted(fold(t["name"]).split())), {"name": t["name"], "ibans": set(), "n": 0,
                                                          "sum": Decimal(0), "how": set()})
            p["ibans"].add(t["iban"]); p["n"] += 1; p["sum"] += t["amount"]; p["how"].add(how)
            e["evidence"].append(f"{t['date']}  {eur(t['amount']):>9}  {t['name']!r}: {t['description']!r}  [{how}]")

    kids = _consolidate(kids)
    inf = k.cfg.get("infer", {})
    for alias, target in inf.get("merge", {}).items():
        a, t_ = fold(alias), fold(target)
        if a in kids:
            e = kids.pop(a)
            tgt = kids.setdefault(t_, {"name": target, "payers": {}, "evidence": []})
            tgt["name"] = target
            tgt["evidence"] += [x + "  [käsitsi liidetud: " + e["name"] + "]" for x in e["evidence"]]
            for pk, p in e["payers"].items():
                q = tgt["payers"].setdefault(pk, {"name": p["name"], "ibans": set(), "n": 0, "sum": Decimal(0), "how": set()})
                q["ibans"] |= p["ibans"]; q["n"] += p["n"]; q["sum"] += p["sum"]; q["how"] |= p["how"]
    dropped = [kids.pop(fold(n)) for n in inf.get("drop", []) if fold(n) in kids]

    # A payer linked to several kids is either a sibling pair, a grandparent, or a
    # mis-parse. Flag it rather than guess.
    payer_kids: dict[str, set] = {}
    for key, e in kids.items():
        for pk in e["payers"]:
            payer_kids.setdefault(pk, set()).add(e["name"])
    pkey = lambda n: " ".join(sorted(fold(n).split()))

    rows, ev = [], [f"# Roster proposal from payment history ({len(txs)} incoming, since {since})", "",
                    "Proposal only. Confirm each link, then copy rows into roster.csv.", ""]
    for i, (key, e) in enumerate(sorted(kids.items(), key=lambda kv: kv[0].split()[-1:] + kv[0].split()[:1]), 1):
        payers = sorted(e["payers"].values(), key=lambda p: -p["n"])
        people = [p for p in payers if not COMPANY.search(p["name"])]
        rest = [p for p in payers if p not in people[:2]]
        weak = all(h.endswith("(oletus)") for p in payers for h in p["how"])
        shared = [p["name"] for p in payers if len(payer_kids[pkey(p["name"])]) > 1]
        flags = (["ainult oletus"] if weak else []) + ([f"maksja ka teistel lastel: {', '.join(shared)}"] if shared else []) \
            + (["üks makse"] if sum(p["n"] for p in payers) == 1 else [])
        dates = sorted(x[:10] for x in e["evidence"])
        if dates[-1] < (args.stale or "0000"):
            flags.append(f"viimane makse {dates[-1]}, kas veel klassis?")
        rows.append({"kid_id": f"{i:02d}", "kid_name": e["name"], "kid_genitive": "",
                     "parent1_name": people[0]["name"].title() if people else "", "parent1_email": "", "parent1_phone": "",
                     "parent2_name": people[1]["name"].title() if len(people) > 1 else "", "parent2_email": "", "parent2_phone": "",
                     "payer_aliases": ";".join(p["name"] for p in rest),
                     "notes": "; ".join(flags), "first_paid": dates[0], "last_paid": dates[-1],
                     "payments": len(dates)})
        ev += [f"## {i:02d} {e['name']}" + (f"  ⚠ {'; '.join(flags)}" if flags else ""), ""]
        for p in payers:
            ev.append(f"- maksja **{p['name']}** · {p['n']}× · {eur(p['sum'])} · IBAN {', '.join(sorted(x for x in p['ibans'] if x)) or '-'}")
        ev += ["", "```", *e["evidence"], "```", ""]
    if dropped:
        ev += ["## Välja jäetud (config [infer] drop)", ""] + [f"- {e['name']}: {len(e['evidence'])} makset" for e in dropped] + [""]
    ev += [f"## Seostamata laekumised ({len(orphans)})", "", "```"]
    ev += [f"{t['date']}  {eur(t['amount']):>9}  {t['name']!r}: {t['description']!r}" for t in orphans]
    ev += ["```", ""]

    out = k.root / "roster.proposed.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["kid_id"])
        w.writeheader(); w.writerows(rows)
    (k.root / "roster.evidence.md").write_text("\n".join(ev), encoding="utf-8")
    print(f"{len(txs)} incoming payments → {len(rows)} candidate kids, {len(orphans)} unlinked.")
    print(f"Wrote {out.name} and roster.evidence.md (roster.csv untouched).")
    for r in rows:
        print(f"  {r['kid_id']}  {r['kid_name']:<24} ← {r['parent1_name'] or '?'}"
              f"{' / ' + r['parent2_name'] if r['parent2_name'] else ''}"
              f"{'  +' + r['payer_aliases'] if r['payer_aliases'] else ''}"
              f"{'  ⚠ ' + r['notes'] if r['notes'] else ''}")


