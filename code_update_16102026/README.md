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

Giao diện cho phép chọn Gemini hoặc OpenAI theo từng câu hỏi. Provider chỉ khả
dụng khi API key tương ứng đã được cấu hình trong `backend/.env`.

Giao diện dùng một khung chat thống nhất. Client gửi `data_source=auto`;
backend tự phân loại câu hỏi sang kho tài liệu hoặc kho sản phẩm.
Khi người dùng chọn phạm vi tài liệu, truy vấn được cố định vào kho
tài liệu. Khi gửi ảnh, client gọi trực tiếp pipeline nhận diện sản phẩm.

- Giao diện: `http://127.0.0.1:8100`
- Swagger: `http://127.0.0.1:8100/docs`

Mặc định giao diện ẩn ký hiệu trích dẫn `[S...]`, danh sách tài liệu tham khảo,
nội dung truy xuất và nút mở kho tài liệu. Dùng
`http://127.0.0.1:8100/?debug=true` khi cần kiểm tra đầy đủ các nguồn RAG này.

API proxy sản phẩm:

- `GET /api/products?q=S5921`
- `GET /api/products/latest?limit=10`
- `GET /api/products/latest?date_from=...&date_to=...&page=1&limit=10`
- `GET /api/products/latest/details?date_from=...&date_to=...&page=1`
- `GET /api/products/S5921`
- `POST /api/products/image-search` (multipart field `file`)

Nút `Tìm bằng ảnh` gửi JPEG/PNG/WebP về Client Backend.
Backend dùng cùng OpenCLIP `ViT-B-32/laion2b_s34b_b79k` để tạo vector 512
chiều, truy vấn collection `PRODUCT_IMAGE_COLLECTION`, loại kết quả trùng theo
mã sản phẩm, sau đó gọi RAG Service lấy chi tiết và tồn kho. Qdrant key
chỉ tồn tại trong `backend/.env`, không được gửi xuống trình duyệt.

Kết quả sản phẩm mới dùng khoảng ngày và phân trang từ RAG
Server. Giao diện hiển thị `X/Y` và cho phép bấm `Xem thêm`; múi giờ
và kích thước trang được cấu hình bằng các biến `PRODUCT_*` trong
`backend/.env`.

Chat sản phẩm nhận diện các nhóm câu hỏi:

- Sản phẩm mới nhất/mới hiện tại.
- Sản phẩm còn hàng, còn kho hoặc có sẵn.
- Sản phẩm hết hàng, hết kho hoặc không còn hàng.
- Kiểm tra mã, màu, size, giá và tồn kho cụ thể.

Product API của RAG Service yêu cầu quyền admin. Trình duyệt chỉ gọi Client
Backend; `RAG_ADMIN_API_KEY` không được gửi xuống frontend.

## Kiểm thử

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

## Hướng dẫn triển khai

Xem `HUONG_DAN_TRIEN_KHAI.txt` để cấu hình đầy đủ, kiểm tra RAG/LLM và triển
khai production bằng systemd + Nginx.
