"""Tests for client accounts (Almas, Week 13): sign up with e-mail, password check, login, the three roles.
Run:  python test_client.py     (the clock is moved by the test, nobody waits 15 minutes)"""
import json, os, tempfile, threading, time, unittest, urllib.request, urllib.error
import app

class Api:
    def __init__(self, base): self.base, self.cookie = base, None
    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Cookie": self.cookie} if self.cookie else {})})
        try: r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: r = e
        if r.headers.get("Set-Cookie") and "sid=" in r.headers["Set-Cookie"]: self.cookie = r.headers["Set-Cookie"].split(";")[0]
        return r.status, json.loads(r.read() or b"{}")

NEW = {"full_name": "Client One", "phone": "+7 701 111 22 33", "email": "client1@example.com", "password": "clientpass1"}

class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "client0.db"); app.SESSIONS.clear()
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self):
        self.clock = [2_000_000.0]; app._now = lambda: self.clock[0]; app.FAILED.clear(); app.SESSIONS.clear()
        ClientTests.n = getattr(ClientTests, "n", 0) + 1
        app.DB_PATH = os.path.join(self.tmp, f"client{ClientTests.n}.db"); app.init_db()          # a fresh database for every test
    def tearDown(self): app._now = time.time

    def signup(self, **over):
        c = Api(self.base); s, j = c.call("POST", "/api/client/register", {**NEW, **over}); return c, s, j

    # --- sign up: e-mail, password check, phone check ---
    def test_01_signup_creates_account_and_logs_in(self):
        c, s, j = self.signup(); self.assertEqual((s, j["role"]), (201, "Client"))
        s, me = c.call("GET", "/api/client/me"); self.assertEqual((s, me["phone"], me["email"], me["loyalty_points"]), (200, NEW["phone"], NEW["email"], 0))
    def test_02_email_required_and_checked(self):
        self.assertEqual(self.signup(email="")[1], 400); self.assertEqual(self.signup(email="not-an-email")[1], 400)
    def test_03_weak_password_refused(self):
        for pw in ("short1", "onlyletters", "12345678"): self.assertEqual(self.signup(password=pw)[1], 400)
    def test_04_bad_phone_and_name_refused(self):
        self.assertEqual(self.signup(phone="555-103")[1], 400); self.assertEqual(self.signup(full_name="A")[1], 400)
    def test_05_phone_written_in_other_style_is_accepted(self):
        _, s, j = self.signup(phone="87011112233"); self.assertEqual(s, 201); self.assertEqual(Api(self.base).call("POST", "/api/client/login", {"phone": NEW["phone"], "password": NEW["password"]})[0], 200)
    def test_06_failed_signup_saves_nothing(self):
        self.signup(password="weak"); db = app.connect(); n = db.execute("SELECT COUNT(*) FROM Customer WHERE phone=?", (NEW["phone"],)).fetchone()[0]; db.close(); self.assertEqual(n, 0)
    def test_07_duplicate_account_refused(self):
        self.signup(); self.assertEqual(self.signup()[1], 409)

    # --- phone already known by the shop: no takeover from the web page ---
    def test_08_shop_customer_cannot_be_taken_over(self):
        _, s, j = self.signup(phone="+7 700 000 01 02", password="hackerpass1")            # Dana Serik in data.sql, has points
        self.assertEqual(s, 409); self.assertIn("cashier", j["error"])
        self.assertEqual(Api(self.base).call("POST", "/api/client/login", {"phone": "+7 700 000 01 02", "password": "hackerpass1"})[0], 401)
    def test_09_customer_made_by_employee_is_also_protected(self):
        emp = Api(self.base); emp.call("POST", "/api/login", {"username": "aruzhan", "password": "cashier123"})
        self.assertEqual(emp.call("POST", "/api/customer", {"full_name": "Shop Made", "phone": "+7 702 222 33 44"})[0], 201)
        self.assertEqual(self.signup(phone="+7 702 222 33 44")[1], 409)

    # --- log in, lock, password ---
    def test_10_client_login_ok_and_wrong_password(self):
        self.signup(); c = Api(self.base)
        self.assertEqual(c.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": "wrongpass1"})[0], 401)
        self.assertEqual(c.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": NEW["password"]})[0], 200)
    def test_11_client_login_locked_after_5_wrong_and_opens_later(self):
        self.signup(); c = Api(self.base)
        self.assertEqual([c.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": "wrongpass1"})[0] for _ in range(5)], [401] * 5)
        self.assertEqual(c.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": NEW["password"]})[0], 429)
        self.clock[0] += app.LOCK_SECONDS + 1
        self.assertEqual(c.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": NEW["password"]})[0], 200)
    def test_12_client_changes_password(self):
        c, _, _ = self.signup()
        self.assertEqual(c.call("POST", "/api/client/password", {"current_password": "WRONGpass1", "new_password": "newclient22"})[0], 403)
        self.assertEqual(c.call("POST", "/api/client/password", {"current_password": NEW["password"], "new_password": "weak"})[0], 400)
        self.assertEqual(c.call("POST", "/api/client/password", {"current_password": NEW["password"], "new_password": "newclient22"})[0], 200)
        d = Api(self.base); self.assertEqual(d.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": NEW["password"]})[0], 401)
        self.assertEqual(d.call("POST", "/api/client/login", {"phone": NEW["phone"], "password": "newclient22"})[0], 200)
    def test_13_password_stored_hashed(self):
        self.signup(); db = app.connect(); h = db.execute("SELECT password_hash FROM Customer WHERE phone=?", (NEW["phone"],)).fetchone()[0]; db.close()
        self.assertNotIn(NEW["password"], h); self.assertIn("$", h)
    def test_14_shop_customer_without_account_cannot_log_in(self):
        self.assertEqual(Api(self.base).call("POST", "/api/client/login", {"phone": "+7 700 000 01 01", "password": "anything123"})[0], 401)

    # --- three roles: Employee, Manager, Client ---
    def test_15_client_cannot_use_staff_routes(self):
        c, _, _ = self.signup()
        for method, path, body in [("GET", "/api/products", None), ("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001", None),
                                   ("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved"}),
                                   ("GET", "/api/users", None), ("POST", "/api/users", {"full_name": "X Y", "username": "xyz", "password": "goodpass1", "role": "Manager"}),
                                   ("GET", "/api/report/top?month=2026-10", None), ("POST", "/api/password", {"current_password": "a", "new_password": "goodpass1"}),
                                   ("POST", "/api/admin/merge-customers", {"source_id": 1, "target_id": 2}), ("GET", "/api/points-log?customer_id=1", None)]:
            self.assertEqual(c.call(method, path, body)[0], 403, path)
    def test_16_staff_cannot_open_client_page(self):
        emp = Api(self.base); emp.call("POST", "/api/login", {"username": "aruzhan", "password": "cashier123"})
        self.assertNotEqual(emp.call("GET", "/api/client/me")[0], 200)
    def test_17_client_page_needs_login(self):
        self.assertEqual(Api(self.base).call("GET", "/api/client/me")[0], 401)
    def test_18_names_of_the_two_login_kinds_do_not_mix(self):
        self.signup(); c = Api(self.base)
        self.assertEqual(c.call("POST", "/api/login", {"username": NEW["phone"], "password": NEW["password"]})[0], 401)
        self.assertEqual(c.call("POST", "/api/client/login", {"phone": "aruzhan", "password": "cashier123"})[0], 401)
    def test_19_no_password_hash_leaks(self):
        self.signup(); mgr = Api(self.base); mgr.call("POST", "/api/login", {"username": "daniyar", "password": "manager123"})
        s, j = mgr.call("GET", "/api/customer?phone=%2B7%20701%20111%2022%2033"); self.assertNotIn("password_hash", json.dumps(j))
        db = app.connect(); ids = [r[0] for r in db.execute("SELECT customer_id FROM Customer ORDER BY 1 LIMIT 2")]; db.close()
        s, j = mgr.call("POST", "/api/admin/merge-customers", {"source_id": ids[0], "target_id": ids[1]}); self.assertEqual(s, 200); self.assertNotIn("password_hash", json.dumps(j))
    def test_20_logout_closes_client_session(self):
        c, _, _ = self.signup(); self.assertEqual(c.call("POST", "/api/logout", {})[0], 200); self.assertEqual(c.call("GET", "/api/client/me")[0], 401)
    def test_21_client_sees_own_points_history_only(self):
        c, _, _ = self.signup(); s, hist = c.call("GET", "/api/client/points"); self.assertEqual((s, hist), (200, []))

if __name__ == "__main__":
    unittest.main(verbosity=2)