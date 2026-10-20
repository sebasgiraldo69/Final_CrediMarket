"""Durable inbox, outbox and failure/retry state."""
from alembic import op
from shared.messaging_models import metadata

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
