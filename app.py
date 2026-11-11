"""CRM for Small Business - prototype (Week 10).
Only the Python standard library is used. Run:  python app.py   then open http://localhost:8000
Main process: employee logs in -> finds customer by phone -> adds products -> card terminal result
-> purchase saved in ONE transaction (stock and loyalty points updated, or everything rolled back).
"""
import hashlib, json, os, re, secrets, sqlite3
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB", os.path.join(BASE, "crm.db"))
PHONE_RE = re.compile(r"^\+7 \d{3} \d{3} \d{2} \d{2}$")   # Kazakhstan format: +7 XXX XXX XX XX
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")              # login name: small letters, digits, underscore
SESSIONS = {}          # session id -> {"employee_id", "username", "role"}
POINTS_RULE = 1        # 1 loyalty point for every whole currency unit spent (team rule, to be confirmed)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message); self.status, self.message = status, message


# ---------- passwords (never stored in clear text) ----------
def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"

def check_pw(password, stored):
    salt = stored.split("$")[0]
    return secrets.compare_digest(hash_pw(password, salt), stored)


# ---------- database ----------
def connect():
    db = sqlite3.connect(DB_PATH, isolation_level=None)      # we control BEGIN / COMMIT / ROLLBACK ourselves
    db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = sqlite3.Row
    return db

def init_db():
    if os.path.exists(DB_PATH):
        return
    db = connect()
    with open(os.path.join(BASE, "schema.sql")) as f: db.executescript(f.read())
    with open(os.path.join(BASE, "data.sql")) as f: db.executescript(f.read())
    # demo accounts (change these passwords before any real use)
    db.execute("UPDATE Employee SET password_hash=? WHERE username='aruzhan'", (hash_pw("cashier123"),))
    db.execute("UPDATE Employee SET password_hash=? WHERE username='daniyar'", (hash_pw("manager123"),))
    db.close()


# ---------- business functions ----------
def login(data):
    user, pw = str(data.get("username", "")), str(data.get("password", ""))
    db = connect()
    row = db.execute("SELECT * FROM Employee WHERE username=?", (user,)).fetchone()
    db.close()
    if not row or not check_pw(pw, row["password_hash"]):
        raise ApiError(401, "Wrong username or password")
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"employee_id": row["employee_id"], "username": row["username"], "role": row["role"], "name": row["full_name"]}
    return sid, SESSIONS[sid]

# ---------- users: registration, adding users, passwords (Week 11) ----------
def validate_password(pw):
    if not isinstance(pw, str) or len(pw) < 8 or len(pw) > 72:
        raise ApiError(400, "Password must be 8-72 characters")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise ApiError(400, "Password must contain at least one letter and one digit")

def add_user(data, role):
    """Creates an Employee row. Used by public registration (role always Employee) and by a Manager (Employee or Manager)."""
    name = str(data.get("full_name", "")).strip()
    username = str(data.get("username", "")).strip().lower()
    password = data.get("password", "")
    if not (2 <= len(name) <= 80):
        raise ApiError(400, "Full name must be 2-80 characters")
    if not USERNAME_RE.match(username):
        raise ApiError(400, "Username: 3-30 characters, small letters, digits or _")
    validate_password(password)
    db = connect()
    try:
        if db.execute("SELECT 1 FROM Employee WHERE username=?", (username,)).fetchone():
            raise ApiError(409, "This username is already taken")
        cur = db.execute("INSERT INTO Employee (full_name, role, username, password_hash) VALUES (?,?,?,?)",
                         (name, role, username, hash_pw(password)))
        return {"employee_id": cur.lastrowid, "username": username, "full_name": name, "role": role}
    finally:
        db.close()

def register(data):                                   # public: anyone can create an Employee account
    return add_user(data, "Employee")

def create_user(user, data):                          # Manager only: choose the role
    require_manager(user)
    role = data.get("role", "Employee")
    if role not in ("Employee", "Manager"):
        raise ApiError(400, "role must be 'Employee' or 'Manager'")
    return add_user(data, role)

def list_users(user):
    require_manager(user)
    db = connect()
    rows = [dict(r) for r in db.execute("SELECT employee_id, full_name, username, role FROM Employee ORDER BY employee_id")]
    db.close(); return rows                           # password_hash is never sent to the browser

