-- checks.sql  (Nurislam) - two data checks. Each query must return ZERO rows on good data.
-- Run in DB Browser for SQLite (Execute SQL tab) on crm.db, or on a COPY of it for the "break it" demo.

-- CHECK 1: the saved total of a purchase must equal the sum of its item lines.
SELECT p.purchase_id, p.total_amount, SUM(i.quantity * i.unit_price) AS items_sum
FROM   Purchase p
JOIN   Purchase_Item i ON i.purchase_id = p.purchase_id
GROUP BY p.purchase_id, p.total_amount
HAVING ROUND(p.total_amount, 2) <> ROUND(SUM(i.quantity * i.unit_price), 2);

-- CHECK 2: the points balance of every customer must equal the sum of that customer's rows in the points ledger.
SELECT c.customer_id, c.loyalty_points AS balance, COALESCE(SUM(l.points_change), 0) AS ledger_sum
FROM   Customer c
LEFT JOIN Points_Log l ON l.customer_id = c.customer_id
GROUP BY c.customer_id, c.loyalty_points
HAVING c.loyalty_points <> COALESCE(SUM(l.points_change), 0);

-- BREAK IT ON PURPOSE (only on a copy!), then run the checks again: each must show exactly 1 row.
-- UPDATE Purchase SET total_amount = 99 WHERE purchase_id = 1;     -- check 1 finds purchase 1
-- UPDATE Customer SET loyalty_points = 10 WHERE customer_id = 1;   -- check 2 finds customer 1