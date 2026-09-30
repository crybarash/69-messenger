import os
import sqlite3

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg


def get_db():
    if USE_POSTGRES:
        return psycopg.connect(DATABASE_URL)

    return sqlite3.connect("messenger.db")


def migrate():
    db = get_db()
    cursor = db.cursor()

    if USE_POSTGRES:
        id_type = "BIGSERIAL PRIMARY KEY"
        user_id_type = "BIGINT"
        timestamp_type = "TIMESTAMPTZ"
        now_default = "CURRENT_TIMESTAMP"
        boolean_type = "BOOLEAN"
        false_value = "FALSE"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
        user_id_type = "INTEGER"
        timestamp_type = "DATETIME"
        now_default = "CURRENT_TIMESTAMP"
        boolean_type = "INTEGER"
        false_value = "0"

    # -------------------------
    # НОВЫЕ ПОЛЯ ПОЛЬЗОВАТЕЛЯ
    # -------------------------

    new_user_columns = [
        ("email", "TEXT"),
        ("display_name", "TEXT"),
        ("avatar_url", "TEXT"),
        ("bio", "TEXT"),
        ("created_at", f"{timestamp_type} DEFAULT {now_default}"),
    ]

    for column_name, column_type in new_user_columns:
        try:
            cursor.execute(
                f"""
                ALTER TABLE users
                ADD COLUMN {column_name} {column_type}
                """
            )
            print(f"users: добавлено поле {column_name}")
        except Exception:
            db.rollback()
            print(f"users: поле {column_name} уже существует")

    # Индекс email создаём отдельно.
    # Пока email может быть NULL у старых аккаунтов.
    try:
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique
            ON users(email)
            """
        )
        db.commit()
    except Exception as error:
        db.rollback()
        print("Не удалось создать индекс email:", error)

    # -------------------------
    # CHATS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chats (
            id {id_type},
            chat_type TEXT NOT NULL DEFAULT 'private',
            title TEXT,
            avatar_url TEXT,
            created_by {user_id_type},
            created_at {timestamp_type} DEFAULT {now_default}
        )
        """
    )

    # -------------------------
    # CHAT MEMBERS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chat_members (
            chat_id {user_id_type} NOT NULL,
            user_id {user_id_type} NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            joined_at {timestamp_type} DEFAULT {now_default},
            last_read_message_id {user_id_type},
            PRIMARY KEY (chat_id, user_id)
        )
        """
    )

    # -------------------------
    # MESSAGES V2
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS messages_v2 (
            id {id_type},
            chat_id {user_id_type} NOT NULL,
            sender_id {user_id_type},
            message_type TEXT NOT NULL DEFAULT 'text',
            text TEXT,
            reply_to_id {user_id_type},
            created_at {timestamp_type} DEFAULT {now_default},
            edited_at {timestamp_type},
            deleted_at {timestamp_type}
        )
        """
    )

    # -------------------------
    # ATTACHMENTS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS attachments (
            id {id_type},
            message_id {user_id_type} NOT NULL,
            attachment_type TEXT NOT NULL,
            url TEXT NOT NULL,
            public_id TEXT,
            original_name TEXT,
            mime_type TEXT,
            size_bytes {user_id_type},
            width INTEGER,
            height INTEGER,
            duration_ms INTEGER,
            created_at {timestamp_type} DEFAULT {now_default}
        )
        """
    )

    # -------------------------
    # MESSAGE REACTIONS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS message_reactions (
            message_id {user_id_type} NOT NULL,
            user_id {user_id_type} NOT NULL,
            reaction TEXT NOT NULL,
            created_at {timestamp_type} DEFAULT {now_default},
            PRIMARY KEY (message_id, user_id, reaction)
        )
        """
    )

    # -------------------------
    # USER BLOCKS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_blocks (
            blocker_id {user_id_type} NOT NULL,
            blocked_id {user_id_type} NOT NULL,
            created_at {timestamp_type} DEFAULT {now_default},
            PRIMARY KEY (blocker_id, blocked_id)
        )
        """
    )

    # -------------------------
    # DEVICES
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS devices (
            id {id_type},
            user_id {user_id_type} NOT NULL,
            device_name TEXT,
            push_token TEXT,
            last_seen_at {timestamp_type},
            created_at {timestamp_type} DEFAULT {now_default}
        )
        """
    )

    # -------------------------
    # CALLS
    # -------------------------

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS calls (
            id {id_type},
            chat_id {user_id_type} NOT NULL,
            started_by {user_id_type} NOT NULL,
            call_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ringing',
            started_at {timestamp_type} DEFAULT {now_default},
            answered_at {timestamp_type},
            ended_at {timestamp_type}
        )
        """
    )

    db.commit()
    cursor.close()
    db.close()

    print("")
    print("===================================")
    print("69 Messenger V2 database ready")
    print("===================================")


if __name__ == "__main__":
    migrate()
