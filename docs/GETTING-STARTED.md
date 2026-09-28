# Getting started: klassikassa for your class

For a parent who wants to run their class's money with this tool. No programming needed;
about half an hour and a terminal. *Eesti keeles: [ALUSTAMINE.md](ALUSTAMINE.md) (fuller).*

## Two rules first

1. **Code and class data live in separate folders.** The code is this repository. Your
   class data (children's and parents' names, contacts, bank statements) lives in its own
   folder on your computer, **never inside the code folder and never on GitHub**.
2. **Your copy is yours.** If you copy it on GitHub, make it **private**. The owner of the
   original repository cannot see your copy or your data.

## Steps

1. **Get a copy.** On GitHub: **Use this template → Create a new repository → Private**
   (an independent copy, not linked to the original). Or **Code → Download ZIP**.
   Do not use **Fork**: a fork stays in the original's network.
2. **Install uv** (once). Mac/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
   Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
3. **Create your class folder outside the code folder:**
   ```bash
   cd ~/Documents/klassikassa-code
   uv run python -m klassikassa --dir ~/Documents/klassikassa-data/3a-2026 init
   export KLASSIKASSA_DIR=~/Documents/klassikassa-data/3a-2026
   ```
4. **Edit `config.toml`**: class name, account holder and IBAN (a separate account for
   class money is best), signature, parents' list address, start date, opening balance,
   `transparency = "private"`, and `language = "en"` for English messages.
5. **Fill `roster.csv`**: one row per child (`kid_id`, `kid_name` as parents write it in
   payments, parents' names and emails, `payer_aliases` for grandparents or company
   accounts). If the account already has history, run `infer-roster` after step 6 and
   confirm its proposal row by row.
6. **Import a bank statement**: internet bank, account statement, format ISO 20022 XML
   (camt.053) or CSV. Then `ingest <file>` and `review`.
7. **Day to day**: `status`, `propose`, `announce`, `remind`, `mark-reminded`, `advance`,
   `reimburse`, `check-list`, `report`. See `--help` and the table in ALUSTAMINE.md.
8. **With an AI assistant** (optional): open it in the code folder and say *"Read AGENT.md
   and help me run our class fund; the class folder is ..."*.
9. **Updating**: replace the code folder with a new download; your class folder is untouched.

Privacy details: [PRIVACY.md](PRIVACY.md).
