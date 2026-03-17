import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not found. Environment variables will be read directly from the system.")

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'stockpro_secret_key_v1')
    DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'data', 'database.db'))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(os.path.dirname(__file__), 'data', 'uploads'))
    TEMPLATE_PATH = os.environ.get('TEMPLATE_PATH', os.path.join(os.path.dirname(__file__), 'template.xlsx'))
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(',')
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
    PORT = int(os.environ.get('PORT', 5000))
