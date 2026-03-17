from functools import wraps
from flask import session, jsonify

def login_required():
    return 'user_id' in session

def unauthorized():
    return jsonify({'error': 'Нэвтрэх шаардлагатай'}), 401

def has_role(required_role):
    user_role = session.get('role', 'user')
    roles = {'user': 1, 'manager': 2, 'admin': 3}
    return roles.get(user_role, 0) >= roles.get(required_role, 0)

def safe_int(val, default=0):
    if val is None: return default
    try:
        return int(float(str(val).strip() or default))
    except:
        return default

def safe_float(val, default=0.0):
    if val is None: return default
    try:
        return float(str(val).strip() or default)
    except:
        return default
