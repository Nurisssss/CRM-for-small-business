"""Automated tests for the CRM prototype. Run:  python test_app.py
Each test prints PASS or FAIL, so the result can be pasted into the team's test table."""
import json, os, tempfile, threading, unittest, urllib.request, urllib.error
import app
from decimal import Decimal

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

class CrmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "test.db"); app.SESSIONS.clear()
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self):
        self.emp, self.mgr = Api(self.base), Api(self.base)
        self.emp.login("aruzhan", "cashier123"); self.mgr.login("daniyar", "manager123")
    def state(self):
        db = app.connect(); r = (db.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0], db.execute("SELECT stock_qty FROM Product WHERE product_id=1").fetchone()[0],
                                 db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=1").fetchone()[0]); db.close(); return r

    def test_01_login_ok(self):                 self.assertEqual(Api(self.base).login("aruzhan", "cashier123")[0], 200)
    def test_02_wrong_password_refused(self):   self.assertEqual(Api(self.base).login("aruzhan", "wrong")[0], 401)
    def test_03_no_login_refused(self):         self.assertEqual(Api(self.base).call("GET", "/api/products")[0], 401)
    def test_04_find_customer(self):
        s, j = self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001"); self.assertEqual((s, j["full_name"]), (200, "Aigerim Nurova"))
    def test_05_employee_does_not_see_email(self):
        s, j = self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001"); self.assertNotIn("email", j)
    def test_06_wrong_phone_format_refused(self):  self.assertEqual(self.emp.call("GET", "/api/customer?phone=555-103")[0], 400)
    def test_07_unknown_customer_refused(self):    self.assertEqual(self.emp.call("GET", "/api/customer?phone=%2B7%20700%20999%2099%2099")[0], 404)
    def test_08_purchase_saved_stock_and_points(self):
        before = self.state(); s, j = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 2}], "payment": "approved"})
        after = self.state(); expected = min(app.MAX_EARN_PER_PURCHASE, app.whole(Decimal("36.00") * app.POINTS_RATE / app.POINT_VALUE))   # follows the rule, not a fixed number
        self.assertEqual(s, 201); self.assertEqual(j["total"], 36.0)
        self.assertEqual((after[0] - before[0], before[1] - after[1], after[2] - before[2]), (1, 2, expected))
    def test_09_not_enough_stock_rolls_back(self):
        before = self.state(); s, _ = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 100}], "payment": "approved"})
        self.assertEqual(s, 409); self.assertEqual(self.state(), before)
    def test_10_declined_payment_saves_nothing(self):
        before = self.state(); s, _ = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "payment": "declined"})
        self.assertEqual(s, 402); self.assertEqual(self.state(), before)
    def test_11_unknown_customer_purchase_refused(self):
        self.assertEqual(self.emp.call("POST", "/api/purchase", {"customer_id": 77, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved"})[0], 404)
    def test_12_negative_quantity_refused(self):
        self.assertEqual(self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": -5}], "payment": "approved"})[0], 400)
    def test_13_employee_cannot_open_reports(self):  self.assertEqual(self.emp.call("GET", "/api/report/top?month=2026-10")[0], 403)
    def test_14_manager_top_customer_report(self):
        s, j = self.mgr.call("GET", "/api/report/top?month=2026-10"); self.assertEqual(s, 200); self.assertEqual(j[0]["full_name"], "Aigerim Nurova")
    def test_15_totals_check_has_no_mismatch(self):
        self.emp.call("POST", "/api/purchase", {"customer_id": 2, "items": [{"product_id": 2, "quantity": 3}], "payment": "approved"})
        s, j = self.mgr.call("GET", "/api/report/check"); self.assertEqual((s, j["mismatches"]), (200, []))

    def test_16_customer_notes_add(self):
        """Тест 16: Успешное добавление заметки для клиента"""
        s, _ = self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "VIP клиент, любит скидки"})
        self.assertEqual(s, 201)

    def test_17_customer_notes_refused_for_unknown(self):
        """Тест 17: Отказ в добавлении заметки для несуществующего клиента (например, ID 77)"""
        s, _ = self.emp.call("POST", "/api/customer/notes", {"customer_id": 77, "note": "Тестовая заметка"})
        self.assertEqual(s, 404)

    def test_18_merge_customers(self):
        """Тест 18: Слияние дублирующихся клиентов с суммированием баллов"""
        s, j = self.mgr.call("POST", "/api/admin/merge-customers", {"source_id": 5, "target_id": 4})
        self.assertEqual(s, 200)

    def test_19_customer_registration_success(self):
        """Тест 19: Успешная регистрация нового клиента через API"""
        s, _ = self.emp.call("POST", "/api/customer/register", {"name": "Иван", "phone": "+77029998877"})
        self.assertEqual(s, 201)

    def test_20_customer_registration_duplicate_phone(self):
        """Тест 20: Отказ в регистрации при дублировании номера телефона"""
        # Первый раз регистрируем
        self.emp.call("POST", "/api/customer/register", {"name": "Петр", "phone": "+77025554433"})
        # Второй раз с тем же номером — ожидаем ошибку
        s, _ = self.emp.call("POST", "/api/customer/register", {"name": "Другой Петр", "phone": "+77025554433"})
        self.assertEqual(s, 400)

    def test_21_loyalty_points_calculation(self):
        """Тест 21: Проверка корректности начисления баллов за покупку"""
        # Проверяем начисление 1 балла за целую единицу валюты
        s, j = self.emp.call("POST", "/api/purchase", {"customer_id": 2, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved"})
        self.assertEqual(s, 201)

    def test_22_manager_checks_sql_query(self):
        """Тест 22: Проверка работы аналитического запроса checks.sql менеджером"""
        s, j = self.mgr.call("GET", "/api/report/checks")
        self.assertEqual(s, 200)

    def test_23_employee_unauthorized_action(self):
        """Тест 23: Обычный сотрудник не может выполнять административные действия"""
        s, _ = self.emp.call("POST", "/api/admin/merge-customers", {"source_id": 1, "target_id": 2})
        self.assertEqual(s, 403)

class PointsTests(unittest.TestCase):
    """Earning and spending bonus points. Own temporary database; prices are set here so the numbers are easy to read."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(); app.DB_PATH = os.path.join(cls.tmp, "points.db"); app.SESSIONS.clear()
        cls.srv = app.make_server(0); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        db = app.connect(); db.execute("UPDATE Product SET price=100, stock_qty=1000 WHERE product_id=1")         # coffee = $100 per unit
        db.execute("UPDATE Product SET price=2000, stock_qty=1000 WHERE product_id=3")                            # mug = $2000 (for the cap test)
        db.execute("UPDATE Customer SET loyalty_points = loyalty_points + 10000 WHERE customer_id=1")              # give customer 1 enough points ...
        db.execute("INSERT INTO Points_Log (customer_id, purchase_id, points_change, reason, created_at) VALUES (1, NULL, 10000, 'correction', datetime('now'))")   # ... and keep the ledger in step
        db.close()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): self.emp = Api(self.base); self.emp.login("aruzhan", "cashier123")
    def snap(self, cid=1):
        db = app.connect(); r = (db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=?", (cid,)).fetchone()[0],
                                 db.execute("SELECT COUNT(*) FROM Points_Log").fetchone()[0], db.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0]); db.close(); return r
    def buy(self, items, pts=None, pay="approved", cid=1):
        body = {"customer_id": cid, "items": items, "payment": pay}
        if pts is not None: body["points_to_use"] = pts
        return self.emp.call("POST", "/api/purchase", body)
    def earn(self, money): return min(app.MAX_EARN_PER_PURCHASE, app.whole(Decimal(money) * app.POINTS_RATE / app.POINT_VALUE))

    def test_p01_points_earned_on_money_paid(self):
        b = self.snap(); s, j = self.buy([{"product_id": 1, "quantity": 2}]); a = self.snap()      # bill $200, no points used
        self.assertEqual((s, j["points_used"], j["amount_to_pay"]), (201, 0, 200.0)); self.assertEqual(a[0] - b[0], self.earn(200)); self.assertEqual(a[1] - b[1], 1)
    def test_p02_spend_points_and_earn_on_the_rest(self):
        b = self.snap(); s, j = self.buy([{"product_id": 1, "quantity": 2}], pts=1000); a = self.snap()   # bill $200: pay $190 in money + 1000 points ($10)
        self.assertEqual((s, j["total"], j["points_used"], j["amount_to_pay"]), (201, 200.0, 1000, 190.0))
        self.assertEqual(a[0] - b[0], -1000 + self.earn(190)); self.assertEqual(a[1] - b[1], 2)       # one 'spent' row and one 'earned' row
    def test_p03_points_over_the_share_limit_refused(self):
        b = self.snap(); limit = app.whole(200 * app.MAX_REDEEM_SHARE / app.POINT_VALUE)                 # 30 % of $200 = $60 = 6000 points
        s, _ = self.buy([{"product_id": 1, "quantity": 2}], pts=limit + 1); self.assertEqual(s, 400); self.assertEqual(self.snap(), b)
        s, _ = self.buy([{"product_id": 1, "quantity": 2}], pts=limit);     self.assertEqual(s, 201)   # exactly the limit is allowed
    def test_p04_more_points_than_balance_refused(self):
        b = self.snap(4); s, _ = self.buy([{"product_id": 1, "quantity": 10}], pts=b[0] + 1, cid=4)    # customer 4 has few points
        self.assertEqual(s, 409); self.assertEqual(self.snap(4), b)
    def test_p05_declined_payment_gives_points_back(self):
        b = self.snap(); s, _ = self.buy([{"product_id": 1, "quantity": 2}], pts=1000, pay="declined")
        self.assertEqual(s, 402); self.assertEqual(self.snap(), b)                                    # balance, ledger and purchases unchanged
    def test_p06_bad_points_value_refused(self):
        for bad in (-5, "abc", 2.5, True): self.assertEqual(self.buy([{"product_id": 1, "quantity": 1}], pts=bad)[0], 400)
    def test_p07_earning_has_a_cap(self):
        s, j = self.buy([{"product_id": 3, "quantity": 1}])                                            # bill $2000 x 3 % = $60 = 6000 points, the cap (5000) is lower
        self.assertEqual((s, j["points_earned"]), (201, app.MAX_EARN_PER_PURCHASE))
    def test_p08_rules_endpoint(self):
        s, j = self.emp.call("GET", "/api/rules"); self.assertEqual((s, j["max_earn_per_purchase"]), (200, app.MAX_EARN_PER_PURCHASE))
    def test_p09_history_shows_the_spend_as_a_minus(self):
        s, j = self.buy([{"product_id": 1, "quantity": 2}], pts=300)
        s2, rows = self.emp.call("GET", "/api/points-log?customer_id=1"); self.assertEqual(s2, 200)
        self.assertTrue(any(r["purchase_id"] == j["purchase_id"] and r["reason"] == "spent" and r["points_change"] == -300 for r in rows))
        self.assertTrue(any(r["purchase_id"] == j["purchase_id"] and r["reason"] == "earned" and r["points_change"] > 0 for r in rows))
    def test_p10_history_unknown_customer_refused(self):
        self.assertEqual(self.emp.call("GET", "/api/points-log?customer_id=777")[0], 404)

    def test_p99_balance_equals_ledger_for_every_customer(self):
        db = app.connect(); rows = db.execute("""SELECT c.customer_id FROM Customer c LEFT JOIN Points_Log l ON l.customer_id=c.customer_id
                                                  GROUP BY c.customer_id, c.loyalty_points HAVING c.loyalty_points <> COALESCE(SUM(l.points_change),0)""").fetchall(); db.close()
        self.assertEqual(rows, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
    
    
    
