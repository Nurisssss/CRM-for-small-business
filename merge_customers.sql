-- merge_customers.sql  (Inkar) - merge two profiles of the SAME customer into one.
--
-- Problem (Task 9 problem table: duplicate customers): a customer changes the phone number, the cashier
-- cannot find her by the new number and creates a NEW profile. Now one person has two profiles, and her
-- purchases and loyalty points are split between them.
--
-- What this script does, in ONE transaction (all steps or nothing):
--   1. checks the input (two different existing customers, the person who merges is a Manager)
--   2. moves purchases, notes and the points history from the duplicate (source) to the kept profile (target)
--   3. adds the points of the duplicate to the kept profile
--   4. deletes the duplicate and gives its phone (the NEW number) to the kept profile
--   5. writes a note "merged ..." so everyone can see what happened
--
-- HOW TO RUN: change the three numbers in STEP 0, then run the whole file
--   (DB Browser for SQLite: Execute SQL tab -> Execute all -> Write Changes; or: python test_merge.py).
--   Run it on a COPY of crm.db first. Before running, look at both profiles (query at the end, "LOOK FIRST").
--   If a step fails, nothing is saved: run ROLLBACK; (DB Browser: Revert Changes).

-- STEP 0: who is merged into whom
DROP TABLE IF EXISTS temp.merge_args;
CREATE TEMP TABLE merge_args AS
SELECT 5 AS source_id,      -- the duplicate profile (made with the NEW phone) - will be deleted
       4 AS target_id,      -- the profile that stays (the old one, with the purchase history)
       2 AS manager_id;     -- employee_id of the Manager who does the merge

BEGIN;

-- STEP 1: check the input. If anything is wrong, this INSERT fails and the script stops.
CREATE TEMP TABLE merge_guard (merge_input_is_valid INTEGER CHECK (merge_input_is_valid = 1));
INSERT INTO merge_guard
SELECT a.source_id <> a.target_id
   AND EXISTS (SELECT 1 FROM Customer WHERE customer_id = a.source_id)
   AND EXISTS (SELECT 1 FROM Customer WHERE customer_id = a.target_id)
   AND EXISTS (SELECT 1 FROM Employee WHERE employee_id = a.manager_id AND role = 'Manager')
FROM merge_args a;

-- remember both profiles as they were before the merge
CREATE TEMP TABLE merge_source AS SELECT c.* FROM Customer c JOIN merge_args a ON c.customer_id = a.source_id;
CREATE TEMP TABLE merge_target AS SELECT c.* FROM Customer c JOIN merge_args a ON c.customer_id = a.target_id;

-- STEP 2: move everything that points to the duplicate (foreign keys) to the kept profile
UPDATE Purchase      SET customer_id = (SELECT target_id FROM merge_args) WHERE customer_id = (SELECT source_id FROM merge_args);
UPDATE Customer_Note SET customer_id = (SELECT target_id FROM merge_args) WHERE customer_id = (SELECT source_id FROM merge_args);
UPDATE Points_Log    SET customer_id = (SELECT target_id FROM merge_args) WHERE customer_id = (SELECT source_id FROM merge_args);

-- STEP 3: add the points; keep the old email, take the new one only if the old profile had none
UPDATE Customer
SET loyalty_points = loyalty_points + (SELECT loyalty_points FROM merge_source),
    email          = COALESCE(email, (SELECT email FROM merge_source)),
    last_updated   = date('now', 'localtime')
WHERE customer_id = (SELECT target_id FROM merge_args);

-- STEP 4: delete the duplicate first (phone is UNIQUE), then give its NEW phone to the kept profile
DELETE FROM Customer WHERE customer_id = (SELECT source_id FROM merge_args);
UPDATE Customer SET phone = (SELECT phone FROM merge_source)
WHERE customer_id = (SELECT target_id FROM merge_args);

-- STEP 5: leave a trace of the merge
INSERT INTO Customer_Note (customer_id, employee_id, note_text)
SELECT a.target_id, a.manager_id,
       'Merged duplicate profile #' || s.customer_id || ' into this one. Phone changed from '
       || t.phone || ' to ' || s.phone || '. Points added: ' || s.loyalty_points || '.'
FROM merge_args a, merge_source s, merge_target t;

COMMIT;

DROP TABLE temp.merge_guard; DROP TABLE temp.merge_source; DROP TABLE temp.merge_target;

-- SHOW THE RESULT: the kept profile, and what now belongs to it
SELECT * FROM Customer WHERE customer_id = (SELECT target_id FROM merge_args);
SELECT purchase_id, customer_id, purchase_date, total_amount, payment_status FROM Purchase
WHERE customer_id = (SELECT target_id FROM merge_args) ORDER BY purchase_date;
SELECT * FROM Customer_Note WHERE customer_id = (SELECT target_id FROM merge_args);
-- every count must be 0: nothing points to the deleted duplicate any more
SELECT 'Purchase' AS left_over, COUNT(*) FROM Purchase WHERE customer_id = (SELECT source_id FROM merge_args)
UNION ALL SELECT 'Customer_Note', COUNT(*) FROM Customer_Note WHERE customer_id = (SELECT source_id FROM merge_args)
UNION ALL SELECT 'Points_Log', COUNT(*) FROM Points_Log WHERE customer_id = (SELECT source_id FROM merge_args);

-- LOOK FIRST (run alone, before the merge): are these really the same person?
-- SELECT customer_id, full_name, phone, email, loyalty_points, last_updated FROM Customer WHERE full_name LIKE '%Madina%';
