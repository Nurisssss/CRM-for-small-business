"""Automated tests for the CRM prototype.
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
        # Явно логинимся под реальными учетками из data.sql
        self.emp.login("aknur", "hash1")
        self.mgr.login("daniyar", "hash2")
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
        after = self.state(); expected = min(app.MAX_EARN_PER_PURCHASE, app.whole(Decimal("36.00") * app.POINTS_RATE / app.POINT_VALUE))
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

    # добавила еще 10 тестов 
    def test_16_customer_notes_add(self):
        s, _ = self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "VIP"})
        self.assertEqual(s, 201)
    def test_17_customer_notes_refused_for_unknown(self):
        s, _ = self.emp.call("POST", "/api/customer/notes", {"customer_id": 77, "note": "Test"})
        self.assertEqual(s, 404)
    def test_18_merge_customers(self):
        s, _ = self.mgr.call("POST", "/api/admin/merge-customers", {"source_id": 5, "target_id": 4})
        self.assertEqual(s, 200)
    def test_19_customer_registration_success(self):
        s, _ = self.emp.call("POST", "/api/customer/register", {"name": "Ivan", "phone": "+77029998877"})
        self.assertEqual(s, 201)
    def test_20_customer_registration_duplicate_phone(self):
        self.emp.call("POST", "/api/customer/register", {"name": "Petr", "phone": "+77025554433"})
        s, _ = self.emp.call("POST", "/api/customer/register", {"name": "Other", "phone": "+77025554433"})
        self.assertEqual(s, 400)
    def test_21_loyalty_points_calculation(self):
        s, _ = self.emp.call("POST", "/api/purchase", {"customer_id": 2, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved"})
        self.assertEqual(s, 201)
    def test_22_manager_checks_sql_query(self):
        s, _ = self.mgr.call("GET", "/api/report/checks")
        self.assertEqual(s, 200)
    def test_23_employee_unauthorized_action(self):
        """Тест 23: Обычный сотрудник не может выполнять административные действия"""
        self.emp.login("aruzhan", "cashier123")   
        s, _ = self.emp.call("POST", "/api/admin/merge-customers", {"source_id": 1, "target_id": 2})
        self.assertEqual(s, 403)
    def test_24_rules_endpoint(self):
        """Тест 24: Проверка эндпоинта правил"""
        self.emp.login("aruzhan", "cashier123")  
        s, _ = self.emp.call("GET", "/api/rules")
        self.assertEqual(s, 200)
    def test_25_points_history(self):
        """Тест 25: Проверка истории баллов клиента"""
        self.emp.login("aruzhan", "cashier123")  
        s, _ = self.emp.call("GET", "/api/points-log?customer_id=1")
        self.assertEqual(s, 200)
        
if __name__ == "__main__":
    unittest.main(verbosity=2) 