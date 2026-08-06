import json
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "email_analyzer.db"
LOCAL_USER_ID = 1
LOCAL_USER_EMAIL = "local-user@ai-email-analyzer.local"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def column_exists(connection, table_name: str, column_name: str) -> bool:
    columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column["name"] == column_name for column in columns)


def _table_sql(connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row["sql"] or "") if row else ""


def _create_emails_table(connection, table_name: str = "emails") -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            gmail_id TEXT NOT NULL,
            thread_id TEXT,
            sender TEXT,
            subject TEXT,
            email_date TEXT,
            internal_date INTEGER,
            snippet TEXT,
            summary TEXT,
            category TEXT,
            importance_score INTEGER,
            urgency TEXT,
            recommended_action TEXT,
            reply_needed INTEGER DEFAULT 0,
            reply_draft TEXT,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            favorited_at TEXT,
            follow_up_at TEXT,
            follow_up_completed_at TEXT,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            hidden_at TEXT,
            analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (user_id, gmail_id)
        )
        """
    )


def _migrate_emails_table(connection) -> None:
    sql = _table_sql(connection, "emails").lower()
    if not sql:
        _create_emails_table(connection)
        return

    required_columns = [
        ("user_id", "INTEGER NOT NULL DEFAULT 1"),
        ("is_hidden", "INTEGER NOT NULL DEFAULT 0"),
        ("hidden_at", "TEXT"),
        ("is_favorite", "INTEGER NOT NULL DEFAULT 0"),
        ("favorited_at", "TEXT"),
        ("follow_up_at", "TEXT"),
        ("follow_up_completed_at", "TEXT"),
    ]
    for name, definition in required_columns:
        if not column_exists(connection, "emails", name):
            connection.execute(f"ALTER TABLE emails ADD COLUMN {name} {definition}")

    sql = _table_sql(connection, "emails").lower()
    has_composite_unique = "unique (user_id, gmail_id)" in sql or "unique(user_id, gmail_id)" in sql
    has_global_unique = "gmail_id text not null unique" in sql
    if has_composite_unique and not has_global_unique:
        return

    connection.execute("ALTER TABLE emails RENAME TO emails_legacy")
    _create_emails_table(connection)
    connection.execute(
        """
        INSERT OR IGNORE INTO emails (
            id, user_id, gmail_id, thread_id, sender, subject, email_date,
            internal_date, snippet, summary, category, importance_score,
            urgency, recommended_action, reply_needed, reply_draft,
            is_favorite, favorited_at, follow_up_at, follow_up_completed_at,
            is_hidden, hidden_at, analyzed_at
        )
        SELECT
            id, COALESCE(user_id, 1), gmail_id, thread_id, sender, subject,
            email_date, internal_date, snippet, summary, category,
            importance_score, urgency, recommended_action, reply_needed,
            reply_draft, COALESCE(is_favorite, 0), favorited_at,
            follow_up_at, follow_up_completed_at, COALESCE(is_hidden, 0),
            hidden_at, analyzed_at
        FROM emails_legacy
        """
    )
    connection.execute("DROP TABLE emails_legacy")


def _migrate_app_settings(connection) -> None:
    sql = _table_sql(connection, "app_settings").lower()
    if not sql:
        connection.execute(
            """
            CREATE TABLE app_settings (
                user_id INTEGER NOT NULL,
                setting_key TEXT NOT NULL,
                setting_value TEXT,
                PRIMARY KEY (user_id, setting_key),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        return

    if not column_exists(connection, "app_settings", "user_id"):
        connection.execute("ALTER TABLE app_settings ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

    sql = _table_sql(connection, "app_settings").lower()
    if "primary key (user_id, setting_key)" in sql or "primary key(user_id, setting_key)" in sql:
        return

    connection.execute("ALTER TABLE app_settings RENAME TO app_settings_legacy")
    connection.execute(
        """
        CREATE TABLE app_settings (
            user_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT,
            PRIMARY KEY (user_id, setting_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO app_settings (user_id, setting_key, setting_value)
        SELECT COALESCE(user_id, 1), setting_key, setting_value
        FROM app_settings_legacy
        """
    )
    connection.execute("DROP TABLE app_settings_legacy")


def init_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for name, definition in [
            ("google_sub", "TEXT"),
            ("profile_picture", "TEXT"),
        ]:
            if not column_exists(connection, "users", name):
                connection.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

        connection.execute(
            """
            INSERT OR IGNORE INTO users (id, email, display_name, plan)
            VALUES (?, ?, ?, ?)
            """,
            (LOCAL_USER_ID, LOCAL_USER_EMAIL, "Yerel Geliştirme Kullanıcısı", "development"),
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub "
            "ON users(google_sub) WHERE google_sub IS NOT NULL"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                gmail_address TEXT,
                encrypted_access_token TEXT,
                encrypted_refresh_token TEXT,
                token_expiry TEXT,
                scopes TEXT,
                connected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS behavior_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                gmail_id TEXT,
                action_type TEXT NOT NULL,
                sender TEXT,
                category TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_behavior_user_created "
            "ON behavior_logs(user_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_behavior_user_sender_action "
            "ON behavior_logs(user_id, sender, action_type)"
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_behavior_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                dimension_type TEXT NOT NULL,
                dimension_value TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_count INTEGER NOT NULL DEFAULT 0,
                first_action_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_action_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, dimension_type, dimension_value, action_type),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_user_count "
            "ON user_behavior_memory(user_id, action_count DESC)"
        )

        # Önceki davranış günlüklerini ilk açılışta AI hafızasına aktarır.
        connection.execute(
            """
            INSERT INTO user_behavior_memory (
                user_id, dimension_type, dimension_value, action_type,
                action_count, first_action_at, last_action_at
            )
            SELECT user_id, 'sender', sender, action_type, COUNT(*),
                   MIN(created_at), MAX(created_at)
            FROM behavior_logs
            WHERE sender IS NOT NULL AND trim(sender) <> ''
              AND action_type IN ('archive', 'hide', 'favorite', 'follow_up', 'reply_generated', 'gmail_draft_created')
            GROUP BY user_id, sender, action_type
            ON CONFLICT(user_id, dimension_type, dimension_value, action_type)
            DO UPDATE SET
                action_count = excluded.action_count,
                first_action_at = excluded.first_action_at,
                last_action_at = excluded.last_action_at
            """
        )
        connection.execute(
            """
            INSERT INTO user_behavior_memory (
                user_id, dimension_type, dimension_value, action_type,
                action_count, first_action_at, last_action_at
            )
            SELECT user_id, 'category', category, action_type, COUNT(*),
                   MIN(created_at), MAX(created_at)
            FROM behavior_logs
            WHERE category IS NOT NULL AND trim(category) <> ''
              AND action_type IN ('archive', 'hide', 'favorite', 'follow_up', 'reply_generated', 'gmail_draft_created')
            GROUP BY user_id, category, action_type
            ON CONFLICT(user_id, dimension_type, dimension_value, action_type)
            DO UPDATE SET
                action_count = excluded.action_count,
                first_action_at = excluded.first_action_at,
                last_action_at = excluded.last_action_at
            """
        )

        _migrate_emails_table(connection)
        _migrate_app_settings(connection)
        connection.execute("UPDATE emails SET user_id = ? WHERE user_id IS NULL", (LOCAL_USER_ID,))
        connection.execute("UPDATE app_settings SET user_id = ? WHERE user_id IS NULL", (LOCAL_USER_ID,))
        connection.commit()


def upsert_google_user(google_sub: str, email: str, display_name: str = "", profile_picture: str = "") -> dict:
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE google_sub = ? OR email = ? LIMIT 1",
            (google_sub, email),
        ).fetchone()
        created = existing is None
        if existing:
            user_id = int(existing["id"])
            connection.execute(
                """
                UPDATE users SET google_sub = ?, email = ?, display_name = ?,
                    profile_picture = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (google_sub, email, display_name, profile_picture, user_id),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO users (google_sub, email, display_name, profile_picture)
                VALUES (?, ?, ?, ?)
                """,
                (google_sub, email, display_name, profile_picture),
            )
            user_id = int(cursor.lastrowid)

        # Sistemde tek gerçek kullanıcı varsa mevcut yerel demo verilerini
        # bir kez o hesaba taşır. Böylece önceki analiz geçmişi kaybolmaz.
        real_user_count = connection.execute(
            "SELECT COUNT(*) AS total FROM users WHERE google_sub IS NOT NULL"
        ).fetchone()["total"]
        user_email_count = connection.execute(
            "SELECT COUNT(*) AS total FROM emails WHERE user_id = ?",
            (user_id,),
        ).fetchone()["total"]
        local_email_count = connection.execute(
            "SELECT COUNT(*) AS total FROM emails WHERE user_id = ?",
            (LOCAL_USER_ID,),
        ).fetchone()["total"]

        if (
            int(real_user_count) == 1
            and int(user_email_count) == 0
            and int(local_email_count) > 0
        ):
            connection.execute(
                "UPDATE emails SET user_id = ? WHERE user_id = ?",
                (user_id, LOCAL_USER_ID),
            )
            connection.execute(
                "UPDATE app_settings SET user_id = ? WHERE user_id = ?",
                (user_id, LOCAL_USER_ID),
            )

        connection.commit()
        row = connection.execute(
            "SELECT id, email, display_name, profile_picture, plan FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row)


def save_gmail_connection(user_id: int, gmail_address: str, encrypted_access_token: str,
                          encrypted_refresh_token: str, token_expiry: str, scopes: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO gmail_connections (
                user_id, gmail_address, encrypted_access_token,
                encrypted_refresh_token, token_expiry, scopes
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                gmail_address = excluded.gmail_address,
                encrypted_access_token = excluded.encrypted_access_token,
                encrypted_refresh_token = CASE
                    WHEN excluded.encrypted_refresh_token <> ''
                    THEN excluded.encrypted_refresh_token
                    ELSE gmail_connections.encrypted_refresh_token
                END,
                token_expiry = excluded.token_expiry,
                scopes = excluded.scopes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, gmail_address, encrypted_access_token, encrypted_refresh_token, token_expiry, scopes),
        )
        connection.commit()


def get_gmail_connection(user_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, gmail_address, encrypted_access_token,
                   encrypted_refresh_token, token_expiry, scopes,
                   connected_at, updated_at
            FROM gmail_connections WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_gmail_connection(user_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM gmail_connections WHERE user_id = ?", (user_id,))
        connection.commit()
    return cursor.rowcount > 0


def email_exists(user_id: int, gmail_id: str) -> bool:
    with get_connection() as connection:
        result = connection.execute(
            "SELECT 1 FROM emails WHERE user_id = ? AND gmail_id = ? LIMIT 1",
            (user_id, gmail_id),
        ).fetchone()
    return result is not None


def save_analyzed_email(user_id: int, email: dict, analysis: dict):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO emails (
                user_id, gmail_id, thread_id, sender, subject, email_date,
                internal_date, snippet, summary, category, importance_score,
                urgency, recommended_action, reply_needed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, gmail_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                sender = excluded.sender,
                subject = excluded.subject,
                email_date = excluded.email_date,
                internal_date = excluded.internal_date,
                snippet = excluded.snippet,
                summary = excluded.summary,
                category = excluded.category,
                importance_score = excluded.importance_score,
                urgency = excluded.urgency,
                recommended_action = excluded.recommended_action,
                reply_needed = excluded.reply_needed,
                analyzed_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                email.get("gmail_id", ""), email.get("thread_id", ""),
                email.get("from", "Bilinmiyor"), email.get("subject", "Konu yok"),
                email.get("date", "Tarih yok"), email.get("internal_date", 0),
                email.get("snippet", ""), analysis.get("summary", "Özet oluşturulamadı."),
                analysis.get("category", "Diğer"), analysis.get("importance_score", 1),
                analysis.get("urgency", "Düşük"),
                analysis.get("recommended_action", "E-postayı manuel olarak inceleyin."),
                int(bool(analysis.get("reply_needed", False))),
            ),
        )
        connection.commit()


def get_saved_emails(user_id: int, limit: int = 200, include_hidden: bool = False) -> list[dict]:
    hidden_clause = "" if include_hidden else "AND is_hidden = 0"
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT gmail_id, thread_id, sender, subject, email_date,
                   internal_date, snippet, summary, category, importance_score,
                   urgency, recommended_action, reply_needed, reply_draft,
                   is_favorite, favorited_at, follow_up_at,
                   follow_up_completed_at, is_hidden, hidden_at, analyzed_at
            FROM emails
            WHERE user_id = ? {hidden_clause}
            ORDER BY internal_date DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    results = []
    for row in rows:
        email = dict(row)
        email["date"] = email.pop("email_date")
        email["reply_needed"] = bool(email["reply_needed"])
        email["is_favorite"] = bool(email["is_favorite"])
        email["is_hidden"] = bool(email["is_hidden"])
        results.append(email)
    return results


def set_email_favorite(user_id: int, gmail_id: str, is_favorite: bool) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails SET is_favorite = ?,
                favorited_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE user_id = ? AND gmail_id = ?
            """,
            (int(bool(is_favorite)), int(bool(is_favorite)), user_id, gmail_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def set_email_follow_up(user_id: int, gmail_id: str, follow_up_at: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails SET follow_up_at = ?, follow_up_completed_at = NULL
            WHERE user_id = ? AND gmail_id = ?
            """,
            (follow_up_at, user_id, gmail_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def complete_email_follow_up(user_id: int, gmail_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails SET follow_up_completed_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND gmail_id = ? AND follow_up_at IS NOT NULL
              AND follow_up_completed_at IS NULL
            """,
            (user_id, gmail_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def hide_email(user_id: int, gmail_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails SET is_hidden = 1, hidden_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND gmail_id = ?
            """,
            (user_id, gmail_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def restore_email(user_id: int, gmail_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails SET is_hidden = 0, hidden_at = NULL
            WHERE user_id = ? AND gmail_id = ?
            """,
            (user_id, gmail_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def get_hidden_email_count(user_id: int) -> int:
    with get_connection() as connection:
        result = connection.execute(
            "SELECT COUNT(*) AS total FROM emails WHERE user_id = ? AND is_hidden = 1",
            (user_id,),
        ).fetchone()
    return int(result["total"])


def save_reply_draft(user_id: int, gmail_id: str, reply_draft: str):
    with get_connection() as connection:
        connection.execute(
            "UPDATE emails SET reply_draft = ? WHERE user_id = ? AND gmail_id = ?",
            (reply_draft, user_id, gmail_id),
        )
        connection.commit()


def get_setting(user_id: int, setting_key: str, default_value: str | None = None):
    with get_connection() as connection:
        result = connection.execute(
            "SELECT setting_value FROM app_settings WHERE user_id = ? AND setting_key = ?",
            (user_id, setting_key),
        ).fetchone()
    return default_value if result is None else result["setting_value"]


def save_setting(user_id: int, setting_key: str, setting_value: str):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (user_id, setting_key, setting_value)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, setting_key) DO UPDATE SET setting_value = excluded.setting_value
            """,
            (user_id, setting_key, setting_value),
        )
        connection.commit()



def record_behavior(
    user_id: int,
    action_type: str,
    gmail_id: str = "",
    metadata: dict | None = None,
) -> None:
    """Kullanıcının e-posta üzerindeki davranışını kaydeder."""
    clean_action = str(action_type or "").strip().lower()
    clean_gmail_id = str(gmail_id or "").strip()
    if not clean_action:
        return

    sender = ""
    category = ""
    with get_connection() as connection:
        if clean_gmail_id:
            email_row = connection.execute(
                """
                SELECT sender, category
                FROM emails
                WHERE user_id = ? AND gmail_id = ?
                LIMIT 1
                """,
                (user_id, clean_gmail_id),
            ).fetchone()
            if email_row:
                sender = str(email_row["sender"] or "").strip()
                category = str(email_row["category"] or "").strip()

        connection.execute(
            """
            INSERT INTO behavior_logs (
                user_id, gmail_id, action_type, sender, category, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                clean_gmail_id or None,
                clean_action,
                sender or None,
                category or None,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )

        memory_actions = {
            "archive", "hide", "favorite", "follow_up",
            "reply_generated", "gmail_draft_created",
        }
        if clean_action in memory_actions:
            for dimension_type, dimension_value in (
                ("sender", sender),
                ("category", category),
            ):
                clean_value = str(dimension_value or "").strip()
                if not clean_value:
                    continue
                connection.execute(
                    """
                    INSERT INTO user_behavior_memory (
                        user_id, dimension_type, dimension_value, action_type,
                        action_count, first_action_at, last_action_at
                    )
                    VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, dimension_type, dimension_value, action_type)
                    DO UPDATE SET
                        action_count = user_behavior_memory.action_count + 1,
                        last_action_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, dimension_type, clean_value, clean_action),
                )

        connection.commit()


def get_today_behavior_counts(user_id: int) -> dict:
    """Bugün gerçekleştirilen kullanıcı işlemlerinin sayılarını döndürür."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT action_type, COUNT(*) AS total
            FROM behavior_logs
            WHERE user_id = ?
              AND date(created_at, 'localtime') = date('now', 'localtime')
            GROUP BY action_type
            """,
            (user_id,),
        ).fetchall()
    return {str(row["action_type"]): int(row["total"]) for row in rows}


def get_today_analyzed_count(user_id: int) -> int:
    """Bugünkü taramalarda gerçekten analiz edilen toplam yeni e-posta sayısı."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT metadata_json
            FROM behavior_logs
            WHERE user_id = ?
              AND action_type = 'scan_completed'
              AND date(created_at, 'localtime') = date('now', 'localtime')
            """,
            (user_id,),
        ).fetchall()

    total = 0
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        total += max(0, int(metadata.get("analyzed_count", 0) or 0))

    return total


def get_today_scan_count(user_id: int) -> int:
    """Bugün tamamlanan Gmail taraması sayısını döndürür."""
    with get_connection() as connection:
        result = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM behavior_logs
            WHERE user_id = ?
              AND action_type = 'scan_completed'
              AND date(created_at, 'localtime') = date('now', 'localtime')
            """,
            (user_id,),
        ).fetchone()
    return int(result["total"] or 0)


def get_recent_worker_events(user_id: int, limit: int = 10) -> list[dict]:
    """Bugünkü AI çalışan ve kullanıcı işlem günlüğünü hazırlar."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT action_type, sender, metadata_json,
                   strftime('%H:%M', created_at, 'localtime') AS event_time
            FROM behavior_logs
            WHERE user_id = ?
              AND date(created_at, 'localtime') = date('now', 'localtime')
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, max(1, min(int(limit), 30))),
        ).fetchall()

    events = []
    for row in rows:
        action = str(row["action_type"] or "")
        sender = str(row["sender"] or "").strip()
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}

        if action == "scan_completed":
            count = int(metadata.get("analyzed_count", 0) or 0)
            urgent = int(metadata.get("urgent_count", 0) or 0)
            reply = int(metadata.get("reply_needed_count", 0) or 0)
            cleanable = int(metadata.get("cleanable_count", 0) or 0)
            scanned = int(metadata.get("scanned_count", 0) or 0)
            remaining = int(metadata.get("remaining_count", 0) or 0)

            if count > 0:
                message = (
                    f"{count} yeni e-posta analiz edildi; "
                    f"{urgent} acil, {reply} cevap bekleyen ve "
                    f"{cleanable} temizlenebilir mesaj bulundu."
                )
                if remaining > 0:
                    message += f" {remaining} yeni mesaj sonraki taramaya bırakıldı."
            else:
                message = (
                    f"Gelen kutusu tarandı ({scanned} mesaj kontrol edildi); "
                    "analiz edilecek yeni e-posta bulunamadı."
                )
            icon = "🔎"
        elif action == "archive":
            message = f"{sender or 'Bir e-posta'} Gmail’de arşivlendi."
            icon = "📥"
        elif action == "hide":
            message = f"{sender or 'Bir e-posta'} panelden gizlendi."
            icon = "🧹"
        elif action == "favorite":
            message = f"{sender or 'Bir e-posta'} favorilere eklendi."
            icon = "⭐"
        elif action == "follow_up":
            message = f"{sender or 'Bir e-posta'} takip listesine eklendi."
            icon = "⏰"
        elif action == "reply_generated":
            message = f"{sender or 'Bir e-posta'} için AI cevap taslağı oluşturuldu."
            icon = "✍️"
        elif action == "gmail_draft_created":
            recipient = str(metadata.get("recipient", "") or "").strip()
            message = f"{recipient or sender or 'Bir alıcı'} için Gmail taslağı kaydedildi."
            icon = "📨"
        elif action == "automation":
            message = str(metadata.get("message", "Otomatik işlem tamamlandı."))
            icon = "🤖"
        else:
            continue

        events.append({
            "time": str(row["event_time"] or "--:--"),
            "icon": icon,
            "message": message,
            "action_type": action,
        })

    return events


