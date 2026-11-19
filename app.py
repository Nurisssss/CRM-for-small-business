"""CRM for Small Business - prototype (Week 13).
Only the Python standard library is used. Run:  python app.py   then open http://localhost:8000
Main process: employee logs in -> finds customer by phone -> adds products (optionally pays part of the bill with bonus points)
-> card terminal result -> purchase saved in ONE transaction (stock, bonus points and the points ledger updated, or everything rolled back).
"""
import hashlib, json, os, re, secrets, sqlite3, threading, time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB", os.path.join(BASE, "crm.db"))
PHONE_RE = re.compile(r"^\+7 \d{3} \d{3} \d{2} \d{2}$")   # Kazakhstan format: +7 XXX XXX XX XX
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")              # login name: small letters, digits, underscore
SESSIONS = {}          # session id -> {"employee_id", "username", "role", "name", "last_seen"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")      # simple e-mail check (optional field)

# ---------- security settings (Week 12) ----------
MAX_FAILED_LOGINS = 5                    # the 5th wrong password locks the login name; the 6th attempt gets 429
LOCK_SECONDS = 15 * 60                   # how long the lock lasts
SESSION_IDLE_SECONDS = 30 * 60           # a session with no request for 30 minutes expires (401)
SHOP_CODE = os.environ.get("CRM_SHOP_CODE", "SHOP-2026")   # needed to register; set your own: CRM_SHOP_CODE=... python app.py
FAILED = {}                              # login name -> {"count": wrong attempts in a row, "locked_until": time}
SEC_LOCK = threading.Lock()              # the server handles requests in threads, so the counters need a lock

def _now():                              # one place for the clock, so the tests can move time forward
    return time.time()

# ---------- loyalty points rules (change the numbers here; everything else uses these constants) ----------
# All money is in US dollars ($). Points are small on purpose: 1 point = 1 cent, so a normal purchase earns a visible number of points.
POINTS_RATE = Decimal("0.03")            # cashback: 3 % of the money PAID IN MONEY comes back as points (not on the part paid with points)
POINT_VALUE = Decimal("0.01")            # 1 point is worth $0.01 when spent (100 points = $1)
MAX_REDEEM_SHARE = Decimal("0.30")       # points may pay at most 30 % of one bill
MAX_EARN_PER_PURCHASE = 5000             # safety cap: one purchase never earns more than 5000 points (= $50)


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

LEDGER_DDL = """CREATE TABLE IF NOT EXISTS Points_Log (
  log_id        INTEGER PRIMARY KEY,
  customer_id   INTEGER      NOT NULL REFERENCES Customer(customer_id),
  purchase_id   INTEGER      REFERENCES Purchase(purchase_id),
  points_change INTEGER      NOT NULL CHECK (points_change <> 0),
  reason        VARCHAR(12)  NOT NULL CHECK (reason IN ('opening','earned','spent','correction')),
  created_at    TIMESTAMP    NOT NULL
)"""

def ensure_points_log():
    """Runs at every start. Creates the Points_Log table if it is missing (old crm.db, or schema.sql without it),
    and if the ledger is empty, turns every current balance into an 'opening' row, so balance = sum of the ledger from day one."""
    db = connect()
    db.execute(LEDGER_DDL)
    if db.execute("SELECT COUNT(*) FROM Points_Log").fetchone()[0] == 0:
        db.execute("INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at) "
                   "SELECT customer_id, NULL, loyalty_points, 'opening', datetime('now') FROM Customer WHERE loyalty_points > 0")
    db.close()

def ensure_client_support():
    """Runs at every start (old crm.db too): adds the login column for client accounts to Customer."""
    db = connect()
    if "password_hash" not in [r["name"] for r in db.execute("PRAGMA table_info(Customer)")]:
        db.execute("ALTER TABLE Customer ADD COLUMN password_hash VARCHAR(255)")
    db.close()

