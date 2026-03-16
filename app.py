from flask import Flask, request, jsonify, session, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
import hashlib
import os
import secrets
import sys
import io

sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app, supports_credentials=True, origins=["http://localhost:3000"])

DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'template.xlsx')

# ─── Roles ───────────────────────────────────────────────────────────────────
# admin   → бүх зүйл хийх боломжтой
# manager → бараа нэмэх, засах, зарлага, орлого оруулах боломжтой (устгах БҮҮ)
# user    → зөвхөн зарлага/орлого оруулах боломжтой (харах + гүйлгээ хийх)

ROLE_LEVELS = {'user': 1, 'manager': 2, 'admin': 3}


def has_role(min_role: str) -> bool:
    return ROLE_LEVELS.get(session.get('role', ''), 0) >= ROLE_LEVELS[min_role]


def login_required():
    return 'user_id' in session


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user'
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT DEFAULT '',
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
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transaction_bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('in','out')),
            total_amount REAL DEFAULT 0,
            note TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    ''')

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

    # Keep legacy transactions table for now but we will migrate it
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('in','out')),
            quantity INTEGER NOT NULL,
            note TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    ''')

    # Migrate: add new columns to existing products table if missing
    existing_cols = [row[1] for row in c.execute('PRAGMA table_info(products)').fetchall()]
    for col, coltype in [('brand', 'TEXT DEFAULT ""'), ('barcode', 'TEXT DEFAULT ""'), ('unit', 'TEXT DEFAULT ""'), ('price_cn', 'REAL DEFAULT 0'), ('pack_qty', 'INTEGER DEFAULT 0'), ('has_vat', 'INTEGER DEFAULT 0'), ('location', 'TEXT DEFAULT "Үндсэн Агуулах"'), ('location_id', 'INTEGER')]:
        if col not in existing_cols:
            c.execute(f'ALTER TABLE products ADD COLUMN {col} {coltype}')

    # Ensure default location exists
    c.execute('SELECT * FROM locations WHERE name = ?', ('Үндсэн Агуулах',))
    if not c.fetchone():
        c.execute('INSERT INTO locations (name, description) VALUES (?, ?)', ('Үндсэн Агуулах', 'Админаас үүсгэсэн үндсэн агуулах'))
    
    default_loc = c.execute('SELECT id FROM locations WHERE name = ?', ('Үндсэн Агуулах',)).fetchone()
    if default_loc:
        c.execute('UPDATE products SET location_id = ? WHERE location_id IS NULL', (default_loc['id'],))

    # Populate brands from existing products
    c.execute('SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != ""')
    existing_brands = c.fetchall()
    for b in existing_brands:
        c.execute('INSERT OR IGNORE INTO brands (name) VALUES (?)', (b['brand'],))

    # Data Migration: Migrate legacy transactions to bundles
    legacy_txs = c.execute('SELECT * FROM transactions').fetchall()
    if legacy_txs:
        for tx in legacy_txs:
            # Check if already migrated (this is a simple heuristic)
            # Actually, let's just create a bundle for each legacy transaction to be safe
            p = c.execute('SELECT price FROM products WHERE id = ?', (tx['product_id'],)).fetchone()
            price = p['price'] if p else 0
            total = tx['quantity'] * price
            
            c.execute('INSERT INTO transaction_bundles (id, type, total_amount, note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                      (tx['id'], tx['type'], total, tx['note'], tx['created_by'], tx['created_at']))
            c.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                      (tx['id'], tx['product_id'], tx['quantity'], price, 0))
        
        # Clear legacy transactions to avoid double migration next time
        c.execute('DELETE FROM transactions')

    # Migrate categories from existing products to new table
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


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': 'Нэвтрэх нэр болон нууц үг оруулна уу'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?',
                        (username, hash_password(password))).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({'message': 'Амжилттай нэвтэрлээ', 'username': user['username'], 'role': user['role']})
    return jsonify({'error': 'Нэвтрэх нэр эсвэл нууц үг буруу байна'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Гарлаа'})


@app.route('/api/me', methods=['GET'])
def me():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    return jsonify({'username': session['username'], 'role': session['role']})


@app.route('/api/change-password', methods=['POST'])
def change_password():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    data = request.get_json()
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if not old_pw or not new_pw:
        return jsonify({'error': 'Мэдээлэл дутуу'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'Нууц үг хамгийн багадаа 6 тэмдэгтэй байна'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ? AND password = ?',
                        (session['user_id'], hash_password(old_pw))).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'Хуучин нууц үг буруу байна'}), 401
    conn.execute('UPDATE users SET password = ? WHERE id = ?',
                 (hash_password(new_pw), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Нууц үг амжилттай солигдлоо'})


# ─── Users (admin only) ───────────────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
def get_users():
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    conn = get_db()
    users = conn.execute('SELECT id, username, role FROM users ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/users', methods=['POST'])
def add_user():
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')
    if role not in ('user', 'manager', 'admin'):
        return jsonify({'error': 'Буруу эрх'}), 400
    if not username or not password:
        return jsonify({'error': 'Мэдээлэл дутуу байна'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Нууц үг хамгийн багадаа 6 тэмдэгт'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     (username, hash_password(password), role))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэвтрэх нэр аль хэдийн байна'}), 409
    conn.close()
    return jsonify({'message': 'Хэрэглэгч нэмэгдлээ'}), 201


@app.route('/api/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    if uid == session['user_id']:
        return jsonify({'error': 'Өөрийгөө устгах боломжгүй'}), 400
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id = ?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Устгагдлаа'})


@app.route('/api/users/<int:uid>/role', methods=['PUT'])
def change_user_role(uid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    if uid == session['user_id']:
        return jsonify({'error': 'Өөрийн эрхийг өөрчлөх боломжгүй'}), 400
    data = request.get_json()
    role = data.get('role', '')
    if role not in ('user', 'manager', 'admin'):
        return jsonify({'error': 'Буруу эрх'}), 400
    conn = get_db()
    conn.execute('UPDATE users SET role = ? WHERE id = ?', (role, uid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Эрх өөрчлөгдлөө'})


# ─── Products ─────────────────────────────────────────────────────────────────

@app.route('/api/products', methods=['GET'])
def get_products():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    location_id = request.args.get('location_id')
    
    conn = get_db()
    query = '''
        SELECT p.*, l.name as location_name 
        FROM products p
        LEFT JOIN locations l ON p.location_id = l.id
        WHERE 1=1
    '''
    params = []
    if search:
        query += ' AND (p.name LIKE ? OR p.description LIKE ? OR p.brand LIKE ? OR p.barcode LIKE ?)'
        params += [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%']
    if category:
        query += ' AND p.category = ?'
        params.append(category)
    if location_id:
        query += ' AND p.location_id = ?'
        params.append(location_id)
        
    query += ' ORDER BY p.name ASC'
    products = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])


@app.route('/api/products', methods=['POST'])
def add_product():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Бараа нэмэх эрх байхгүй (manager эсвэл admin шаардлагатай)'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Барааны нэр заавал оруулна уу'}), 400
    brand = data.get('brand', '').strip()
    barcode = data.get('barcode', '').strip()
    unit = data.get('unit', '').strip()
    category = data.get('category', '').strip()
    pack_qty = max(0, int(data.get('pack_qty', 0)))
    quantity = max(0, int(data.get('quantity', 0)))
    price = max(0.0, float(data.get('price', 0)))
    price_cn = max(0.0, float(data.get('price_cn', 0)))
    has_vat = 1 if data.get('has_vat') else 0
    location_id = data.get('location_id')
    description = data.get('description', '').strip()
    
    conn = get_db()
    # If location_id is not provided, try to find default
    if not location_id:
        loc = conn.execute('SELECT id FROM locations LIMIT 1').fetchone()
        location_id = loc['id'] if loc else None

    conn.execute('INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа нэмэгдлээ'}), 201


@app.route('/api/products/<int:pid>', methods=['PUT'])
def update_product(pid):
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Бараа засах эрх байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Барааны нэр заавал оруулна уу'}), 400
    brand = data.get('brand', '').strip()
    barcode = data.get('barcode', '').strip()
    unit = data.get('unit', '').strip()
    category = data.get('category', '').strip()
    pack_qty = max(0, int(data.get('pack_qty', 0)))
    quantity = max(0, int(data.get('quantity', 0)))
    price = max(0.0, float(data.get('price', 0)))
    price_cn = max(0.0, float(data.get('price_cn', 0)))
    has_vat = 1 if data.get('has_vat') else 0
    location_id = data.get('location_id')
    description = data.get('description', '').strip()
    conn = get_db()
    conn.execute('UPDATE products SET name=?, brand=?, barcode=?, unit=?, category=?, pack_qty=?, quantity=?, price=?, price_cn=?, has_vat=?, location_id=?, description=? WHERE id=?',
                 (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, pid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа шинэчлэгдлээ'})


@app.route('/api/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Бараа устгах эрх байхгүй (admin шаардлагатай)'}), 403
    conn = get_db()
    conn.execute('DELETE FROM products WHERE id = ?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа устгагдлаа'})


@app.route('/api/categories', methods=['GET'])
def get_categories_db():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    conn = get_db()
    cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(c) for c in cats])


@app.route('/api/categories', methods=['POST'])
def add_category():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    desc = data.get('description', '').strip()
    if not name:
        return jsonify({'error': 'Нэр оруулна уу'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэртэй ангилал аль хэдийн байна'}), 409
    conn.close()
    return jsonify({'message': 'Ангилал нэмэгдлээ'}), 201


@app.route('/api/categories/<int:cid>', methods=['PUT'])
def update_category(cid):
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    desc = data.get('description', '').strip()
    if not name:
        return jsonify({'error': 'Нэр оруулна уу'}), 400
    conn = get_db()
    try:
        conn.execute('UPDATE categories SET name=? WHERE id=?', (name, cid))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэртэй ангилал аль хэдийн байна'}), 409
    conn.close()
    return jsonify({'message': 'Ангилал шинэчлэгдлээ'})


@app.route('/api/categories/<int:cid>', methods=['DELETE'])
def delete_category(cid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй (admin шаардлагатай)'}), 403
    conn = get_db()
    # Optional: check if any products use this category name?
    # For now, just delete the category from the list. 
    # Products store category as a string, so they won't break but might lose the reference in the list.
    conn.execute('DELETE FROM categories WHERE id = ?', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Ангилал устгагдлаа'})


@app.route('/api/locations', methods=['GET'])
def get_locations():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    conn = get_db()
    locs = conn.execute("SELECT * FROM locations ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(l) for l in locs])


@app.route('/api/locations', methods=['POST'])
def add_location():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    desc = data.get('description', '').strip()
    if not name:
        return jsonify({'error': 'Нэр оруулна уу'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO locations (name, description) VALUES (?, ?)', (name, desc))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэртэй агуулах аль хэдийн байна'}), 409
    conn.close()
    return jsonify({'message': 'Агуулах нэмэгдлээ'}), 201


@app.route('/api/locations/<int:lid>', methods=['DELETE'])
def delete_location(lid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй (admin шаардлагатай)'}), 403
    conn = get_db()
    # Check if any products are in this location
    count = conn.execute('SELECT COUNT(*) FROM products WHERE location_id = ?', (lid,)).fetchone()[0]
    if count > 0:
        conn.close()
        return jsonify({'error': f'Энэ агуулахад {count} бараа байгаа тул устгах боломжгүй'}), 400
    
    conn.execute('DELETE FROM locations WHERE id = ?', (lid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Агуулах устгагдлаа'})


# ─── Transactions (зарлага / орлого) ─────────────────────────────────────────

@app.route('/api/transactions', methods=['POST'])
def add_transaction_bundle():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    data = request.get_json()
    items = data.get('items', [])
    tx_type = data.get('type')  # 'in' or 'out'
    note = data.get('note', '').strip()

    if not items or tx_type not in ('in', 'out'):
        return jsonify({'error': 'Мэдээлэл дутуу байна'}), 400

    conn = get_db()
    total_amount = 0
    
    try:
        # Validate all items first
        for item in items:
            p_id = item.get('product_id')
            qty = int(item.get('quantity', 0))
            if qty <= 0: continue
            
            product = conn.execute('SELECT quantity, name FROM products WHERE id = ?', (p_id,)).fetchone()
            if not product:
                raise ValueError(f'Бараа олдсонгүй (ID: {p_id})')
            
            if tx_type == 'out' and product['quantity'] < qty:
                raise ValueError(f"'{product['name']}' барааны үлдэгдэл хүрэлцэхгүй байна (Үлдэгдэл: {product['quantity']})")
            
            price = float(item.get('price', 0))
            total_amount += qty * price

        # Create Bundle
        cursor = conn.execute('INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
                             (tx_type, total_amount, note, session['user_id']))
        bundle_id = cursor.lastrowid

        # Process Items
        for item in items:
            p_id = item.get('product_id')
            qty = int(item.get('quantity', 0))
            if qty <= 0: continue
            
            price = float(item.get('price', 0))
            has_vat = 1 if item.get('has_vat') else 0
            
            delta = qty if tx_type == 'in' else -qty
            conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (delta, p_id))
            conn.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                         (bundle_id, p_id, qty, price, has_vat))
            
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 400

@app.route('/api/brands', methods=['GET'])
def get_brands():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    conn = get_db()
    brands = conn.execute('SELECT * FROM brands ORDER BY name ASC').fetchall()
    conn.close()
    return jsonify([dict(b) for b in brands])

@app.route('/api/brands', methods=['POST'])
def add_brand():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Брэндийн нэр хоосон байна'}), 400
    
    conn = get_db()
    try:
        conn.execute('INSERT INTO brands (name) VALUES (?)', (name,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Брэнд амжилттай үүсгэгдлээ'}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэртэй брэнд аль хэдийн байна'}), 409
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/brands/<int:bid>', methods=['PUT'])
def update_brand(bid):
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Нэр хоосон байна'}), 400
    
    conn = get_db()
    try:
        conn.execute('UPDATE brands SET name=? WHERE id=?', (name, bid))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Брэнд амжилттай шинэчлэгдлээ'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Ийм нэртэй брэнд аль хэдийн байна'}), 409
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/brands/<int:bid>', methods=['DELETE'])
def delete_brand(bid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй (admin шаардлагатай)'}), 403
    conn = get_db()
    try:
        conn.execute('DELETE FROM brands WHERE id=?', (bid,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Брэнд устгагдлаа'})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500
    action = 'Орлого' if tx_type == 'in' else 'Зарлага'
    return jsonify({'message': f'{action} амжилттай бүртгэгдлээ', 'bundle_id': bundle_id}), 201


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    tx_type = request.args.get('type', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    limit = min(int(request.args.get('limit', 100)), 500)

    conn = get_db()
    query = '''
        SELECT b.*, u.username as created_by 
        FROM transaction_bundles b
        JOIN users u ON b.created_by = u.id
        WHERE 1=1
    '''
    params = []
    if tx_type in ('in', 'out'):
        query += ' AND b.type = ?'
        params.append(tx_type)
    if start_date:
        query += ' AND DATE(b.created_at) >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND DATE(b.created_at) <= ?'
        params.append(end_date)
    query += ' ORDER BY b.created_at DESC LIMIT ?'
    params.append(limit)
    
    bundles = conn.execute(query, params).fetchall()
    result = []
    for b in bundles:
        bundle_dict = dict(b)
        items = conn.execute('''
            SELECT ti.*, p.name as product_name, p.brand, p.barcode
            FROM transaction_items ti
            JOIN products p ON ti.product_id = p.id
            WHERE ti.bundle_id = ?
        ''', (b['id'],)).fetchall()
        bundle_dict['items'] = [dict(i) for i in items]
        result.append(bundle_dict)
        
    conn.close()
    return jsonify(result)


# ─── Stats ────────────────────────────────────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
def get_stats():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    conn = get_db()
    total_products = conn.execute('SELECT COUNT(*) as c FROM products').fetchone()['c']
    total_qty = conn.execute('SELECT COALESCE(SUM(quantity),0) as s FROM products').fetchone()['s']
    total_value = conn.execute('SELECT COALESCE(SUM(quantity*price),0) as v FROM products').fetchone()['v']
    # Low stock: quantity < 20% of pack_qty (if pack_qty > 0) or quantity <= 5
    low_stock = conn.execute("SELECT COUNT(*) as c FROM products WHERE (pack_qty > 0 AND quantity < 0.2 * pack_qty) OR (pack_qty = 0 AND quantity <= 5)").fetchone()['c']
    
    # Revenue/Expense stats
    today_out = conn.execute("SELECT COALESCE(SUM(total_amount),0) as s FROM transaction_bundles WHERE type='out' AND date(created_at)=date('now')").fetchone()['s']
    today_in = conn.execute("SELECT COALESCE(SUM(total_amount),0) as s FROM transaction_bundles WHERE type='in' AND date(created_at)=date('now')").fetchone()['s']
    
    week_out = conn.execute("SELECT COALESCE(SUM(total_amount),0) as s FROM transaction_bundles WHERE type='out' AND date(created_at) >= date('now', '-7 days')").fetchone()['s']
    month_out = conn.execute("SELECT COALESCE(SUM(total_amount),0) as s FROM transaction_bundles WHERE type='out' AND date(created_at) >= date('now', '-30 days')").fetchone()['s']

    conn.close()
    return jsonify({
        'total_products': total_products,
        'total_quantity': total_qty,
        'total_value': round(total_value, 2),
        'low_stock': low_stock,
        'today_out_amount': today_out,
        'today_in_amount': today_in,
        'week_out_amount': week_out,
        'month_out_amount': month_out
    })


@app.route('/api/stats/revenue', methods=['GET'])
def get_stats_revenue():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    
    period = request.args.get('period', 'monthly')
    conn = get_db()
    
    if period == 'weekly':
        interval = '-7 days'
        group_by = "strftime('%Y-%m-%d', created_at)"
    elif period == 'annually':
        interval = '-1 year'
        group_by = "strftime('%Y-%m', created_at)"
    else:  # monthly
        interval = '-30 days'
        group_by = "strftime('%Y-%m-%d', created_at)"

    query = f'''
        SELECT {group_by} as day,
               SUM(CASE WHEN type='out' THEN total_amount ELSE 0 END) as income,
               SUM(CASE WHEN type='in' THEN total_amount ELSE 0 END) as expense
        FROM transaction_bundles
        WHERE created_at >= date('now', '{interval}')
        GROUP BY day
        ORDER BY day ASC
    '''
    rows = conn.execute(query).fetchall()
    
    # Distribution by Location
    loc_dist = conn.execute('''
        SELECT l.name, SUM(p.quantity * p.price) as value
        FROM products p
        JOIN locations l ON p.location_id = l.id
        GROUP BY l.name
    ''').fetchall()
    
    # Distribution by Category
    cat_dist = conn.execute('''
        SELECT category, SUM(quantity * price) as value
        FROM products p
        WHERE category != ''
        GROUP BY category
    ''').fetchall()
    
    conn.close()
    return jsonify({
        'revenue_chart': [dict(r) for r in rows],
        'location_distribution': [dict(l) for l in loc_dist],
        'category_distribution': [dict(c) for c in cat_dist]
    })

@app.route('/api/stats/product-trend', methods=['GET'])
def get_stats_product_trend():
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    
    period = request.args.get('period', 'monthly')
    conn = get_db()
    
    if period == 'weekly':
        interval = '-7 days'
        group_by = "strftime('%Y-%m-%d', created_at)"
    elif period == 'annually':
        interval = '-1 year'
        group_by = "strftime('%Y-%m', created_at)"
    else:  # monthly
        interval = '-30 days'
        group_by = "strftime('%Y-%m-%d', created_at)"

    query = f'''
        SELECT {group_by} as date, COUNT(*) as count
        FROM products
        WHERE created_at >= date('now', '{interval}')
        GROUP BY date
        ORDER BY date ASC
    '''
    rows = conn.execute(query).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─── Excel Import ─────────────────────────────────────────────────────────────

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def parse_excel(file_bytes):
    """Excel файл уншиж, мөр бүрийг dict болгон буцаана."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    header_row = None
    col_map = {}

    FIELD_ALIASES = {
        'name':     ['бараа нэр', 'нэр'],
        'unit':     ['нэгж'],
        'qty_new':  ['тоо ширхэг', 'тоо', 'ширхэг'],
        'qty_rem':  ['үлдэгдэл'],
        'price_cn': ['урдаас ирсэн үнэ юань', 'юань', 'үнэ юань'],
        'price':    ['төгрөг', 'үнэ төгрөг', 'мнт'],
        'brand':    ['брэнд'],
        'code':     ['бараа код', 'код'],
    }

    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), start=1):
        for col_idx, cell in enumerate(row, start=1):
            if cell is None:
                continue
            val = str(cell).strip().lower()
            for field, aliases in FIELD_ALIASES.items():
                if any(a in val for a in aliases):
                    if field not in col_map:
                        col_map[field] = col_idx
        if col_map.get('name'):
            header_row = row_idx
            break

    if not header_row or not col_map.get('name'):
        return None, '"Бараа нэр" гарчиг олдсонгүй. Excel файлаа шалгана уу.'

    rows = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        def g(field):
            idx = col_map.get(field)
            return row[idx - 1] if idx and idx <= len(row) else None

        name = g('name')
        if not name or str(name).strip() == '':
            continue
        name = str(name).strip()

        try:
            qty_new = int(float(g('qty_new') or 0))
        except (ValueError, TypeError):
            qty_new = 0
        try:
            qty_rem = int(float(g('qty_rem') or 0))
        except (ValueError, TypeError):
            qty_rem = qty_new
        try:
            price = float(g('price') or 0)
        except (ValueError, TypeError):
            price = 0.0

        brand = str(g('brand') or '').strip()
        unit = str(g('unit') or '').strip()
        code = g('code')
        code = str(int(code)) if code is not None else ''

        rows.append({
            'name': name,
            'brand': brand,
            'unit': unit,
            'code': code,
            'qty_new': qty_new,
            'qty_rem': qty_rem,
            'price': price,
        })

    return rows, None


@app.route('/api/import/products', methods=['POST'])
def import_products_excel():
    """Excel-ээс бараа импортлох (manager+)"""
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Эрх байхгүй'}), 403
    if 'file' not in request.files:
        return jsonify({'error': 'Файл олдсонгүй'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': 'Зөвхөн .xlsx файл зөвшөөрнө'}), 400
    if not HAS_OPENPYXL:
        return jsonify({'error': 'openpyxl суулгаагүй байна'}), 500

    file_bytes = f.read()
    rows, err = parse_excel(file_bytes)
    if err:
        return jsonify({'error': err}), 400

    mode = request.form.get('mode', 'skip')
    added = 0
    updated = 0
    skipped = 0
    errors = []

    conn = get_db()
    for r in rows:
        name = r['name']
        brand = r['brand'] or ''
        barcode = r['code'] or ''
        unit = r['unit'] or ''
        category = brand
        location = r.get('location', 'Үндсэн Агуулах') or 'Үндсэн Агуулах'
        desc = ''
        pack_qty = r['qty_new']  # Тоо Ширхэг = number of packages
        qty = r['qty_rem'] if r['qty_rem'] > 0 else r['qty_new']  # Үлдэгдэл = total items
        price = r['price']

        existing = conn.execute('SELECT * FROM products WHERE name = ? AND location = ?', (name, location)).fetchone()
        try:
            if existing:
                if mode == 'update':
                    conn.execute('UPDATE products SET brand=?, barcode=?, unit=?, category=?, pack_qty=?, quantity=?, price=?, description=? WHERE id=?',
                                 (brand, barcode, unit, category, pack_qty, qty, price, desc, existing['id']))
                    updated += 1
                elif mode == 'add':
                    conn.execute('INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, location, description) VALUES (?,?,?,?,?,?,?,?,?,?)',
                                 (name, brand, barcode, unit, category, pack_qty, qty, price, location, desc))
                    added += 1
                else:
                    skipped += 1
            else:
                conn.execute('INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, location, description) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (name, brand, barcode, unit, category, pack_qty, qty, price, location, desc))
                added += 1
        except Exception as ex:
            errors.append(f'{name}: {ex}')

    conn.commit()
    conn.close()

    return jsonify({
        'message': f'{added} бараа нэмэгдлээ, {updated} шинэчлэгдлээ, {skipped} алгасагдлаа',
        'added': added, 'updated': updated, 'skipped': skipped,
        'errors': errors[:10]
    })


@app.route('/api/import/transactions', methods=['POST'])
def import_transactions_excel():
    """Excel-ээс гүйлгээ (орлого/зарлага) импортлох"""
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'Файл олдсонгүй'}), 400
    f = request.files['file']
    if not f.filename.endswith('.xlsx'):
        return jsonify({'error': 'Зөвхөн .xlsx файл зөвшөөрнө'}), 400
    if not HAS_OPENPYXL:
        return jsonify({'error': 'openpyxl суулгаагүй байна'}), 500

    tx_type = request.form.get('type', 'in')
    if tx_type not in ('in', 'out'):
        return jsonify({'error': 'Төрөл буруу (in эсвэл out)'}), 400

    note = request.form.get('note', '').strip()

    file_bytes = f.read()
    rows, err = parse_excel(file_bytes)
    if err:
        return jsonify({'error': err}), 400

    added = 0
    skipped = 0
    not_found = []
    errors = []

    conn = get_db()
    for r in rows:
        name = r['name']
        qty = r['qty_new'] if tx_type == 'in' else r['qty_rem']
        if qty <= 0:
            qty = r['qty_new'] or r['qty_rem']
        if qty <= 0:
            skipped += 1
            continue

        product = conn.execute('SELECT * FROM products WHERE name = ?', (name,)).fetchone()
        if not product:
            not_found.append(name)
            skipped += 1
            continue

        if tx_type == 'out' and product['quantity'] < qty:
            errors.append(f'{name}: үлдэгдэл хүрэлцэхгүй ({product["quantity"]} < {qty})')
            skipped += 1
            continue

        try:
            delta = qty if tx_type == 'in' else -qty
            conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (delta, product['id']))
            conn.execute('INSERT INTO transactions (product_id, type, quantity, note, created_by) VALUES (?,?,?,?,?)',
                         (product['id'], tx_type, qty, note or 'Excel импорт', session['user_id']))
            added += 1
        except Exception as ex:
            errors.append(f'{name}: {ex}')
            skipped += 1

    conn.commit()
    conn.close()

    action = 'Орлого' if tx_type == 'in' else 'Зарлага'
    msg = f'{action}: {added} бараа бүртгэгдлээ'
    if skipped:
        msg += f', {skipped} алгасагдлаа'

    return jsonify({
        'message': msg,
        'added': added, 'skipped': skipped,
        'not_found': not_found[:20],
        'errors': errors[:10]
    })


# ─── Excel Export ─────────────────────────────────────────────────────────────

@app.route('/api/export/products', methods=['GET'])
def export_products():
    """Бүх барааг Excel файлаар татах"""
    if not login_required():
        return jsonify({'error': 'Нэвтрээгүй байна'}), 401
    if not HAS_OPENPYXL:
        return jsonify({'error': 'openpyxl суулгаагүй байна'}), 500

    conn = get_db()
    products = conn.execute('SELECT * FROM products ORDER BY name ASC').fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Барааны жагсаалт'

    headers = ['№', 'Брэнд', 'Бараа код', 'Бараа нэр', 'Агуулах', 'Нэгж', 'Тоо Ширхэг', 'Үлдэгдэл', 'Урдаас ирсэн үнэ Юань', 'Төгрөг', 'НӨАТ', 'Нийт үнэ (₮)', 'Огноо']
    ws.append(headers)

    # Style header
    from openpyxl.styles import Font, PatternFill, Alignment
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')
    for col_idx, cell in enumerate(ws[1], 1):
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    for i, p in enumerate(products, 1):
        ws.append([
            i,
            p['brand'] or '',
            p['barcode'] or '',
            p['name'],
            p['location'] or 'Үндсэн Агуулах',
            p['unit'] or '',
            p['pack_qty'] or 0,
            p['quantity'],
            p['price_cn'] or 0,
            p['price'],
            'Тийм' if p['has_vat'] else 'Үгүй',
            round(p['quantity'] * p['price'], 2),
            p['created_at'] or ''
        ])

    # Auto-width
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 40)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='products_export.xlsx'
    )


# ─── Template Download ────────────────────────────────────────────────────────

@app.route('/api/template', methods=['GET'])
def download_template():
    """Import template файл татах"""
    if os.path.exists(TEMPLATE_PATH):
        return send_file(TEMPLATE_PATH, as_attachment=True, download_name='template.xlsx')
    # Generate template on the fly
    if not HAS_OPENPYXL:
        return jsonify({'error': 'openpyxl суулгаагүй байна'}), 500

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Бараа импорт'

    from openpyxl.styles import Font, PatternFill, Alignment
    headers = ['Бараа нэр', 'Брэнд', 'Нэгж', 'Бараа код', 'Тоо Ширхэг', 'Үлдэгдэл', 'Төгрөг']
    ws.append(headers)

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    # Example rows
    ws.append(['Жишээ бараа 1', 'Samsung', 'ширхэг', '001', 10, 10, 50000])
    ws.append(['Жишээ бараа 2', 'LG', 'хайрцаг', '002', 5, 5, 120000])

    for col in ws.columns:
        col_letter = col[0].column_letter
        ws.column_dimensions[col_letter].width = 18

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='template.xlsx')


if __name__ == '__main__':
    init_db()
    print("Server started: http://localhost:5000")
    # Admin login info removed for security
    print("Roles: admin > manager > user")
    app.run(debug=True, port=5000)
