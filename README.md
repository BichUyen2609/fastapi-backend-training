# TaskHub — Ngày 3: Authentication và JWT

Backend quản lý công việc dùng FastAPI, Pydantic v2, SQLAlchemy 2.x async và
PostgreSQL 16. Day 3 bổ sung đăng ký, đăng nhập, access token JWT, profile hiện tại
và bảo vệ CRUD Task bằng quyền workspace trên nền database của Day 2.

## Cài đặt và chạy

Yêu cầu Python 3.11+ và PostgreSQL 16. Có thể dùng Docker Compose để chạy DB:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Đặt khóa ngẫu nhiên vừa tạo vào `JWT_SECRET` trong `.env`, thay giá trị `change-me`.
Giữ khóa này riêng cho từng môi trường; `.env` đã được Git ignore. Sau đó chạy:

```powershell
docker compose up -d --wait db
docker compose exec db createdb -U taskhub taskhub_test
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m app.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Chỉ cần tạo `taskhub_test` một lần. Nếu dùng PostgreSQL đã cài sẵn, tạo hai DB riêng
`taskhub` và `taskhub_test`, rồi cập nhật hai URL trong `.env`. Trên Linux/macOS,
thay `.\.venv\Scripts\python.exe` bằng `.venv/bin/python`.

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>

Các mật khẩu trong `.env.example` là dữ liệu mẫu cho local. Credential thực chỉ
đặt trong `.env`, file này đã được Git ignore. Config đọc tập trung qua
`pydantic-settings`; code không có credential mặc định. `DATABASE_ECHO` điều khiển
SQL logging. `requirements.txt` lưu UTF-8 không BOM và là nguồn dependency runtime
duy nhất; `pyproject.toml` đọc trực tiếp từ file này.

API kiểm tra khóa JWT ngay khi startup: thiếu khóa, dùng placeholder hoặc khóa
ngắn hơn 32 byte sẽ bị từ chối. Lệnh Alembic chỉ cần cấu hình database khi
`JWT_SECRET` chưa được khai báo. Test tự tạo khóa riêng và chỉ dùng DB test.

`app.seed` hash mật khẩu demo bằng Argon2 trước khi lưu và tạo user, workspace,
membership OWNER, project trong cùng transaction. Chạy lại không tạo demo trùng.
Lệnh log `user_id` và `project_id` thực tế để dùng khi gọi API.

## Cấu trúc

```text
app/
├── main.py
├── database.py
├── seed.py
├── api/
│   ├── dependencies.py
│   └── v1/
│       ├── auth.py
│       └── tasks.py
├── core/
│   ├── config.py
│   ├── constants.py
│   ├── enums.py
│   ├── exceptions.py
│   └── security.py
├── models/entities.py
├── repositories/
│   ├── base.py
│   ├── auth.py
│   └── task.py
├── schemas/
│   ├── base.py
│   ├── auth.py
│   └── task.py
└── services/
    ├── auth.py
    └── task.py