def init_db():
    if not os.path.exists(DB_PATH):
        db = connect()
        with open(os.path.join(BASE, "schema.sql")) as f: db.executescript(f.read())
        with open(os.path.join(BASE, "data.sql")) as f: db.executescript(f.read())
        # demo accounts (change these passwords before any real use)
        if db.execute("UPDATE Employee SET password_hash=? WHERE username='aruzhan'", (hash_pw("cashier123"),)).rowcount == 0:
            db.execute("INSERT INTO Employee (full_name, role, username, password_hash) VALUES ('Aruzhan K.', 'Employee', 'aruzhan', ?)",
                       (hash_pw("cashier123"),))      # data.sql in this copy has no 'aruzhan': create the demo cashier
        db.execute("UPDATE Employee SET password_hash=? WHERE username='daniyar'", (hash_pw("manager123"),))
        db.close()
    ensure_points_log()
    ensure_client_support()


# ---------- business functions ----------
def login(data):
    user, pw = str(data.get("username", "")), str(data.get("password", ""))
    key = user.strip().lower()[:60]
    with SEC_LOCK:                                    # locked? refuse before even looking at the password
        f = FAILED.get(key)
        if f and f["locked_until"]:
            if f["locked_until"] > _now():
                minutes = int((f["locked_until"] - _now()) // 60) + 1
                raise ApiError(429, f"Too many wrong attempts. Try again in {minutes} minute(s)")
            del FAILED[key]                           # the lock is over: start counting again
    db = connect()
    row = db.execute("SELECT * FROM Employee WHERE username=?", (user,)).fetchone()
    db.close()
    if not row or not check_pw(pw, row["password_hash"]):
        with SEC_LOCK:                                # unknown names are counted too, so nobody can tell which names exist
            f = FAILED.setdefault(key, {"count": 0, "locked_until": 0})
            f["count"] += 1
            if f["count"] >= MAX_FAILED_LOGINS:
                f["locked_until"] = _now() + LOCK_SECONDS
        raise ApiError(401, "Wrong username or password")
    with SEC_LOCK:
        FAILED.pop(key, None)                         # a good login clears the counter
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"employee_id": row["employee_id"], "username": row["username"], "role": row["role"],
                     "name": row["full_name"], "last_seen": _now()}
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

def register(data):                                   # public page, but the shop code is required (Manager can also use /api/users)
    code = str(data.get("shop_code", ""))
    if not secrets.compare_digest(code.encode(), SHOP_CODE.encode()):
        raise ApiError(403, "Wrong or missing shop code - ask your manager")
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

def normalize_phone(raw):
    """Accepts +7 700 000 01 01, +77000000101, 87000000101, 7000000101 ... and returns the stored format, or None."""
    s = str(raw or "").strip()
    if PHONE_RE.match(s): return s
    if not re.fullmatch(r"[+\d\s\-()]+", s): return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits[0] in "78": digits = digits[1:]
    elif len(digits) != 10: return None
    return f"+7 {digits[0:3]} {digits[3:6]} {digits[6:8]} {digits[8:10]}"

