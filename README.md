🇹🇭 ภาษาไทย: [README.th.md](README.th.md)

# bladeball-ledger

A bookkeeping system for my **Blade Ball (Roblox)** item shop, which I've run as a real business for 2 years.
Collect data → calculate true cost → analyze with SQL → make real decisions.

> **Status:** Data collection started on 15 Sep 2026 · for the 2 years before that, I never recorded anything.
> **So far (15 Sep – 17 Nov 2026):** 461 orders · 617 items · THB 131,726 in revenue · 134 stock purchases

---

## The Problem

The shop sells in-game items to Thai customers through 2 Facebook groups.
Before this project there was **no data at all**. Every number was a guess.

The main question I couldn't answer:

> **What causes the days with no revenue?**

There are 4 possible causes, and each needs a completely different fix:

| Cause | Fix |
|---|---|
| Shop wasn't open | Fix my own consistency |
| Open, but no one messaged | Expand customer channels |
| People messaged, but I couldn't close the sale | Fix price / stock / how I reply |
| Sold but forgot to record it | A data-quality problem, not a business problem |

If I only record "sales", I can't tell these 4 apart, because they all look the same: *no rows*.
That's why the system has a `day_log` table that records **every day**, not just the days with sales.

---

## The Hardest Problem: Cost Isn't the Number You Paid

Items in the game are bought with **Tokens**, not baht, and Tokens are bought from traders at a **non-fixed rate**.

```
true cost (THB) = item's Token price ÷ rate at which the Tokens were acquired
```

The same 192-Token item can have a true cost that differs by nearly 2x, depending on where the Tokens came from:

| Source | Rate | Cost of 192 Tokens |
|---|---|---|
| Buy Tokens from a trader in the group | 10 – 11.1 | 17.3 – 19.2 THB |
| **Take a bulk lot ("เหมา" / bundle) and resell it piece by piece** | **17 – 25** | **7.7 – 11.3 THB** |

A "bundle" (เหมา) is when someone posts a whole set of items for one price, where the set's combined RAP is higher than what the normal rate would give.
A real example from the group: a **130 THB** bundle containing 7 items. For just the 5 visible items,
the combined RAP is **2,297** → a rate of **17.7 Tokens/THB, 1.6x better than the trader rate**.

### But the two routes can't be compared directly

| | Buy Tokens | Take a bundle |
|---|---|---|
| What you get for your money | **Tokens immediately** | **Items**, not Tokens |
| Usable right away? | Yes | **No. You must list them at a booth before the Tokens reach you** |
| When you learn the rate | At payment | After everything is resold |
| Risk | None | Unsold items = money stuck |

### 1% booth fee

When listing an item at the booth, the game deducts a fee. Measured in-game at 3 points:

| Listed at | Received | Formula `floor(price × 0.99)` |
|---|---|---|
| 17 | 16 | 16 ✓ |
| 20 | 19 | 19 ✓ |
| 40,000 | 39,600 | 39,600 ✓ |

All three cases match **1%, rounded down**, exactly → listing at exactly RAP always returns less than RAP.
You need to list about 1.1% or more above RAP (RAP 670 → list at 677 to get 670 back).

**Booth pricing is not meant to make a profit.** It only needs to avoid a loss against RAP,
because the profit was already locked in when the bundle was bought cheaply. The booth is just a way to convert items into Tokens.

### Three layers of rate

| | How it's calculated | Example: lot of 130 THB, RAP 2,297 |
|---|---|---|
| `rate_on_paper` | RAP ÷ THB | **17.67** ← the number you see when you buy |
| `rate_expected` | RAP × 0.99 ÷ THB | **17.49** ← after the booth fee |
| `rate_actual` | Tokens actually received ÷ THB | **13.85** if only 79% sold |

The gap between these 3 layers is the price of the risk taken in exchange for a better-looking rate,
and it's a question that can't be answered at all without collecting data.

### Two layers of cost

Because bundles make per-item cost only an estimate, the system splits the numbers into 2 layers:

