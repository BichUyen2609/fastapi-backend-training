# TaskHub — FastAPI Backend Training

Day 2 được chia thành hai PR: database/model/migration, sau đó async CRUD và
phân trang. Phần database định nghĩa đủ 8 bảng của sample app: users, workspaces,
workspace_members, projects, tasks, labels, task_labels, comments. API Day 1 được
giữ nguyên trong PR database; PR tiếp theo chuyển API sang SQLAlchemy async.

## Database và migration

```powershell
Copy-Item .env.example .env
docker compose up -d db
docker compose exec db createdb -U taskhub taskhub_test
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m app.seed
```

Các giá trị mật khẩu trong `.env.example` chỉ là dữ liệu mẫu cho local. Config đọc
qua `Settings`; code không có credential mặc định. `requirements.txt` là nguồn
khai báo dependency runtime, `pyproject.toml` đọc trực tiếp từ file này.

Model ORM nằm trong `app/models/entities.py`, enum ở `app/core/enums.py`, cấu hình
session ở `app/database.py`. Mỗi request sẽ có session riêng với
`expire_on_commit=False`. Timestamps dùng `TIMESTAMP WITH TIME ZONE` và được đọc
về UTC. Enum dùng CHECK constraint (`native_enum=False`, `create_constraint=True`),
nên downgrade không để lại PostgreSQL enum type. Các cột có default dùng
`server_default`; độ dài chuỗi dùng constants chung cho schema, model và migration.

Workspace/project/task dùng CASCADE cho dữ liệu con; xóa assignee đặt
`assignee_id=NULL`; xóa owner/creator/author còn dữ liệu tham chiếu bị RESTRICT.
Relationship cấu hình `passive_deletes` và `lazy="raise"` để tránh ghi FK null hoặc
phát sinh lazy query ngoài ý muốn trong async. FK dùng để filter/join có index;
hai bảng liên kết có thêm index cho cột không đứng đầu khóa chính ghép.

`python -m app.seed` tạo user đã hash mật khẩu bằng Argon2, workspace, membership
OWNER và project trong cùng transaction. Chạy lại không tạo demo trùng. Lệnh log
`user_id` và `project_id` thực tế để dùng khi thử API ở PR tích hợp.

Test database chỉ nhận `TEST_DATABASE_URL` có tên DB kết thúc bằng `_test` và khác
DB dev. Mỗi test mở transaction riêng và rollback khi kết thúc. Kiểm thử migration
chạy upgrade/downgrade/upgrade trong schema tạm của DB test, không thay schema dev.
Test dùng PostgreSQL thật; không thay bằng SQLite hoặc tắt kiểm tra foreign key.

## Day 1: Core Setup & CRUD

Skeleton API quản lý công việc theo layered architecture, dùng FastAPI và Pydantic v2.
Phạm vi Day 1: app instance, APIRouter, lifespan, dependency injection và CRUD cho
một resource `Task`.

## Chạy local

Yêu cầu Python 3.11 trở lên. Chạy trong thư mục project:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Linux/macOS: thay `.\.venv\Scripts\python.exe` bằng `.venv/bin/python`.

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>

Repository hiện lưu dữ liệu trong bộ nhớ của từng app instance. Restart sẽ mất
dữ liệu; chạy một worker. SQLAlchemy async, Alembic, database, auth/RBAC, Redis và
Docker Compose thuộc các session tiếp theo, chưa nằm trong bản Day 1 này.

## Cấu trúc

```text
app/
├── main.py                 # App factory, lifespan, exception handler
├── api/
│   ├── dependencies.py     # Wiring repository → service bằng Depends
│   └── v1/tasks.py         # HTTP endpoints, status code, response schemas
├── core/
│   ├── constants.py        # Giới hạn và thông báo dùng chung
│   └── exceptions.py       # Exception nghiệp vụ, không phụ thuộc HTTP
├── models/task.py          # Dataclass Task, enums, kiểu dữ liệu cập nhật
├── schemas/
│   ├── base.py             # ConfigDict dùng chung
│   └── task.py             # TaskCreate / TaskUpdate / TaskResponse
├── repositories/task.py    # Protocol và implementation in-memory
└── services/task.py        # Use cases, chỉ dùng self.repository
tests/                      # API, validation, DI, isolation, OpenAPI
```

