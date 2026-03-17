from flask import Blueprint, request, jsonify, current_app, session
from app.database import get_db
from app.utils import login_required, unauthorized, has_role, safe_int, safe_float
import os
import secrets

products_bp = Blueprint('products', __name__)

def safe_delete_image(conn, image_filename):
    if not image_filename: return
    try:
        count_row = conn.execute('SELECT COUNT(*) as c FROM products WHERE image=?', (image_filename,)).fetchone()
        if count_row and count_row['c'] == 0:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], image_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
    except Exception as e:
        print(f"Error checking/deleting orphaned image {image_filename}: {e}")

@products_bp.route('/products', methods=['GET'])
def get_products():
    if not login_required():
        return unauthorized()
    
    search = request.args.get('search', '')
    cat = request.args.get('category', '')
    loc = request.args.get('location', '')
    
    conn = get_db()
    query = 'SELECT * FROM products WHERE 1=1'
    params = []
    
    if search:
        query += ' AND (name LIKE ? OR barcode LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    if cat:
        query += ' AND category = ?'
        params.append(cat)
    if loc:
        query += ' AND location_id = ?'
        params.append(loc)
        
    query += ' ORDER BY created_at DESC'
    products = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(p) for p in products])

@products_bp.route('/catalog', methods=['GET'])
def get_catalog():
    if not login_required():
        return unauthorized()
    
    conn = get_db()
    # Fetch distinct products globally by barcode or name
    query = '''
        SELECT name, brand, barcode, unit, category, description, image, price, price_cn, has_vat, pack_qty
        FROM products 
        GROUP BY COALESCE(NULLIF(barcode, ''), name)
        ORDER BY name ASC
    '''
    catalog = conn.execute(query).fetchall()
    conn.close()
    return jsonify([dict(c) for c in catalog])