| | How it's calculated | Used for |
|---|---|---|
| **Actual cash profit** | Money customers transferred in − money paid to buy stock | Must match the Krungthai balance exactly; used at month-end close |
| **Per-order profit** | Σ (sale price − Tokens ÷ rate) | Used to analyze which kinds of items are worth it |

The difference between the two layers = **the value still tied up in goods that were bought but not sold**, not a recording error.
The bot reports this difference at month-end so the numbers aren't mistaken for being off.

## The Second Problem: Tens of Thousands of Items, Almost No Repeats

The question *"Which item sells best?"* can't be answered, because `GROUP BY item_name` gives 1 row per group.

The solution is to **not use the item name as an analysis dimension**, and use repeatable attributes instead:

- **Token price band** (`token_band`) ← the most important dimension
- Type (sword / bomb / emote)
- Facebook group the customer came from
- Source of the Tokens

Item names are still stored in the `note` column for reference, but never aggregated.

---

## Hypothesis Tested With Data

The shop's pricing doesn't follow a formula. It follows habit, and the result is an **inverted profit ratio**:

| Cost (Tokens) | Cost (THB) | Sold for | Profit | Markup | Profit/Token |
|---|---|---|---|---|---|
| 100 | 9 | 80 | **71** | 8.8x | **0.71** |
| 500 | 45 | 80 | 35 | 1.8x | 0.07 |
| 2,200 | 200 | 240 | 40 | 1.2x | 0.018 |

*(Rate 11 Tokens/THB · figures from prices regularly sold at)*

**Hypothesis: cheap items earn more profit than expensive ones, both per sale and per Token.**
The shop uses tiered flat prices (e.g. a 55 or 80 THB bundle) while costs vary several-fold.
Expensive items get negotiated down to 1.2–1.5x cost, so profit per sale ends up about the same as cheap items,
but finding the stock takes far longer.

If the data confirmed this, it would mean I should **stop chasing expensive items**. That was the decision this project was meant to answer.
→ See [`analysis/queries.sql`](analysis/queries.sql), Q2

### Result (461 orders, 15 Sep – 17 Nov 2026)

| Token band | Orders | Avg profit / order (THB) | Profit / Token |
|---|---|---|---|
| under 100 | 30 | 64 | 1.30 |
| 100–299 | 83 | 79 | 0.44 |
| 300–599 | 143 | 107 | 0.25 |
| 600–1,499 | 116 | 147 | 0.16 |
| 1,500+ | 84 | 434 | 0.09 |

**Half right, and the wrong half mattered.** Cheap items do earn more *per Token*, but expensive orders earn **6.8x more profit per order** (434 vs 64 THB).
Tokens are not a scarce resource, so profit per Token is the wrong metric; profit per order is the one that pays.
**Decision: keep selling expensive items.** Dropping them would have cut the biggest source of profit.

---

## Architecture

```
Telegram (type a single line)
        │
        ▼
   src/parser.py     converts "55 192 10.5 ดาบ a" (sword, group a) into structured data
        │
        ▼
   src/db.py  ──────► PostgreSQL (Supabase) in production · SQLite locally
        │                 └─ VIEW v_sale / v_day compute cost and profit in one place
        ▼
   analysis/queries.sql → business questions answered with SQL
```

**Why split into 3 files:** `parser.py` and `db.py` know nothing about Telegram.
To add LINE later, I only need to write a new message receiver; everything else is reusable.

**Why profit is a VIEW, not a column:** If `profit` were stored as a value and I later corrected `token_rate`
retroactively, the numbers wouldn't match. Always calculating on the fly is safer.

---

## Setup

```bash
pip install -r requirements.txt
```

1. Open Telegram, find **@BotFather** → `/newbot` → pick a name → you get a token
2. Copy `.env.example` to `.env` and paste the token into `BOT_TOKEN`
3. Double-click `run.bat`
4. Message the bot once in Telegram → your `CHAT_ID` appears in the console window → put it in `.env`
5. Close and reopen `run.bat`. Done.

