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

## Kuidas oma klassile kasutusele võtta

**Samm-sammult juhend: [docs/ALUSTAMINE.md](docs/ALUSTAMINE.md)** (English:
[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)). Lühidalt:

1. **Tee endale koopia:** *Use this template → Private*, või *Code → Download ZIP*.
   Ära kasuta *Fork*-i. Sinu koopia ei ole selle repositooriumiga seotud ja selle omanik
   ei näe sinu andmeid.
2. **Paigalda [uv](https://docs.astral.sh/uv/)** (käivitab programmi, Python tuleb ise kaasa).
3. **Loo klassi kaust väljaspool koodi kausta:**
   ```bash
   uv run python -m klassikassa --dir ~/Dokumendid/klassikassa-andmed/3a-2026 init
   ```
4. Täida `config.toml` ja `roster.csv`, loe sisse pangaväljavõte (camt.053 XML või CSV),
   ja `status` näitab, kes on maksnud.

Kui kontol on juba mitme aasta ajalugu, oskab tööriist sellest laste ja maksjate
nimekirja ette pakkuda (`infer-roster`). Tulemus on ettepanek, mitte nimekiri; iga seos
kinnitab inimene.

Töö jaotus laekuri ja abi vahel: [docs/ROLES.md](docs/ROLES.md). AI-assistendiga
kasutamiseks: [AGENT.md](AGENT.md).

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