def change_password(user, data):
    old, new = data.get("current_password", ""), data.get("new_password", "")
    validate_password(new)
    db = connect()
    try:
        row = db.execute("SELECT password_hash FROM Employee WHERE employee_id=?", (user["employee_id"],)).fetchone()
        if not row or not check_pw(str(old), row["password_hash"]):
            raise ApiError(403, "Current password is wrong")
        db.execute("UPDATE Employee SET password_hash=? WHERE employee_id=?", (hash_pw(new), user["employee_id"]))
        return {"ok": True}
    finally:
        db.close()


def find_customer(user, phone):
    if not PHONE_RE.match(phone or ""):
        raise ApiError(400, "Phone must look like +7 700 000 01 01")
    db = connect()
    c = db.execute("SELECT * FROM Customer WHERE phone=?", (phone,)).fetchone()
    db.close()
    if not c:
        raise ApiError(404, "Customer not found")
    out = {"customer_id": c["customer_id"], "full_name": c["full_name"], "phone": c["phone"], "loyalty_points": c["loyalty_points"]}
    if user["role"] == "Manager":                       # employees do not see email or last_updated
        out.update(email=c["email"], last_updated=c["last_updated"])
    return out

def list_products():
    db = connect()
    rows = [dict(r) for r in db.execute("SELECT product_id, product_name, price, stock_qty FROM Product ORDER BY product_id")]
    db.close(); return rows

def record_purchase(user, data):
    try:
        customer_id = int(data.get("customer_id"))
        raw = data.get("items")
        pay = data.get("payment")
        if not isinstance(raw, list) or not raw: raise ValueError
        items = {}
        for it in raw:
            pid, qty = int(it["product_id"]), int(it["quantity"])
            if not (1 <= qty <= 100): raise ValueError
            items[pid] = items.get(pid, 0) + qty          # same product twice -> one line
    except (TypeError, ValueError, KeyError):
        raise ApiError(400, "Send customer_id and a list of items with product_id and quantity (1-100)")
    if pay not in ("approved", "declined"):
        raise ApiError(400, "payment must be 'approved' or 'declined'")

    db = connect()
    try:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM Customer WHERE customer_id=?", (customer_id,)).fetchone():
            raise ApiError(404, "Customer not found")
        lines, total = [], Decimal("0")
        for pid, qty in items.items():                    # prices come from the database, never from the browser
            p = db.execute("SELECT product_name, price FROM Product WHERE product_id=?", (pid,)).fetchone()
            if not p: raise ApiError(404, f"Product {pid} not found")
            price = Decimal(str(p["price"])); total += price * qty
            lines.append((pid, qty, price, p["product_name"]))
        ref = "TX" + secrets.token_hex(4).upper()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        # step 1: save Purchase
        cur = db.execute("INSERT INTO Purchase (customer_id, employee_id, purchase_date, total_amount, payment_status, payment_ref) VALUES (?,?,?,?,?,?)",
                         (customer_id, user["employee_id"], now, float(total), "approved", ref))
        pid_new = cur.lastrowid
        # step 2: save the item lines
        for pid, qty, price, _ in lines:
            db.execute("INSERT INTO Purchase_Item VALUES (?,?,?,?)", (pid_new, pid, qty, float(price)))
        # step 3: reduce stock (fails when there is not enough)
        for pid, qty, _, name in lines:
            if db.execute("UPDATE Product SET stock_qty = stock_qty - ? WHERE product_id=? AND stock_qty >= ?", (qty, pid, qty)).rowcount == 0:
                raise ApiError(409, f"Not enough stock for {name}")
        # step 4: payment result from the (simulated) card terminal
        if pay == "declined":
            raise ApiError(402, "Payment declined - nothing was saved")
        # step 5: loyalty points
        earned = int(total) * POINTS_RULE
        db.execute("UPDATE Customer SET loyalty_points = loyalty_points + ?, last_updated = ? WHERE customer_id=?", (earned, now[:10], customer_id))
        db.execute("COMMIT")
        points = db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=?", (customer_id,)).fetchone()[0]
        return {"purchase_id": pid_new, "payment_ref": ref, "total": float(total), "points_earned": earned, "loyalty_points": points,
                "lines": [{"product": n, "quantity": q, "unit_price": float(p)} for _, q, p, n in lines]}
    except Exception:
        db.execute("ROLLBACK")                            # undo steps 1-3 if anything failed
        raise
    finally:
        db.close()

