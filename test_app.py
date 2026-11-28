"""Automated tests for the CRM prototype.
Each line shows ok or FAIL, so the result can be pasted into the team's test table."""
import json, os, tempfile, threading, unittest, urllib.request, urllib.error
import app
from decimal import Decimal

class Api:
    def __init__(self, base): self.base, self.cookie = base, None
    def call(self, method, path, body=None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **({"Cookie": self.cookie} if self.cookie else {})}
        )
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        if r.headers.get("Set-Cookie") and "sid=" in r.headers["Set-Cookie"]:
            self.cookie = r.headers["Set-Cookie"].split(";")[0]
        return r.status, json.loads(r.read() or b"{}")
    def login(self, u, p):
        return self.call("POST", "/api/login", {"username": u, "password": p})

class CrmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        app.DB_PATH = os.path.join(cls.tmp, "test.db")
        app.SESSIONS.clear()
        app.FAILED.clear()
        cls.srv = app.make_server(0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        app.FAILED.clear()
        self.emp, self.mgr = Api(self.base), Api(self.base)
        self.emp.login("aruzhan", "cashier123")
        self.mgr.login("daniyar", "manager123")

    def state(self):
        db = app.connect()
        r = (
            db.execute("SELECT COUNT(*) FROM Purchase").fetchone()[0],
            db.execute("SELECT stock_qty FROM Product WHERE product_id=1").fetchone()[0],
            db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=1").fetchone()[0],
        )
        db.close()
        return r

    # --- Core Auth, Lookup, Purchases & Reports (Tests 01-25) ---
    def test_01_login_ok(self):
        self.assertEqual(Api(self.base).login("aruzhan", "cashier123")[0], 200)

    def test_02_wrong_password_refused(self):
        self.assertEqual(Api(self.base).login("aruzhan", "wrong")[0], 401)

    def test_03_no_login_refused(self):
        self.assertEqual(Api(self.base).call("GET", "/api/products")[0], 401)

    def test_04_find_customer(self):
        s, j = self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001")
        self.assertEqual((s, j["full_name"]), (200, "Aigerim Nurova"))

    def test_05_employee_does_not_see_email(self):
        s, j = self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001")
        self.assertNotIn("email", j)

    def test_06_wrong_phone_format_refused(self):
        self.assertEqual(self.emp.call("GET", "/api/customer?phone=555-103")[0], 400)

    def test_07_unknown_customer_refused(self):
        self.assertEqual(self.emp.call("GET", "/api/customer?phone=%2B7%20700%20999%2099%2099")[0], 404)

    def test_08_purchase_saved_stock_and_points(self):
        before = self.state()
        s, j = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 2}], "payment": "approved"})
        after = self.state()
        expected = min(app.MAX_EARN_PER_PURCHASE, app.whole(Decimal("36.00") * app.POINTS_RATE / app.POINT_VALUE))
        self.assertEqual(s, 201)
        self.assertEqual(j["total"], 36.0)
        self.assertEqual((after[0] - before[0], before[1] - after[1], after[2] - before[2]), (1, 2, expected))

    def test_09_not_enough_stock_rolls_back(self):
        before = self.state()
        s, _ = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 100}], "payment": "approved"})
        self.assertEqual(s, 409)
        self.assertEqual(self.state(), before)

    def test_10_declined_payment_saves_nothing(self):
        before = self.state()
        s, _ = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "payment": "declined"})
        self.assertEqual(s, 402)
        self.assertEqual(self.state(), before)

    def test_11_unknown_customer_purchase_refused(self):
        self.assertEqual(self.emp.call("POST", "/api/purchase", {"customer_id": 77, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved"})[0], 404)

    def test_12_negative_quantity_refused(self):
        self.assertEqual(self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": -5}], "payment": "approved"})[0], 400)

    def test_13_employee_cannot_open_reports(self):
        self.assertEqual(self.emp.call("GET", "/api/report/top?month=2026-10")[0], 403)

    def test_14_manager_top_customer_report(self):
        s, j = self.mgr.call("GET", "/api/report/top?month=2026-10")
        self.assertEqual(s, 200)
        self.assertEqual(j[0]["full_name"], "Aigerim Nurova")

    def test_15_totals_check_has_no_mismatch(self):
        self.emp.call("POST", "/api/purchase", {"customer_id": 2, "items": [{"product_id": 2, "quantity": 3}], "payment": "approved"})
        s, j = self.mgr.call("GET", "/api/report/check")
        self.assertEqual((s, j["mismatches"]), (200, []))

    def test_16_customer_notes_add(self):
        s, _ = self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "VIP"})
        self.assertEqual(s, 201)
        s, j = self.emp.call("GET", "/api/customer/notes?customer_id=1")
        self.assertEqual((s, j[0]["note_text"]), (200, "VIP"))

    def test_17_customer_notes_refused_for_unknown(self):
        s, j = self.emp.call("POST", "/api/customer/notes", {"customer_id": 77, "note": "Test"})
        self.assertEqual((s, j["error"]), (404, "Customer not found"))

    def test_18_merge_customers(self):
        s, j = self.mgr.call("POST", "/api/admin/merge-customers", {"source_id": 5, "target_id": 4})
        self.assertEqual(s, 200)
        self.assertEqual((j["customer"]["customer_id"], j["customer"]["phone"], j["customer"]["loyalty_points"]), (4, "+7 701 555 04 04", 24))
        self.assertEqual(self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2004")[0], 404)

    def test_19_customer_registration_success(self):
        s, j = self.emp.call("POST", "/api/customer/register", {"name": "Ivan", "phone": "+77029998877"})
        self.assertEqual((s, j["phone"]), (201, "+7 702 999 88 77"))

    def test_20_customer_registration_duplicate_phone(self):
        self.emp.call("POST", "/api/customer/register", {"name": "Petr", "phone": "+77025554433"})
        s, _ = self.emp.call("POST", "/api/customer/register", {"name": "Other", "phone": "8 702 555 44 33"})
        self.assertEqual(s, 409)

    def test_21_loyalty_points_calculation(self):
        s, j = self.emp.call("POST", "/api/purchase", {"customer_id": 1, "items": [{"product_id": 1, "quantity": 1}], "payment": "approved", "points_to_use": 100})
        self.assertEqual(s, 201)
        self.assertEqual((j["points_used"], j["amount_to_pay"], j["points_earned"]), (100, 17.0, 51))

    def test_22_manager_checks_sql_query(self):
        s, j = self.mgr.call("GET", "/api/report/checks")
        self.assertEqual((s, j["totals_mismatches"], j["points_mismatches"]), (200, [], []))

    def test_23_employee_unauthorized_action(self):
        s, _ = self.emp.call("POST", "/api/admin/merge-customers", {"source_id": 1, "target_id": 2})
        self.assertEqual(s, 403)
        self.assertEqual(self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2001")[0], 200)

    def test_24_rules_endpoint(self):
        s, j = self.emp.call("GET", "/api/rules")
        self.assertEqual((s, j["points_rate"], j["max_redeem_share"]), (200, "0.03", "0.30"))

    def test_25_points_history(self):
        s, j = self.emp.call("GET", "/api/points-log?customer_id=1")
        self.assertEqual(s, 200)
        self.assertIn("opening", [r["reason"] for r in j])

    # --- Employee Registration (Tests 26-29) ---
    def test_26_employee_register_success(self):
        s, j = Api(self.base).call("POST", "/api/register", {
            "full_name": "Nurlan T.", "username": "nurlan_t", "password": "Password1", "shop_code": app.SHOP_CODE
        })
        self.assertEqual((s, j["role"], j["username"]), (201, "Employee", "nurlan_t"))
        self.assertEqual(Api(self.base).login("nurlan_t", "Password1")[0], 200)

    def test_27_employee_register_wrong_shop_code_refused(self):
        s, _ = Api(self.base).call("POST", "/api/register", {
            "full_name": "Fake User", "username": "fake_user", "password": "Password1", "shop_code": "WRONG-CODE"
        })
        self.assertEqual(s, 403)

    def test_28_employee_register_weak_password_refused(self):
        s, _ = Api(self.base).call("POST", "/api/register", {
            "full_name": "Weak Pass", "username": "weak_pass", "password": "onlyletters", "shop_code": app.SHOP_CODE
        })
        self.assertEqual(s, 400)

    def test_29_employee_register_duplicate_username_refused(self):
        s, _ = Api(self.base).call("POST", "/api/register", {
            "full_name": "Dup Cashier", "username": "aruzhan", "password": "Password1", "shop_code": app.SHOP_CODE
        })
        self.assertEqual(s, 409)

    # --- Password Change (Tests 30-33) ---
    def test_30_password_change_success(self):
        Api(self.base).call("POST", "/api/register", {
            "full_name": "Pw Tester", "username": "pw_user", "password": "OldPass123", "shop_code": app.SHOP_CODE
        })
        cli = Api(self.base)
        cli.login("pw_user", "OldPass123")
        s, j = cli.call("POST", "/api/password", {"current_password": "OldPass123", "new_password": "NewPass456"})
        self.assertEqual((s, j["ok"]), (200, True))
        self.assertEqual(Api(self.base).login("pw_user", "OldPass123")[0], 401)
        self.assertEqual(Api(self.base).login("pw_user", "NewPass456")[0], 200)

    def test_31_password_change_wrong_current_refused(self):
        s, _ = self.emp.call("POST", "/api/password", {"current_password": "WrongOld1", "new_password": "NewPass456"})
        self.assertEqual(s, 403)

    def test_32_password_change_weak_new_password_refused(self):
        s, _ = self.emp.call("POST", "/api/password", {"current_password": "cashier123", "new_password": "short1"})
        self.assertEqual(s, 400)

    def test_33_password_change_requires_login(self):
        s, _ = Api(self.base).call("POST", "/api/password", {"current_password": "cashier123", "new_password": "NewPass456"})
        self.assertEqual(s, 401)

    # --- User Management (Tests 34-37) ---
    def test_34_manager_list_users_hides_password_hashes(self):
        s, j = self.mgr.call("GET", "/api/users")
        self.assertEqual(s, 200)
        self.assertTrue(len(j) >= 3)
        for u in j:
            self.assertNotIn("password_hash", u)

    def test_35_employee_cannot_list_users(self):
        self.assertEqual(self.emp.call("GET", "/api/users")[0], 403)

    def test_36_manager_create_manager_user(self):
        s, j = self.mgr.call("POST", "/api/users", {
            "full_name": "Asel M.", "username": "asel_mgr", "password": "Manager99", "role": "Manager"
        })
        self.assertEqual((s, j["role"]), (201, "Manager"))
        new_mgr = Api(self.base)
        self.assertEqual(new_mgr.login("asel_mgr", "Manager99")[0], 200)
        self.assertEqual(new_mgr.call("GET", "/api/users")[0], 200)

    def test_37_manager_create_user_invalid_role_refused(self):
        s, _ = self.mgr.call("POST", "/api/users", {
            "full_name": "Bad Role", "username": "bad_role", "password": "UserPass1", "role": "SuperAdmin"
        })
        self.assertEqual(s, 400)

    # --- Customer Registration Validation & Visibility (Tests 38-41) ---
    def test_38_customer_registration_with_email_and_role_visibility(self):
        s, j = self.emp.call("POST", "/api/customer/register", {
            "full_name": "Arman B.", "phone": "87071112233", "email": "arman@example.com"
        })
        self.assertEqual((s, j["phone"]), (201, "+7 707 111 22 33"))
        self.assertNotIn("email", j)  # Employee does not see email
        s2, j2 = self.mgr.call("GET", "/api/customer?phone=%2B7%20707%20111%2022%2033")
        self.assertEqual((s2, j2["email"], j2["loyalty_points"]), (200, "arman@example.com", 0))

    def test_39_customer_registration_invalid_phone_refused(self):
        s, _ = self.emp.call("POST", "/api/customer/register", {"full_name": "Bad Phone", "phone": "12345"})
        self.assertEqual(s, 400)

    def test_40_customer_registration_invalid_email_refused(self):
        s, _ = self.emp.call("POST", "/api/customer/register", {
            "full_name": "Bad Email", "phone": "+7 707 222 33 44", "email": "not-an-email"
        })
        self.assertEqual(s, 400)

    def test_41_customer_registration_short_name_refused(self):
        s, _ = self.emp.call("POST", "/api/customer/register", {"full_name": "A", "phone": "+7 707 333 44 55"})
        self.assertEqual(s, 400)

    # --- Purchase validation & transaction details (Tests 42-49) ---
    def buy(self, items, payment="approved", customer_id=3, **extra):
        return self.emp.call("POST", "/api/purchase", {"customer_id": customer_id, "items": items, "payment": payment, **extra})

    def test_42_quantity_limits_0_and_101_refused(self):
        before = self.state()
        self.assertEqual(self.buy([{"product_id": 1, "quantity": 0}])[0], 400)
        self.assertEqual(self.buy([{"product_id": 1, "quantity": 101}])[0], 400)
        self.assertEqual(self.state(), before)

    def test_43_invalid_payment_value_refused(self):
        before = self.state()
        s, j = self.buy([{"product_id": 1, "quantity": 1}], payment="maybe")
        self.assertEqual(s, 400)
        self.assertIn("payment", j["error"])
        self.assertEqual(self.state(), before)

    def test_44_unknown_product_rolls_back_whole_purchase(self):
        before = self.state()
        s, j = self.buy([{"product_id": 1, "quantity": 1}, {"product_id": 999, "quantity": 1}])
        self.assertEqual((s, j["error"]), (404, "Product 999 not found"))
        self.assertEqual(self.state(), before)          # coffee stock was not reduced, no Purchase saved

    def test_45_same_product_twice_becomes_one_line(self):
        s, j = self.buy([{"product_id": 2, "quantity": 1}, {"product_id": 2, "quantity": 2}])
        self.assertEqual(s, 201)
        self.assertEqual(len(j["lines"]), 1)
        self.assertEqual((j["lines"][0]["quantity"], j["total"]), (3, 19.5))
        db = app.connect()
        n = db.execute("SELECT COUNT(*) FROM Purchase_Item WHERE purchase_id=?", (j["purchase_id"],)).fetchone()[0]
        db.close()
        self.assertEqual(n, 1)

    def test_46_price_from_browser_is_ignored(self):
        s, j = self.buy([{"product_id": 2, "quantity": 2, "price": 0.01}, {"product_id": 3, "quantity": 1, "unit_price": 0}])
        self.assertEqual(s, 201)
        self.assertEqual(j["total"], 17.0)              # 2 x 6.50 + 1 x 4.00 from the database

    def test_47_bad_points_to_use_refused(self):
        before = self.state()
        for bad in (-5, 1.5, True, "abc", [10]):
            s, _ = self.buy([{"product_id": 1, "quantity": 1}], customer_id=1, points_to_use=bad)
            self.assertEqual(s, 400, repr(bad))
        self.assertEqual(self.state(), before)

    def test_48_not_enough_points_rolls_back(self):
        db = app.connect()
        pts = db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=3").fetchone()[0]
        stock = db.execute("SELECT stock_qty FROM Product WHERE product_id=1").fetchone()[0]
        db.close()
        s, j = self.buy([{"product_id": 1, "quantity": 3}], points_to_use=pts + 1)   # $54: up to 1620 points allowed by the 30 % rule
        self.assertEqual((s, j["error"]), (409, "Not enough bonus points"))
        db = app.connect()
        after = (db.execute("SELECT loyalty_points FROM Customer WHERE customer_id=3").fetchone()[0],
                 db.execute("SELECT stock_qty FROM Product WHERE product_id=1").fetchone()[0])
        db.close()
        self.assertEqual(after, (pts, stock))

    def test_49_points_log_rows_written_for_purchase(self):
        s, j = self.buy([{"product_id": 2, "quantity": 1}], customer_id=2, points_to_use=10)
        self.assertEqual(s, 201)
        s, hist = self.emp.call("GET", "/api/points-log?customer_id=2")
        rows = {r["reason"]: r for r in hist if r["purchase_id"] == j["purchase_id"]}
        self.assertEqual(rows["spent"]["points_change"], -10)
        self.assertEqual(rows["earned"]["points_change"], j["points_earned"])
        s, checks = self.mgr.call("GET", "/api/report/checks")
        self.assertEqual(checks["points_mismatches"], [])   # balance still equals the ledger

    # --- Points history, reports, session, notes, merge (Tests 50-56) ---
    def test_50_points_log_bad_or_unknown_customer(self):
        self.assertEqual(self.emp.call("GET", "/api/points-log?customer_id=abc")[0], 400)
        self.assertEqual(self.emp.call("GET", "/api/points-log?customer_id=777")[0], 404)

    def test_51_report_bad_month_format_refused(self):
        for m in ("2026-13", "2026-1", "october", ""):
            self.assertEqual(self.mgr.call("GET", f"/api/report/top?month={m}")[0], 400, m)

    def test_52_report_month_without_purchases_is_empty(self):
        s, j = self.mgr.call("GET", "/api/report/top?month=2025-01")
        self.assertEqual((s, j), (200, []))

    def test_53_logout_ends_employee_session(self):
        cli = Api(self.base)
        self.assertEqual(cli.login("aruzhan", "cashier123")[0], 200)
        self.assertEqual(cli.call("GET", "/api/products")[0], 200)
        self.assertEqual(cli.call("POST", "/api/logout", {})[0], 200)
        self.assertEqual(cli.call("GET", "/api/products")[0], 401)

    def test_54_me_shows_role_without_internal_fields(self):
        s, j = self.mgr.call("GET", "/api/me")
        self.assertEqual((s, j["role"], j["username"]), (200, "Manager", "daniyar"))
        self.assertNotIn("last_seen", j)
        self.assertNotIn("password_hash", j)

    def test_55_customer_note_empty_or_too_long_refused(self):
        self.assertEqual(self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "   "})[0], 400)
        self.assertEqual(self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "x" * 256})[0], 400)
        self.assertEqual(self.emp.call("POST", "/api/customer/notes", {"customer_id": 1, "note": "x" * 255})[0], 201)

    def test_56_merge_with_self_or_unknown_customer_refused(self):
        s, j = self.mgr.call("POST", "/api/admin/merge-customers", {"source_id": 2, "target_id": 2})
        self.assertEqual(s, 400)
        s, j = self.mgr.call("POST", "/api/admin/merge-customers", {"source_id": 777, "target_id": 2})
        self.assertEqual((s, j["error"]), (404, "Customer not found"))
        self.assertEqual(self.emp.call("GET", "/api/customer?phone=%2B7%20700%20000%2001%2002")[0], 200)   # customer 2 still there

