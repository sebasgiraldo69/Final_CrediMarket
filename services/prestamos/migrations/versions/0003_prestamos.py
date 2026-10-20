"""Loan lifecycle, state machine, idempotency and audit history."""
from alembic import op
from app.models import metadata

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
