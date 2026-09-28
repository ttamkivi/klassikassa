# Alustamine: klassikassa oma klassile

See juhend on lapsevanemale, kes tahab klassikassat oma klassi rahaasjade jaoks kasutada.
Programmeerimist ei ole vaja; vaja on umbes pool tundi ja oskust avada terminal.
*English: [GETTING-STARTED.md](GETTING-STARTED.md).*

## Enne alustamist: kaks reeglit

1. **Kood ja klassi andmed on eraldi kaustades.** Kood on see repositoorium. Klassi andmed
   (laste ja vanemate nimed, kontaktid, pangaväljavõtted) on sinu arvutis **eraldi kaustas,
   mitte kunagi koodi kaustas ega GitHubis**. Nii ei saa sa neid kogemata kuhugi üles laadida,
   ja koodi uuendamine ei puuduta sinu andmeid.
2. **Sinu koopia on sinu oma.** Kui teed koopia GitHubis, tee see **privaatseks**. Algse
   repositooriumi omanik ei näe sinu koopiat ega sinu andmeid ning ei saa neid kunagi.

## 1. Võta endale koopia

Vali üks:

- **GitHubi kaudu:** ava repositoorium, vajuta **Use this template → Create a new repository**,
  vali **Private**. Saad eraldiseisva koopia, mis ei ole algsega seotud.
- **Ilma GitHubita:** vajuta **Code → Download ZIP** ja paki lahti näiteks kausta
  `Dokumendid/klassikassa-kood`.

Ära kasuta "Fork" nuppu: fork jääb algse repositooriumiga ühte võrku.

## 2. Paigalda uv (ühekordne)

`uv` käivitab programmi ja hoolitseb ise õige Pythoni eest.

- **Mac või Linux** (Terminal):
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows** (PowerShell):
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Sulge terminal ja ava uuesti. Kontroll: `uv --version`.

## 3. Loo oma klassi kaust

Mine koodi kausta ja loo klassi kaust **väljaspool seda**:

```bash
cd ~/Dokumendid/klassikassa-kood
uv run python -m klassikassa --dir ~/Dokumendid/klassikassa-andmed/3a-2026 init
```

Iga klassi ja õppeaasta jaoks oma kaust (`3a-2026`, `3a-2027`, ...). Et `--dir` ei peaks iga
kord kirjutama, määra see korraks terminali jaoks:

```bash
export KLASSIKASSA_DIR=~/Dokumendid/klassikassa-andmed/3a-2026      # Mac, Linux
$env:KLASSIKASSA_DIR="$HOME\Dokumendid\klassikassa-andmed\3a-2026"  # Windows PowerShell
```

Edaspidi piisab: `uv run python -m klassikassa status`.

## 4. Täida `config.toml`

Ava klassi kaustas `config.toml` suvalise tekstiredaktoriga. Näidis on täidetud väljamõeldud
andmetega; kirjuta need üle.

| Väli | Mis sinna käib |
|---|---|
| `name` | klassi nimi, nt `"3A"` |
| `account_holder`, `account_iban` | kelle nimel konto on ja selle IBAN. **Soovitus: eraldi konto ainult klassirahale** (paljud pangad avavad lisakonto tasuta). |
| `signature` | kuidas kirjad lõpevad, nt `"Kati (Liisi ema, klassi laekur)"` |
| `parents_list` | vanemate listi aadress, kuhu kogumiskirjad lähevad |
| `start` | alates mis kuupäevast arvestus käib (tavaliselt 1. september) |
| `opening_balance` | kui palju oli kontol `start` kuupäeval (eelmise aasta jääk) |
| `transparency` | `"private"`: iga pere näeb ainult oma seisu (soovitatav). `"open"`: klass on kokku leppinud ühise tabeli. |
| `language` | kirjade keel: `"et"` või `"en"` |
| `[reminders]` | mitu päeva pärast tähtaega esimene meeldetuletus, kui tihti, mitu kõige rohkem |
| `[[collection]]` | iga kogumine: summa, tähtaeg, kellele kehtib. Selle saab ka lasta arvutada, vt samm 7. |

## 5. Täida `roster.csv` (laste nimekiri)

Ava tabelarvutuses (Excel, Numbers, Google Sheets, LibreOffice) ja salvesta CSV-na.

| Veerg | Näide | Märkus |
|---|---|---|
| `kid_id` | `01` | järjekorranumber, ei muutu aasta jooksul |
| `kid_name` | `Mari Kask` | nii, nagu vanemad selle maksekorraldusse kirjutavad |
| `kid_genitive` | `Mari` | omastav kääne kirjade jaoks: Jaan → *Jaani*, Rait → *Raidu* |
| `parent1_name`, `parent1_email`, `parent1_phone` | | vähemalt üks kontakt |
| `parent2_...` | | teine vanem, kui on |
| `payer_aliases` | `Vanaema Helgi Kask;Kask Holding OÜ` | kes veel selle lapse eest maksab |

