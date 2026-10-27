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

## Đăng nhập

Ứng dụng bắt buộc đăng nhập trước khi sử dụng chat, tài liệu và sản phẩm.
Phiên đăng nhập được lưu bằng cookie `HttpOnly`; frontend không đọc hoặc lưu
JWT và không lưu mật khẩu. Có thể đăng nhập bằng tên đăng nhập hoặc email.

Các biến bắt buộc trong `backend/.env`:

```ini
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
AUTH_SECRET_KEY=<chuỗi ngẫu nhiên tối thiểu 32 ký tự>
AUTH_COOKIE_NAME=mshai_session
AUTH_TOKEN_EXPIRE_MINUTES=480
AUTH_COOKIE_SECURE=false
```

Khi triển khai bằng HTTPS, đặt `AUTH_COOKIE_SECURE=true`. Tạo tài khoản bằng
`backend/create_admin.py` cho tài khoản quản trị đầu tiên. Sau khi đăng nhập,
Admin có thể tạo và chỉnh sửa tài khoản trực tiếp trong trang quản trị. Trang
này hỗ trợ chọn vai trò, gán một nhóm quyền, bật/tắt tài khoản, xem lần đăng
nhập cuối và đặt lại mật khẩu. Không ghi mật khẩu vào mã nguồn hoặc Git.
Mỗi tài khoản có vùng lịch sử hội thoại riêng trên trình duyệt đang sử dụng.

## Quản trị nhóm quyền tài liệu

Tài khoản có `role=admin` sẽ thấy nút hình khiên trên thanh tiêu đề. Nút này mở
trang quản trị toàn màn hình với menu riêng cho “Nhóm & phạm vi” và “Người dùng”.
Giao diện quản trị cho phép:

- Tạo, đổi tên và khóa/mở một nhóm quyền.
- Cấp toàn bộ kho tài liệu, một loại tài liệu (mục cha), hoặc từng nhóm tài liệu
  (mục con).
- Gán đúng một nhóm quyền cho mỗi người dùng; có thể để trống để tạm thời không
  cho người đó truy cập tài liệu.
- Tạo/sửa người dùng, bật hoặc vô hiệu hóa tài khoản và đặt lại mật khẩu.
- Xem thời điểm đăng nhập gần nhất của tài khoản.

Nút quản trị chỉ là lớp giao diện. Các endpoint `/api/admin/*` vẫn kiểm tra
`role=admin` ở backend, và `/api/chat`, `/api/taxonomy`, `/api/documents` cùng
`/api/rag-assets/*` đều áp dụng phạm vi của nhóm đang gán cho người dùng.

Sau khi cập nhật mã nguồn, chạy migration an toàn (có thể chạy lại nhiều lần):

```powershell
cd backend
python -X utf8 init_db.py
```

Schema dùng `rag_client.users.permission_group_id` nên một user chỉ thuộc một
nhóm. Bảng `document_permissions` cũ chỉ được giữ để tương thích và chuyển dữ
liệu; luồng phân quyền mới không đọc bảng này.

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

Kiểm tra tích hợp với PostgreSQL, RAG Server và các API thật sau khi backend đã
chạy:

```powershell
cd backend
.\.venv\Scripts\python.exe smoke_check.py --username <tai-khoan-admin>
```

Script sẽ yêu cầu mật khẩu trong terminal, không ghi mật khẩu vào command
history. Nó kiểm tra health, đăng nhập/cookie, provider, taxonomy, tài liệu, sản
phẩm và API quản trị. Có thể thêm `--skip-products` nếu môi trường chưa đồng bộ
kho sản phẩm.

## Hướng dẫn triển khai

Xem `HUONG_DAN_TRIEN_KHAI.txt` để cấu hình đầy đủ, kiểm tra RAG/LLM và triển
khai production bằng systemd + Nginx.
