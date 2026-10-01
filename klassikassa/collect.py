"""The helper's side of the job: proposing a collection from real costs, announcing it,
tracking money a parent paid out of pocket, sharing the payment table when the class
has agreed to that, and checking an organiser's list against the account.

These came from how an experienced class-fund helper actually works (five years of her
mails to a class list): costs first, per-child amount second, rounded up with a small
buffer, a warm short mail, and a private way out for families who cannot pay.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import re
import sys
from decimal import Decimal
from pathlib import Path

from .core import D, Kassa, append_csv, eur, fold, payto_link, read_csv, today

ADV_FIELDS = ["date", "who", "amount", "activity", "note"]


# ── propose: costs -> per-child amount ───────────────────────────────────────

def parse_item(spec: str) -> dict:
    """'Teater=35/laps' or 'Päikesesüsteemi materjalid=52.20/klass' or 'Kingitus=10'."""
    m = re.fullmatch(r"\s*(.+?)\s*=\s*([\d.,]+)\s*(?:/\s*(laps|lapse kohta|child|klass|class))?\s*", spec)
    if not m:
        raise ValueError(f"cannot read item {spec!r}; use 'Label=35/laps' or 'Label=180/klass'")
    label, amount, unit = m.group(1), D(m.group(2).replace(",", ".")), (m.group(3) or "laps")
    return {"label": label, "amount": amount, "per": "class" if unit in ("klass", "class") else "child"}


def propose(k: Kassa, items: list[str], kids: int | None, round_to: int, buffer: Decimal,
            from_balance: Decimal = Decimal(0)) -> dict:
    n = kids or len(k.kids)
    if not n:
        raise ValueError("no kids in roster.csv; pass --kids N")
    lines, total = [], Decimal(0)
    for spec in items:
        it = parse_item(spec)
        per_kid = D(it["amount"] / n) if it["per"] == "class" else it["amount"]
        total += per_kid
        lines.append({**it, "per_kid": per_kid})
    # money already on the account that the class decides to spend on this (last year's
    # leftover, fair proceeds) lowers what each family is asked for
    credit = D(from_balance / n) if from_balance else Decimal(0)
    raw = max(total + buffer - credit, Decimal(0))
    ask = D(math.ceil(raw / round_to) * round_to) if round_to else D(raw)
    return {"kids": n, "lines": lines, "total": total, "buffer": buffer, "credit": credit,
            "from_balance": D(from_balance), "ask": ask}


def cmd_propose(k: Kassa, args):
    p = propose(k, args.item, args.kids, args.round, D(args.buffer), D(args.from_balance))
    print(f"{p['kids']} last\n")
    for l in p["lines"]:
        basis = f"{eur(l['amount'])} klassi peale" if l["per"] == "class" else "lapse kohta"
        print(f"  {l['label']:<36} {eur(l['per_kid']):>9}   ({basis})")
    print(f"  {'Kokku':<36} {eur(p['total']):>9}")
    if p["buffer"]:
        print(f"  {'Puhver':<36} {eur(p['buffer']):>9}")
    if p["credit"]:
        print(f"  {'Kontojäägist (' + eur(p['from_balance']) + ')':<36} {'-' + eur(p['credit']):>9}")
    print(f"\nEttepanek: {eur(p['ask'])} lapse kohta"
          f" (ümardatud üles {args.round} euroni, laekub {eur(p['ask'] * p['kids'])})")
    block = [f'\n[[collection]]', f'id = "{args.id}"', f'label = "{args.label}"',
             f'amount = {p["ask"]}', f'due = "{args.due}"', 'applies = "all"', 'exempt = []']
    block += [f'[[collection.items]]\nlabel = "{l["label"]}"\nper_kid = {l["per_kid"]}' for l in p["lines"]]
    if p["buffer"]:
        block.append(f'[[collection.items]]\nlabel = "Puhver ootamatuteks kuludeks"\nper_kid = {p["buffer"]}')
    text = "\n".join(block) + "\n"
    if args.add:
        with (k.root / "config.toml").open("a", encoding="utf-8") as f:
            f.write(text)
        print(f"\nAdded collection '{args.id}' to config.toml. Next: announce {args.id}")
    else:
        print("\nNothing written. Re-run with --add to append this to config.toml:" + text)


# ── announce: the collection mail ────────────────────────────────────────────

from .core import template as _template


def bank_balance(k: Kassa) -> Decimal:
    con = k.db()
    (c,) = con.execute("select coalesce(sum(cents),0) from tx where state!='ignored' and source='bank'").fetchone()
    return D(Decimal(c) / 100) + D(k.cls.get("opening_balance", 0))


def _paylink_group(k: Kassa, c: dict) -> str:
    """A link for the whole list: amount filled in, the child's name left for the parent.
    A bank-made link in the collection's pay_link (e.g. Swedbank) wins over payto://."""
    from .core import WORDS
    W = WORDS.get(k.cls.get("language", "et"), WORDS["et"])
    link = c.get("pay_link") or payto_link(k, D(c["amount"]), c.get("purpose", c["label"]))
    if not link:
        return ""
    if k.cls.get("language") == "en":
        return f"Payment link: {link}\n(add your child's name to the reference text)\n"
    return f"Makselink: {link}\n(lisa selgitusse lapse nimi)\n"


