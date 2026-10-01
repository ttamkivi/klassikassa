# A school year of class money: what a long-serving treasurer actually does

This page comes from nine years of one treasurer's mail to his class's parents, grade 1
to grade 9, in a school that keeps a class together the whole way through. Everything
here is anonymised: no names, accounts, schools or amounts that identify a family. Where
the tool already does something, the command is named. Where a habit is worth keeping
but the tool cannot do it, it says so.

[ROLES.md](ROLES.md) describes how work splits between the treasurer and a helper. This
page describes the year.

## The rhythm

| When | What he sent | Command |
|---|---|---|
| First meeting of the year | Agree the semester amount with the parents and the class teacher | `propose`, then `--add` |
| Days after the meeting | The collection mail: what it is for, how much, by when, where to pay | `announce <id>` |
| Monthly, from about two weeks after the due date | "N of M families have paid, thank you, the rest please do" | `draft progress` |
| Privately, to the few still missing | One personal line, never in the list | `remind` |
| Teacher announces a trip or event | "The fund covers it, no separate transfer needed" | `draft covered --what ...` |
| Fund runs dry mid-semester | A top-up round with the spend so far itemised | `propose` + `announce` |
| End of the school year | Balance, a teacher's gift, carry the rest into next year, ask for objections | `draft yearend` |
| Start of next year | "We carried over X; after the school's fees, Y is left per child" | `report`, then `propose --from-balance` |

The semester amount moved between 20 and 50 € per child depending on the year and what
the school billed separately. It was always agreed at a meeting first and announced
afterwards, never the other way round.

## The habits that kept trust for nine years

**The payment block never changed.** Every money mail, for nine years, ended in the same
four lines: recipient, account, amount, description with the child's name. Parents
copied it without reading the rest. Keep the template's block as it is.

**Progress is counts, not names.** Early on he once posted the list of children whose
payment had arrived. Within a few years he had moved to "20 children's payments have
arrived, thank you to those who paid, I am waiting for the rest" and wrote privately to
the missing ones ("I'll let you know personally"). That is the tool's default:
`draft progress` prints counts, and `remind` writes one private draft per family.

**Thank the payers in every chase.** No chase went out without "thank you to everyone
who already has". It turns a reminder into a status update.

**Say when no money is needed.** When the teacher announced a ski day or a museum visit,
he replied the same day that the fund covers it. That stops twenty separate transfers
and twenty unmatched payments. Give `draft covered` the cost with `--cost` and it warns
you when the balance does not cover it.

**Net out what was already paid.** When a family had already paid a separate event fee
before a new semester round was announced, he told them to subtract it ("pay 31 instead
of 50"). The tool allocates payments to collections oldest-due-first, so a partial or
earlier payment is already counted; `status` shows what is left.

**Instalments are always allowed.** "If needed, half now and half next month." The
templates keep that line.

**Attendance fairness waits for the next round.** When tickets were bought for 27 of 30
children, he asked who had not gone and settled the difference in the next collection
rather than with individual refunds. Use `[[collection]] overrides` for a lower amount
for specific children in the next round.

**One parent pays, the class shares.** Gifts, flowers and once a large print bill were
paid by one parent and then shared. When that bill was larger than the balance, the
shortfall was split over every child and rounded up to the cent, so the class was never
a cent short. `advance` records it; `draft shortfall` computes and writes the ask;
`reimburse` closes it when the money goes back.

**A double payment is a question, not a refund.** When both parents paid the same
amount, he asked them which account to send the refund to before sending anything.
`draft duplicate --kid ID` writes that question; `refund <txid> <kid>` records the
transfer so the family's paid total goes back down.

**Check before the trip, not after.** The day before a class trip he checked the
account and wrote to the one family whose trip money had not arrived. Run `status` the
day before any event with a fee.

**Close the year in June.** One year he forgot to close the books after a busy end of
school and found three missing payments in September, by which time nobody remembered
the details. `draft yearend` lists, to you only, how many families still owe before you
propose carrying the balance over.

**The leftover moves on, by consent.** At year end: a gift for the teacher from the
balance, and the rest carried into next year. He proposed it, and replies of "fine by
us" came back. Set `opening_balance` in next year's config to the carried amount.

## Two channels, and why

The class had two mailing lists: the school's official one, which includes the class
teacher, and a parents-only one. Gifts and surprises for the teacher were discussed only
on the parents-only list. Money collections went to the official list, because the
teacher needs to know the fund exists and what it covers. Set `parents_list` to
whichever list the class uses for money. Never discuss a gift on a list the teacher reads.

## Payment links

Twice he added a bank-made one-tap payment link under the account details. The tool can
do this two ways:

- `pay_link = "https://..."` on a `[[collection]]`: a link your bank made (for example
  a Swedbank payment link). It goes into `announce` and `draft progress` as it is.
- `payment_links = "payto"` under `[class]`: the tool builds a standard `payto://` link
  (RFC 8905) with the amount and description filled in. In a private reminder it carries
  that family's open amount and their child's name; in a mail to the whole list it
  carries the amount and asks the parent to add the child's name.

A `payto://` link opens a payment only where the payer's bank app and mail client handle
it. It always goes next to the account details, never instead of them. Test it from
your own phone before the parents see it.

## What stays human

Choosing the gift, judging when to stop chasing, and talking to a family that cannot
pay. He did all three in person or one to one, never on the list.
