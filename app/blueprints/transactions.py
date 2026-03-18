from flask import Blueprint, request, jsonify, session
from app.database import get_db
from app.utils import login_required, unauthorized, safe_int, safe_float

transactions_bp = Blueprint('transactions', __name__)

@transactions_bp.route('/transactions', methods=['GET'])
def get_transactions():
    if not login_required():
        return unauthorized()
    tx_type = request.args.get('type', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    limit = min(safe_int(request.args.get('limit'), 100), 500)
    location_id = request.args.get('location_id', '')

    conn = get_db()
    query = '''
        SELECT b.*, u.username as created_by 
        FROM transaction_bundles b
        JOIN users u ON b.created_by = u.id
        WHERE 1=1
    '''
    params = []
    
    if location_id:
        query += ''' AND EXISTS (
            SELECT 1 FROM transaction_items ti 
            JOIN products p ON ti.product_id = p.id 
            WHERE ti.bundle_id = b.id AND p.location_id = ?
        )'''
        params.append(location_id)
        
    if tx_type in ('in', 'out', 'fix'):
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
            SELECT ti.*, p.name as product_name, p.brand, p.barcode, p.pack_qty, p.unit, p.image
            FROM transaction_items ti
            JOIN products p ON ti.product_id = p.id
            WHERE ti.bundle_id = ?
        ''', (b['id'],)).fetchall()
        bundle_dict['items'] = [dict(i) for i in items]
        result.append(bundle_dict)
        
    conn.close()
    return jsonify(result)

@transactions_bp.route('/transactions', methods=['POST'])
def add_transaction():
    if not login_required():
        return unauthorized()
    
    data = request.json
    tx_type = data.get('type') # 'in' or 'out'
    items = data.get('items', [])
    note = data.get('note', '')
    total_amount = safe_float(data.get('total_amount'), 0)
    location_id = data.get('location_id')
    if location_id == 'all':
        location_id = None
    
    if tx_type not in ('in', 'out'):
        return jsonify({'error': 'Төрөл буруу'}), 400
    if not items:
        return jsonify({'error': 'Бараа сонгоогүй байна'}), 400
        
    conn = get_db()
    try:
        # 1. Create bundle
        cursor = conn.execute('INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
                             (tx_type, total_amount, note, session['user_id']))
        bundle_id = cursor.lastrowid
        
        # 2. Add items and update quantities
        for it in items:
            p_id_raw = str(it.get('product_id', ''))
            qty = safe_int(it.get('quantity'), 0)
            price = safe_float(it.get('price'), 0)
            has_vat = 1 if it.get('has_vat') else 0
            
            if p_id_raw.startswith('new_'):
                if not location_id:
                    raise Exception("Шинэ бараа нэмэхийн тулд тодорхой агуулах сонгох шаардлагатай.")
                
                name = it.get('name', '')
                barcode = it.get('barcode', '')
                
                # Check for existing
                existing = conn.execute('''
                    SELECT id FROM products 
                    WHERE location_id = ? AND name = ? AND barcode = ?
                ''', (location_id, name, barcode)).fetchone()
                
                if existing:
                    p_id = existing['id']
                    delta = qty if tx_type == 'in' else -qty
                    conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (delta, p_id))
                else:
                    loc_row = conn.execute('SELECT name FROM locations WHERE id=?', (location_id,)).fetchone()
                    loc_name = loc_row['name'] if loc_row else 'Үндсэн Агуулах'
                    
                    c2 = conn.execute('''
                        INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, has_vat, location_id, location, image, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        name,
                        it.get('brand', ''),
                        barcode,
                        it.get('unit', ''),
                        it.get('category', ''),
                        safe_int(it.get('pack_qty'), 1),
                        qty if tx_type == 'in' else 0,
                        price,
                        has_vat,
                        location_id,
                        loc_name,
                        it.get('image', ''),
                        it.get('description', '')
                    ))
                    p_id = c2.lastrowid
            else:
                p_id = int(p_id_raw)
                # Update stock
                delta = qty if tx_type == 'in' else -qty
                conn.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (delta, p_id))
            
            # Record item
            conn.execute('INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                         (bundle_id, p_id, qty, price, has_vat))
                         
        conn.commit()
        return jsonify({'message': 'Гүйлгээ амжилттай бүртгэгдлээ', 'id': bundle_id})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@transactions_bp.route('/transactions/move', methods=['POST'])
def move_products():
    if not login_required():
        return unauthorized()

    data = request.json or {}
    from_location_id = data.get('from_location_id')
    to_location_id = data.get('to_location_id')
    items = data.get('items', [])
    note = data.get('note', '')

    if not from_location_id or not to_location_id:
        return jsonify({'error': 'Агуулах сонгоно уу'}), 400
    if str(from_location_id) == str(to_location_id):
        return jsonify({'error': 'Ижил агуулах руу зөөх боломжгүй'}), 400
    if not items:
        return jsonify({'error': 'Бараа сонгоогүй байна'}), 400

    conn = get_db()
    try:
        # Validate locations exist
        from_loc = conn.execute('SELECT id, name FROM locations WHERE id=?', (from_location_id,)).fetchone()
        to_loc = conn.execute('SELECT id, name FROM locations WHERE id=?', (to_location_id,)).fetchone()
        if not from_loc or not to_loc:
            return jsonify({'error': 'Агуулах олдсонгүй'}), 404

        # Create two bundles (move) with total_amount=0 so stats/revenue are unaffected
        move_note = f"Зөөвөрлөлт: {from_loc['name']} → {to_loc['name']}"
        if note:
            move_note = f"{move_note}. {note}"

        out_cur = conn.execute(
            'INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
            ('move', 0, move_note, session['user_id'])
        )
        out_bundle_id = out_cur.lastrowid

        in_cur = conn.execute(
            'INSERT INTO transaction_bundles (type, total_amount, note, created_by) VALUES (?, ?, ?, ?)',
            ('move', 0, move_note, session['user_id'])
        )
        in_bundle_id = in_cur.lastrowid

        moved_lines = 0

        for it in items:
            src_pid = it.get('product_id')
            qty = safe_int(it.get('quantity'), 0)
            if not src_pid or qty <= 0:
                continue

            src = conn.execute('SELECT * FROM products WHERE id=? AND location_id=?', (src_pid, from_location_id)).fetchone()
            if not src:
                return jsonify({'error': 'Эх агуулахад бараа олдсонгүй'}), 400
            if qty > safe_int(src['quantity'], 0):
                return jsonify({'error': f"Үлдэгдэл хүрэлцэхгүй байна: {src['name']}"}), 400

            # Find matching destination product in target location (barcode preferred)
            dest = None
            if src['barcode']:
                dest = conn.execute(
                    "SELECT * FROM products WHERE location_id=? AND barcode=? AND barcode!='' LIMIT 1",
                    (to_location_id, src['barcode'])
                ).fetchone()
            if not dest:
                dest = conn.execute(
                    "SELECT * FROM products WHERE location_id=? AND name=? LIMIT 1",
                    (to_location_id, src['name'])
                ).fetchone()

            if not dest:
                # Create destination product copy (quantity starts at 0)
                cur = conn.execute('''
                    INSERT INTO products (name, brand, barcode, unit, category, pack_qty, quantity, price, price_cn, has_vat, location_id, description, image)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    src['name'],
                    src['brand'] or '',
                    src['barcode'] or '',
                    src['unit'] or '',
                    src['category'] or '',
                    safe_int(src['pack_qty'], 0),
                    0,
                    safe_float(src['price'], 0),
                    safe_float(src['price_cn'], 0),
                    0,
                    to_location_id,
                    src['description'] or '',
                    src['image']
                ))
                dest_id = cur.lastrowid
            else:
                dest_id = dest['id']

            # Update stocks
            conn.execute('UPDATE products SET quantity = quantity - ? WHERE id=?', (qty, src_pid))
            conn.execute('UPDATE products SET quantity = quantity + ? WHERE id=?', (qty, dest_id))

            # Record transaction items (no VAT needed here)
            price = safe_float(src['price'], 0)
            conn.execute(
                'INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                (out_bundle_id, src_pid, qty, price, 0)
            )
            conn.execute(
                'INSERT INTO transaction_items (bundle_id, product_id, quantity, price, has_vat) VALUES (?, ?, ?, ?, ?)',
                (in_bundle_id, dest_id, qty, price, 0)
            )
            moved_lines += 1

        if moved_lines == 0:
            conn.rollback()
            return jsonify({'error': 'Зөөх бараа олдсонгүй'}), 400

        conn.commit()
        return jsonify({'message': f'{moved_lines} бараа амжилттай зөөлөө'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
