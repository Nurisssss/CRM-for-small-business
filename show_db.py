import html, os, sqlite3, sys, webbrowser
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("CRM_DB", os.path.join(BASE, "crm.db"))
if not os.path.exists(DB):
    sys.exit("crm.db not found. Start the program once with:  python app.py   (it creates crm.db), then run this again.")
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)          # read-only: cannot change anything
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]

def cell(table, col, v):
    if col == "password_hash" and v: return str(v)[:14] + "... (hidden)"      # never show full hashes
    return "" if v is None else str(v)

def data(t):
    cur = db.execute(f"SELECT * FROM {t}")
    cols = [d[0] for d in cur.description]
    rows = [[cell(t, c, v) for c, v in zip(cols, r)] for r in cur.fetchall()]
    fks = [f"{r[3]} -> {r[2]}.{r[4]}" for r in db.execute(f"PRAGMA foreign_key_list({t})")]
    return cols, rows, fks

if "--html" in sys.argv:
    out = ["<!DOCTYPE html><meta charset='utf-8'><title>CRM database</title><style>body{font-family:Arial;max-width:1000px;margin:24px auto;padding:0 16px}",
           "table{border-collapse:collapse;margin:8px 0 22px}th,td{border:1px solid #333;padding:5px 9px;text-align:left}small{color:#555}</style>",
           "<h1>CRM for Small Business - database crm.db</h1><small>Read-only view. Tables: " + ", ".join(tables) + "</small>"]
    for t in tables:
        cols, rows, fks = data(t)
        out.append(f"<h2>{html.escape(t)} ({len(rows)} rows)</h2>")
        if fks: out.append("<small>Foreign keys: " + html.escape("; ".join(fks)) + "</small>")
        out.append("<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr>" + "".join("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in r) + "</tr>" for r in rows) + "</table>")
    path = os.path.join(BASE, "db_view.html"); open(path, "w", encoding="utf-8").write("\n".join(out)); print("Created", path); webbrowser.open("file://" + path)
else:
    for t in tables:
        cols, rows, fks = data(t)
        print(f"\n=== {t} ({len(rows)} rows) ===" + (f"   foreign keys: {'; '.join(fks)}" if fks else ""))
        w = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
        print(" | ".join(c.ljust(w[i]) for i, c in enumerate(cols))); print("-+-".join("-" * x for x in w))
        for r in rows: print(" | ".join(v.ljust(w[i]) for i, v in enumerate(r)))
