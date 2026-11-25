from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("tasks_version", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.execute(
        """
        CREATE FUNCTION bump_project_tasks_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            project_ids integer[];
        BEGIN
            IF TG_OP = 'INSERT' THEN
                project_ids := ARRAY[NEW.project_id];
            ELSIF TG_OP = 'DELETE' THEN
                project_ids := ARRAY[OLD.project_id];
            ELSE
                project_ids := ARRAY[OLD.project_id, NEW.project_id];
            END IF;
            PERFORM id FROM projects
                WHERE id = ANY(project_ids) ORDER BY id FOR NO KEY UPDATE;
            UPDATE projects SET tasks_version = tasks_version + 1
                WHERE id = ANY(project_ids);
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER tasks_version_changed
        AFTER INSERT OR UPDATE OR DELETE ON tasks
        FOR EACH ROW EXECUTE FUNCTION bump_project_tasks_version()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER tasks_version_changed ON tasks")
    op.execute("DROP FUNCTION bump_project_tasks_version()")
    op.drop_column("projects", "tasks_version")
