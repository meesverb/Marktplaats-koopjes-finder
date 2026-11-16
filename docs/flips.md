# Flips — `/flips`

[← README](../README.md) · [alle naslag](README.md)

Elke flip als kaart: fase, klussen, onderdelen en aanbiedingen, foto's, biedingen van kopers, en wat het opleverde. De koppeling met een Google Sheet staat in [SHEETS.md](../SHEETS.md).

## Flips — `/flips` (`flips.py`, `flips_sheets.py`)

`python dashboard.py --serve` also serves **`/flips`**: every flip you own on
one page, bikes, spare parts and the computers/watches you bought off the
dashboards (the rows from Mijn flips, same table `trade`). At the top: what
you earned (realised profit), **net after investments** (earned minus tools),
what is tied up in running flips and what they should make, the investments
pot, and days to sell / profit per hour.

Per flip a card with:

- **stage**: op voorraad → gekocht → opknappen → te koop → verkocht, with how
  many days it has been in that stage;
- **money**: purchase, spent so far, still planned (estimates), expected cost
  price, your **target price** (low–high), a **market check** (median asking
  price of listings in `koopjes.db` with your search words, last 180 days —
  asking prices, not sale prices), expected profit at low and high, highest
  bid, hours and profit per hour;
- **checklist**: parts (estimate → real price = bought → ✓ fitted), jobs
  (✓ done) and trips (full OV fare + *vol / 40% korting / gratis*; the page
  works out what you paid). A part with only an estimate counts as planned
  (grey); once you enter the real price, that counts. Mark a line as
  **gereedschap** to move it to the investments pot;
- **offers** per part (*Aanbiedingen (n)* under the line, table
  `flip_offer`, migration 21): paste a link with the price you saw, plus
  shipping, shop (taken from the link if empty) and a note; cheapest
  (with shipping) first. Tracking codes go (`?utm_…`, `_gl`, `gclid`,
  AliExpress' `spm`/`algo_…`), a long AliExpress link becomes
  `aliexpress.com/item/<number>.html`, and a share link from the AliExpress
  app (`a.aliexpress.com/_…`) is kept as it is. No link is fine if the note
  says where to find it (shop + search term), marked *geen link*.
  **kies deze** sets the line's shop, link and estimate (price + shipping:
  what it costs bought on its own) and its source; **weg** removes an offer.
  The page never fetches a price from a shop: you type it. The line's own
  shop and link can be changed there too;
- **shopping basket** per shop, with a warning below free shipping
  (FuturumShop €49, AliExpress €10: `flips.FREE_SHIPPING_FROM`);
- **specs** and a **draft ad text** built only from what you entered and the
  parts you fitted (you post it yourself), **photos** (before/after, stored
  in `flip_fotos/`, not in git), the **bids** buyers make on your ad (you
  type them over), and the sale.

**Profit.** Spent = purchase + purchase costs + what parts, jobs and trips of
this flip really cost. Expected profit = target − spent − still planned.
After the sale: sale price − sale costs − spent (a part you never bought no
longer counts). Tools and supplies you use for several flips are
**investments**: not in any one flip's profit, but subtracted in *net after
investments*.

**Stock.** Things you own but haven't decided to sell (stage *op voorraad*)
are listed apart with **flippen** (→ te koop) and don't count as running.

**Importing a list.** `python flips.py import flips_import/cube_peloton_pro.json`
reads flips, their checklists and loose investments from a JSON file
(Dutch keys, see that file). Importing twice adds nothing. `python flips.py`
prints the overview. A better offer for lines that are already there — another shop, a
product link, a new estimate — goes in with
`python flips.py bijwerken flips_import/cube_bike24.json`: it finds each line
by its title within the flip, leaves lines you already bought alone, and says
what it couldn't find. A line in that file can also carry `"aanbiedingen"`:
`[{"url", "prijs", "verzending", "winkel", "notitie", "bron", "bekeken"}]`
(`bron`: `gecontroleerd` or `schatting`; the same link at the same price is
not added twice). The price research for the Cube Peloton Pro (02-10-2026:
offers with links per part, three baskets, AliExpress after the €3 import
duty of 1 July 2026, the chainring question) is in
`flips_import/cube_prijsonderzoek.md`; its offers go in with
`python flips.py bijwerken flips_import/cube_aanbiedingen.json`.

Bike and stock flips use `trade.market` = `fietsen`/`spullen`; they don't
appear in Mijn flips of the computer or watch dashboard. Database migration 17
adds the tables `flip`, `trade_stage`, `flip_task`, `flip_bid`, `flip_photo`.

**Google Sheets, both ways.** See `SHEETS.md`: paste `flips_sheets.gs` into
your sheet as an Apps Script web app, put its URL and a secret in
`sheets.json` (not in git). Each round (on opening `/flips`, or the button;
or `python flips_sheets.py`) takes over what you changed in the sheet since
the last round — new rows without an id become new lines, deleted rows are
deleted, and when the page and the sheet both changed the same line the
later change wins and the message says what was overwritten — then rewrites
the tabs Flips, Klussen, Investeringen and Totalen with numbers as numbers,
plus a read-only tab Aanbiedingen (after 02-10-2026: paste `flips_sheets.gs`
again, see `SHEETS.md`).
Build your own formulas and charts on a tab of your own. No new dependency:
it uses `requests`.
