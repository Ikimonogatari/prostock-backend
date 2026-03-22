import sqlite3
import os
import hashlib
from flask import current_app

def get_db():
    conn = sqlite3.connect(current_app.config['DB_PATH'])
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    db_path = current_app.config['DB_PATH']
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    ''')

    # Locations table
    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Categories table
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    # Brands table
    c.execute('''
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    # Products table
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT DEFAULT '',
            product_code TEXT DEFAULT '',
            barcode TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            category TEXT,
            pack_qty INTEGER DEFAULT 0,
            quantity INTEGER DEFAULT 0,
            price REAL DEFAULT 0,
            price_cn REAL DEFAULT 0,
            has_vat INTEGER DEFAULT 0,
            location_id INTEGER,
            location TEXT DEFAULT 'Үндсэн Агуулах',
            image TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    ''')

    # Transaction bundles table
    c.execute('''
        CREATE TABLE IF NOT EXISTS transaction_bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('in','out','fix','move')),
            total_amount REAL DEFAULT 0,
            note TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    ''')

    # Migration: rebuild transaction_bundles if 'move' type is not in the CHECK constraint
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='transaction_bundles'").fetchone()
    if row and "'move'" not in row[0]:
        c.execute('ALTER TABLE transaction_bundles RENAME TO _transaction_bundles_old')
        c.execute('''
            CREATE TABLE transaction_bundles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL CHECK(type IN ('in','out','fix','move')),
                total_amount REAL DEFAULT 0,
                note TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
        ''')
        c.execute('INSERT INTO transaction_bundles SELECT * FROM _transaction_bundles_old')
        c.execute('DROP TABLE _transaction_bundles_old')

    # Transaction items table
    c.execute('''
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL DEFAULT 0,
            has_vat INTEGER DEFAULT 0,
            FOREIGN KEY(bundle_id) REFERENCES transaction_bundles(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    ''')

    # Ensure default location exists
    c.execute('SELECT * FROM locations WHERE name = ?', ('Үндсэн Агуулах',))
    if not c.fetchone():
        c.execute('INSERT INTO locations (name, description) VALUES (?, ?)', 
                  ('Үндсэн Агуулах', 'Админаас үүсгэсэн үндсэн агуулах'))
    
    # Handle missing/renamed columns (Migration)
    existing_cols = [row[1] for row in c.execute('PRAGMA table_info(products)').fetchall()]
    
    # 1. Check if we need to rename barcode to product_code
    if 'barcode' in existing_cols and 'product_code' not in existing_cols:
        try:
            # Rename barcode to product_code
            c.execute('ALTER TABLE products RENAME COLUMN barcode TO product_code')
            print("Renamed 'barcode' column to 'product_code'")
            # Refresh existing_cols after rename
            existing_cols = [row[1] for row in c.execute('PRAGMA table_info(products)').fetchall()]
        except Exception as e:
            print(f"Migration error renaming barcode: {e}")

    migration_cols = [
        ('brand', 'TEXT DEFAULT ""'), 
        ('product_code', 'TEXT DEFAULT ""'), 
        ('barcode', 'TEXT DEFAULT ""'), 
        ('unit', 'TEXT DEFAULT ""'), 
        ('price_cn', 'REAL DEFAULT 0'), 
        ('pack_qty', 'INTEGER DEFAULT 0'), 
        ('has_vat', 'INTEGER DEFAULT 0'), 
        ('location', 'TEXT DEFAULT "Үндсэн Агуулах"'), 
        ('location_id', 'INTEGER'),
        ('image', 'TEXT')
    ]
    for col, coltype in migration_cols:
        if col not in existing_cols:
            try:
                c.execute(f'ALTER TABLE products ADD COLUMN {col} {coltype}')
            except Exception as e:
                print(f"Migration error for {col}: {e}")

    # Set default location for products if null
    default_loc = c.execute('SELECT id FROM locations WHERE name = ?', ('Үндсэн Агуулах',)).fetchone()
    if default_loc:
        c.execute('UPDATE products SET location_id = ? WHERE location_id IS NULL', (default_loc['id'],))

    # Populate brands from existing products
    c.execute('SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != ""')
    existing_brands = c.fetchall()
    for b in existing_brands:
        c.execute('INSERT OR IGNORE INTO brands (name) VALUES (?)', (b['brand'],))

    # Populate categories from existing products
    existing_cats = c.execute('SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ""').fetchall()
    for row in existing_cats:
        c.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (row['category'],))

    # Default admin
    c.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not c.fetchone():
        c.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                  ('admin', hash_password('admin' + '123'), 'admin'))

    conn.commit()
    conn.close()