class DiscountBusinessLogicTests(unittest.TestCase):
    """Unit tests for the loyalty-discount business rule."""

    def test_no_discount_when_order_is_below_5000(self):
        self.assertEqual(
            app.calculate_discount(Decimal("4999.99"), 500000),
            Decimal("0.00"),
        )

    def test_no_discount_when_bonus_value_is_exactly_30_percent(self):
        # 150,000 points * $0.01 = $1,500 = exactly 30% of $5,000.
        self.assertEqual(
            app.calculate_discount(Decimal("5000.00"), 150000),
            Decimal("0.00"),
        )

    def test_discount_when_bonus_value_is_more_than_30_percent(self):
        # 150,001 points = $1,500.01, strictly above 30%.
        self.assertEqual(
            app.calculate_discount(Decimal("5000.00"), 150001),
            Decimal("500.00"),
        )

    def test_discount_for_order_above_5000(self):
        self.assertEqual(
            app.calculate_discount(Decimal("10000.00"), 300001),
            Decimal("1000.00"),
        )

    def test_no_discount_when_bonus_balance_is_too_low(self):
        self.assertEqual(
            app.calculate_discount(Decimal("5000.00"), 100000),
            Decimal("0.00"),
        )

    def test_order_exactly_5000_is_eligible_if_bonus_threshold_is_met(self):
        self.assertEqual(
            app.calculate_discount(Decimal("5000.00"), 150100),
            Decimal("500.00"),
        )

    def test_whole_keeps_existing_round_down_behavior(self):
        self.assertEqual(app.whole(Decimal("12.99")), 12)

    def test_points_rules_exposes_discount_configuration(self):
        rules = app.points_rules()
        self.assertEqual(rules["min_discount_order"], "5000.00")
        self.assertEqual(rules["discount_bonus_share"], "0.30")
        self.assertEqual(rules["discount_rate"], "0.10")

if __name__ == "__main__":
    unittest.main(verbosity=2)