Request đi qua `router → service → repository`. Repository chỉ lưu model nội bộ
`Task`, không lưu `TaskResponse`. Model bất biến giúp tránh sửa dữ liệu ngoài
repository; lock bảo vệ từng thao tác đọc/ghi và cập nhật từng phần một cách atomic.
Repository được khởi tạo trong lifespan cho từng app, không dùng singleton global.
Có thể thay implementation qua `get_task_repository` và `app.dependency_overrides`.

## API

| Method | Endpoint | Thành công |
| --- | --- | --- |
| POST | `/api/v1/tasks` | 201, task mới và header `Location` |
| GET | `/api/v1/tasks` | 200, danh sách task |
| GET | `/api/v1/tasks/{task_id}` | 200, chi tiết task |
| PATCH | `/api/v1/tasks/{task_id}` | 200, task sau cập nhật |
| DELETE | `/api/v1/tasks/{task_id}` | 204, body rỗng |

`task_id` là UUID. Task có `title`, `description`, `status`, `priority`, `due_date`,
`created_at`, `updated_at`. ID và timestamp do server tạo; timestamp dùng UTC.

```json
{
  "title": "Hoàn thành Day 1",
  "description": "Core setup và CRUD",
  "status": "TODO",
  "priority": "MEDIUM",
  "due_date": "2027-01-15"
}
```

POST chỉ bắt buộc `title`. `status` mặc định `TODO`, nhận
`TODO / IN_PROGRESS / IN_REVIEW / DONE`; `priority` mặc định `MEDIUM`, nhận
`LOW / MEDIUM / HIGH / URGENT`. `due_date` là ngày theo định dạng `YYYY-MM-DD`.

## Validation và PATCH

- `title`: trim khoảng trắng, dài 1–200 ký tự sau trim; chuỗi toàn khoảng trắng bị từ chối.
- `description`: trim khoảng trắng, tối đa 5.000 ký tự; cho phép `null`.
- `due_date`: cho phép `null` để xóa hạn công việc.
- `title`, `status`, `priority`: không nhận `null`, cả POST lẫn PATCH.
- Field không khai báo hoặc field do server quản lý: trả 422.
- Validation chạy trước khi gọi service, nên request không hợp lệ không ghi một phần dữ liệu.

| PATCH body | Kết quả |
| --- | --- |
| `{"status": "DONE"}` | Chỉ đổi status, giữ các field còn lại |
| `{"description": null}` | Xóa description |
| `{"due_date": null}` | Xóa due_date |
| `{"title": null}` | 422, giữ nguyên task; GET tiếp tục trả 200 |
| `{"title": "   "}` | 422, giữ nguyên task |
| `{}` | 200, không thay đổi dữ liệu hoặc updated_at |

`exclude_unset=True` chỉ bỏ field không được gửi, vẫn giữ `null` được gửi tường minh.
Vì vậy `TaskUpdate` dùng `field_validator` để chặn null cho các field không nullable.
`SkipJsonSchema` giúp OpenAPI không quảng bá null là giá trị hợp lệ cho những field đó.

## Xử lý lỗi

Service raise `NotFoundException`; handler đăng ký tại `main.py` chuyển thành 404:

```json
{"detail": "Task not found"}
```

GET/PATCH/DELETE dùng chung thông báo trong `constants.py`. UUID sai định dạng,
JSON lỗi và dữ liệu không hợp lệ trả 422 theo định dạng validation mặc định của
FastAPI. Swagger/ReDoc mô tả các response 404 và 422.

## Kiểm tra chất lượng

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

Ruff kiểm tra format, import, lỗi phổ biến và chặn `print` bằng rule T20; ứng dụng
dùng `logging`. CI chạy format check, lint, mypy strict và pytest trên Python
3.11 và 3.12. Regression test bao phủ null PATCH, whitespace/giới hạn title,
giữ dữ liệu khi request lỗi, nullable/omission, toàn bộ CRUD qua repository được
inject, storage độc lập giữa các app và tài liệu OpenAPI.

Tài liệu tham chiếu:
[Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/),
[Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/),
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[FastAPI exception handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/),
[Starlette TestClient](https://starlette.dev/testclient/),
[Ruff configuration](https://docs.astral.sh/ruff/configuration/).
