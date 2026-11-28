"""Security tests (Nurislam, Week 13): other sessions are closed after a password change, wrong shop codes are limited.
Run:  python test_security_week13.py        (9 tests; every test uses its own NEW temporary database; the clock is fake)"""
import json, os, tempfile, threading, time, unittest, urllib.request, urllib.error
import app

class Api:
    """A tiny browser with its own cookie: two Api objects = two browsers (two sessions)."""
    def __init__(self, base): self.base, self.cookie = base, None
    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Cookie": self.cookie} if self.cookie else {})})
        try: r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: r = e
        if r.headers.get("Set-Cookie") and "sid=" in r.headers["Set-Cookie"]: self.cookie = r.headers["Set-Cookie"].split(";")[0]
        return r.status, json.loads(r.read() or b"{}")
    def login(self, u, p): return self.call("POST", "/api/login", {"username": u, "password": p})

class Week13Security(unittest.TestCase):
    n = 0
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "start.db")
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self):
        app.SMS_PROVIDER = "console"                                                            # never send a real SMS from a test
        self.clock = [1_000_000.0]; app._now = lambda: self.clock[0]
        Week13Security.n += 1; app.DB_PATH = os.path.join(self.tmp, f"w13_{Week13Security.n}.db"); app.init_db()    # a NEW database for every test
        app.SESSIONS.clear(); app.FAILED.clear(); app.SMS_CODES.clear(); app.SMS_LOG.clear()
    def tearDown(self): app._now = time.time
    def api(self): return Api(self.base)
    def staff(self, name="aruzhan", pw="cashier123"):
        a = self.api(); self.assertEqual(a.login(name, pw)[0], 200); return a
    def client(self, phone="+7 705 111 22 33", pw="clientpass1"):                             # sign up with the SMS code, like test_client.py
        a = self.api(); s, j = a.call("POST", "/api/client/send-sms", {"phone": phone}); self.assertEqual(s, 200, j)
        s, j = a.call("POST", "/api/client/register", {"full_name": "Client Test", "phone": phone, "email": "c@c.kz", "password": pw, "sms_code": j["demo_code"]})
        self.assertEqual(s, 201, j); return a
    def reg(self, code, n=0): return self.api().call("POST", "/api/register", {"full_name": "New Worker", "username": f"new_worker{n}", "password": "Worker2026pass", "shop_code": code})

    # ---- password change closes the other sessions ----
    def test_s05_password_change_closes_the_other_logins_of_the_same_employee(self):
        a, b = self.staff(), self.staff()                                                         # two browsers, same employee
        self.assertEqual(b.call("GET", "/api/products")[0], 200)
        self.assertEqual(a.call("POST", "/api/password", {"current_password": "cashier123", "new_password": "Fresh2026pass"})[0], 200)
        self.assertEqual(a.call("GET", "/api/products")[0], 200)                                  # the browser that changed it stays logged in
        s, j = b.call("GET", "/api/products"); self.assertEqual((s, j["error"]), (401, "Please log in"))   # the other one is out
        self.assertEqual(self.api().login("aruzhan", "Fresh2026pass")[0], 200); self.assertEqual(self.api().login("aruzhan", "cashier123")[0], 401)
    def test_s06_other_accounts_are_not_touched(self):
        a, m = self.staff(), self.staff("daniyar", "manager123")
        a.call("POST", "/api/password", {"current_password": "cashier123", "new_password": "Fresh2026pass"})
        self.assertEqual(m.call("GET", "/api/products")[0], 200)                                  # the manager keeps working
    def test_s07_a_wrong_current_password_closes_nothing(self):
        a, b = self.staff(), self.staff()
        self.assertEqual(a.call("POST", "/api/password", {"current_password": "WRONG", "new_password": "Fresh2026pass"})[0], 403)
        self.assertEqual(b.call("GET", "/api/products")[0], 200)
    def test_s08_client_password_change_closes_the_other_client_logins(self):
        a = self.client(); b = self.api(); self.assertEqual(b.call("POST", "/api/client/login", {"phone": "87051112233", "password": "clientpass1"})[0], 200)
        self.assertEqual(b.call("GET", "/api/client/me")[0], 200)
        self.assertEqual(a.call("POST", "/api/client/password", {"current_password": "clientpass1", "new_password": "Newer2026pass"})[0], 200)
        self.assertEqual(a.call("GET", "/api/client/me")[0], 200); self.assertEqual(b.call("GET", "/api/client/me")[0], 401)
    def test_s09_a_client_and_an_employee_never_close_each_other(self):
        c = self.client(); e = self.staff()
        c.call("POST", "/api/client/password", {"current_password": "clientpass1", "new_password": "Newer2026pass"})
        self.assertEqual(e.call("GET", "/api/products")[0], 200)                                  # the employee is not affected

    # ---- wrong shop codes are limited ----
    def test_s10_five_wrong_shop_codes_lock_the_registration(self):
        for i in range(5): self.assertEqual(self.reg("WRONG" + str(i), i)[0], 403)
        s, j = self.reg(app.SHOP_CODE, 9); self.assertEqual(s, 429); self.assertIn("Try again", j["error"])      # even the RIGHT code is refused now
    def test_s11_the_shop_code_lock_does_not_block_the_normal_login(self):
        for i in range(5): self.reg("WRONG", i)
        self.assertEqual(self.api().login("aruzhan", "cashier123")[0], 200)                       # a separate counter: login still works
    def test_s12_the_shop_code_lock_ends_after_the_lock_time(self):
        for i in range(5): self.reg("WRONG", i)
        self.clock[0] += app.LOCK_SECONDS - 5; self.assertEqual(self.reg(app.SHOP_CODE, 1)[0], 429)
        self.clock[0] += 10; self.assertEqual(self.reg(app.SHOP_CODE, 2)[0], 201)
    def test_s13_the_right_code_resets_the_counter(self):
        for i in range(4): self.assertEqual(self.reg("WRONG", i)[0], 403)
        self.assertEqual(self.reg(app.SHOP_CODE, 5)[0], 201)
        for i in range(4): self.assertEqual(self.reg("WRONG", 10 + i)[0], 403)                   # counting started again: not locked yet

if __name__ == "__main__":
    unittest.main(verbosity=2)