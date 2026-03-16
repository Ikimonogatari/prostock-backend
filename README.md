# StockPro Backend (Flask API)

Барааны бүртгэлийн систем — REST API сервер.

## Шаардлага

- Python 3.12+
- pip (python3 -m pip)

## Суулгах

```bash
cd backend
python3 -m pip install --user --break-system-packages flask flask-cors openpyxl
```

## Ажиллуулах

```bash
cd backend
python3 app.py
```

Сервер `http://localhost:5000` дээр ажиллана.

## Анхны нэвтрэх

- **Нэвтрэх нэр:** `admin`
- **Нууц үг:** `admin123`

## API Endpoints

| Method | Endpoint | Тайлбар | Эрх |
|--------|----------|---------|-----|
| POST | `/api/login` | Нэвтрэх | — |
| POST | `/api/logout` | Гарах | — |
| GET | `/api/me` | Одоогийн хэрэглэгч | login |
| POST | `/api/change-password` | Нууц үг солих | login |
| GET | `/api/products` | Бүх бараа | login |
| POST | `/api/products` | Бараа нэмэх | manager+ |
| PUT | `/api/products/:id` | Бараа засах | manager+ |
| DELETE | `/api/products/:id` | Бараа устгах | admin |
| GET | `/api/categories` | Ангилалууд | login |
| POST | `/api/transactions` | Гүйлгээ нэмэх | login |
| GET | `/api/transactions` | Гүйлгээний түүх | login |
| GET | `/api/stats` | Статистик | login |
| GET | `/api/users` | Хэрэглэгчид | admin |
| POST | `/api/users` | Хэрэглэгч нэмэх | admin |
| DELETE | `/api/users/:id` | Хэрэглэгч устгах | admin |
| PUT | `/api/users/:id/role` | Эрх өөрчлөх | admin |
| POST | `/api/import/products` | Excel-ээс бараа импорт | manager+ |
| POST | `/api/import/transactions` | Excel-ээс гүйлгээ импорт | login |
| GET | `/api/export/products` | Бараа Excel-ээр татах | login |
| GET | `/api/template` | Импорт загвар файл татах | — |

## Эрхийн түвшин

- **admin** — бүх зүйл
- **manager** — бараа нэмэх/засах, гүйлгээ
- **user** — зөвхөн гүйлгээ + харах
