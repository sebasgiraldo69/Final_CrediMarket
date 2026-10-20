"""Messaging infrastructure tables; each service owns its own database."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

metadata = sa.MetaData()
outbox = sa.Table('outbox', metadata,
    sa.Column('sequence', sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column('event_id', UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column('topic', sa.Text, nullable=False),
    sa.Column('message_key', sa.Text, nullable=False),
    sa.Column('body', JSONB, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True)),
)
inbox = sa.Table('inbox', metadata,
    sa.Column('event_id', UUID(as_uuid=True), primary_key=True),
    sa.Column('body_hash', sa.Text, nullable=False),
    sa.Column('body', JSONB, nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)
failures = sa.Table('message_failures', metadata,
    sa.Column('topic', sa.Text, primary_key=True),
    sa.Column('partition', sa.Integer, primary_key=True),
    sa.Column('offset', sa.BigInteger, primary_key=True),
    sa.Column('attempts', sa.Integer, nullable=False),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('terminal', sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column('envelope', JSONB),
)
sa.Index('ix_outbox_pending', outbox.c.sequence, postgresql_where=outbox.c.sent_at.is_(None))
