from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'True').lower() == 'true'
    print(f"Modular Server started: http://localhost:{port}")
    app.run(debug=debug, host='0.0.0.0', port=port)
