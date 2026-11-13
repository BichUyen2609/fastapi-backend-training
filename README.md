# TaskHub — Ngày 5: Middleware và Exception Handling

Backend quản lý công việc dùng FastAPI, Pydantic v2, SQLAlchemy 2.x async và
PostgreSQL 16. Day 3 bổ sung đăng ký, đăng nhập, access token JWT và bảo vệ CRUD
Task. Day 4 hoàn thiện vòng đời phiên đăng nhập (refresh token xoay vòng, logout),
quản lý profile/mật khẩu, CRUD Workspace, mời/xóa member, CRUD Project có archive,
và gom toàn bộ phân quyền ADMIN/OWNER/EDITOR/VIEWER về một chỗ. Day 5 thêm
middleware (request ID, access log, thời gian xử lý, security header, CORS), xử lý
lỗi tập trung với một định dạng response duy nhất, API Label/Comment và lọc task
theo status, priority, assignee.

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
│   ├── params.py
│   └── v1/
│       ├── auth.py
│       ├── users.py
│       ├── workspaces.py
│       ├── projects.py
│       ├── tasks.py
│       ├── labels.py
│       └── comments.py
├── core/
│   ├── config.py
│   ├── constants.py
│   ├── enums.py
│   ├── errors.py
│   ├── exceptions.py
│   ├── middleware.py
│   └── security.py
├── models/entities.py
├── repositories/
│   ├── base.py
│   ├── access.py
│   ├── auth.py
│   ├── workspace.py
│   ├── project.py
│   ├── task.py
│   ├── label.py
│   └── comment.py
├── schemas/
│   ├── base.py
│   ├── auth.py
│   ├── workspace.py
│   ├── project.py
│   ├── task.py
│   ├── label.py
│   └── comment.py
└── services/
    ├── base.py
    ├── auth.py
    ├── user.py
    ├── workspace.py
    ├── project.py
    ├── task.py
    ├── label.py
    └── comment.py
migrations/
├── env.py
├── script.py.mako
└── versions/
    ├── 0001_create_taskhub_schema.py
    └── 0002_create_refresh_tokens.py
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

Định nghĩa 8 bảng nghiệp vụ: `users`, `workspaces`, `workspace_members`,
`projects`, `tasks`, `labels`, `task_labels`, `comments`, cùng bảng
`refresh_tokens` (Day 4) lưu hash SHA-256 của refresh token. Enum đặt trong `core/enums.py`; giới
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
| User → refresh token | CASCADE |
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

## Authentication và phiên đăng nhập

| Method | Endpoint | Dữ liệu và kết quả |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | JSON email/full_name/password → 201, thông tin user |
| POST | `/api/v1/auth/login` | Form username/password → 200, access + refresh token |
| POST | `/api/v1/auth/refresh` | JSON refresh_token → 200, cặp token mới |
| POST | `/api/v1/auth/logout` | JSON refresh_token → 204, thu hồi token |
| GET | `/api/v1/users/me` | Bearer token → 200, profile hiện tại |
| PATCH | `/api/v1/users/me` | JSON email/full_name → 200, profile mới |
| POST | `/api/v1/users/me/password` | JSON current_password/new_password → 204 |

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

Refresh token là chuỗi ngẫu nhiên 48 byte; DB chỉ lưu hash SHA-256 kèm
`expires_at`/`revoked_at`, mặc định sống 7 ngày (`REFRESH_TOKEN_EXPIRE_DAYS`).
Mỗi lần refresh, token cũ bị thu hồi bằng một câu `UPDATE ... WHERE revoked_at IS
NULL` nguyên tử rồi mới cấp token mới. Dùng lại token đã thu hồi được coi là token
bị lộ: mọi refresh token còn hiệu lực của user bị thu hồi và trả 401. Logout luôn
trả 204 để không lộ token nào tồn tại. Validation error của field password/token
không phản chiếu giá trị đã gửi.

PATCH `/users/me` chỉ nhận `email`, `full_name`, không nhận null; email được chuẩn
hóa và trùng thì trả 409. Đổi mật khẩu yêu cầu mật khẩu hiện tại (sai trả 400),
mật khẩu mới phải khác mật khẩu cũ và mọi refresh token bị thu hồi; access token
đã cấp tự hết hạn theo thời gian sống ngắn.

## Phân quyền (RBAC)

Quyền hiệu lực trong workspace: `owner_id` của workspace là OWNER, còn lại lấy
role trong `workspace_members`. ADMIN hệ thống bỏ qua kiểm tra. Mọi service dùng
chung `ensure_role(actor, role, minimum)` với thứ bậc VIEWER < EDITOR < OWNER nên
quy tắc chỉ định nghĩa một lần; truy vấn quyền nằm trong `AccessRepository`.

