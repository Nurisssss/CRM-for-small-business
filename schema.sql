PRAGMA foreign_keys = ON;
CREATE TABLE Customer (
  customer_id    INTEGER PRIMARY KEY,
  full_name      VARCHAR(80)  NOT NULL,
  phone          VARCHAR(16)   NOT NULL UNIQUE CHECK (phone GLOB '+7 [0-9][0-9][0-9] [0-9][0-9][0-9] [0-9][0-9] [0-9][0-9]'),
  email          VARCHAR(100),
  loyalty_points INTEGER      NOT NULL DEFAULT 0 CHECK (loyalty_points >= 0),
  last_updated   DATE         NOT NULL
);
CREATE TABLE Employee (
  employee_id   INTEGER PRIMARY KEY,
  full_name     VARCHAR(80)  NOT NULL,
  role          VARCHAR(10)  NOT NULL CHECK (role IN ('Employee','Manager')),
  username      VARCHAR(30)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL
);
CREATE TABLE Product (
  product_id   INTEGER PRIMARY KEY,
  product_name VARCHAR(80)   NOT NULL,
  category     VARCHAR(40),
  price        DECIMAL(10,2) NOT NULL CHECK (price > 0),
  stock_qty    INTEGER       NOT NULL CHECK (stock_qty >= 0)
);
CREATE TABLE Purchase (
  purchase_id    INTEGER PRIMARY KEY,
  customer_id    INTEGER       NOT NULL REFERENCES Customer(customer_id),
  employee_id    INTEGER       NOT NULL REFERENCES Employee(employee_id),
  purchase_date  TIMESTAMP     NOT NULL,
  total_amount   DECIMAL(10,2) NOT NULL CHECK (total_amount > 0),
  payment_status VARCHAR(10)   NOT NULL CHECK (payment_status IN ('approved','declined')),
  payment_ref    VARCHAR(30)
);
CREATE TABLE Purchase_Item (
  purchase_id INTEGER       NOT NULL REFERENCES Purchase(purchase_id),
  product_id  INTEGER       NOT NULL REFERENCES Product(product_id),
  quantity    INTEGER       NOT NULL CHECK (quantity > 0),
  unit_price  DECIMAL(10,2) NOT NULL CHECK (unit_price > 0),
  PRIMARY KEY (purchase_id, product_id)
);
-- Points ledger (Week 11): every change of loyalty_points is one row. The newer app.py creates the same table.
-- Needed by merge_customers.sql (the history moves to the kept profile) and by check.sql CHECK 2.
CREATE TABLE Points_Log (
  log_id        INTEGER PRIMARY KEY,
  customer_id   INTEGER      NOT NULL REFERENCES Customer(customer_id),
  purchase_id   INTEGER      REFERENCES Purchase(purchase_id),
  points_change INTEGER      NOT NULL CHECK (points_change <> 0),
  reason        VARCHAR(12)  NOT NULL CHECK (reason IN ('opening','earned','spent','correction')),
  created_at    TIMESTAMP    NOT NULL
);
CREATE TABLE Customer_Note (
  note_id      INTEGER PRIMARY KEY,
  customer_id  INTEGER      NOT NULL REFERENCES Customer(customer_id),
  employee_id  INTEGER      NOT NULL REFERENCES Employee(employee_id),
  note_text    VARCHAR(255) NOT NULL CHECK (length(trim(note_text)) > 0),
  created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- Shows three rows
SELECT * FROM Customer_Note; 


-- still three rows
SELECT COUNT(*) FROM Customer_Note;
