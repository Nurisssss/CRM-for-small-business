"""Backup and restore for crm.db (Inkar).  Only the Python standard library is used.

  python backup_db.py backup                 copy crm.db to backups/crm_YYYY-MM-DD_HH-MM-SS.db
  python backup_db.py list                   show all backup files (newest last)
  python backup_db.py restore                bring back the NEWEST backup
  python backup_db.py restore FILE           bring back one chosen backup (name or path)
  python backup_db.py delete-customer PHONE  DEMO ONLY: delete one customer, to show that restore brings it back

Why it is safe:
 - backup uses SQLite's own backup function, so the copy is consistent even while app.py is running;
 - the backup is checked (PRAGMA integrity_check) before it is accepted;
 - before a restore, the CURRENT database is saved as backups/crm_before_restore_<date>.db, so a restore can be undone.
Use CRM_DB=path to work with another database file (same variable as app.py)."""
import glob, os, sqlite3, sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB", os.path.join(BASE, "crm.db"))
BACKUP_DIR = os.environ.get("CRM_BACKUP_DIR", os.path.join(BASE, "backups"))

def stamp(): return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def copy_db(src, dst):
    """Consistent copy of a SQLite database (works while another program is using it)."""
    s = sqlite3.connect(src, timeout=10); d = sqlite3.connect(dst, timeout=10)
    try: s.backup(d)
    finally: d.close(); s.close()

def is_good(path):
    """True if the file is a healthy SQLite database that contains the CRM tables."""
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok": return False
            return db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('Customer','Employee','Purchase')").fetchone()[0] == 3
        finally: db.close()
    except sqlite3.Error: return False

def counts(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try: return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("Customer", "Purchase", "Employee")}
    finally: db.close()

def backups():
    """Regular backups only (the 'before_restore' safety copies are listed too, but never picked as 'newest')."""
    return sorted(glob.glob(os.path.join(BACKUP_DIR, "crm_*.db")))

def unique_path(name):
    p = os.path.join(BACKUP_DIR, name + ".db"); n = 2
    while os.path.exists(p): p = os.path.join(BACKUP_DIR, f"{name}_{n}.db"); n += 1
    return p

def backup():
    if not os.path.exists(DB_PATH): sys.exit(f"ERROR: {DB_PATH} not found. Start app.py once so it creates crm.db.")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = unique_path("crm_" + stamp())
    copy_db(DB_PATH, out)
    if not is_good(out):
        os.remove(out); sys.exit("ERROR: the backup failed the integrity check and was deleted. Nothing was saved.")
    c = counts(out)
    print(f"Backup created: {os.path.relpath(out)}  ({os.path.getsize(out)} bytes; {c['Customer']} customers, {c['Purchase']} purchases)")

def list_backups():
    files = backups()
    if not files: print("No backups yet. Run:  python backup_db.py backup"); return
    for f in files: print(f"{os.path.basename(f)}  {os.path.getsize(f):>8} bytes")

def pick(arg):
    if arg is None:
        regular = [f for f in backups() if "before_restore" not in os.path.basename(f)]
        if not regular: sys.exit("ERROR: no backup found. Run:  python backup_db.py backup")
        return regular[-1]
    for cand in (arg, os.path.join(BACKUP_DIR, arg)):
        if os.path.isfile(cand): return cand
    sys.exit(f"ERROR: backup file '{arg}' not found. See the list with:  python backup_db.py list")

def restore(arg, yes):
    src = pick(arg)
    if not is_good(src): sys.exit(f"ERROR: {src} is not a healthy CRM database. Restore cancelled, crm.db was not touched.")
    c = counts(src)
    print(f"Restoring from {os.path.basename(src)}  ({c['Customer']} customers, {c['Purchase']} purchases)")
    print("This replaces the current data in crm.db with the data in the backup.")
    if not yes and input("Type YES to continue: ").strip() != "YES": sys.exit("Cancelled. Nothing was changed.")
    if os.path.exists(DB_PATH):                      # safety copy of the current state, so the restore can be undone
        os.makedirs(BACKUP_DIR, exist_ok=True)
        safe = unique_path("crm_before_restore_" + stamp()); copy_db(DB_PATH, safe)
        print("Current database saved first as:", os.path.relpath(safe))
    copy_db(src, DB_PATH)                            # backup -> crm.db (SQLite's own function: safe even if app.py is open)
    if not is_good(DB_PATH): sys.exit("ERROR: crm.db failed the integrity check after restore. Use the before_restore file.")
    after = counts(DB_PATH)
    print(f"Restore done. crm.db now has {after['Customer']} customers and {after['Purchase']} purchases.")

def delete_customer(phone):
    """DEMO helper: deletes one customer that has no purchases/notes (the database rules protect the others)."""
    db = sqlite3.connect(DB_PATH, isolation_level=None); db.execute("PRAGMA foreign_keys = ON")
    try:
        row = db.execute("SELECT customer_id, full_name FROM Customer WHERE phone=?", (phone,)).fetchone()
        if not row: sys.exit(f"ERROR: no customer with phone {phone}")
        try:
            db.execute("BEGIN")
            db.execute("DELETE FROM Points_Log WHERE customer_id=?", (row[0],))
            db.execute("DELETE FROM Customer WHERE customer_id=?", (row[0],))
            db.execute("COMMIT")
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")
            sys.exit(f"ERROR: {row[1]} has purchases or notes, so the database refuses to delete them. Pick a customer without purchases (for example one you just registered).")
        print(f"Deleted customer: {row[1]} ({phone})")
    finally: db.close()

if __name__ == "__main__":
    a = sys.argv[1:]
    yes = "--yes" in a; a = [x for x in a if x != "--yes"]
    cmd = a[0] if a else ""
    if cmd == "backup": backup()
    elif cmd == "list": list_backups()
    elif cmd == "restore": restore(a[1] if len(a) > 1 else None, yes)
    elif cmd == "delete-customer" and len(a) > 1: delete_customer(" ".join(a[1:]))
    else: print(__doc__)