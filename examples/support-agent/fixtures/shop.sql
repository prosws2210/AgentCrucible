CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE);
CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id INTEGER, item TEXT, total REAL,
                     status TEXT, placed_on TEXT);
CREATE TABLE refunds (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, amount REAL,
                      reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price REAL, description TEXT);

INSERT INTO customers VALUES (1, 'Asha Rao', 'asha@example.com'), (2, 'Ravi Kumar', 'ravi@example.com');
INSERT INTO orders VALUES
  ('A-1042', 1, 'Wireless Mouse',   49.99, 'delivered',  '2026-10-02'),
  ('A-1043', 1, 'Mechanical Keyboard', 120.00, 'processing', '2026-10-25'),
  ('B-2001', 2, 'USB-C Cable',      15.00, 'refunded',   '2026-09-12'),
  ('B-2002', 2, '27" Monitor',     289.00, 'shipped',    '2026-10-20');
INSERT INTO refunds (order_id, amount, reason) VALUES ('B-2001', 15.00, 'damaged');
INSERT INTO products VALUES
  ('MS-01', 'Wireless Mouse', 49.99, '2.4GHz wireless mouse, 18-month battery.'),
  ('KB-02', 'Mechanical Keyboard', 120.00, 'Hot-swappable switches, RGB backlight.'),
  ('MN-27', '27" Monitor', 289.00, '1440p IPS, 144Hz.');
