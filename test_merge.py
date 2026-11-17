"""test_merge.py  (Inkar) - tests for merge_customers.sql. Only the Python standard library is used.
Run:  python test_merge.py           (to save the output:  python test_merge.py > merge_results.txt 2>&1)
Every test builds a NEW temporary database from schema.sql + data.sql, so crm.db is never touched.
First it prints the demo (customer 4 and duplicate 5 BEFORE and AFTER the merge), then the 8 tests."""
import os, re, sqlite3, tempfile, unittest

BASE = os.path.dirname(os.path.abspath(__file__))
def read(name):
    with open(os.path.join(BASE, name), encoding="utf-8") as f: return f.read()

def new_db():
    path = os.path.join(tempfile.mkdtemp(), "merge_test.db")
    db = sqlite3.connect(path, isolation_level=None)          # the SQL file controls BEGIN / COMMIT itself
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(read("schema.sql")); db.executescript(read("data.sql"))
    # like app.py at start: every current balance becomes an 'opening' row of the points ledger
    db.execute("""INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at)
                  SELECT customer_id, NULL, loyalty_points, 'opening', '2026-11-01 00:00' FROM Customer WHERE loyalty_points > 0""")
    return db

def run_merge(db, source, target, manager=2):
    sql = read("merge_customers.sql")
    sql = re.sub(r"SELECT \d+ AS source_id", f"SELECT {source} AS source_id", sql)
    sql = re.sub(r"\d+ AS target_id", f"{target} AS target_id", sql)
    sql = re.sub(r"\d+ AS manager_id", f"{manager} AS manager_id", sql)
    try:
        db.executescript(sql)
    except sqlite3.DatabaseError:
        if db.in_transaction: db.execute("ROLLBACK")          # undo everything, like the app does
        raise

def snapshot(db):
    """Everything the merge may change, to prove that a refused merge changes nothing."""
    return [db.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("Customer", "Purchase", "Customer_Note", "Points_Log")]

CHECK1 = re.search(r"-- CHECK 1.*?\n(SELECT.*?);", read("check.sql"), re.S).group(1)
CHECK2 = re.search(r"-- CHECK 2.*?\n(SELECT.*?);", read("check.sql"), re.S).group(1)

def show(db, title):
    print(f"\n--- {title} ---")
    for r in db.execute("SELECT customer_id, full_name, phone, email, loyalty_points, last_updated FROM Customer WHERE customer_id IN (4,5)"):
        print("Customer  ", tuple(r))
    for r in db.execute("SELECT purchase_id, customer_id, purchase_date, total_amount FROM Purchase WHERE customer_id IN (4,5) ORDER BY purchase_id"):
        print("Purchase  ", tuple(r))
    for r in db.execute("SELECT customer_id, note_text FROM Customer_Note WHERE customer_id IN (4,5)"):
        print("Note      ", tuple(r))


class MergeTests(unittest.TestCase):
    def setUp(self): self.db = new_db()
    def tearDown(self): self.db.close()

    def test_01_duplicate_is_deleted(self):
        run_merge(self.db, 5, 4)
        self.assertIsNone(self.db.execute("SELECT 1 FROM Customer WHERE customer_id=5").fetchone())

    def test_02_kept_profile_gets_the_new_phone(self):
        run_merge(self.db, 5, 4)
        self.assertEqual(self.db.execute("SELECT customer_id FROM Customer WHERE phone='+7 701 555 04 04'").fetchone()[0], 4)
        self.assertIsNone(self.db.execute("SELECT 1 FROM Customer WHERE phone='+7 700 000 01 04'").fetchone())

    def test_03_points_are_added(self):
        run_merge(self.db, 5, 4)                                   # 18 + 6
        self.assertEqual(self.db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=4").fetchone()[0], 24)

    def test_04_all_purchases_and_notes_move(self):
        run_merge(self.db, 5, 4)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM Purchase WHERE customer_id=4").fetchone()[0], 3)   # 4, 6 and 9
        for t in ("Purchase", "Customer_Note", "Points_Log"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {t} WHERE customer_id=5").fetchone()[0], 0, t)
        self.assertIn("Merged duplicate profile #5", self.db.execute("SELECT group_concat(note_text) FROM Customer_Note WHERE customer_id=4").fetchone()[0])

    def test_05_data_checks_still_pass(self):
        before = self.db.execute(CHECK1).fetchall()
        run_merge(self.db, 5, 4)
        self.assertEqual(self.db.execute(CHECK1).fetchall(), before)   # totals are not changed by the merge
        self.assertEqual(self.db.execute(CHECK2).fetchall(), [])       # balance = sum of the points ledger
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_06_merge_into_itself_refused(self):
        before = snapshot(self.db)
        with self.assertRaises(sqlite3.IntegrityError): run_merge(self.db, 4, 4)
        self.assertEqual(snapshot(self.db), before)

    def test_07_unknown_customer_refused(self):
        before = snapshot(self.db)
        with self.assertRaises(sqlite3.IntegrityError): run_merge(self.db, 99, 4)
        self.assertEqual(snapshot(self.db), before)

    def test_08_employee_cannot_merge(self):
        before = snapshot(self.db)
        with self.assertRaises(sqlite3.IntegrityError): run_merge(self.db, 5, 4, manager=1)   # employee 1 is not a Manager
        self.assertEqual(snapshot(self.db), before)


if __name__ == "__main__":
    demo = new_db(); show(demo, "BEFORE the merge"); run_merge(demo, 5, 4); show(demo, "AFTER the merge (5 merged into 4)"); demo.close()
    print()
    unittest.main(verbosity=2)
