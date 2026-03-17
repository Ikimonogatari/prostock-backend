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
