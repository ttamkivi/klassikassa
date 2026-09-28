# klassikassa

**Klassiraha arvestus lapsevanematele.** Kes on maksnud, kes mitte, kuhu raha läks, ja
sõbralik meeldetuletus ainult neile, kellel on veel tasumata. Kõik andmed jäävad sinu
arvutisse; serverit, kontot ega pilve ei ole.

*A class-fund treasurer for parents. Who paid, who has not, where the money went, and a
kind reminder only to the families who still owe. All data stays on your computer. English
summary at the end.*

## Kellele

Lapsevanemale, kes on võtnud enda kanda klassi raha kogumise ("klassipankur", "laekur")
või aitab selles ("laekuri abi"). Tööriist asendab käsitsi peetud tabelit ja vastab
küsimustele, mis muidu võtavad õhtu:

- Kes on selle kogumise eest maksnud? Kas see 145 € on ühe lapse või kaksikute eest?
- Palju peaks sel korral lapse kohta küsima, kui teater on 35 €, bussi hind 180 € klassi peale
  ja õpetajale läheb kingitus?
- Kellele ja kuidas meelde tuletada, ilma et keegi end avalikult häbistatuna tunneks?
- Mis on kontojääk ja mille peale raha kulus, poolaasta aruandeks vanematele?
- Kas ekskursiooni korraldaja nimekirjas olevad lapsed on tegelikult maksnud?

## Kuidas see töötab

1. **Pangaväljavõte sisse.** Kõik Eesti pangad (LHV, Swedbank, SEB, Coop, Luminor) annavad
   väljavõtte ISO 20022 **camt.053 XML**-ina või **CSV**-na. Sobib ka LHV MCP JSON ja
   vana Exceli tabel, kus on veerud Kuupäev, Saaja/maksja, Summa, Selgitus.
2. **Maksed seotakse lastega.** Viitenumbri, selgituses oleva lapse nime või maksja nime
   järgi (ka vanavanemad ja firmakontod). Mida ei suudeta kindlalt siduda, läheb
   ülevaatusse, mitte oletuseks.
3. **Kogumised on kulupõhised.** Kirjuta teadaolevad kulud, tööriist jagab laste arvuga,
   ümardab üles ja lisab puhvri. Kirja vanematele koostab ta ise.
4. **Meeldetuletused on mustandid.** Mitte midagi ei saadeta automaatselt. Iga pere saab
   ainult oma seisu; pärast kolme meeldetuletust soovitab tööriist rääkida inimesega.
5. **Aruanne vanematele** näitab kogutut, kulusid tegevuste kaupa ja jääki. Kes ei ole
   maksnud, seda aruandes ei ole, välja arvatud kui klass on selles ise kokku leppinud.

Kõik arvutused tehakse koodis (Decimal + SQLite). Kui kasutad seda koos AI-assistendiga,
teeb assistent ainult otsustamist vajavad asjad: kas see makse on selle lapse eest, kas
see kiri on sobiv.

## Paigaldus

```bash
uv tool install git+https://github.com/ttamkivi/klassikassa
```

Repo on praegu privaatne: ligipääsu saab omanikult. Või koodist: `uv run python -m klassikassa --help`. Vajab Python 3.11+. Exceli failide
lugemiseks: `uv tool install 'klassikassa[xlsx] @ git+...'`.

## Esimesed sammud

```bash
export KLASSIKASSA_DIR=~/klassikassa/7b-2026      # üks kaust klassi ja õppeaasta kohta
klassikassa init                                  # näidisklass, mille üle kirjutad
# muuda config.toml: klass, konto, kogumised; asenda roster.csv päris nimekirjaga
klassikassa ingest ~/Downloads/valjavote.xml
klassikassa review                                # mis vajab inimese otsust
klassikassa status
```

Kui kontol on juba mitme aasta ajalugu, oskab tööriist sellest **laste ja maksjate
nimekirja ette pakkuda**: `klassikassa infer-roster --stale 2025-09-01`. Tulemus on
ettepanek (`roster.proposed.csv` + tõendid), mitte nimekiri; iga seos kinnitab inimene.

Kõik käsud: `klassikassa --help`. Töö jaotus laekuri ja abi vahel:
[docs/ROLES.md](docs/ROLES.md). AI-assistendiga kasutamiseks: [AGENT.md](AGENT.md).

## Privaatsus lühidalt

Klassikaust sisaldab teiste perede nimesid, kontakte ja maksete ajalugu. **See kaust ei
lähe kunagi giti, pilve ega vanemate gruppi.** Täpsemalt: [docs/PRIVACY.md](docs/PRIVACY.md).

## English summary

`klassikassa` keeps a class fund's books from bank statements (camt.053 XML, CSV, XLSX,
LHV MCP JSON), matches payments to children by reference number or name, proposes
per-child collection amounts from real costs, drafts announcement and reminder emails
(never sends them), tracks money parents paid out of pocket, and writes a report for
parents that shows totals, not debtors. Data stays in a local folder per class. Messages
default to Estonian; set `language = "en"` in `config.toml` for English templates.
MIT licence.
