from alembic import context
from sqlalchemy import create_engine
from shared.runtime import database_url


def run_migrations():
    if context.is_offline_mode():
        context.configure(url=database_url(), literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(database_url(), hide_parameters=True)
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