@products_bp.route('/products', methods=['POST'])
def add_product():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    
    name = request.form.get('name')
    brand = request.form.get('brand', '')
    barcode = request.form.get('barcode', '')
    unit = request.form.get('unit', '')
    category = request.form.get('category', '')
    pack_qty = safe_int(request.form.get('pack_qty'), 0)
    quantity = safe_int(request.form.get('quantity'), 0)
    price = safe_float(request.form.get('price'), 0.0)
    price_cn = safe_float(request.form.get('price_cn'), 0.0)
    has_vat = 1 if request.form.get('has_vat') == 'true' else 0 # FormData sends 'true'/'false'
    location_id_str = request.form.get('location_id')
    location_id = int(location_id_str) if location_id_str and str(location_id_str).isdigit() else None
    description = request.form.get('description', '')
    
    image_file = request.files.get('image')
    img_name = None
    if image_file and image_file.filename:
        ext = image_file.filename.split('.')[-1].lower()
        if ext in ['png', 'jpg', 'jpeg']:
            img_name = f"{secrets.token_hex(8)}.{ext}"
            image_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], img_name))

    conn = get_db()
    
    # Validation: Check if it already exists in THIS location
    existing = conn.execute('''
        SELECT id FROM products 
        WHERE location_id = ? AND ((barcode != '' AND barcode = ?) OR name = ?)
    ''', (location_id, barcode, name)).fetchone()
    
    if existing:
        conn.close()
        return jsonify({'error': 'Сонгосон агуулахад энэ бараа (ижил нэр эсвэл кодтой) аль хэдийн бүртгэгдсэн байна.'}), 400
        
    try:
        cursor = conn.execute('''
            INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, image) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, img_name))
        pid = cursor.lastrowid
        
        # Add transaction logic
        if quantity > 0:
            total_amount = quantity * price
            cur = conn.execute('INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
                               ('in', total_amount, 'Шинэ бараа бүртгэл', session.get('user_id')))
            bundle_id = cur.lastrowid
            conn.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                         (bundle_id, pid, quantity, price, has_vat))
            
        # Global sync: If barcode or name exists elsewhere, sync their global specs to match this one
        if str(barcode).strip() or str(name).strip():
            sync_query = '''
                UPDATE products 
                SET brand=?, unit=?, category=?, description=?, image=?, has_vat=? 
                WHERE (barcode=? AND barcode!='') OR (name=? AND name!='')
            '''
            conn.execute(sync_query, (brand, unit, category, description, img_name, has_vat, barcode, name))

        conn.commit()
        return jsonify({'message': 'Бараа амжилттай нэмэгдлээ', 'id': pid})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Бүртгэхэд алдаа гарлаа: {str(e)}'}), 500
    finally:
        conn.close()

@products_bp.route('/products/<int:pid>', methods=['PUT', 'PATCH'])
def update_product(pid):
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
    if not product:
        conn.close()
        return jsonify({'error': 'Бараа олдсонгүй'}), 404
        
    old_qty = product['quantity']
    old_img = product['image']
    
    # Use form data if available (for image uploads), otherwise JSON
    if request.form:
        name = request.form.get('name', product['name'])
        brand = request.form.get('brand', product['brand'])
        barcode = request.form.get('barcode', product['barcode'])
        unit = request.form.get('unit', product['unit'])
        category = request.form.get('category', product['category'])
        pack_qty = safe_int(request.form.get('pack_qty'), product['pack_qty'])
        quantity = safe_int(request.form.get('quantity'), product['quantity'])
        price = safe_float(request.form.get('price'), product['price'])
        price_cn = safe_float(request.form.get('price_cn'), product['price_cn'])
        has_vat = 1 if request.form.get('has_vat') == 'true' else 0
        loc_id_str = request.form.get('location_id')
        location_id = int(loc_id_str) if loc_id_str and str(loc_id_str).isdigit() else product['location_id']
        description = request.form.get('description', product['description'])
        
        img_name = product['image']
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            ext = image_file.filename.split('.')[-1].lower()
            if ext in ['png', 'jpg', 'jpeg']:
                img_name = f"{secrets.token_hex(8)}.{ext}"
                image_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], img_name))
    else:
        data = request.json
        name = data.get('name', product['name'])
        brand = data.get('brand', product['brand'])
        barcode = data.get('barcode', product['barcode'])
        unit = data.get('unit', product['unit'])
        category = data.get('category', product['category'])
        pack_qty = safe_int(data.get('pack_qty'), product['pack_qty'])
        quantity = safe_int(data.get('quantity'), product['quantity'])
        price = safe_float(data.get('price'), product['price'])
        price_cn = safe_float(data.get('price_cn'), product['price_cn'])
        has_vat = 1 if data.get('has_vat') else 0
        location_id = data.get('location_id', product['location_id'])
        description = data.get('description', product['description'])
        img_name = product['image']

    try:
        conn.execute('''
            UPDATE products 
            SET name=?, brand=?, barcode=?, unit=?, category=?, pack_qty=?, quantity=?, price=?, price_cn=?, has_vat=?, location_id=?, description=?, image=?
            WHERE id=?
        ''', (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, img_name, pid))
        
        # Global sync: Sync global specs to other products sharing this barcode or name
        if str(barcode).strip() or str(name).strip():
            sync_query = '''
                UPDATE products 
                SET brand=?, unit=?, category=?, description=?, image=?, has_vat=?, name=?, barcode=?
                WHERE id != ? AND ((barcode=? AND barcode!='') OR (name=? AND name!=''))
            '''
            conn.execute(sync_query, (brand, unit, category, description, img_name, has_vat, name, barcode, pid, product['barcode'], product['name']))
        
        # Cleanup old image if it changed
        if old_img and old_img != img_name:
            safe_delete_image(conn, old_img)
            
        # Track manual quantity change as 'fix'
        if quantity != old_qty:
            diff = quantity - old_qty
            total_amount = diff * price
            cursor = conn.execute('INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
                                 ('fix', total_amount, 'Барааны мэдээлэл засварласнаар үлдэгдэл өөрчлөгдлөө', session.get('user_id')))
            bundle_id = cursor.lastrowid
            conn.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                         (bundle_id, pid, diff, price, has_vat))
                         
        conn.commit()
        return jsonify({'message': 'Бараа шинэчлэгдлээ'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Засварлахад алдаа гарлаа: {str(e)}'}), 500
    finally:
        conn.close()

@products_bp.route('/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    conn = get_db()
    product = conn.execute('SELECT image FROM products WHERE id=?', (pid,)).fetchone()
    
    conn.execute('DELETE FROM products WHERE id=?', (pid,))
    
    if product and product['image']:
        safe_delete_image(conn, product['image'])
        
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа устгагдлаа'})

@products_bp.route('/products/bulk-delete', methods=['DELETE'])
def bulk_delete_products():
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403

    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    if not isinstance(ids, list) or len(ids) == 0:
        return jsonify({'error': 'IDs шаардлагатай'}), 400

    # Normalize and keep only ints
    norm_ids = []
    for x in ids:
        try:
            xi = int(x)
            norm_ids.append(xi)
        except Exception:
            continue
    norm_ids = list(dict.fromkeys(norm_ids))
    if len(norm_ids) == 0:
        return jsonify({'error': 'IDs буруу байна'}), 400

    conn = get_db()
    try:
        placeholders = ','.join(['?'] * len(norm_ids))
        rows = conn.execute(f'SELECT id, image FROM products WHERE id IN ({placeholders})', norm_ids).fetchall()
        images = [r['image'] for r in rows if r and r['image']]

        conn.execute(f'DELETE FROM products WHERE id IN ({placeholders})', norm_ids)
        for img in images:
            safe_delete_image(conn, img)

        conn.commit()
        return jsonify({'message': f'{len(rows)} бараа устгагдлаа', 'deleted': len(rows)})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'Устгахад алдаа гарлаа: {str(e)}'}), 500
    finally:
        conn.close()

# Categories, Brands, Locations
@products_bp.route('/categories', methods=['GET'])
def get_categories():
    if not login_required(): return unauthorized()
    conn = get_db()
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(c) for c in cats])

@products_bp.route('/categories', methods=['POST'])
def add_category():
    if not login_required() or not has_role('manager'): return unauthorized()
    name = request.json.get('name')
    if not name: return jsonify({'error': 'Нэр шаардлагатай'}), 400
    conn = get_db()
    conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай нэмэгдлээ'})

@products_bp.route('/categories/<int:cid>', methods=['PUT'])
def update_category(cid):
    if not login_required() or not has_role('manager'): return unauthorized()
    name = request.json.get('name')
    conn = get_db()
    conn.execute('UPDATE categories SET name=? WHERE id=?', (name, cid))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай шинэчлэгдлээ'})

@products_bp.route('/categories/<int:cid>', methods=['DELETE'])
def delete_category(cid):
    if not login_required() or not has_role('manager'): return unauthorized()
    conn = get_db()
    conn.execute('DELETE FROM categories WHERE id=?', (cid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай устгагдлаа'})

@products_bp.route('/brands', methods=['GET'])
def get_brands():
    if not login_required(): return unauthorized()
    conn = get_db()
    brands = conn.execute('SELECT * FROM brands ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(b) for b in brands])

@products_bp.route('/brands', methods=['POST'])
def add_brand():
    if not login_required() or not has_role('manager'): return unauthorized()
    name = request.json.get('name')
    if not name: return jsonify({'error': 'Нэр шаардлагатай'}), 400
    conn = get_db()
    conn.execute('INSERT INTO brands (name) VALUES (?)', (name,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай нэмэгдлээ'})

@products_bp.route('/brands/<int:bid>', methods=['PUT'])
def update_brand(bid):
    if not login_required() or not has_role('manager'): return unauthorized()
    name = request.json.get('name')
    conn = get_db()
    conn.execute('UPDATE brands SET name=? WHERE id=?', (name, bid))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай шинэчлэгдлээ'})

@products_bp.route('/brands/<int:bid>', methods=['DELETE'])
def delete_brand(bid):
    if not login_required() or not has_role('manager'): return unauthorized()
    conn = get_db()
    conn.execute('DELETE FROM brands WHERE id=?', (bid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай устгагдлаа'})

@products_bp.route('/locations', methods=['GET'])
def get_locations():
    if not login_required(): return unauthorized()
    conn = get_db()
    locs = conn.execute('SELECT * FROM locations ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(l) for l in locs])

@products_bp.route('/locations', methods=['POST'])
def add_location():
    if not login_required() or not has_role('manager'): return unauthorized()
    name = request.json.get('name')
    if not name: return jsonify({'error': 'Нэр шаардлагатай'}), 400
    conn = get_db()
    conn.execute('INSERT INTO locations (name) VALUES (?)', (name,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай нэмэгдлээ'})

@products_bp.route('/locations/<int:lid>', methods=['DELETE'])
def delete_location(lid):
    if not login_required() or not has_role('manager'): return unauthorized()
    conn = get_db()
    conn.execute('DELETE FROM locations WHERE id=?', (lid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Амжилттай устгагдлаа'})
