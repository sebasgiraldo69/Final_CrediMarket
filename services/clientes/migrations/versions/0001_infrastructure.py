"""Independent infrastructure baseline; domain tables come in later phases."""
from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    table = op.create_table("infrastructure_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.bulk_insert(table, [{"id": 1, "service": "clientes"}])

def downgrade():
    op.drop_table("infrastructure_metadata")