| Hành động | Quyền tối thiểu |
| --- | --- |
| Tạo workspace | User đăng nhập (trở thành OWNER) |
| Xem workspace, danh sách member, danh sách project | VIEWER |
| Sửa/xóa workspace, mời/đổi role/xóa member | OWNER |
| Rời workspace (xóa chính mình) | VIEWER |
| Tạo/sửa/archive/restore project | EDITOR |
| Xóa project | OWNER |
| Đọc task | VIEWER |
| Tạo/sửa/xóa task | EDITOR |
| Xem label, comment | VIEWER |
| Tạo/sửa/xóa label, gán/bỏ label, thêm comment | EDITOR |
| Xóa comment của chính mình | VIEWER |
| Xóa comment của người khác | OWNER |

Resource không tồn tại trả 404; tồn tại nhưng user không thuộc workspace hoặc
thiếu quyền trả 403. `/workspaces` và `/tasks` chỉ trả dữ liệu user được đọc
(ADMIN thấy tất cả). Khi đổi project của task, phải có quyền sửa cả project nguồn
và đích; assignee phải là user active thuộc workspace đích. Token thiếu/sai/hết
hạn trả 401 với `WWW-Authenticate: Bearer`.

## API Workspace và Project

| Method | Endpoint | Kết quả |
| --- | --- | --- |
| POST | `/api/v1/workspaces` | 201, kèm membership OWNER |
| GET | `/api/v1/workspaces?page=1&limit=20` | 200, workspace user tham gia |
| GET/PATCH/DELETE | `/api/v1/workspaces/{id}` | 200/200/204 |
| GET | `/api/v1/workspaces/{id}/members` | 200, gồm cả owner |
| POST | `/api/v1/workspaces/{id}/members` | 201, mời theo email, role EDITOR/VIEWER |
| PATCH | `/api/v1/workspaces/{id}/members/{user_id}` | 200, đổi role |
| DELETE | `/api/v1/workspaces/{id}/members/{user_id}` | 204 |
| POST | `/api/v1/workspaces/{id}/projects` | 201 |
| GET | `/api/v1/workspaces/{id}/projects?status=ACTIVE` | 200, phân trang |
| GET/PATCH/DELETE | `/api/v1/projects/{id}` | 200/200/204 |
| POST | `/api/v1/projects/{id}/archive` | 200, status ARCHIVED |
| POST | `/api/v1/projects/{id}/restore` | 200, status ACTIVE |

Không thể cấp role OWNER qua API (422); owner của workspace không thể bị xóa hay
đổi role (409). Mời email không tồn tại hoặc tài khoản bị khóa trả 422, mời lại
member hiện có trả 409. Khi xóa member, task trong workspace đó đang assign cho họ
được bỏ assign; task ở workspace khác giữ nguyên. Xóa workspace cascade project,
task, label và comment.

Tên project là duy nhất trong workspace (409). Project ARCHIVED chỉ đọc: tạo, sửa,
xóa task hoặc chuyển task vào project đó trả 409 cho đến khi restore.

Thử trên Swagger: mở `/docs` → **Authorize**, nhập `DEMO_EMAIL` vào username và
`DEMO_PASSWORD` vào password từ `.env`. User seed là owner của workspace/project
demo.

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
trang; mặc định page=1, limit=20, tối đa 100. Cả `/tasks` và
`/projects/{project_id}/tasks` lọc được theo `status`, `priority`, `assignee_id`
(kết hợp được với nhau và với phân trang); `/tasks` lọc thêm theo `project_id`.
Giá trị enum hoặc ID không hợp lệ trả 422. Thứ tự ổn định theo
`created_at DESC, id DESC`, có tie-breaker khi timestamp bằng nhau.

```text
GET /api/v1/projects/1/tasks?status=IN_PROGRESS&priority=HIGH&assignee_id=2&page=1&limit=20
```

PATCH dùng `exclude_unset=True`: bỏ qua field thì giữ nguyên; `description`,
`due_date`, `assignee_id` nhận null để xóa giá trị. `title`, `status`, `priority`,
`project_id` không nhận null. Title trim khoảng trắng và dài 1–200 ký tự;
description tối đa 5.000 ký tự, khớp `String(5000)` trong DB. Field lạ và các field
do server quản lý bị từ chối. `{}` không thay đổi task hay `updated_at`.

UPDATE chỉ ghi các cột client gửi, tránh ghi đè field khác từ snapshot cũ khi có
PATCH đồng thời. ID và `created_at` bất biến; `created_by` không sửa qua PATCH.

## API Label và Comment

