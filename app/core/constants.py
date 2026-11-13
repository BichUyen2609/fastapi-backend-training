from typing import Final

APP_NAME: Final = "TaskHub"
APP_VERSION: Final = "0.1.0"
API_V1_PREFIX: Final = "/api/v1"

TITLE_MIN_LENGTH: Final = 1
TITLE_MAX_LENGTH: Final = 200
DESCRIPTION_MAX_LENGTH: Final = 5_000
NAME_MAX_LENGTH: Final = 150
EMAIL_MAX_LENGTH: Final = 254
PASSWORD_HASH_MAX_LENGTH: Final = 255
COLOR_MAX_LENGTH: Final = 7
COMMENT_MAX_LENGTH: Final = 4_000
DEFAULT_PAGE: Final = 1
DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100
MAX_ENTITY_ID: Final = 2_147_483_647
PASSWORD_MIN_LENGTH: Final = 8
PASSWORD_MAX_LENGTH: Final = 128
JWT_ALGORITHM: Final = "HS256"
JWT_SECRET_MIN_BYTES: Final = 32
ACCESS_TOKEN_EXPIRE_MINUTES: Final = 15
MAX_ACCESS_TOKEN_EXPIRE_MINUTES: Final = 1_440
REFRESH_TOKEN_EXPIRE_DAYS: Final = 7
MAX_REFRESH_TOKEN_EXPIRE_DAYS: Final = 90
REFRESH_TOKEN_BYTES: Final = 48
REFRESH_TOKEN_MAX_LENGTH: Final = 256
TOKEN_HASH_LENGTH: Final = 64
SECONDS_PER_DAY: Final = 86_400
SECONDS_PER_MINUTE: Final = 60

TASK_NOT_FOUND: Final = "Task not found"
PROJECT_NOT_FOUND: Final = "Project not found"
USER_NOT_FOUND: Final = "User not found"
WORKSPACE_NOT_FOUND: Final = "Workspace not found"
MEMBER_NOT_FOUND: Final = "Member not found"
ALREADY_MEMBER: Final = "User is already a workspace member"
OWNER_MEMBERSHIP_LOCKED: Final = "Workspace owner cannot be removed or changed"
OWNER_ROLE_NOT_ASSIGNABLE: Final = "OWNER role cannot be assigned to members"
PROJECT_NAME_TAKEN: Final = "Project name already exists in this workspace"
PROJECT_ARCHIVED: Final = "Project is archived"
INVALID_REFRESH_TOKEN: Final = "Invalid or expired refresh token"
INCORRECT_PASSWORD: Final = "Current password is incorrect"
PASSWORD_UNCHANGED: Final = "New password must differ from the current password"
RESOURCE_CONFLICT: Final = "Resource conflicts with existing data"
AUTHENTICATION_REQUIRED: Final = "Could not validate credentials"
INVALID_CREDENTIALS: Final = "Invalid email or password"
INSUFFICIENT_PERMISSIONS: Final = "Insufficient permissions"
EMAIL_ALREADY_REGISTERED: Final = "Email already registered"
INVALID_ASSIGNEE: Final = "Assignee must be an active workspace member"
NON_NULL_FIELD_MESSAGE: Final = (
    "Field cannot be null; omit it to keep its current value"
)
