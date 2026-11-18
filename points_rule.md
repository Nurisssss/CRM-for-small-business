# Loyalty points rule (one page)

**Project:** CRM for Small Business  **Owner:** Aknur  **Status:** proposed, to be confirmed by the team (see the box at the end)

## 1. The rule in four numbers

| Item | Value | Meaning |
|---|---|---|
| Earn rate | **3 %** | 3 % of the money the customer actually paid comes back as points |
| Point value | **1 point = 1 cent ($0.01)** | 100 points = $1 |
| Spend limit | **30 %** of one bill | Points may pay at most 30 % of a single purchase |
| Earn cap | **5,000 points** (= $50) | One purchase never earns more than 5,000 points |

All money is in US dollars. The numbers live in one place, the constants at the top of `app.py`
(`POINTS_RATE`, `POINT_VALUE`, `MAX_REDEEM_SHARE`, `MAX_EARN_PER_PURCHASE`), and the screen reads them from `GET /api/rules`.

## 2. How a purchase is calculated

1. `total` = sum of price x quantity (prices come from the database, never from the browser).
2. `max points to spend` = `total x 30 % / $0.01`, cut down to a whole number.
3. `to pay in money` = `total - points used x $0.01`.
4. `points earned` = smaller of **5,000** and `to pay in money x 3 % / $0.01`, cut down to a whole number.

Points are earned **only on the part paid in money**, never on the part paid with points.
Cutting down (never rounding up) means the shop never gives more than the rule says.

## 3. Worked examples (coffee beans $18.00)

| Case | Points used | Pays in money | Points earned | Balance change |
|---|---|---|---|---|
| Normal purchase | 0 | $18.00 | 54 | +54 |
| Spend 100 points | 100 | $17.00 | 51 | -100 + 51 = -49 |
| Spend the maximum (30 % of $18.00 = $5.40) | 540 | $12.60 | 37 (37.8 cut down) | -540 + 37 = -503 |
| Try to spend 541 points | 541 | refused (400) | - | none |
| $200,000 order (3 % = 6,000) | 0 | $200,000 | **5,000** (cap) | +5,000 |

## 4. Edge cases

- **Not enough points:** the purchase is refused (409) and nothing is saved.
- **Card declined:** everything is rolled back, so points spent are given back and none are earned.
- **Every change is a row in `Points_Log`:** reasons are `opening`, `earned`, `spent`, `correction`.
  The customer's balance must always equal the sum of that customer's rows (`check.sql`, CHECK 2).
- **Not in this version:** points do not expire; there is no refund or return flow.

## 5. Team confirmation

| Name | Role | Agrees (yes / change needed) | Date |
|---|---|---|---|
| Almas | | | |
| Nurislam | | | |
| Inkar | | | |
| Akbota | | | |
| Aknur | | | |