migrations/
├── env.py
├── script.py.mako
└── versions/0001_create_taskhub_schema.py
tests/
```

Luồng request: router → service → repository → database. `BaseRepository[T]` cung
cấp get/create/update/delete/paginate; `TaskRepository` bổ sung truy vấn tham chiếu.
Repository chỉ flush, không commit. Service quản lý transaction và refresh sau
commit; mỗi request có `AsyncSession` riêng với `expire_on_commit=False`. Việc
xác thực user và thao tác Task dùng chung session; service commit transaction
đang mở sau phần xác thực, không gọi `begin()` chồng lên transaction đó.

Lifespan kiểm tra kết nối và đóng engine khi ứng dụng dừng. Không tự tạo bảng khi
startup; schema được quản lý bằng Alembic. Router, service và repository đều
`async`/`await`; ORM model được tách khỏi các schema request/response.

## Model và migration

Định nghĩa đủ 8 bảng: `users`, `workspaces`, `workspace_members`, `projects`,
`tasks`, `labels`, `task_labels`, `comments`. Enum đặt trong `core/enums.py`; giới
hạn chuỗi dùng chung từ `constants.py` cho model, schema và migration.

Enum dùng `native_enum=False` và `create_constraint=True`, để DB từ chối giá trị
lạ bằng CHECK constraint. Không tạo PostgreSQL enum type nên downgrade không để
lại type rác. Cột có giá trị mặc định dùng `server_default` để insert SQL trực
tiếp vẫn hợp lệ. Timestamp dùng `TIMESTAMP WITH TIME ZONE`, đọc về UTC.

| Quan hệ | Khi xóa bản ghi cha |
| --- | --- |
| Workspace → project/membership | CASCADE |
| Project → task/label | CASCADE |
| Task → comment/task-label | CASCADE |
| User → task được assign | SET NULL |
| User → workspace sở hữu/task đã tạo/comment đã viết | RESTRICT |

Relationship dùng `passive_deletes` phù hợp với FK và `lazy="raise"` để tránh
query ngầm trong async. FK dùng để filter/join có index; bảng liên kết có index
cho `label_id` và `user_id`, bên cạnh khóa chính ghép.

Migration ban đầu được autogenerate từ model và đã rà lại. Khi thay model:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

## Authentication và phân quyền

| Method | Endpoint | Dữ liệu và kết quả |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | JSON email/full_name/password → 201, thông tin user |
| POST | `/api/v1/auth/login` | Form username/password → 200, access token |
| GET | `/api/v1/users/me` | Bearer token → 200, profile hiện tại |

Register chuẩn hóa email về chữ thường, trim họ tên nhưng giữ nguyên khoảng
trắng trong password. Password dài 8–128 ký tự, được hash Argon2 trong thread
pool trước khi lưu. User mới luôn là MEMBER, active theo default của DB; client
không được gửi role, is_active, hashed_password hay id. Email trùng trả 409, kể
cả khi hai đăng ký đồng thời chạm unique constraint.

Login dùng `application/x-www-form-urlencoded`, trường `username` là email.
Sai email/password hoặc tài khoản bị khóa đều trả cùng lỗi 401. Response user
không có password/hash; validation error của password không phản chiếu giá trị
đã gửi. Response token có `Cache-Control: no-store` và `Pragma: no-cache`.

JWT dùng HS256 cố định và chứa sub, exp, iat, nbf, iss, aud, jti, token_type=access.
Server kiểm tra chữ ký, thuật toán, thời gian, issuer, audience và các claim bắt
buộc. Token mặc định hết hạn sau 15 phút, cấu hình bằng
`ACCESS_TOKEN_EXPIRE_MINUTES`. Mỗi request đọc lại user và trạng thái active từ DB;
role trong token không được dùng để nâng quyền.

| Vai trò | Đọc Task | Tạo/sửa/xóa Task |
| --- | --- | --- |
| ADMIN | Tất cả workspace | Tất cả workspace |
| Workspace owner hoặc membership OWNER | Workspace của mình | Workspace của mình |
| EDITOR | Workspace được tham gia | Workspace được tham gia |
| VIEWER | Workspace được tham gia | 403 |
| Không tham gia workspace | 403 khi truy cập trực tiếp | 403 |

GET `/tasks` chỉ trả task và total thuộc các workspace user được đọc. Khi đổi
project của task, phải có quyền sửa cả project nguồn và đích. Assignee phải là
user active và thuộc workspace đích. Mọi endpoint Task yêu cầu Bearer token;
token thiếu/sai/hết hạn trả 401 với `WWW-Authenticate: Bearer`.

Thử trên Swagger: mở `/docs` → **Authorize**, nhập `DEMO_EMAIL` vào username và
`DEMO_PASSWORD` vào password từ `.env`. User seed là owner của project demo.
Đăng ký user mới không tự tạo workspace/project; các API workspace và mời member
được bổ sung ở session sau. Refresh token/logout, middleware và Redis nằm ngoài
phạm vi Day 3 này.

## API Task

| Method | Endpoint | Kết quả |
| --- | --- | --- |
| POST | `/api/v1/tasks` | 201 và header Location |
| GET | `/api/v1/tasks?page=1&limit=20` | 200, danh sách phân trang |
| GET | `/api/v1/projects/{project_id}/tasks` | 200, task trong project |
| GET | `/api/v1/tasks/{task_id}` | 200, chi tiết |
| PATCH | `/api/v1/tasks/{task_id}` | 200, cập nhật từng phần |
| DELETE | `/api/v1/tasks/{task_id}` | 204, body rỗng |

ID chuyển từ UUID của bản in-memory Day 1 sang số nguyên dương do DB sinh.
POST bắt buộc `title`, `project_id`; `created_by` lấy từ user đăng nhập và không
được gửi trong request. Các FK phải tồn tại; ID âm,
bằng 0 hoặc vượt giới hạn kiểu dữ liệu bị từ chối trước khi query DB.

Ví dụ trên DB mới, sau khi chạy seed; dùng ID thực tế trong log nếu DB đã có dữ liệu:

```json
{
  "project_id": 1,
  "title": "Hoàn thành Day 2",
  "priority": "HIGH",
  "due_date": "2027-01-15"
}
```

List trả `items`, `total`, `page`, `limit`. `total` là tổng kết quả trước khi phân
trang; mặc định page=1, limit=20, tối đa 100. Có thể lọc `/tasks` theo `project_id`.
Thứ tự ổn định theo `created_at DESC, id DESC`, có tie-breaker khi timestamp bằng nhau.

PATCH dùng `exclude_unset=True`: bỏ qua field thì giữ nguyên; `description`,
`due_date`, `assignee_id` nhận null để xóa giá trị. `title`, `status`, `priority`,
`project_id` không nhận null. Title trim khoảng trắng và dài 1–200 ký tự;
description tối đa 5.000 ký tự, khớp `String(5000)` trong DB. Field lạ và các field
do server quản lý bị từ chối. `{}` không thay đổi task hay `updated_at`.

UPDATE chỉ ghi các cột client gửi, tránh ghi đè field khác từ snapshot cũ khi có
PATCH đồng thời. ID và `created_at` bất biến; `created_by` không sửa qua PATCH.

Domain exception được handler tập trung chuyển thành 401 khi xác thực thất bại,
403 khi thiếu quyền, 404 khi không tìm thấy,
422 khi tham chiếu đầu vào không hợp lệ, 409 khi xung đột FK/unique lúc ghi DB.
Transaction lỗi được rollback; API không lộ chi tiết SQL. Swagger/ReDoc mô tả
các response 401/403/404/409/422 và hai dạng detail của lỗi domain/validation.

## Kiểm tra chất lượng

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -W error
```

Test chỉ dùng `TEST_DATABASE_URL` có tên DB kết thúc `_test` và khác DB dev.
Mỗi test có outer transaction riêng; session của request dùng savepoint, service
commit vẫn được rollback khi test kết thúc. Test migration chạy upgrade →
downgrade → upgrade trong schema tạm rồi rollback toàn bộ schema đó.

Test PostgreSQL thật kiểm tra default SQL, enum, FK/index, CASCADE/SET NULL/RESTRICT,
rollback nhiều bước, mapping IntegrityError, dependency override, pagination,
snapshot cũ, nullable PATCH và dữ liệu giữa các app instance. Test Day 3 kiểm tra
JWT giả/hết hạn/thiếu claim, khóa user, quyền workspace, giả mạo created_by và
đăng ký trùng email. CI chạy PostgreSQL 16,
Alembic upgrade/check, Ruff, mypy strict và pytest trên Python 3.11/3.12.

Nhánh Day 3 được tạo từ main sau khi merge đầy đủ Day 1 và Day 2. Các phần nghiệp
vụ còn lại trong lịch Day 4–7 được giữ cho các session tiếp theo.
