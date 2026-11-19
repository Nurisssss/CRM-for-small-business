"""Tests of the loyalty points rule (R-01 ... R-07), the numbers are the ones in points_rule.md.
Run:  python test_points_rule.py      (7 tests; every test uses a NEW temporary database, never your real crm.db)

Rule: earn 3 % of the money paid (1 point = $0.01), spend at most 30 % of a bill, one purchase earns at most 5,000 points.
Example product used below: Coffee beans, $18.00 (product 1)."""
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

class PointsRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "start.db"); app.SESSIONS.clear(); app.FAILED.clear()
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self):
        app.DB_PATH = os.path.join(self.tmp, self.id().split(".")[-1] + ".db"); app.init_db()      # a NEW database for every test
        app.SESSIONS.clear(); app.FAILED.clear()
        self.emp = Api(self.base); self.assertEqual(self.emp.call("POST", "/api/login", {"username": "aruzhan", "password": "cashier123"})[0], 200)
        db = app.connect(); db.execute("UPDATE Product SET price=18.00, stock_qty=1000 WHERE product_id=1"); db.close()   # coffee beans $18.00
        self.give_points(1, 1000)                                                                   # customer 1 has enough points for the tests

    def give_points(self, cid, n):                                  # a manager correction: the balance AND the ledger change together
        db = app.connect(); db.execute("UPDATE Customer SET loyalty_points = loyalty_points + ? WHERE customer_id=?", (n, cid))
        db.execute("INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at) VALUES (?,NULL,?,'correction',datetime('now'))", (cid, n)); db.close()
    def state(self, cid=1):
        db = app.connect(); r = (db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=?", (cid,)).fetchone()[0],
                                 db.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0], db.execute("SELECT COUNT(*) FROM Points_Log").fetchone()[0]); db.close(); return r
    def buy(self, qty=1, pts=None, pay="approved", cid=1, pid=1):
        body = {"customer_id": cid, "items": [{"product_id": pid, "quantity": qty}], "payment": pay}
        if pts is not None: body["points_to_use"] = pts
        return self.emp.call("POST", "/api/purchase", body)

    def test_R01_normal_purchase_earns_3_percent(self):                       # $18.00 -> 54 points
        b = self.state(); s, j = self.buy()
        self.assertEqual((s, j["total"], j["amount_to_pay"], j["points_earned"]), (201, 18.0, 18.0, 54)); self.assertEqual(self.state()[0] - b[0], 54)
    def test_R02_spending_100_points_takes_1_dollar_and_earns_on_the_rest(self):    # pays $17.00 -> 51 points, balance -100 + 51 = -49
        b = self.state(); s, j = self.buy(pts=100)
        self.assertEqual((s, j["points_used"], j["amount_to_pay"], j["points_earned"]), (201, 100, 17.0, 51)); self.assertEqual(self.state()[0] - b[0], -49)
    def test_R03_the_30_percent_limit_540_accepted_541_refused(self):         # 30 % of $18.00 = $5.40 = 540 points
        b = self.state(); s, j = self.buy(pts=541)
        self.assertEqual(s, 400); self.assertIn("30%", j["error"]); self.assertEqual(self.state(), b)       # refused, nothing changed
        s, j = self.buy(pts=540); self.assertEqual((s, j["amount_to_pay"], j["points_earned"]), (201, 12.6, 37)); self.assertEqual(self.state()[0] - b[0], -503)
    def test_R04_not_enough_points_is_refused_and_nothing_is_saved(self):
        db = app.connect(); bal = db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=2").fetchone()[0]; db.close()
        b = self.state(2); s, j = self.buy(qty=10, pts=bal + 1, cid=2)         # a $180 bill allows 5,400 points, but customer 2 has only `bal`
        self.assertEqual((s, j["error"]), (409, "Not enough bonus points")); self.assertEqual(self.state(2), b)
    def test_R05_declined_card_gives_the_spent_points_back(self):
        b = self.state(); s, _ = self.buy(pts=100, pay="declined")
        self.assertEqual(s, 402); self.assertEqual(self.state(), b)             # balance, purchases and ledger rows are all unchanged
    def test_R06_one_purchase_never_earns_more_than_5000_points(self):        # $200,000 x 3 % = 6,000 points -> capped
        db = app.connect(); db.execute("UPDATE Product SET price=200000, stock_qty=10 WHERE product_id=3"); db.close()
        s, j = self.buy(pid=3); self.assertEqual((s, j["points_earned"]), (201, app.MAX_EARN_PER_PURCHASE)); self.assertEqual(app.MAX_EARN_PER_PURCHASE, 5000)
    def test_R07_every_balance_equals_the_sum_of_its_ledger_rows(self):
        self.buy(); self.buy(pts=100); self.buy(pts=540); self.buy(pts=100, pay="declined")
        db = app.connect(); bad = db.execute("""SELECT c.customer_id FROM Customer c LEFT JOIN Points_Log l ON l.customer_id = c.customer_id
                                                GROUP BY c.customer_id, c.loyalty_points HAVING c.loyalty_points <> COALESCE(SUM(l.points_change), 0)""").fetchall(); db.close()
        self.assertEqual(bad, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)