**Kui kontol on juba eelmiste aastate ajalugu**, ei pea nimekirja nullist tegema: loe
väljavõte sisse (samm 6) ja käivita `infer-roster`. See pakub laste ja maksjate nimekirja
koos tõenditega (`roster.proposed.csv`, `roster.evidence.md`). **Kontrolli iga rida üle**, siis
kopeeri kinnitatud read `roster.csv`-sse.

## 6. Pangaväljavõte sisse

Internetipangas: **konto väljavõte → vali periood → vorming ISO 20022 / XML (camt.053)**.
Kui XML-i ei pakuta, sobib **CSV**. Salvesta fail ja:

```bash
uv run python -m klassikassa ingest ~/Downloads/valjavote.xml
uv run python -m klassikassa review
```

`review` näitab makseid, mida ei suudetud kindlalt lapsega siduda. Iga rea kohta:

| Olukord | Käsk |
|---|---|
| makse on selle lapse eest | `assign TXID 07` |
| üks makse kahe lapse eest | `split TXID 03=30 04=30` |
| laada tulu, kooli tagasimakse | `income TXID --activity "Sügislaat"` |
| kulu (buss, kingitus, pilet) | `spend TXID --activity "Teater"` |

Sama väljavõtte uuesti sisselugemine on ohutu: topelt ridu ei teki.

## 7. Igapäevane töö

| Mida tahad | Käsk |
|---|---|
| kes on maksnud, kes mitte | `status` |
| palju lapse kohta küsida | `propose --item "Teater=35/laps" --item "Buss=180/klass" --round 5 --id teater --label "Teater" --due 2026-11-01 --add` |
| kogumiskiri vanematele | `announce teater` (mustand kausta `drafts/`) |
| meeldetuletused võlgnikele | `remind` (üks mustand pere kohta, mitte kunagi ei saadeta ise) |
| pärast saatmist märgi ära | `mark-reminded 07 12 --channel email` |
| keegi maksis oma taskust | `advance 45 --who Kati --activity "Õpetaja kingitus"`, hiljem `reimburse TXID --who Kati` |
| korraldaja nimekiri vs konto | `check-list nimekiri.txt --since 2026-10-01 --amount 45` |
| aruanne vanematele | `report --out aruanne.md` |

Kõik käsud: `uv run python -m klassikassa --help`.

## 8. AI-assistendiga (valikuline)

Kui kasutad Claude'i, ChatGPT-d või muud assistenti, mis oskab käske käivitada, ava see koodi
kaustas ja ütle: *"Loe AGENT.md ja aita mul hallata klassiraha. Klassi kaust on
~/Dokumendid/klassikassa-andmed/3a-2026."* `AGENT.md` ütleb assistendile, mida ta tohib ja
mida mitte (näiteks ei saada midagi ise ega näita kellegi võlga teistele). Assistent loeb
sinu klassi andmeid, seega vali assistent, mille andmekäsitlus sobib ka teiste perede andmetele.

## 9. Uuendamine

Uus versioon: laadi kood uuesti alla (või tõmba oma koopiasse) ja asenda koodi kaust.
Klassi kaust on eraldi, seega andmed jäävad puutumata.

## 10. Privaatsus lühidalt

- Klassi kaust ei lähe GitHubi, pilve jagatud kausta ega vanemate gruppi.
- Aruanne vanematele näitab summasid, mitte võlgnike nimesid.
- Ühine maksete tabel ainult siis, kui klass on sellega kirjalikult nõustunud.
- Kui annad rolli üle, anna kaust üle turvaliselt ja kustuta oma koopia kontaktidest.

Täpsemalt: [PRIVACY.md](PRIVACY.md).

## Kui midagi ei tööta

| Viga | Põhjus |
|---|---|
| `No config.toml in ...` | `--dir` või `KLASSIKASSA_DIR` ei osuta klassi kaustale |
| `no recognisable header row` | CSV-l ei ole veergu kuupäeva ja summaga; proovi XML (camt.053) vormingut |
| `... incoming payments are still unmatched` | enne meeldetuletusi tuleb `review` läbi teha: tundmatu makse võib olla just selle pere oma |
| makse ei seostu lapsega | kontrolli, et `kid_name` oleks kirjutatud nii, nagu vanemad selgitusse kirjutavad, või lisa maksja `payer_aliases` alla |