---

## Usage

One line per entry. You can also send multiple lines at once (log everything in one go before bed).

**When stock comes in:** record it once, and the bot remembers the rate and applies it to every sale after that.

```
/ซื้อ 700 63          buy: 63 THB for 700 Tokens → rate 11.1
/เหมา 2297 130 7      bundle: 130 THB for 7 items, total RAP 2,297 → expected rate 17.5
/ตั้ง 670             item with RAP 670: what to list at the booth → list at 677 to receive 670
/ย่อย 1800            resold for 1,800 Tokens actually received → actual rate 13.9
```

(`/ซื้อ` = buy, `/เหมา` = bundle, `/ตั้ง` = set booth price, `/ย่อย` = break down / resell)

**When selling:** just type 2 numbers.

```
55 192
150 565 คละ b x3 +170
80 340 10.5 ดาบ a          you can also give a rate for just this line
เมื่อวาน 55 192 #Dual Hacker Scythe
```

| Part | Meaning |
|---|---|
| 1st number | Price actually sold for (THB) |
| 2nd number | **Tokens actually paid at the booth.** Not "Your Value" (RAP), which is 2-4% lower |
| Other number | Token rate. If omitted, uses the latest rate from `/ซื้อ` or `/เหมา` |
| **`2297/130`** | **Rate as a fraction: paid 130 THB, got total RAP 2,297. The bot does the division** |
| `ดาบ` `ระเบิด` `ท่า` `คละ` | Item type (sword / bomb / emote / mixed) |
| `a` `b` | Facebook group the customer came from |
| `x3` | Number of items in the order |
| `+170` | Price before the discount |
| `เหมา` | Bundle taken in and resold (rate ≥ 13 is tagged automatically) |
| `เมื่อวาน` `d15` | Backdate the entry (`เมื่อวาน` = yesterday, `d15` = the 15th) |
| `#...` | Note, e.g. item name |

**Commands:** `/ซื้อ` `/เหมา` `/ตั้ง` `/ย่อย` `/today` `/yesterday` `/week` `/month` `/band` `/rate 2297 130` `/inq 5` `/close` `/undo` `/help`

### The bot also messages you on its own

- **Every midnight:** a summary of the day that just ended, compared against the daily target (`TARGET_DAY` in `.env`).
  Midnight was chosen because the best selling window is **7 PM–10 PM** (after school), so an earlier summary would be incomplete.
  If there was no revenue at all that day, it asks why, with 4 buttons to tap.
- **Late-night sales after midnight:** prefix the line with `เมื่อวาน` (yesterday) and the sale is logged to the correct date.
- **Every Monday:** a summary of the week that just ended, compared against the weekly target (`TARGET_WEEK` in `.env`).
- **If the bot was off for several days:** it goes back through the last 7 days and asks about the missed days.
- **On the 1st of every month:** the transfer steps, plus a **check that the recorded totals match the bank balance**
  (the Krungthai balance should equal the 1,000 THB float + recorded profit; if they differ by more than 100 THB, something is wrong).

---

## File Structure

```
schema.sql            sale / purchase / day_log tables + VIEWs, with comments explaining the reasoning
src/parser.py         converts short messages into data + validates them
src/db.py             every SQL statement lives here, in one place
src/bot.py            Telegram message handling + scheduled jobs
analysis/queries.sql  11 business questions, each with the SQL that answers it
data/ledger.db        the database (not in git)
tests/smoke.py        one-shot tests, run with: python tests/smoke.py
```

---

## Roadmap

- [x] Collect a full 30 days of data, then answer Q2 with real data (see Result above)
- [x] Migrate SQLite → PostgreSQL (Supabase) and deploy on Render, so the bot runs without my PC on
- [ ] Dashboard + a record of what I decided from the data and how it turned out
- [ ] Add a LINE channel (reusing `parser.py` / `db.py` as-is)
