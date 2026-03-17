from flask import Blueprint, request, jsonify
from app.database import get_db
from app.utils import login_required, unauthorized

stats_bp = Blueprint('stats', __name__)

@stats_bp.route('/stats', methods=['GET'])
def get_stats():
    if not login_required():
        return unauthorized()
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

@stats_bp.route('/stats/revenue', methods=['GET'])
def get_stats_revenue():
    if not login_required():
        return unauthorized()
    
    period = request.args.get('period', 'monthly')
    conn = get_db()
    
    if period == 'annually':
        interval = '-1 year'
        group_by = "strftime('%Y-%m', created_at)"
    else:  # monthly (default)
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

@stats_bp.route('/stats/product-trend', methods=['GET'])
def get_stats_product_trend():
    if not login_required():
        return unauthorized()
    
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
