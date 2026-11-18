# Acceptance criteria, 6-step transaction and traceability (Aknur)

## 1. Database: 6 tables

See `ERD_6_tables.png` (source: `ERD_6_tables.mmd`). Tables of the main process:
`Customer`, `Employee`, `Product`, `Purchase`, `Purchase_Item`, **`Points_Log`** (new in the ERD: one row for every change of a balance).
`Points_Log` links to `Customer` (many rows per customer) and optionally to `Purchase` (`purchase_id` is empty for `opening` and `correction` rows).

## 2. The purchase transaction: 6 steps

Checks first (nothing is saved yet): the user is logged in, the customer and products exist, each quantity is 1-100, `payment` is approved/declined,
points to use are a whole number and **not more than 30 % of the bill**. Then `BEGIN` and:

| Step | Action | If it fails |
|---|---|---|
| 1 | Save the **Purchase** (customer, employee, date, total, receipt number) | rollback |
| 2 | Save the item lines in **Purchase_Item** (unit price copied from Product) | rollback |
| 3 | **Reduce stock** of every product | 409 "Not enough stock", rollback |
| 4 | **Spend points**: reduce the balance and write a `spent` row in Points_Log (only if points are used) | 409 "Not enough bonus points", rollback |
| 5 | **Card terminal result** | declined: 402, rollback (points come back) |
| 6 | **Earn points** (3 % of money paid, max 5,000): raise the balance and write an `earned` row in Points_Log | rollback |

After step 6: `COMMIT`. Either all six steps are saved, or none.

## 3. Eight acceptance criteria and where each is shown

Test names: `A-nn` = `test_app.py`, `S-nn` = `test_security.py`, `R-nn` = `test_points_rule.py`.

| # | Acceptance criterion (measurable) | Test number(s) | Demo step |
|---|---|---|---|
| AC-1 | A user with the right password logs in (200); a wrong password gives 401; no login gives 401; the 6th wrong attempt gives 429; an idle session over 30 minutes gives 401. | A-01, A-02, A-03, S-01, S-02 | Log in with a wrong password 6 times and show the lock message. |
| AC-2 | A new employee can register only with the shop code; without the code the request is refused. | S-03, S-04 | Register once without and once with `SHOP-2026`. |
| AC-3 | A customer is found by phone (`+7 XXX XXX XX XX`); a wrong format gives 400, an unknown phone gives 404; an employee does not see the e-mail. | A-04, A-05, A-06, A-07 | Search `+7 700 000 01 01`, then `555-103`, then an unknown phone. |
| AC-4 | A new customer (name, phone, optional e-mail) is created and found by phone; an existing phone is refused with a clear message (409). | A-19, A-20 | Register a customer on the screen, search them, register the same phone again. |
| AC-5 | A purchase is saved in one 6-step transaction: one new Purchase, stock reduced by the quantity, points added by the rule. | A-08, R-01 | Sell 2 coffee beans to customer 1; show the receipt and the new balance. |
| AC-6 | A failed purchase saves nothing: not enough stock (409), declined card (402), wrong quantity (400), not enough points (409); points spent in a declined purchase come back. | A-09, A-10, A-12, R-04, R-05 | Try 100 units, then a declined payment; show that stock and points did not change. |
| AC-7 | Points follow the rule: earn 3 % of the money paid (1 point = 1 cent), spend at most 30 % of a bill (541 points on $18.00 is refused, 540 is accepted), earn at most 5,000 points per purchase. | A-21, A-24, R-01, R-02, R-03, R-06 | Buy with 100 points ($18.00 gives 51 points), then try 541 points. |
| AC-8 | For every customer, the balance equals the sum of that customer's Points_Log rows, and the history shows each earn (+) and spend (-). | A-25, R-07 | Run `check.sql` CHECK 2 (0 rows); open the points history on the screen. |

Run all of it: `python test_app.py`, `python test_security.py`, `python test_points_rule.py`.