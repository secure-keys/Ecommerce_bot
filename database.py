import sqlite3
import os

def init_db():
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT UNIQUE NOT NULL,
            colour_flavour TEXT,
            price REAL,
            image_path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            user_id INTEGER,
            sku TEXT,
            quantity INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, sku)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            total REAL,
            status TEXT,
            proof_path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            order_id INTEGER,
            sku TEXT,
            quantity INTEGER,
            price REAL,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        )
    ''')
    conn.commit()
    conn.close()

def add_product(name, sku, colour_flavour, price, image_path):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO products (name, sku, colour_flavour, price, image_path) VALUES (?, ?, ?, ?, ?)',
                   (name, sku, colour_flavour, price, image_path))
    conn.commit()
    conn.close()

def remove_product(sku):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM products WHERE sku = ?', (sku,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        return None
    name = product[0]
    cursor.execute('DELETE FROM products WHERE sku = ?', (sku,))
    cursor.execute('DELETE FROM cart WHERE sku = ?', (sku,))
    conn.commit()
    conn.close()
    return name

def search_products(query, user_id):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name, sku, colour_flavour, price, image_path FROM products WHERE name LIKE ?', (f'%{query}%',))
    products = cursor.fetchall()
    cursor.execute('SELECT sku FROM cart WHERE user_id = ?', (user_id,))
    cart_skus = {row[0] for row in cursor.fetchall()}
    conn.close()
    return [(name, sku, colour_flavour, price, image_path, sku in cart_skus) for name, sku, colour_flavour, price, image_path in products]

def toggle_cart(user_id, sku, add=True, quantity=1):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    if add:
        cursor.execute('INSERT OR REPLACE INTO cart (user_id, sku, quantity) VALUES (?, ?, ?)', (user_id, sku, quantity))
    else:
        cursor.execute('DELETE FROM cart WHERE user_id = ? AND sku = ?', (user_id, sku))
    conn.commit()
    conn.close()

def get_cart(user_id):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.name, p.sku, p.colour_flavour, p.price, c.quantity, p.image_path
        FROM cart c
        JOIN products p ON c.sku = p.sku
        WHERE c.user_id = ?
    ''', (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def remove_cart_item_by_index(user_id, index):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('SELECT sku FROM cart WHERE user_id = ?', (user_id,))
    skus = [row[0] for row in cursor.fetchall()]
    conn.close()
    if 1 <= index <= len(skus):
        sku = skus[index - 1]
        toggle_cart(user_id, sku, False)
        return True
    return False

def create_order(user_id, username, total, items, proof_path=None):
    conn = sqlite3.connect('products.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO orders (user_id, username, total, status, proof_path) VALUES (?, ?, ?, ?, ?)',
                   (user_id, username, total, 'pending', proof_path))
    order_id = cursor.lastrowid
    for sku, quantity, price in items:
        cursor.execute('INSERT INTO order_items (order_id, sku, quantity, price) VALUES (?, ?, ?, ?)',
                       (order_id, sku, quantity, price))
    cursor.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return order_id