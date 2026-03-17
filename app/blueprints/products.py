from flask import Blueprint, request, jsonify, current_app
from app.database import get_db
from app.utils import login_required, unauthorized, has_role
import os
import secrets

products_bp = Blueprint('products', __name__)

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

@products_bp.route('/products', methods=['POST'])
def add_product():
    if not login_required() or not has_role('manager'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    
    name = request.form.get('name')
    brand = request.form.get('brand', '')
    barcode = request.form.get('barcode', '')
    unit = request.form.get('unit', '')
    category = request.form.get('category', '')
    pack_qty = int(request.form.get('pack_qty', 0))
    quantity = int(request.form.get('quantity', 0))
    price = float(request.form.get('price', 0))
    price_cn = float(request.form.get('price_cn', 0))
    has_vat = int(request.form.get('has_vat', 0))
    location_id = request.form.get('location_id')
    description = request.form.get('description', '')
    
    image_file = request.files.get('image')
    img_name = None
    if image_file and image_file.filename:
        ext = image_file.filename.split('.')[-1].lower()
        if ext in ['png', 'jpg', 'jpeg']:
            img_name = f"{secrets.token_hex(8)}.{ext}"
            image_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], img_name))

    conn = get_db()
    cursor = conn.execute('''
        INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, image) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, img_name))
    pid = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа амжилттай нэмэгдлээ', 'id': pid})

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
    
    # Use form data if available (for image uploads), otherwise JSON
    if request.form:
        name = request.form.get('name', product['name'])
        brand = request.form.get('brand', product['brand'])
        barcode = request.form.get('barcode', product['barcode'])
        unit = request.form.get('unit', product['unit'])
        category = request.form.get('category', product['category'])
        pack_qty = int(request.form.get('pack_qty', product['pack_qty']))
        quantity = int(request.form.get('quantity', product['quantity']))
        price = float(request.form.get('price', product['price']))
        price_cn = float(request.form.get('price_cn', product['price_cn']))
        has_vat = int(request.form.get('has_vat', product['has_vat']))
        location_id = request.form.get('location_id', product['location_id'])
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
        pack_qty = data.get('pack_qty', product['pack_qty'])
        quantity = data.get('quantity', product['quantity'])
        price = data.get('price', product['price'])
        price_cn = data.get('price_cn', product['price_cn'])
        has_vat = data.get('has_vat', product['has_vat'])
        location_id = data.get('location_id', product['location_id'])
        description = data.get('description', product['description'])
        img_name = product['image']

    conn.execute('''
        UPDATE products 
        SET name=?, brand=?, barcode=?, unit=?, category=?, pack_qty=?, quantity=?, price=?, price_cn=?, has_vat=?, location_id=?, description=?, image=?
        WHERE id=?
    ''', (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, img_name, pid))
    
    # Track manual quantity change as 'fix'
    if quantity != old_qty:
        diff = quantity - old_qty
        cursor = conn.execute('INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
                             ('fix', 0, 'Барааны мэдээлэл засварласнаар үлдэгдэл өөрчлөгдлөө', session['user_id']))
        bundle_id = cursor.lastrowid
        conn.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                     (bundle_id, pid, diff, 0, 0))
                     
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа шинэчлэгдлээ'})

@products_bp.route('/products/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    conn = get_db()
    conn.execute('DELETE FROM products WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Бараа устгагдлаа'})

# Categories, Brands, Locations
@products_bp.route('/categories', methods=['GET'])
def get_categories():
    if not login_required(): return unauthorized()
    conn = get_db()
    cats = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(c) for c in cats])

@products_bp.route('/brands', methods=['GET'])
def get_brands():
    if not login_required(): return unauthorized()
    conn = get_db()
    brands = conn.execute('SELECT * FROM brands ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(b) for b in brands])

@products_bp.route('/locations', methods=['GET'])
def get_locations():
    if not login_required(): return unauthorized()
    conn = get_db()
    locs = conn.execute('SELECT * FROM locations ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(l) for l in locs])
