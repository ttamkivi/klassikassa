"""End-to-end tests on fictional data. Every name here is invented."""
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from klassikassa import banks, cli, collect, core

HERE = Path(__file__).parent
DEMO = Path(core.EXAMPLE)


def run(d, *argv, today="2026-10-20"):
    cli.main(["--dir", str(d), "--today", today, *argv])


@pytest.fixture
def demo(tmp_path):
    d = tmp_path / "demo"
    shutil.copytree(DEMO, d)
    return d


def kassa(d):
    return core.Kassa(d)


def txid_of(d, name):
    return next(t["txid"] for t in kassa(d).txs.values() if t["name"] == name)


# ── ledger basics ────────────────────────────────────────────────────────────

def test_demo_status_and_allocation(demo, capsys):
    k = kassa(demo)
    con = k.db()
    s = {kid: k.family_status(con, kid, core.dt.date(2026, 10, 20)) for kid in k.kids}
    assert s["02"]["due_now"] == 0                     # company account, kid named in text
    assert s["01"]["due_now"] == Decimal("45.00")      # paid 100, oldest-due-first allocation
    assert s["04"]["due_now"] == Decimal("145.00")     # twin: parent paid only for the sibling
    assert s["05"]["due_now"] == 0                     # grandmother alias, 50 € override


def test_remind_refuses_while_unmatched(demo):
    with pytest.raises(SystemExit):
        run(demo, "remind")


def test_remind_cadence_and_cap(demo):
    run(demo, "ignore", txid_of(demo, "Tundmatu Isik"), "--note", "returned")
    run(demo, "remind")
    assert (demo / "drafts" / "2026-10-20" / "04.txt").exists()
    run(demo, "mark-reminded", "04")
    shutil.rmtree(demo / "drafts")
    run(demo, "remind", today="2026-10-25")            # too soon: 10-day gap
    assert not (demo / "drafts" / "2026-10-25" / "04.txt").exists()


def test_split_must_add_up(demo):
    t = txid_of(demo, "Rein Mänd")
    with pytest.raises(SystemExit):
        run(demo, "split", t, "03=100", "04=40")
    run(demo, "split", t, "03=100", "04=45")
    k = kassa(demo)
    assert k.paid(k.db(), "04") == Decimal("45.00")


def test_income_stays_in_balance_ignore_does_not(demo):
    before = collect.bank_balance(kassa(demo))
    run(demo, "income", txid_of(demo, "Tundmatu Isik"), "--activity", "Sügislaat")
    assert collect.bank_balance(kassa(demo)) == before
    assert not [t for t in kassa(demo).txs.values() if "unmatched" in t]


# ── bank formats ─────────────────────────────────────────────────────────────

CAMT = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="EUR">50.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-09-22</Dt></BookgDt>
 <AcctSvcrRef>A1</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Nm>LIISA KASK</Nm></Dbtr>
 <DbtrAcct><Id><IBAN>EE111</IBAN></Id></DbtrAcct></RltdPties><RmtInf><Ustrd>Mari Kask klassiraha</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">12.40</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-09-23</Dt></BookgDt>
 <AcctSvcrRef>A2</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Kommipood OÜ</Nm></Cdtr></RltdPties>
 <RmtInf><Strd><CdtrRefInf><Ref>1234561</Ref></CdtrRefInf></Strd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""


def test_camt053(tmp_path):
    f = tmp_path / "s.xml"
    f.write_text(CAMT)
    a, b = banks.load_file(f)
    assert (a["amount"], a["name"], a["iban"], a["description"]) == (Decimal("50.00"), "LIISA KASK", "EE111", "Mari Kask klassiraha")
    assert (b["amount"], b["reference"]) == (Decimal("-12.40"), "1234561")


