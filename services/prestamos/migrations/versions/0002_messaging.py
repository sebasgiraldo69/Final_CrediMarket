"""Messaging transport and inventory projection, no credit decisions."""
from alembic import op
from shared.messaging_models import metadata
from app.messaging import metadata as projection

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)
    projection.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    projection.drop_all(op.get_bind(), checkfirst=False)
    metadata.drop_all(op.get_bind(), checkfirst=False)
