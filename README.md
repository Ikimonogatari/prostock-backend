# StockPro Backend

Modular Flask Backend for StockPro Inventory Management System.

## Project Structure
```
backend/
├── app/                # Application package
│   ├── __init__.py     # App factory
│   ├── database.py     # DB logic
│   ├── utils.py        # Helpers/Decorators
│   └── blueprints/     # API Routes
├── config.py           # Configuration classes
├── main.py             # Entry point
├── Dockerfile          # Production Docker setup
└── .env                # Environment variables
```

## Local Setup
1. Create a virtual environment: `python -m venv venv`
2. Activate it: `source venv/bin/activate` (Linux) or `venv\Scripts\activate` (Windows)
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env` and fill in values.
5. Run: `python main.py`

## IONOS Deployment Instructions

### Option 1: Docker (Recommended)
1. **Prepare Server**: Ensure Docker and Docker Compose are installed on your IONOS VPS.
2. **Transfer Files**: Upload the `backend` folder to your server.
3. **Configure Environment**: Update the `.env` file with your production domain and secret key.
4. **Build and Run**:
   ```bash
   docker compose up -d --build
   ```
5. **Reverse Proxy (Optional)**: If you're not using Docker for Nginx, configure Nginx on the host to proxy to `http://localhost:5000`.

### Option 2: Manual (Gunicorn)
1. **Install Python**: `sudo apt update && sudo apt install python3-pip python3-venv`
2. **Setup App**: Transfer files, create venv, and install requirements.
3. **Run with Gunicorn**:
   ```bash
   gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 main:app
   ```
4. **Setup Systemd**: Create a service file to keep the app running in the background.

## Database
The system uses SQLite for simplicity. The database file `database.db` will be automatically initialized and migrated on first run. Ensure the service has write permissions to the project directory.
