# TaskHub — Ngày 2: SQLAlchemy async và Alembic

Backend quản lý công việc dùng FastAPI, Pydantic v2, SQLAlchemy 2.x async và
PostgreSQL 16. Day 2 bổ sung model, relationship, migration, repository CRUD async
và phân trang vào ứng dụng Day 1.

## Cài đặt và chạy

Yêu cầu Python 3.11+ và PostgreSQL 16. Có thể dùng Docker Compose để chạy DB:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
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
│   └── v1/tasks.py
├── core/
│   ├── config.py
│   ├── constants.py
│   ├── enums.py
│   ├── exceptions.py
│   └── security.py
├── models/entities.py
├── repositories/
│   ├── base.py
│   └── task.py
├── schemas/
│   ├── base.py
│   └── task.py
└── services/task.py
migrations/
├── env.py
├── script.py.mako
└── versions/0001_create_taskhub_schema.py
tests/
```

Luồng request: router → service → repository → database. `BaseRepository[T]` cung
cấp get/create/update/delete/paginate; `TaskRepository` bổ sung truy vấn tham chiếu.
Repository chỉ flush, không commit. Service quản lý transaction và refresh sau
commit; mỗi request có `AsyncSession` riêng với `expire_on_commit=False`.

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
POST bắt buộc `title`, `project_id`, `created_by`. Các FK phải tồn tại; ID âm,
bằng 0 hoặc vượt giới hạn kiểu dữ liệu bị từ chối trước khi query DB.

Ví dụ trên DB mới, sau khi chạy seed; dùng ID thực tế trong log nếu DB đã có dữ liệu:

```json
{
  "project_id": 1,
  "created_by": 1,
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

Domain exception được handler tập trung chuyển thành 404 khi không tìm thấy,
422 khi tham chiếu đầu vào không hợp lệ, 409 khi xung đột FK/unique lúc ghi DB.
Transaction lỗi được rollback; API không lộ chi tiết SQL. Swagger/ReDoc mô tả
các response 404/409/422 và hai dạng detail của lỗi domain/validation.

Day 2 chưa có authentication/RBAC; `created_by` được truyền tường minh để thử CRUD.
Các API nghiệp vụ của user/workspace/project/label/comment được bổ sung ở session
sau; session này chuẩn bị đầy đủ model và constraint cho chúng.

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
snapshot cũ, nullable PATCH và dữ liệu giữa các app instance. CI chạy PostgreSQL 16,
Alembic upgrade/check, Ruff, mypy strict và pytest trên Python 3.11/3.12.

Day 2 được chia thành PR model/migration và PR tích hợp async CRUD, mỗi PR dưới
20 file. Khi Day 1 chưa merge, các PR dùng nhánh trước làm base để reviewer chỉ
thấy phần thay đổi mới.