def test_csv_estonian_semicolon_comma_decimals(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text('"Kliendi konto";"Rea tüüp";"Kuupäev";"Saaja/Maksja";"Selgitus";"Summa";"Valuuta";"Deebet/Kreedit (D/C)";"Arhiveerimistunnus"\n'
                 '"EE0";"10";"01.09.2026";"";"Algsaldo";"100,00";"EUR";"K";""\n'
                 '"EE0";"20";"22.09.2026";"Liisa Kask";"Mari Kask";"50,00";"EUR";"K";"X1"\n'
                 '"EE0";"20";"23.09.2026";"Kommipood OÜ";"kommid";"1 012,40";"EUR";"D";"X2"\n'
                 '"EE0";"86";"30.09.2026";"";"Lõppsaldo";"0,00";"EUR";"K";""\n', encoding="cp1257")
    rows = banks.load_file(f)
    assert [r["amount"] for r in rows] == [Decimal("50.00"), Decimal("-1012.40")]   # balances skipped
    assert rows[0]["date"] == "2026-09-22"


def test_xlsx_statement_copy(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Kuupäev", "Saaja/maksja nim", "Summa", "Selgitus"])
    ws.append([core.dt.datetime(2022, 9, 2), "LIISA KASK", 50.0, "Mari Kask"])
    wb.save(tmp_path / "s.xlsx")
    (r,) = banks.load_file(tmp_path / "s.xlsx")
    assert (r["date"], r["amount"]) == ("2022-09-02", Decimal("50.00"))


def test_lhv_real_shape_regressions(tmp_path):
    """Three traps found on a real 797-row LHV account."""
    base = {"transactionType": {"domain": "PMNT", "family": "ICDT;RCDT", "subfamily": "OTHR"},
            "customerReference": "", "currency": "EUR"}
    rows = [
        # 1. interest and its tax share one bankReference: both must survive
        {**base, "bankReference": 7, "settlementDtime": "2026-01-31T10:00:00Z", "direction": "CREDIT",
         "amount": 0.30, "description": "Intress", "paymentData": None,
         "transactionType": {"domain": "", "family": "NTDP", "subfamily": "INTR"}},
        {**base, "bankReference": 7, "settlementDtime": "2026-01-31T10:00:00Z", "direction": "DEBIT",
         "amount": -0.07, "description": "Tulumaks", "paymentData": None,
         "transactionType": {"domain": "", "family": "MDOP", "subfamily": "TAXE"}},
        # 2. 21:30 UTC on 31 Aug is 1 Sep in Tallinn
        {**base, "bankReference": 8, "settlementDtime": "2026-08-31T21:30:00Z", "direction": "CREDIT",
         "amount": 50, "description": "Mari Kask", "paymentData": {"debtor": {"name": "LIISA KASK", "accountNo": "EE111"}}},
    ]
    f = tmp_path / "lhv.json"
    f.write_text(json.dumps({"statement": {"transactions": rows}}))
    got = banks.load_file(f)
    assert len({t["txid"] for t in got}) == 3
    assert got[2]["date"] == "2026-09-01" and got[2]["iban"] == "EE111"
    assert {got[0]["ttype"], got[1]["ttype"]} == {"INTR", "TAXE"}


# ── roster inference ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("desc,payer,expected", [
    ("Mari-Liis Kask 7b", "Anu Kask", ["Mari-Liis Kask"]),
    ("mari kask klassiraha", "ANU KASK", ["Mari Kask"]),
    ("Kaspar ja Eva Mänd teater", "Rein Mänd", ["Kaspar Mänd", "Eva Mänd"]),
    ("Poolaasta-tanel Ploom", "Kadi Ploom", ["Tanel Ploom"]),
    ("klassiraha", "Marko Pärn", []),
])
def test_name_extraction(desc, payer, expected):
    assert [n for n, _ in core._kid_candidates(desc, payer)] == expected


def test_infer_roster_merges_noise(tmp_path):
    d = tmp_path / "c"
    run(d, "init")
    (d / "roster.csv").write_text("kid_id,kid_name\n")
    shutil.copy(HERE / "history-lhv.json", d / "statements" / "h.json")
    run(d, "infer-roster")
    names = [l.split(",")[1] for l in (d / "roster.proposed.csv").read_text().splitlines()[1:]]
    assert sorted(names) == ["Eva Mänd", "Jaan Tamm", "Karl Saar", "Kaspar Mänd", "Mari Kask"]
    assert (d / "roster.csv").read_text() == "kid_id,kid_name\n"      # proposal never overwrites


# ── the helper's side ────────────────────────────────────────────────────────

def test_propose_rounds_up_per_child(demo):
    p = collect.propose(kassa(demo), ["Teater=35/laps", "Materjalid=52.20/klass", "Kingitus=10"],
                        kids=28, round_to=5, buffer=Decimal("0"))
    assert p["total"] == Decimal("46.86") and p["ask"] == Decimal("50.00")


