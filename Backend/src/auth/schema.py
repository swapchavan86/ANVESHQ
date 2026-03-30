from __future__ import annotations

import logging

from sqlalchemy import inspect

from src.database import get_engine
from src.models import Base

logger = logging.getLogger("Anveshq.Auth.Schema")


USER_TABLE_ALTER_STATEMENTS = {
    "hashed_password": "ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255) DEFAULT ''",
    "role": "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'",
    "current_tier": "ALTER TABLE users ADD COLUMN current_tier VARCHAR(20) NOT NULL DEFAULT 'free'",
    "is_active": "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1",
    "delegated_by_id": "ALTER TABLE users ADD COLUMN delegated_by_id INTEGER",
    "stripe_customer_id": "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(100)",
    "subscription_expiry": "ALTER TABLE users ADD COLUMN subscription_expiry DATETIME",
    "telegram_chat_id": "ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(50)",
}


def ensure_identity_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    with engine.begin() as connection:
        for column_name, ddl in USER_TABLE_ALTER_STATEMENTS.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(ddl)
                logger.info("Added missing users.%s column for SaaS auth schema.", column_name)

        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_role ON users (role)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_current_tier ON users (current_tier)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_subscription_expiry ON users (subscription_expiry)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_delegated_by_id ON users (delegated_by_id)")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id ON users (stripe_customer_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id)")
        connection.exec_driver_sql("UPDATE users SET role = COALESCE(NULLIF(role, ''), 'user')")
        connection.exec_driver_sql("UPDATE users SET current_tier = COALESCE(NULLIF(current_tier, ''), 'free')")
        connection.exec_driver_sql("UPDATE users SET hashed_password = COALESCE(hashed_password, '')")
