from flask import Flask
from flask_cors import CORS
import os
from config import Config
from app.database import init_db

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    try:
        # Initialize CORS
        CORS(app, supports_credentials=True, origins=app.config['CORS_ORIGINS'])

        # Ensure upload folder exists
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])

        # Initialize DB (Run migrations)
        with app.app_context():
            init_db()

        # Register blueprints
        from app.blueprints.auth import auth_bp
        from app.blueprints.users import users_bp
        from app.blueprints.products import products_bp
        from app.blueprints.transactions import transactions_bp
        from app.blueprints.stats import stats_bp
        from app.blueprints.excel import excel_bp

        app.register_blueprint(auth_bp, url_prefix='/api')
        app.register_blueprint(users_bp, url_prefix='/api')
        app.register_blueprint(products_bp, url_prefix='/api')
        app.register_blueprint(transactions_bp, url_prefix='/api')
        app.register_blueprint(stats_bp, url_prefix='/api')
        app.register_blueprint(excel_bp, url_prefix='/api')

        # Serve uploads
        from flask import send_from_directory
        @app.route('/uploads/<path:filename>')
        @app.route('/api/uploads/<path:filename>')
        def uploaded_file(filename):
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    except Exception as e:
        print(f"!!! CRITICAL ERROR DURING BOOT !!!: {e}")
        import traceback
        traceback.print_exc()
        raise e

    return app