def test_announce_draft(demo):
    run(demo, "propose", "--item", "Teater=35/laps", "--id", "teater", "--label", "Teater", "--due", "2026-11-01", "--add")
    run(demo, "announce", "teater")
    text = (demo / "drafts" / "2026-10-20" / "announce-teater.txt").read_text()
    assert "35.00 €" in text and "01.11.2026" in text and "EE000000000000000000" in text


def test_advance_reimburse_and_balance(demo, tmp_path):
    run(demo, "advance", "80", "--who", "Kati", "--activity", "Õpetaja kingitus")
    k = kassa(demo)
    assert collect.owed_to(k, "Kati") == Decimal("80.00")
    # the bank transfer back to Kati
    f = tmp_path / "back.json"
    f.write_text(json.dumps({"transactions": [{"transactionId": "r1", "bookingDate": "2026-10-10", "amount": -80,
                  "direction": "DEBIT", "description": "tagasi", "paymentData": {"creditor": {"name": "Kati Pärn"}}}]}))
    run(demo, "ingest", str(f))
    run(demo, "reimburse", txid_of(demo, "Kati Pärn"), "--who", "Kati")
    k = kassa(demo)
    assert collect.owed_to(k, "Kati") == 0
    run(demo, "report", "--out", str(tmp_path / "r.md"))
    r = (tmp_path / "r.md").read_text()
    assert "| Õpetaja kingitus | 80.00 € |" in r and "tagasimakse" not in r   # counted once


def test_table_private_by_default(demo, tmp_path):
    with pytest.raises(SystemExit):
        run(demo, "table")
    run(demo, "table", "--treasurer", "--out", str(tmp_path / "t.csv"))
    assert "Mari Kask" in (tmp_path / "t.csv").read_text(encoding="utf-8-sig")


def test_check_list(demo, tmp_path, capsys):
    (tmp_path / "list.txt").write_text("Mari Kask\nEva Mänd\nKeegi Muu\n")
    run(demo, "check-list", str(tmp_path / "list.txt"), "--amount", "45")
    out = capsys.readouterr().out
    assert "✓  Mari Kask" in out and "✗  Eva Mänd" in out and "not in roster" in out


def test_propose_uses_leftover_balance(demo):
    """A real 2023 collection: costs 60.31 per child, part paid from last year's leftover."""
    items = ["Tehnoloogia=12", "Kaustikud=8", "Teater=35", "Paber=2", "Sünnipäev=1.45", "Materjalid=52.20/klass"]
    k = kassa(demo)
    assert collect.propose(k, items, 28, 5, Decimal(0))["ask"] == Decimal("65.00")
    assert collect.propose(k, items, 28, 5, Decimal(0), from_balance=Decimal("112"))["ask"] == Decimal("60.00")


def test_english_class_gets_english_reminders(demo):
    cfg = (demo / "config.toml").read_text().replace('language = "et"', 'language = "en"')
    (demo / "config.toml").write_text(cfg)
    run(demo, "ignore", txid_of(demo, "Tundmatu Isik"), "--note", "returned")
    run(demo, "remind")
    text = (demo / "drafts" / "2026-10-20" / "04.txt").read_text()
    assert "Subject: 10C class money: Eva" in text and "A small reminder" in text
    assert "tasumata" not in text and "tähtaeg" not in text


def test_status_marks_not_yet_due_apart_from_paid(demo, capsys):
    # before any due date nobody is late, but unpaid families must not look paid
    run(demo, "status", today="2026-09-30")
    out = capsys.readouterr().out
    assert "⚠ tähtaeg möödas 0" in out
    assert any(l.startswith("·") for l in out.splitlines())
    run(demo, "status", today="2026-10-20")
    assert "⚠ tähtaeg möödas 0" not in capsys.readouterr().out


def test_ingest_file_already_in_statements_is_not_copied(demo, capsys):
    f = demo / "statements" / "2026-09-lhv.json"
    run(demo, "ingest", str(f))
    assert "already in statements/" in capsys.readouterr().out
    assert [p.name for p in (demo / "statements").iterdir()] == ["2026-09-lhv.json"]
