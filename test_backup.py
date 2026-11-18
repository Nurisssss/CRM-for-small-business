"""Backup/restore tests (Inkar).  Run:  python test_backup.py   (uses a temporary database, never your real crm.db)"""
import os, sqlite3, tempfile, unittest
import backup_db

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        backup_db.DB_PATH = os.path.join(self.tmp, "t.db"); backup_db.BACKUP_DIR = os.path.join(self.tmp, "backups")
        db = sqlite3.connect(backup_db.DB_PATH)
        db.executescript("""CREATE TABLE Customer(customer_id INTEGER PRIMARY KEY, full_name TEXT, phone TEXT);
            CREATE TABLE Employee(employee_id INTEGER PRIMARY KEY); CREATE TABLE Purchase(purchase_id INTEGER PRIMARY KEY);
            CREATE TABLE Points_Log(log_id INTEGER PRIMARY KEY, customer_id INTEGER);
            INSERT INTO Customer VALUES (1,'Test One','+7 700 000 01 01'),(2,'Test Two','+7 700 000 01 02');""")
        db.commit(); db.close()
    def n(self): 
        db = sqlite3.connect(backup_db.DB_PATH); r = db.execute("SELECT COUNT(*) FROM Customer").fetchone()[0]; db.close(); return r

    def test_01_backup_creates_dated_file(self):
        backup_db.backup(); f = backup_db.backups()
        self.assertEqual(len(f), 1); self.assertRegex(os.path.basename(f[0]), r"^crm_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.db$")
    def test_02_two_backups_in_one_second_do_not_overwrite(self):
        backup_db.backup(); backup_db.backup(); self.assertEqual(len(backup_db.backups()), 2)
    def test_03_deleted_customer_comes_back_after_restore(self):
        backup_db.backup(); backup_db.delete_customer("+7 700 000 01 02"); self.assertEqual(self.n(), 1)
        backup_db.restore(None, True); self.assertEqual(self.n(), 2)
    def test_04_restore_saves_current_state_first(self):
        backup_db.backup(); backup_db.delete_customer("+7 700 000 01 02"); backup_db.restore(None, True)
        self.assertTrue(any("before_restore" in x for x in os.listdir(backup_db.BACKUP_DIR)))
    def test_05_broken_backup_is_refused_and_db_untouched(self):
        os.makedirs(backup_db.BACKUP_DIR); bad = os.path.join(backup_db.BACKUP_DIR, "crm_bad.db"); 
        with open(bad, "wb") as fh: fh.write(b"not a database")
        with self.assertRaises(SystemExit): backup_db.restore(bad, True)
        self.assertEqual(self.n(), 2)
    def test_06_restore_without_any_backup_is_refused(self):
        with self.assertRaises(SystemExit): backup_db.restore(None, True)

if __name__ == "__main__": unittest.main(verbosity=2)