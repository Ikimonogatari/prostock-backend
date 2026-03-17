from flask import Blueprint, request, jsonify, session
from app.database import get_db, hash_password
from app.utils import login_required, unauthorized

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    
    if user and user['password'] == hash_password(password + '123'):
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({
            'message': 'Амжилттай нэвтэрлээ',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'role': user['role']
            }
        })
    return jsonify({'error': 'Нэвтрэх нэр эсвэл нууц үг буруу байна'}), 401

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Амжилттай гарлаа'})

@auth_bp.route('/me', methods=['GET'])
def get_me():
    if not login_required():
        return unauthorized()
    return jsonify({
        'id': session['user_id'],
        'username': session['username'],
        'role': session['role']
    })

@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    if not login_required():
        return unauthorized()
    
    data = request.json
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Мэдээлэл дутуу байна'}), 400
        
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    if user and user['password'] == hash_password(old_password + '123'):
        conn.execute('UPDATE users SET password = ? WHERE id = ?', 
                     (hash_password(new_password + '123'), session['user_id']))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Нууц үг амжилттай солигдлоо'})
        
    conn.close()
    return jsonify({'error': 'Хуучин нууц үг буруу байна'}), 400
