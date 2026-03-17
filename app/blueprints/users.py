from flask import Blueprint, request, jsonify
from app.database import get_db, hash_password
from app.utils import login_required, has_role

users_bp = Blueprint('users', __name__)

@users_bp.route('/users', methods=['GET'])
def get_users():
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    conn = get_db()
    users = conn.execute('SELECT id, username, role FROM users').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@users_bp.route('/users', methods=['POST'])
def add_user():
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'user')
    
    if not username or not password:
        return jsonify({'error': 'Мэдээлэл дутуу байна'}), 400
        
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     (username, hash_password(password + '123'), role))
        conn.commit()
    except Exception as e:
        return jsonify({'error': f'Бүртгэлтэй хэрэглэгч байна: {str(e)}'}), 400
    finally:
        conn.close()
    return jsonify({'message': 'Хэрэглэгч амжилттай нэмэгдлээ'})

@users_bp.route('/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    if not login_required() or not has_role('admin'):
        return jsonify({'error': 'Зөвшөөрөл байхгүй'}), 403
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Хэрэглэгч устгагдлаа'})