def require_manager(user):
    if user["role"] != "Manager":
        raise ApiError(403, "Only a Manager can open reports")

def report_top(user, month):
    require_manager(user)
    if not MONTH_RE.match(month or ""):
        raise ApiError(400, "month must look like 2026-10")
    y, m = int(month[:4]), int(month[5:])
    start, end = f"{y:04d}-{m:02d}-01", (f"{y+1:04d}-01-01" if m == 12 else f"{y:04d}-{m+1:02d}-01")
    db = connect()
    rows = [dict(r) for r in db.execute(
        """SELECT c.customer_id, c.full_name, c.phone, COUNT(p.purchase_id) AS visits, SUM(p.total_amount) AS total_spent
           FROM Customer c JOIN Purchase p ON p.customer_id = c.customer_id
           WHERE p.payment_status='approved' AND p.purchase_date >= ? AND p.purchase_date < ?
           GROUP BY c.customer_id, c.full_name, c.phone ORDER BY total_spent DESC LIMIT 3""", (start, end))]
    db.close(); return rows

def report_check(user):
    require_manager(user)
    db = connect()
    rows = [dict(r) for r in db.execute(
        """SELECT p.purchase_id, p.total_amount, SUM(i.quantity*i.unit_price) AS items_sum
           FROM Purchase p JOIN Purchase_Item i ON i.purchase_id=p.purchase_id
           GROUP BY p.purchase_id, p.total_amount HAVING ROUND(p.total_amount,2) <> ROUND(SUM(i.quantity*i.unit_price),2)""")]
    db.close(); return {"mismatches": rows}


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, status, payload, extra=None, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def _user(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid" and v in SESSIONS: return SESSIONS[v]
        raise ApiError(401, "Please log in")

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            return data if isinstance(data, dict) else {}
        except (ValueError, json.JSONDecodeError):
            raise ApiError(400, "Bad JSON")

    def _handle(self, method):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if method == "GET" and u.path in ("/", "/index.html"):
                with open(os.path.join(BASE, "index.html"), "rb") as f: page = f.read()
                return self._send(200, page, ctype="text/html; charset=utf-8")
            if method == "POST" and u.path == "/api/login":
                sid, s = login(self._body())
                return self._send(200, {"username": s["username"], "role": s["role"], "name": s["name"]},
                                  {"Set-Cookie": f"sid={sid}; HttpOnly; SameSite=Strict; Path=/"})
            if method == "POST" and u.path == "/api/register":
                return self._send(201, register(self._body()))
            user = self._user()
            if method == "POST" and u.path == "/api/logout":
                for k in [k for k, v in SESSIONS.items() if v is user]: del SESSIONS[k]
                return self._send(200, {"ok": True}, {"Set-Cookie": "sid=; Max-Age=0; Path=/"})
            if method == "GET" and u.path == "/api/me": return self._send(200, user)
            if method == "POST" and u.path == "/api/password": return self._send(200, change_password(user, self._body()))
            if method == "POST" and u.path == "/api/users": return self._send(201, create_user(user, self._body()))
            if method == "GET" and u.path == "/api/users": return self._send(200, list_users(user))
            if method == "GET" and u.path == "/api/customer": return self._send(200, find_customer(user, q.get("phone")))
            if method == "GET" and u.path == "/api/products": return self._send(200, list_products())
            if method == "POST" and u.path == "/api/purchase": return self._send(201, record_purchase(user, self._body()))
            if method == "GET" and u.path == "/api/report/top": return self._send(200, report_top(user, q.get("month")))
            if method == "GET" and u.path == "/api/report/check": return self._send(200, report_check(user))
            raise ApiError(404, "Not found")
        except ApiError as e:
            self._send(e.status, {"error": e.message})
        except Exception as e:                           # never show internal details to the user
            print("Server error:", repr(e)); self._send(500, {"error": "Server error"})

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")


def make_server(port=8000):
    init_db()
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)

if __name__ == "__main__":
    srv = make_server()
    print("CRM prototype running on http://localhost:8000  (Ctrl+C to stop)")
    print("Demo logins: aruzhan / cashier123 (Employee)   daniyar / manager123 (Manager)")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nStopped")