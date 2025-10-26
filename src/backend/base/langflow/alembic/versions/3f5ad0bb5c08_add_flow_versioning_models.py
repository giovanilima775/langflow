"""Add flow versioning models

Revision ID: 3f5ad0bb5c08
Revises: 3162e83e485f
Create Date: 2025-02-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f5ad0bb5c08"
down_revision: str | Sequence[str] | None = "3162e83e485f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if _table_exists(inspector, "flow"):
        with op.batch_alter_table("flow", schema=None) as batch_op:
            if not _column_exists(inspector, "flow", "is_draft"):
                batch_op.add_column(
                    sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("true"))
                )
            if not _column_exists(inspector, "flow", "active_version_id"):
                batch_op.add_column(
                    sa.Column("active_version_id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=True)
                )
            if not _column_exists(inspector, "flow", "version_count"):
                batch_op.add_column(
                    sa.Column("version_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
                )
            if not _column_exists(inspector, "flow", "last_published_at"):
                batch_op.add_column(sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True))

        if not _index_exists(inspector, "flow", "idx_flow_is_draft"):
            op.create_index("idx_flow_is_draft", "flow", ["is_draft"])
        if not _index_exists(inspector, "flow", "idx_flow_active_version"):
            op.create_index("idx_flow_active_version", "flow", ["active_version_id"])

    if not _table_exists(inspector, "flow_version"):
        op.create_table(
            "flow_version",
            sa.Column("id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=False),
            sa.Column("flow_id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("version_tag", sa.String(length=50), nullable=True),
            sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("icon", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("icon_bg_color", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("gradient", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("endpoint_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("mcp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("run_in_background", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("action_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column("action_description", sa.Text(), nullable=True),
            sa.Column(
                "access_type",
                sa.Enum("PRIVATE", "PUBLIC", name="access_type_enum", create_type=False),
                nullable=False,
                server_default=sa.text("'PRIVATE'"),
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("published_by", sqlmodel.sql.sqltypes.types.Uuid(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("description_version", sa.Text(), nullable=True),
            sa.Column("changelog", sa.Text(), nullable=True),
            sa.Column("created_from_version_id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=True),
            sa.Column("parent_flow_data_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["flow_id"], ["flow.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["published_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["created_from_version_id"], ["flow_version.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("flow_id", "version_number", name="unique_flow_version_number"),
            sa.UniqueConstraint("flow_id", "version_tag", name="unique_flow_version_tag"),
        )
        op.create_index("idx_flow_version_flow_id", "flow_version", ["flow_id"])
        op.create_index("idx_flow_version_active", "flow_version", ["flow_id", "is_active"])
        op.create_index("idx_flow_version_published_at", "flow_version", ["published_at"])
        op.create_index("idx_flow_version_number", "flow_version", ["flow_id", "version_number"], unique=False)
        op.create_index("idx_flow_version_endpoint_name", "flow_version", ["endpoint_name"])

    if not _table_exists(inspector, "version_metadata"):
        op.create_table(
            "version_metadata",
            sa.Column("id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=False),
            sa.Column("version_id", sqlmodel.sql.sqltypes.types.Uuid(), nullable=False),
            sa.Column("execution_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_execution_time_ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_execution_time_ms", sa.Numeric(10, 2), nullable=True),
            sa.Column("error_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("api_executions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("mcp_executions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("public_executions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("webhook_executions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("deployment_environment", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
            sa.Column("rollback_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["version_id"], ["flow_version.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("version_id", name="unique_version_metadata_version_id"),
        )
        op.create_index("idx_version_metadata_version_id", "version_metadata", ["version_id"])
        op.create_index("idx_version_metadata_executions", "version_metadata", ["execution_count"])

    if _column_exists(inspector, "flow", "active_version_id"):
        existing_fks = inspector.get_foreign_keys("flow")
        fk_names = {fk["name"] for fk in existing_fks}
        if "fk_flow_active_version" not in fk_names:
            op.create_foreign_key(
                "fk_flow_active_version",
                "flow",
                "flow_version",
                ["active_version_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if _column_exists(inspector, "flow", "active_version_id"):
        existing_fks = inspector.get_foreign_keys("flow")
        fk_names = {fk["name"] for fk in existing_fks}
        if "fk_flow_active_version" in fk_names:
            op.drop_constraint("fk_flow_active_version", "flow", type_="foreignkey")

    if _index_exists(inspector, "flow", "idx_flow_active_version"):
        op.drop_index("idx_flow_active_version", table_name="flow")
    if _index_exists(inspector, "flow", "idx_flow_is_draft"):
        op.drop_index("idx_flow_is_draft", table_name="flow")

    if _table_exists(inspector, "version_metadata"):
        op.drop_index("idx_version_metadata_executions", table_name="version_metadata")
        op.drop_index("idx_version_metadata_version_id", table_name="version_metadata")
        op.drop_table("version_metadata")

    if _table_exists(inspector, "flow_version"):
        op.drop_index("idx_flow_version_endpoint_name", table_name="flow_version")
        op.drop_index("idx_flow_version_number", table_name="flow_version")
        op.drop_index("idx_flow_version_published_at", table_name="flow_version")
        op.drop_index("idx_flow_version_active", table_name="flow_version")
        op.drop_index("idx_flow_version_flow_id", table_name="flow_version")
        op.drop_table("flow_version")

    if _table_exists(inspector, "flow"):
        with op.batch_alter_table("flow", schema=None) as batch_op:
            if _column_exists(inspector, "flow", "last_published_at"):
                batch_op.drop_column("last_published_at")
            if _column_exists(inspector, "flow", "version_count"):
                batch_op.drop_column("version_count")
            if _column_exists(inspector, "flow", "active_version_id"):
                batch_op.drop_column("active_version_id")
            if _column_exists(inspector, "flow", "is_draft"):
                batch_op.drop_column("is_draft")
