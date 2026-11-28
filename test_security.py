"""Security tests: IP-based login lock, session expiry, shop code for registration.
Run: python test_security.py (the fake clock avoids waiting for lock/session expiry)."""
import json, os, tempfile, threading, unittest, urllib.request, urllib.error
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
    def login(self, u, p): return self.call("POST", "/api/login", {"username": u, "password": p})

class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "sec.db"); app.SESSIONS.clear()
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self):
        self.clock = [1_000_000.0]; app._now = lambda: self.clock[0]     # fake clock we can move forward
        app.FAILED.clear(); app.SESSIONS.clear()
    def tearDown(self):
        import time; app._now = time.time

    def test_01_username_rotation_does_not_bypass_ip_lock(self):
        c = Api(self.base)
        # Five failed attempts using five different usernames still share one IP counter.
        self.assertEqual(
            [c.login(f"random_user_{i}", "wrong")[0] for i in range(5)],
            [401] * 5
        )
        # A different username and even a correct password cannot bypass the IP lock.
        self.assertEqual(c.login("aruzhan", "cashier123")[0], 429)
        # The same IP limit is shared by staff and customer login endpoints.
        self.assertEqual(
            c.call("POST", "/api/client/login", {"phone": "+7 700 000 01 01", "password": "wrong"})[0],
            429
        )
        self.clock[0] += app.LOCK_SECONDS + 1
        self.assertEqual(c.login("aruzhan", "cashier123")[0], 200)

    def test_02_expired_session_gives_401(self):
        c = Api(self.base); self.assertEqual(c.login("aruzhan", "cashier123")[0], 200)
        self.clock[0] += 29 * 60; self.assertEqual(c.call("GET", "/api/products")[0], 200)   # 29 min idle: still valid (and the timer restarts)
        self.clock[0] += 31 * 60; s, j = c.call("GET", "/api/products")                      # 31 min idle: expired
        self.assertEqual(s, 401); self.assertIn("expired", j["error"])
        self.assertEqual(c.call("GET", "/api/products")[0], 401)                              # and the session is really gone

    def test_03_registration_without_shop_code_refused(self):
        c = Api(self.base); user = {"full_name": "New Person", "username": "newperson", "password": "pass12345"}
        self.assertEqual(c.call("POST", "/api/register", user)[0], 403)                                  # no code
        self.assertEqual(c.call("POST", "/api/register", {**user, "shop_code": "WRONG"})[0], 403)        # wrong code
        self.assertEqual(Api(self.base).login("newperson", "pass12345")[0], 401)                         # the account was not created

    def test_04_registration_with_shop_code_works(self):
        c = Api(self.base)
        s, j = c.call("POST", "/api/register", {"full_name": "Code Person", "username": "codeperson", "password": "pass12345", "shop_code": app.SHOP_CODE})
        self.assertEqual((s, j["role"]), (201, "Employee"))
        self.assertEqual(Api(self.base).login("codeperson", "pass12345")[0], 200)

if __name__ == "__main__":
    unittest.main(verbosity=2)