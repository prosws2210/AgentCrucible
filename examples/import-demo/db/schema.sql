CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id INTEGER, item TEXT, total REAL, status TEXT);
CREATE TABLE refunds (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, amount REAL, reason TEXT);

INSERT INTO customers VALUES (1, 'Asha Rao', 'asha@example.com');
INSERT INTO orders VALUES ('A-1001', 1, 'Wireless Mouse', 49.99, 'delivered');
INSERT INTO orders VALUES ('A-1002', 1, 'USB-C Hub', 29.5, 'processing');