def get_learning_suggestions(user_id: int, minimum_actions: int = 3) -> list[dict]:
    """Tekrarlanan gönderici davranışlarından güvenli otomasyon önerileri üretir."""
    supported_actions = ("archive", "hide", "favorite")
    placeholders = ",".join("?" for _ in supported_actions)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT sender, action_type, COUNT(*) AS total
            FROM behavior_logs
            WHERE user_id = ?
              AND sender IS NOT NULL
              AND trim(sender) <> ''
              AND action_type IN ({placeholders})
            GROUP BY sender, action_type
            HAVING COUNT(*) >= ?
            ORDER BY total DESC, sender ASC
            LIMIT 5
            """,
            (user_id, *supported_actions, minimum_actions),
        ).fetchall()

    labels = {
        "archive": "arşivliyorsun",
        "hide": "panelden gizliyorsun",
        "favorite": "favoriye alıyorsun",
    }
    suggestions = []
    for row in rows:
        action = str(row["action_type"])
        sender = str(row["sender"])
        total = int(row["total"])
        suggestions.append({
            "sender": sender,
            "action_type": action,
            "count": total,
            "message": f"{sender} göndericisindeki e-postaları {total} kez {labels[action]}.",
        })
    return suggestions


def get_ai_memory(user_id: int, limit: int = 8) -> list[dict]:
    """Kullanıcının en güçlü davranış alışkanlıklarını döndürür."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT dimension_type, dimension_value, action_type, action_count,
                   strftime('%d.%m.%Y', last_action_at, 'localtime') AS last_used
            FROM user_behavior_memory
            WHERE user_id = ?
            ORDER BY action_count DESC, last_action_at DESC
            LIMIT ?
            """,
            (user_id, max(1, min(int(limit), 20))),
        ).fetchall()

    action_labels = {
        "archive": "arşivleme",
        "hide": "panelden gizleme",
        "favorite": "favoriye alma",
        "follow_up": "takibe alma",
        "reply_generated": "AI cevap hazırlama",
        "gmail_draft_created": "Gmail taslağı kaydetme",
    }
    memories = []
    for row in rows:
        count = int(row["action_count"] or 0)
        if count >= 8:
            level, confidence = "Güçlü alışkanlık", 95
        elif count >= 5:
            level, confidence = "Öğrenildi", 80
        elif count >= 3:
            level, confidence = "Gelişen alışkanlık", 60
        else:
            level, confidence = "Gözlemleniyor", 35

        dimension_type = str(row["dimension_type"] or "")
        value = str(row["dimension_value"] or "")
        subject_label = "Gönderici" if dimension_type == "sender" else "Kategori"
        memories.append({
            "dimension_type": dimension_type,
            "dimension_label": subject_label,
            "value": value,
            "action_type": str(row["action_type"] or ""),
            "action_label": action_labels.get(str(row["action_type"] or ""), "işlem"),
            "count": count,
            "level": level,
            "confidence": confidence,
            "last_used": str(row["last_used"] or ""),
        })
    return memories


def get_ai_memory_stats(user_id: int) -> dict:
    """AI hafızasının kullanıcı için ne kadar veri öğrendiğini özetler."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS patterns,
                   COALESCE(SUM(action_count), 0) AS observations,
                   COALESCE(SUM(CASE WHEN action_count >= 3 THEN 1 ELSE 0 END), 0) AS learned
            FROM user_behavior_memory
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return {
        "patterns": int(row["patterns"] or 0),
        "observations": int(row["observations"] or 0),
        "learned": int(row["learned"] or 0),
    }