def cmd_announce(k: Kassa, args):
    c = next((c for c in k.collections if c["id"] == args.id), None)
    if not c:
        sys.exit(f"No collection {args.id} in config.toml.")
    items = c.get("items", [])
    lines = "".join(f"   - {i['label']}: {eur(D(i['per_kid']))}\n" for i in items) or f"   - {c['label']}\n"
    body = _template(k, "announce").format(
        cls=k.cls["name"], label=c["label"], lines=lines, amount=eur(D(c["amount"])),
        due=dt.date.fromisoformat(c["due"]).strftime("%d.%m.%Y"),
        balance=eur(bank_balance(k)), holder=k.cls["account_holder"], iban=k.cls["account_iban"],
        purpose=c.get("purpose", c["label"]),
        paylink=_paylink_group(k, c),
        signature=k.cls.get("signature", k.cls.get("treasurer", "")))
    to = k.cls.get("parents_list", "")
    out = k.root / "drafts" / today(args).isoformat()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"announce-{c['id']}.txt"
    path.write_text(f"To: {to}\nSubject: {k.cls['name']}: {c['label']}\n\n{body}", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
    print(f"\nDraft saved to {path}. Nothing was sent.")


# ── advances: money a parent paid out of pocket ──────────────────────────────

def advances(k: Kassa) -> list[dict]:
    return read_csv(k.root / "advances.csv")


def cmd_advance(k: Kassa, args):
    row = {"date": args.date or dt.date.today().isoformat(), "who": args.who,
           "amount": str(D(args.amount)), "activity": args.activity, "note": args.note or ""}
    append_csv(k.root / "advances.csv", ADV_FIELDS, row)
    print(f"Recorded: {args.who} paid {eur(D(args.amount))} for {args.activity}. "
          f"Owed to {args.who} now: {eur(owed_to(k, args.who, extra=D(args.amount)))}")


def owed_to(k: Kassa, who: str, extra: Decimal = Decimal(0)) -> Decimal:
    paid_out = sum((D(a["amount"]) for a in advances(k) if fold(a["who"]) == fold(who)), Decimal(0))
    back = sum((-t["amount"] for t in k.txs.values()
                if t.get("reimburse") and fold(t["reimburse"]) == fold(who)), Decimal(0))
    return paid_out + extra - back


def cmd_reimburse(k: Kassa, args):
    t = k.txs.get(args.txid)
    if not t or t["amount"] >= 0:
        sys.exit("reimburse takes an outgoing bank transaction (the transfer back to the parent).")
    from .core import _decide
    _decide(k, args.txid, "reimburse", args.who, args.note or "")


def cmd_owed(k: Kassa, args):
    people = sorted({a["who"] for a in advances(k)})
    if not people:
        print("No advances recorded.")
    for who in people:
        print(f"  {who:<20} ettemakstud {eur(sum((D(a['amount']) for a in advances(k) if a['who'] == who), Decimal(0))):>10}"
              f"   tagastamata {eur(owed_to(k, who)):>10}")


# ── table: the payment table, only when the class agreed to share it ─────────

def cmd_table(k: Kassa, args):
    mode = k.cls.get("transparency", "private")
    if mode != "open" and not args.treasurer:
        sys.exit("This class keeps payments private (config: transparency = \"private\").\n"
                 "Use --treasurer for your own copy. To share the table with parents, first ask\n"
                 "the class (opt-out is the usual way), then set transparency = \"open\".")
    con, as_of = k.db(), today(args)
    cols = [c["id"] for c in k.collections]
    rows = []
    for kid in sorted(k.kids, key=lambda x: k.kids[x]["kid_name"]):
        s = k.family_status(con, kid, as_of)
        cells = {r["collection"]["id"]: ("✓" if r["got"] == r["amount"] else eur(r["got"]) if r["got"] else "")
                 for r in s["rows"]}
        rows.append([k.kids[kid]["kid_name"]] + [cells.get(c, "-") for c in cols])
    out = Path(args.out or k.root / f"tabel-{as_of}.csv")
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Õpilane"] + [c["label"] for c in k.collections])
        w.writerows(rows)
    print(f"Wrote {out} ({len(rows)} rows, {'shareable' if mode == 'open' else 'TREASURER ONLY, do not share'}).")


# ── check-list: an organiser's list against the account ──────────────────────

def cmd_check_list(k: Kassa, args):
    names = [l.strip().split(";")[0].split(",")[0] for l in Path(args.file).read_text(encoding="utf-8").splitlines()
             if l.strip()]
    since = args.since or "0000"
    con = k.db()
    print(f"{len(names)} names on the list, payments since {since}"
          f"{' matching ' + repr(args.match) if args.match else ''}:\n")
    missing = 0
    for n in names:
        kid = next((kid for kid, r in k.kids.items() if fold(r["kid_name"]) == fold(n)), None)
        if not kid:
            print(f"  ?  {n:<28} not in roster.csv")
            continue
        q = "select date, cents, description from tx where kid_id=? and cents>0 and date>=?"
        rows = [r for r in con.execute(q, (kid, since)).fetchall()
                if not args.match or fold(args.match) in fold(r[2])]
        paid = D(Decimal(sum(r[1] for r in rows)) / 100)
        ok = args.amount is None or paid >= D(args.amount)
        missing += not ok
        print(f"  {'✓' if ok else '✗'}  {n:<28} {eur(paid):>10}  " + ", ".join(r[0] for r in rows))
    print(f"\n{missing} not (fully) paid." + (" Reminders go to those families only, never the whole list." if missing else ""))


# ── draft: the other messages a treasurer sends ──────────────────────────────
# Learned from nine years of a second treasurer's mail to his class list (first grade
# to ninth): besides "please pay" and "you have not paid yet", the same five
# messages came back every year. Each one here gets its numbers from the ledger.

DRAFTS = ("progress", "covered", "yearend", "shortfall", "duplicate")


def _collection(k: Kassa, cid: str | None) -> dict:
    cs = k.collections
    if not cs:
        sys.exit("No collection in config.toml.")
    c = next((c for c in cs if c["id"] == cid), None) if cid else max(cs, key=lambda c: c["due"])
    if not c:
        sys.exit(f"No collection {cid} in config.toml.")
    return c


def _paylines(k: Kassa, amount: Decimal | None, purpose: str, link: str = "",
              link_msg: str | None = None) -> str:
    L = [f"Makse saaja: {k.cls['account_holder']}", f"Konto: {k.cls['account_iban']}"]
    if k.cls.get("language", "et") == "en":
        L = [f"Recipient: {k.cls['account_holder']}", f"Account: {k.cls['account_iban']}"]
    if amount is not None:
        L.append(("Amount: " if k.cls.get("language") == "en" else "Summa: ") + eur(amount))
    L.append(("Reference text: " if k.cls.get("language") == "en" else "Selgitus: ") + purpose)
    link = link or payto_link(k, amount, purpose if link_msg is None else link_msg)
    if link:
        L.append(("Payment link: " if k.cls.get("language") == "en" else "Makselink: ") + link)
        if link_msg is not None:  # a mail to the whole list: the link cannot know the child
            L.append("(add your child's name to the reference text)" if k.cls.get("language") == "en"
                     else "(lisa selgitusse lapse nimi)")
    return "\n".join(L)


def per_child_ceil(amount: Decimal, n: int) -> Decimal:
    """Split a sum over n children, rounded UP to the cent so the class is never short."""
    return D(Decimal(math.ceil(amount * 100 / n)) / 100)


def cmd_draft(k: Kassa, args):
    con, as_of = k.db(), today(args)
    sig = k.cls.get("signature", k.cls.get("treasurer", ""))
    bal = bank_balance(k)
    n = len(k.kids)
    to = k.cls.get("parents_list", "")
    f: dict = {"cls": k.cls["name"], "balance": eur(bal), "signature": sig, "kids": n}
    note = []  # for the treasurer only, never in the draft

    if args.kind == "progress":
        # counts, never names: who has not paid hears it privately (remind)
        c = _collection(k, args.id)
        rows = [r for kid in k.kids for r in k.family_status(con, kid, as_of)["rows"]
                if r["collection"]["id"] == c["id"]]
        full = sum(1 for r in rows if r["got"] == r["amount"])
        f |= {"label": c["label"], "paid": full, "total": len(rows),
              "due": dt.date.fromisoformat(c["due"]).strftime("%d.%m.%Y"),
              "pay": _paylines(k, D(c["amount"]), c.get("purpose", c["label"]) + ", lapse nimi"
                               if k.cls.get("language", "et") == "et" else c.get("purpose", c["label"]) + ", child's name",
                               c.get("pay_link", ""), link_msg=c.get("purpose", c["label"]))}
        subject = f"{k.cls['name']}: {c['label']}"
    elif args.kind == "covered":
        if not args.what:
            sys.exit("draft covered needs --what (the event the fund pays for)")
        if args.cost and D(args.cost) > bal:
            note.append(f"⚠ {args.what} costs {eur(D(args.cost))} but the account holds {eur(bal)}. "
                        "Do not send this; use propose / announce instead.")
        f |= {"what": args.what}
        subject = f"{k.cls['name']}: {args.what}"
    elif args.kind == "yearend":
        inc = D(Decimal(con.execute("select coalesce(sum(cents),0) from tx where cents>0 and state!='ignored'").fetchone()[0]) / 100)
        spent = D(Decimal(-con.execute("select coalesce(sum(cents),0) from tx where cents<0 and state!='ignored'").fetchone()[0]) / 100)
        gift = D(args.gift) if args.gift else Decimal(0)
        carry = bal - gift
        late = [kid for kid in k.kids if k.family_status(con, kid, as_of)["due_now"] > 0]
        if late:
            note.append(f"⚠ {len(late)} families still owe for past collections. Settle them before "
                        "the summer: the carry-over in this draft assumes nothing more arrives. (status, remind)")
        n_unc = con.execute("select count(*) from tx where state in ('unmatched','uncategorised')").fetchone()[0]
        if n_unc:
            note.append(f"⚠ {n_unc} rows still need review; the figures below are not final.")
        f |= {"income": eur(inc), "spent": eur(spent), "gift": eur(gift), "carry": eur(carry),
              "carry_kid": eur(D(carry / n)) if n else "", "reply_by": args.reply_by or "[kuupäev]"}
        subject = f"{k.cls['name']}: {'school year end' if k.cls.get('language') == 'en' else 'klassirahad ja kooliaasta lõpp'}"
    elif args.kind == "shortfall":
        cost = D(args.cost) if args.cost else sum((owed_to(k, w) for w in {a["who"] for a in advances(k)}), Decimal(0))
        if not cost:
            sys.exit("draft shortfall needs --cost, or an advance recorded with `advance`.")
        short = cost - bal
        if short <= 0:
            sys.exit(f"The account ({eur(bal)}) covers {eur(cost)}; no collection needed.")
        per = per_child_ceil(short, n)
        what = args.what or "[mille eest]"
        f |= {"what": what, "cost": eur(cost), "short": eur(short), "per": eur(per),
              "paid_by": args.paid_by or "[kes maksis]",
              "pay": _paylines(k, per, f"{k.cls['name']} {what}", args.link or "")}
        note.append(f"To track it: propose --item '{what}={per}/laps' --round 0 --id <id> --due <date> --add")
        subject = f"{k.cls['name']}: {what}"
    elif args.kind == "duplicate":
        if args.kid not in k.kids:
            sys.exit("draft duplicate needs --kid ID")
        s = k.family_status(con, args.kid, as_of)
        if s["credit"] <= 0 and not args.amount:
            sys.exit(f"{k.kids[args.kid]['kid_name']} has no overpayment on the ledger; pass --amount if you know better.")
        r = k.kids[args.kid]
        f |= {"amount": eur(D(args.amount) if args.amount else s["credit"]),
              "kid_gen": r.get("kid_genitive") or r["kid_name"].split()[0]}
        to = ", ".join(e for e in (r.get("parent1_email"), r.get("parent2_email")) if e)
        note.append("After the refund appears on the statement: refund <txid> " + args.kid)
        subject = f"{k.cls['name']}: {'double payment' if k.cls.get('language') == 'en' else 'topeltmakse'}"
    else:
        sys.exit(f"kind must be one of {', '.join(DRAFTS)}")

    body = _template(k, f"draft-{args.kind}").format(**f)
    out = k.root / "drafts" / as_of.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.kind}.txt"
    path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
    for line in note:
        print(line)
    print(f"\nDraft saved to {path}. Nothing was sent.")
