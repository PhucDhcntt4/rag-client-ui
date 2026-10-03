# RAG Client UI

Ứng dụng gồm frontend HTML/CSS/JavaScript và backend FastAPI. Backend đọc dữ liệu
từ RAG Service, chuyển ngữ cảnh truy xuất sang LLM riêng và trả câu trả lời kèm
nguồn cho trình duyệt. API key không được đưa xuống frontend.

## Chạy ứng dụng

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
```

Sao chép các biến trong `.env.example` sang `.env` và điền key thật trước khi
chạy. FastAPI phục vụ cả backend lẫn thư mục `frontend`.

- Giao diện: `http://127.0.0.1:8100`
- Swagger: `http://127.0.0.1:8100/docs`

## Kiểm thử

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```
