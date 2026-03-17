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
            p_id = it['product_id']
            qty = safe_int(it['quantity'])
            price = safe_float(it['price'])
            has_vat = 1 if it.get('has_vat') else 0
            
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
