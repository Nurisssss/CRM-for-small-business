INSERT INTO Customer (customer_id, full_name, phone, email, loyalty_points, last_updated) VALUES 
(1, 'Aigerim Nurova', '+7 700 000 01 01', 'aigerim@example.com', 121, '2026-10-22'),
(2, 'Dana Serik', '+7 700 000 01 02', 'dana@example.com', 72, '2026-10-22'),
(3, 'Timur Bek', '+7 700 000 01 03', NULL, 18, '2026-10-15'),
(4, 'Madina Omar', '+7 700 000 01 04', 'madina@example.com', 18, '2026-09-28'),
(77, 'Test Refused Customer', '+7 700 000 77 77', 'refused@example.com', 0, '2026-11-04');

INSERT INTO Employee (employee_id, full_name, role, username, password_hash) VALUES 
(1, 'Aknur K.', 'Employee', 'aknur', 'hash1'),
(2, 'Daniyar S.', 'Manager', 'daniyar', 'hash2');

INSERT INTO Product (product_id, product_name, category, price, stock_qty) VALUES 
(1, 'Coffee beans 1 kg', 'Coffee', 18.00, 40),
(2, 'Tea box', 'Tea', 6.50, 60),
(3, 'Mug', 'Accessories', 4.00, 25);

INSERT INTO Purchase (purchase_id, customer_id, employee_id, purchase_date, total_amount, payment_status, payment_ref) VALUES 
(1, 1, 1, '2026-10-03 11:20', 36.00, 'approved', 'TX1001'),
(2, 2, 1, '2026-10-05 15:05', 23.50, 'approved', 'TX1002'),
(3, 3, 1, '2026-10-12 12:40', 21.00, 'approved', 'TX1003'),
(4, 4, 1, '2026-10-15 17:10', 18.00, 'approved', 'TX1004'),
(5, 1, 1, '2026-10-20 10:30', 4.00, 'approved', 'TX1005'),
(6, 4, 1, '2026-09-28 13:00', 18.00, 'approved', 'TX0998'),
(7, 2, 1, '2026-10-22 16:45', 24.50, 'approved', 'TX1006'),
(8, 3, 1, '2026-10-25 18:20', 6.50, 'declined', 'TX1007');

INSERT INTO Purchase_Item (purchase_id, product_id, quantity, unit_price) VALUES 
(1, 1, 2, 18.00),
(2, 2, 3, 6.50),
(2, 3, 1, 4.00),
(3, 1, 1, 18.00),
(3, 2, 2, 6.50),
(3, 3, 2, 4.00),
(4, 1, 1, 18.00),
(5, 3, 1, 4.00),
(6, 1, 1, 18.00),
(7, 1, 1, 18.00),
(7, 2, 1, 6.50),
(8, 2, 1, 6.50);

INSERT INTO Customer_Note (customer_id, employee_id, note_text) VALUES 
(1, 1, 'Prefers to be contacted by phone, not email.'),
(2, 1, 'Asked about a discount for bulk orders.'),
(3, 1, 'Complained about a late delivery; offered 50 bonus points.'),
(77, 1, 'This note should be refused.');