def create_customer(user, data):
    """Any logged-in employee can register a new loyalty customer (starts with 0 points)."""
    name = str(data.get("full_name") or data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone"))
    email = str(data.get("email") or "").strip()
    if not (2 <= len(name) <= 80):
        raise ApiError(400, "Full name must be 2-80 characters")
    if not phone:
        raise ApiError(400, "Phone must look like +7 700 000 01 01")
    if email and (len(email) > 100 or not EMAIL_RE.match(email)):
        raise ApiError(400, "E-mail is not valid (or leave it empty)")
    db = connect()
    try:
        if db.execute("SELECT 1 FROM Customer WHERE phone=?", (phone,)).fetchone():
            raise ApiError(409, f"A customer with the phone {phone} already exists - find them by phone")
        try:
            db.execute("INSERT INTO Customer (full_name, phone, email, loyalty_points, last_updated) VALUES (?,?,?,0,?)",
                       (name, phone, email or None, datetime.now().strftime("%Y-%m-%d")))
        except sqlite3.IntegrityError:                # two people registered the same phone at the same moment
            raise ApiError(409, f"A customer with the phone {phone} already exists - find them by phone")
    finally:
        db.close()
    return find_customer(user, phone)

# ---------- client accounts: sign up, log in, own page (Week 13) ----------
def _client_session(customer_id, name, phone):
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = {"customer_id": customer_id, "username": phone, "role": "Client", "name": name, "last_seen": _now()}
    return sid, SESSIONS[sid]

def client_register(data):
    """A new client signs up alone: full name, phone, e-mail (required) and a checked password. He is logged in at once.
    A phone that the shop already has in Customer cannot be taken over from the web page (there is no proof that the phone is his)."""
    name = str(data.get("full_name") or "").strip()
    phone = normalize_phone(data.get("phone"))
    email = str(data.get("email") or "").strip()
    password = data.get("password", "")
    if not (2 <= len(name) <= 80): raise ApiError(400, "Full name must be 2-80 characters")
    if not phone: raise ApiError(400, "Phone must look like +7 700 000 01 01")
    if not email or len(email) > 100 or not EMAIL_RE.match(email): raise ApiError(400, "A valid e-mail is required")
    validate_password(password)
    db = connect()
    try:
        c = db.execute("SELECT password_hash FROM Customer WHERE phone=?", (phone,)).fetchone()
        if c and c["password_hash"]:
            raise ApiError(409, "This phone already has an account - please log in")
        if c:
            raise ApiError(409, "This phone is already in the shop's records - ask the cashier to open your account")
        try:
            cid = db.execute("INSERT INTO Customer (full_name, phone, email, loyalty_points, last_updated, password_hash) VALUES (?,?,?,0,?,?)",
                             (name, phone, email, datetime.now().strftime("%Y-%m-%d"), hash_pw(password))).lastrowid
        except sqlite3.IntegrityError:                # the same phone registered at the same moment
            raise ApiError(409, "This phone already has an account - please log in")
    finally:
        db.close()
    return _client_session(cid, name, phone)

def client_login(data):
    phone = normalize_phone(data.get("phone"))
    pw = str(data.get("password", ""))
    key = "client:" + (phone or str(data.get("phone", ""))[:30])
    with SEC_LOCK:                                    # same lock rule as staff: 5 wrong passwords lock for 15 minutes
        f = FAILED.get(key)
        if f and f["locked_until"]:
            if f["locked_until"] > _now():
                raise ApiError(429, f"Too many wrong attempts. Try again in {int((f['locked_until'] - _now()) // 60) + 1} minute(s)")
            del FAILED[key]
    row = None
    if phone:
        db = connect()
        row = db.execute("SELECT customer_id, full_name, password_hash FROM Customer WHERE phone=?", (phone,)).fetchone()
        db.close()
    if not row or not row["password_hash"] or not check_pw(pw, row["password_hash"]):
        with SEC_LOCK:
            f = FAILED.setdefault(key, {"count": 0, "locked_until": 0})
            f["count"] += 1
            if f["count"] >= MAX_FAILED_LOGINS: f["locked_until"] = _now() + LOCK_SECONDS
        raise ApiError(401, "Wrong phone or password")
    with SEC_LOCK: FAILED.pop(key, None)
    return _client_session(row["customer_id"], row["full_name"], phone)

def require_client(user):
    if user["role"] != "Client":
        raise ApiError(403, "Only for client accounts")

def client_me(user):
    require_client(user)
    db = connect()
    c = db.execute("SELECT full_name, phone, email, loyalty_points, last_updated FROM Customer WHERE customer_id=?", (user["customer_id"],)).fetchone()
    db.close()
    if not c: raise ApiError(404, "Customer not found")
    return dict(c)

def client_points(user):
    require_client(user)
    return points_history(user["customer_id"])

def client_change_password(user, data):
    require_client(user)
    old, new = data.get("current_password", ""), data.get("new_password", "")
    validate_password(new)
    db = connect()
    try:
        row = db.execute("SELECT password_hash FROM Customer WHERE customer_id=?", (user["customer_id"],)).fetchone()
        if not row or not row["password_hash"] or not check_pw(str(old), row["password_hash"]):
            raise ApiError(403, "Current password is wrong")
        db.execute("UPDATE Customer SET password_hash=? WHERE customer_id=?", (hash_pw(new), user["customer_id"]))
        return {"ok": True}
    finally:
        db.close()


def list_products():
    db = connect()
    rows = [dict(r) for r in db.execute("SELECT product_id, product_name, price, stock_qty FROM Product ORDER BY product_id")]
    db.close(); return rows

def whole(amount):
    """Cut an amount down to a whole number (no rounding up, so the shop never gives more than the rule says)."""
    return int(Decimal(amount).to_integral_value(rounding=ROUND_DOWN))

def points_rules():
    return {"points_rate": str(POINTS_RATE), "point_value": str(POINT_VALUE),
            "max_redeem_share": str(MAX_REDEEM_SHARE), "max_earn_per_purchase": MAX_EARN_PER_PURCHASE}

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
    raw_pts = data.get("points_to_use", 0)
    if raw_pts is None: raw_pts = 0
    try:
        if isinstance(raw_pts, bool) or not isinstance(raw_pts, (int, str)): raise ValueError
        points_use = int(raw_pts)
        if points_use < 0: raise ValueError
    except ValueError:
        raise ApiError(400, "points_to_use must be a whole number, 0 or more")

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
        max_by_share = whole(total * MAX_REDEEM_SHARE / POINT_VALUE)
        if points_use > max_by_share:                     # rule: points pay at most MAX_REDEEM_SHARE of the bill
            raise ApiError(400, f"Points can pay at most {int(MAX_REDEEM_SHARE * 100)}% of the bill (max {max_by_share} points for this purchase)")
        to_pay = total - POINT_VALUE * points_use         # the part of the bill paid in money
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
        # step 4: spend bonus points (atomic: the UPDATE only works when the customer has enough points)
        if points_use:
            if db.execute("UPDATE Customer SET loyalty_points = loyalty_points - ? WHERE customer_id=? AND loyalty_points >= ?",
                          (points_use, customer_id, points_use)).rowcount == 0:
                raise ApiError(409, "Not enough bonus points")
            db.execute("INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at) VALUES (?,?,?,?,?)",
                       (customer_id, pid_new, -points_use, "spent", now))
        # step 5: payment result from the (simulated) card terminal - on "declined" the rollback also gives the points back
        if pay == "declined":
            raise ApiError(402, "Payment declined - nothing was saved")
        # step 6: earn points on the money actually paid (not on the part paid with points)
        earned = min(MAX_EARN_PER_PURCHASE, whole(to_pay * POINTS_RATE / POINT_VALUE))
        db.execute("UPDATE Customer SET loyalty_points = loyalty_points + ?, last_updated = ? WHERE customer_id=?", (earned, now[:10], customer_id))
        if earned:
            db.execute("INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at) VALUES (?,?,?,?,?)",
                       (customer_id, pid_new, earned, "earned", now))
        db.execute("COMMIT")
        points = db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=?", (customer_id,)).fetchone()[0]
        return {"purchase_id": pid_new, "payment_ref": ref, "total": float(total), "points_used": points_use, "amount_to_pay": float(to_pay),
                "points_earned": earned, "loyalty_points": points,
                "lines": [{"product": n, "quantity": q, "unit_price": float(p)} for _, q, p, n in lines]}
    except Exception:
        db.execute("ROLLBACK")                            # undo every step if anything failed
        raise
    finally:
        db.close()

def points_history(customer_id):
    """Last 10 changes of the points balance of one customer (from the ledger), newest first."""
    try:
        cid = int(customer_id)
    except (TypeError, ValueError):
        raise ApiError(400, "customer_id must be a number")
    db = connect()
    if not db.execute("SELECT 1 FROM Customer WHERE customer_id=?", (cid,)).fetchone():
        db.close(); raise ApiError(404, "Customer not found")
    rows = [dict(r) for r in db.execute("SELECT created_at, points_change, reason, purchase_id FROM Points_Log WHERE customer_id=? ORDER BY log_id DESC LIMIT 10", (cid,))]
    db.close(); return rows

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

def report_checks(user):
    require_manager(user)
    db = connect()
    totals_mismatches = [dict(r) for r in db.execute(
        """SELECT p.purchase_id, p.total_amount, SUM(i.quantity*i.unit_price) AS items_sum
           FROM Purchase p JOIN Purchase_Item i ON i.purchase_id=p.purchase_id
           GROUP BY p.purchase_id, p.total_amount HAVING ROUND(p.total_amount,2) <> ROUND(SUM(i.quantity*i.unit_price),2)""")]
    points_mismatches = [dict(r) for r in db.execute(
        """SELECT c.customer_id, c.loyalty_points AS balance, COALESCE(SUM(l.points_change), 0) AS ledger_sum
           FROM Customer c LEFT JOIN Points_Log l ON l.customer_id = c.customer_id
           GROUP BY c.customer_id, c.loyalty_points
           HAVING c.loyalty_points <> COALESCE(SUM(l.points_change), 0)""")]
    db.close()
    return {"totals_mismatches": totals_mismatches, "points_mismatches": points_mismatches}

def add_customer_note(user, data):
    try:
        cid = int(data.get("customer_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "customer_id must be a number")
    note = str(data.get("note") or data.get("note_text") or "").strip()
    if not (1 <= len(note) <= 255):
        raise ApiError(400, "Note must be 1-255 characters")
    db = connect()
    try:
        if not db.execute("SELECT 1 FROM Customer WHERE customer_id=?", (cid,)).fetchone():
            raise ApiError(404, "Customer not found")
        cur = db.execute("INSERT INTO Customer_Note (customer_id, employee_id, note_text) VALUES (?,?,?)",
                         (cid, user["employee_id"], note))
        return {"note_id": cur.lastrowid, "customer_id": cid, "note_text": note}
    finally:
        db.close()

def list_customer_notes(customer_id):
    try:
        cid = int(customer_id)
    except (TypeError, ValueError):
        raise ApiError(400, "customer_id must be a number")
    db = connect()
    if not db.execute("SELECT 1 FROM Customer WHERE customer_id=?", (cid,)).fetchone():
        db.close(); raise ApiError(404, "Customer not found")
    rows = [dict(r) for r in db.execute(
        "SELECT note_id, customer_id, employee_id, note_text, created_at FROM Customer_Note WHERE customer_id=? ORDER BY note_id DESC",
        (cid,))]
    db.close(); return rows

def merge_customers(user, data):
    require_manager(user)
    try:
        src_id = int(data.get("source_id"))
        tgt_id = int(data.get("target_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "source_id and target_id must be numbers")
    if src_id == tgt_id:
        raise ApiError(400, "Cannot merge a customer with themselves")
    db = connect()
    try:
        db.execute("BEGIN")
        src = db.execute("SELECT * FROM Customer WHERE customer_id=?", (src_id,)).fetchone()
        tgt = db.execute("SELECT * FROM Customer WHERE customer_id=?", (tgt_id,)).fetchone()
        if not src or not tgt:
            raise ApiError(404, "Customer not found")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Move purchases, notes, and points ledger rows to target_id
        db.execute("UPDATE Purchase SET customer_id=? WHERE customer_id=?", (tgt_id, src_id))
        db.execute("UPDATE Customer_Note SET customer_id=? WHERE customer_id=?", (tgt_id, src_id))
        db.execute("UPDATE Points_Log SET customer_id=? WHERE customer_id=?", (tgt_id, src_id))
        # Combine points and keep newer phone/email
        new_phone = src["phone"]
        new_email = tgt["email"] or src["email"]
        new_points = tgt["loyalty_points"] + src["loyalty_points"]
        db.execute("DELETE FROM Customer WHERE customer_id=?", (src_id,))
        db.execute("UPDATE Customer SET phone=?, email=?, loyalty_points=?, last_updated=? WHERE customer_id=?",
                   (new_phone, new_email, new_points, now[:10], tgt_id))
        db.execute("COMMIT")
        updated = dict(db.execute("SELECT * FROM Customer WHERE customer_id=?", (tgt_id,)).fetchone())
        updated.pop("password_hash", None)                # never send a password hash to the browser
        return {"ok": True, "customer": updated}
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


# ---------- HTTP ----------
CLIENT_ROUTES = {("POST", "/api/logout"), ("GET", "/api/me"), ("GET", "/api/client/me"), ("GET", "/api/client/points"), ("POST", "/api/client/password")}

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
            if k == "sid" and v in SESSIONS:
                s = SESSIONS[v]
                if _now() - s["last_seen"] > SESSION_IDLE_SECONDS:      # idle too long: the session is deleted
                    SESSIONS.pop(v, None)
                    raise ApiError(401, "Session expired - please log in again")
                s["last_seen"] = _now()                                  # every request moves the 30 minutes forward
                return s
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
            if method == "GET" and u.path == "/style.css":
                with open(os.path.join(BASE, "style.css"), "rb") as f: css = f.read()
                return self._send(200, css, ctype="text/css; charset=utf-8")
            if method == "POST" and u.path == "/api/login":
                sid, s = login(self._body())
                return self._send(200, {"username": s["username"], "role": s["role"], "name": s["name"]},
                                  {"Set-Cookie": f"sid={sid}; HttpOnly; SameSite=Strict; Path=/"})
            if method == "POST" and u.path == "/api/register":
                return self._send(201, register(self._body()))
            if method == "POST" and u.path in ("/api/client/register", "/api/client/login"):
                sid, s = (client_register if u.path.endswith("register") else client_login)(self._body())
                return self._send(201 if u.path.endswith("register") else 200, {"username": s["username"], "role": s["role"], "name": s["name"]},
                                  {"Set-Cookie": f"sid={sid}; HttpOnly; SameSite=Strict; Path=/"})
            user = self._user()
            if user["role"] == "Client":                  # a client sees only his own account: every staff route is closed
                if (method, u.path) not in CLIENT_ROUTES: raise ApiError(403, "Clients can only open their own account")
                if (method, u.path) == ("GET", "/api/client/me"): return self._send(200, client_me(user))
                if (method, u.path) == ("GET", "/api/client/points"): return self._send(200, client_points(user))
                if (method, u.path) == ("POST", "/api/client/password"): return self._send(200, client_change_password(user, self._body()))
            if method == "POST" and u.path == "/api/logout":
                for k in [k for k, v in SESSIONS.items() if v is user]: del SESSIONS[k]
                return self._send(200, {"ok": True}, {"Set-Cookie": "sid=; Max-Age=0; Path=/"})
            if method == "GET" and u.path == "/api/me": return self._send(200, {k: v for k, v in user.items() if k != "last_seen"})
            if method == "POST" and u.path == "/api/password": return self._send(200, change_password(user, self._body()))
            if method == "POST" and u.path == "/api/users": return self._send(201, create_user(user, self._body()))
            if method == "GET" and u.path == "/api/users": return self._send(200, list_users(user))
            if method == "GET" and u.path == "/api/customer": return self._send(200, find_customer(user, q.get("phone")))
            if method == "POST" and u.path in ("/api/customer", "/api/customer/register"): return self._send(201, create_customer(user, self._body()))
            if method == "GET" and u.path == "/api/products": return self._send(200, list_products())
            if method == "GET" and u.path == "/api/rules": return self._send(200, points_rules())
            if method == "GET" and u.path == "/api/points-log": return self._send(200, points_history(q.get("customer_id")))
            if method == "POST" and u.path == "/api/purchase": return self._send(201, record_purchase(user, self._body()))
            if method == "GET" and u.path == "/api/report/top": return self._send(200, report_top(user, q.get("month")))
            if method == "GET" and u.path == "/api/report/check": return self._send(200, report_check(user))
            if method == "GET" and u.path == "/api/report/checks": return self._send(200, report_checks(user))
            if method == "GET" and u.path == "/api/customer/notes": return self._send(200, list_customer_notes(q.get("customer_id")))
            if method == "POST" and u.path == "/api/customer/notes": return self._send(201, add_customer_note(user, self._body()))
            if method == "POST" and u.path == "/api/admin/merge-customers": return self._send(200, merge_customers(user, self._body()))
            raise ApiError(404, "Not found")
        except ApiError as e:
            self._send(e.status, {"error": e.message})
        except Exception as e:                           # never show internal details to the user
            print("Server error:", repr(e)); self._send(500, {"error": "Server error"})

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")

class ThreadedServer(ThreadingHTTPServer):
    request_queue_size = 128

def make_server(port=8000):
    init_db()
    return ThreadedServer(("127.0.0.1", port), Handler)

if __name__ == "__main__":
    srv = make_server()
    print("CRM prototype running on http://localhost:8000  (Ctrl+C to stop)")
    print(f"Shop code for registering new employees: {SHOP_CODE}  (change it: CRM_SHOP_CODE=yourcode python app.py)")
    print("Demo logins: aruzhan / cashier123 (Employee)   daniyar / manager123 (Manager)")
    print("Clients: sign up on the page (Client log in / sign up)")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nStopped")