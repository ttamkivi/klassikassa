"""Bank statement readers. Every reader returns normalised transactions:

    {txid, date (YYYY-MM-DD, local), amount (Decimal, + in / - out), currency,
     name (counterparty), iban (counterparty), description, reference (digits only),
     source, ttype}

Supported inputs, by file extension:

    .json   LHV MCP `get_account_statement` (verified against a real 797-row account),
            or any JSON holding a list of transaction objects
    .xml    ISO 20022 camt.053 / camt.052 (the standard export of every Estonian bank:
            LHV, Swedbank, SEB, Coop, Luminor)
    .csv    bank CSV exports; columns are recognised by Estonian or English header names
    .xlsx   same header recognition, every sheet (needs openpyxl)

Adding a bank means adding header aliases below, not a new code path.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .core import D, _find_tx_list, fold, normalise_tx


def _txid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:8]


def _tx(date, amount, name="", iban="", desc="", ref="", native="", ttype="", source="bank", currency="EUR"):
    amount = D(amount)
    key = f"{native}|{date}|{amount}" if native else f"{date}|{amount}|{name}|{iban}|{desc}|{ref}"
    return {"txid": _txid(key), "date": date, "amount": amount, "currency": currency,
            "name": (name or "").strip(), "iban": (iban or "").replace(" ", ""),
            "description": (desc or "").strip(), "reference": re.sub(r"\D", "", ref or ""),
            "source": source, "ttype": ttype}


# ── JSON (LHV MCP and look-alikes) ───────────────────────────────────────────

def read_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    lst = _find_tx_list(data)
    if lst is None:
        raise ValueError(f"{path.name}: no transaction list found")
    return [normalise_tx(r) for r in lst]


# ── camt.053 / camt.052 ──────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, path: str):
    """Namespace-agnostic child lookup: _find(e, 'NtryDtls/TxDtls')."""
    cur = [el]
    for step in path.split("/"):
        cur = [c for e in cur for c in e if _local(c.tag) == step]
        if not cur:
            return []
    return cur


def _text(el, path: str) -> str:
    found = _find(el, path)
    return (found[0].text or "").strip() if found else ""


def _party(txd, role: str) -> tuple[str, str]:
    """camt v2 puts the name at RltdPties/Dbtr/Nm, v8+ at RltdPties/Dbtr/Pty/Nm."""
    name = _text(txd, f"RltdPties/{role}/Nm") or _text(txd, f"RltdPties/{role}/Pty/Nm")
    iban = _text(txd, f"RltdPties/{role}Acct/Id/IBAN") or _text(txd, f"RltdPties/{role}Acct/Id/Othr/Id")
    return name, iban


def read_camt(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    out = []
    for ntry in root.iter():
        if _local(ntry.tag) != "Ntry":
            continue
        sign = -1 if _text(ntry, "CdtDbtInd") == "DBIT" else 1
        date = (_text(ntry, "BookgDt/Dt") or _text(ntry, "BookgDt/DtTm") or _text(ntry, "ValDt/Dt"))[:10]
        entry_ref = _text(ntry, "AcctSvcrRef") or _text(ntry, "NtryRef")
        ttype = _text(ntry, "BkTxCd/Domn/Fmly/SubFmlyCd")
        details = _find(ntry, "NtryDtls/TxDtls") or [ntry]
        for i, txd in enumerate(details):
            amt = _text(txd, "AmtDtls/TxAmt/Amt") or _text(txd, "Amt") if len(details) > 1 else _text(ntry, "Amt")
            name, iban = _party(txd, "Dbtr" if sign > 0 else "Cdtr")
            desc = " ".join(e.text.strip() for e in _find(txd, "RmtInf/Ustrd") if e.text)
            ref = _text(txd, "RmtInf/Strd/CdtrRefInf/Ref")
            native = _text(txd, "Refs/AcctSvcrRef") or (f"{entry_ref}#{i}" if entry_ref else "")
            out.append(_tx(date, Decimal(amt or "0") * sign, name, iban, desc, ref, native,
                           {"INTR": "INTR", "TAXE": "TAXE"}.get(ttype, ttype)))
    return out


# ── CSV / XLSX with header recognition ───────────────────────────────────────

HEADERS = {
    "date": ["kuupaev", "kande kuupaev", "date", "booking date", "value date", "kuupäev"],
    "name": ["saaja maksja", "saaja maksja nimi", "saaja maksja nim", "saaja voi maksja",
             "maksja saaja", "counterparty", "payer payee", "beneficiary remitter", "name"],
    "iban": ["saaja maksja konto", "vastaspoole konto", "konto", "counterparty account", "account"],
    "amount": ["summa", "amount", "summa eur"],
    "direction": ["deebet kreedit", "deebet kreedit d c", "d k", "d c", "debit credit", "cdt dbt"],
    "desc": ["selgitus", "description", "details", "explanation", "maksekorralduse selgitus"],
    "ref": ["viitenumber", "viide", "reference", "reference number"],
    "id": ["arhiveerimistunnus", "arhiivitunnus", "dokumendi number", "archive id", "transaction id", "kande id"],
    "rowtype": ["rea tuup"],   # Swedbank: 20 = transaction; 10/82/86 = balances and totals
    "currency": ["valuuta", "currency"],
}


def _map_header(row: list) -> dict[str, int]:
    m = {}
    for i, h in enumerate(row):
        f = fold(str(h or ""))
        for key, aliases in HEADERS.items():
            if key not in m and f in aliases:
                m[key] = i
    return m if {"date", "amount"} <= m.keys() else {}


def _num(v) -> Decimal:
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    s = str(v or "").replace("\xa0", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")


def _date(v) -> str:
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = str(v or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s[:19] if "%H" in fmt else s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"not a date: {v!r}")


def _rows_to_txs(rows: list[list], source: str) -> list[dict]:
    out, m = [], {}
    for row in rows:
        if not m:
            m = _map_header(row)
            continue
        if not any(c not in (None, "") for c in row):
            continue
        g = lambda k: row[m[k]] if k in m and m[k] < len(row) else ""
        if "rowtype" in m and str(g("rowtype")).strip() not in ("20", ""):
            continue
        try:
            amount, date = _num(g("amount")), _date(g("date"))
        except ValueError:
            continue  # footer, totals, a second header
        d = fold(str(g("direction")))
        if d in ("d", "deebet", "debit", "dbit") and amount > 0:
            amount = -amount
        out.append(_tx(date, amount, str(g("name")), str(g("iban")), str(g("desc")),
                       str(g("ref")), str(g("id")), source=source,
                       currency=str(g("currency") or "EUR")))
    if not m:
        raise ValueError("no recognisable header row (need at least a date and an amount column)")
    return out


def read_csv_export(path: Path) -> list[dict]:
    raw = path.read_bytes()
    text = next((raw.decode(e) for e in ("utf-8-sig", "cp1257", "latin-1") if _decodes(raw, e)), "")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    return _rows_to_txs(list(csv.reader(io.StringIO(text), dialect)), "bank")


def _decodes(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def read_xlsx(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        raise ValueError("reading .xlsx needs openpyxl: pip install openpyxl")
    out = []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        try:
            out += _rows_to_txs([list(r) for r in ws.iter_rows(values_only=True)], "bank")
        except ValueError:
            continue  # a sheet with no transaction table
    if not out:
        raise ValueError(f"{path.name}: no sheet with a date + amount table")
    return out


READERS = {".json": read_json, ".xml": read_camt, ".csv": read_csv_export, ".xlsx": read_xlsx}


def load_file(path: Path) -> list[dict]:
    reader = READERS.get(path.suffix.lower())
    if not reader:
        raise ValueError(f"{path.name}: unsupported file type (use {', '.join(READERS)})")
    return reader(path)