| Method | Endpoint | Kết quả |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/labels` | 201, label mới |
| GET | `/api/v1/projects/{project_id}/labels` | 200, sắp theo tên |
| PATCH/DELETE | `/api/v1/labels/{label_id}` | 200/204 |
| GET | `/api/v1/tasks/{task_id}/labels` | 200, label của task |
| POST | `/api/v1/tasks/{task_id}/labels/{label_id}` | 200, danh sách label sau khi gán |
| DELETE | `/api/v1/tasks/{task_id}/labels/{label_id}` | 204 |
| POST | `/api/v1/tasks/{task_id}/comments` | 201, `author_id` là user đăng nhập |
| GET | `/api/v1/tasks/{task_id}/comments?page=1&limit=20` | 200, phân trang |
| DELETE | `/api/v1/comments/{comment_id}` | 204 |

Label có `name` (1–150 ký tự, duy nhất trong project, trùng trả 409) và `color`
dạng `#RRGGBB`, lưu chữ thường. Chỉ gán được label cùng project với task (422).
Gán và bỏ gán đều idempotent. Khi task chuyển sang project khác, các label của
project cũ được gỡ khỏi task; xóa label sẽ gỡ label đó khỏi mọi task. Comment dài
1–4.000 ký tự sau khi trim; client không gửi được `author_id`. Project ARCHIVED
chỉ đọc nên tạo/sửa label, gán label, thêm hoặc xóa comment đều trả 409.

## Middleware và xử lý lỗi

Thứ tự middleware từ ngoài vào trong: `RequestContextMiddleware` → CORS →
`SecurityHeadersMiddleware` → router. Các middleware viết dạng ASGI thuần, không
dùng `BaseHTTPMiddleware`, nên không đọc lại body và không chặn streaming.

- **Request ID:** nhận `X-Request-ID` của client nếu khớp `[A-Za-z0-9._-]{8,64}`,
  ngược lại sinh UUID mới. ID được trả về trong header, trong body lỗi và ghi vào
  log để truy vết một request xuyên suốt.
- **Access log:** logger `taskhub.access` ghi request ID, method, path, status và
  thời gian xử lý, kể cả khi request lỗi 500. Không ghi header hay body nên token
  và mật khẩu không lọt vào log.
- **Thời gian xử lý:** header `X-Process-Time-Ms`.
- **Security header:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`.
- **CORS:** chỉ cho phép các origin trong `CORS_ORIGINS` (JSON list trong `.env`,
  mặc định rỗng là chặn mọi origin), expose `X-Request-ID` và `X-Process-Time-Ms`.

Mọi lỗi trả cùng một định dạng:

```json
{"detail": "Task not found", "code": "NOT_FOUND", "request_id": "3f9c..."}
```

| Nguồn lỗi | Status | `code` |
| --- | --- | --- |
| Vi phạm quy tắc nghiệp vụ | 400 | `BAD_REQUEST` |
| Thiếu/sai token | 401 | `UNAUTHORIZED` (kèm `WWW-Authenticate: Bearer`) |
| Thiếu quyền | 403 | `FORBIDDEN` |
| Không tìm thấy resource hoặc route | 404 | `NOT_FOUND` |
| Sai HTTP method | 405 | `METHOD_NOT_ALLOWED` |
| Xung đột unique/FK, project archived | 409 | `CONFLICT` |
| Tham chiếu không hợp lệ | 422 | `INVALID_REFERENCE` |
| Body/query/path sai kiểu | 422 | `VALIDATION_ERROR`, `detail` là danh sách lỗi |
| Mất kết nối database | 503 | `SERVICE_UNAVAILABLE` (kèm `Retry-After`) |
| Lỗi không lường trước | 500 | `INTERNAL_ERROR` |

Mỗi domain exception tự khai báo `status_code` và `code`, handler chung trong
`core/errors.py` chỉ việc đọc ra. Lỗi 500 trả thông điệp chung, còn traceback
cùng request ID được ghi vào logger `taskhub.errors`; response không bao giờ chứa
chi tiết exception hay câu SQL. Validation error của field password/token bỏ
`input` và `ctx` để không phản chiếu giá trị đã gửi. Transaction lỗi được
rollback. Swagger/ReDoc mô tả các response 401/403/404/409/422 theo schema
`ErrorResponse`.

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
đăng ký trùng email. Test Day 4 kiểm tra refresh token xoay vòng, dùng lại, hết
hạn, logout; đổi mật khẩu thu hồi phiên; PATCH profile; ma trận quyền
VIEWER/EDITOR/OWNER/ADMIN/người ngoài cho workspace, member và project; khóa
owner; bỏ assign khi xóa member và chặn ghi task trong project archived. Test
Day 5 kiểm tra request ID (sinh mới, nhận từ client, thay giá trị không hợp lệ),
security header, access log, CORS, định dạng lỗi 404/405/422/401, lỗi 500 không lộ
chi tiết, 503 khi mất DB, CRUD và phân quyền Label/Comment, gán label khác project,
gỡ label khi chuyển task và lọc task theo từng tiêu chí lẫn kết hợp.
CI chạy PostgreSQL 16,
Alembic upgrade/check, Ruff, mypy strict và pytest trên Python 3.11/3.12.

Nhánh Day 5 được tạo từ nhánh Day 4. Caching Redis, background task và Docker cho
app được giữ cho các session tiếp theo.
