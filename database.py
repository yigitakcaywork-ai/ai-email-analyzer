import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "email_analyzer.db"
LOCAL_USER_ID = 1
LOCAL_USER_EMAIL = "local-user@ai-email-analyzer.local"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    return connection


def column_exists(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    columns = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(
        column["name"] == column_name
        for column in columns
    )


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

        connection.execute(
            """
            INSERT OR IGNORE INTO users (
                id,
                email,
                display_name,
                plan
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                LOCAL_USER_ID,
                LOCAL_USER_EMAIL,
                "Yerel Geliştirme Kullanıcısı",
                "development",
            ),
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
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                gmail_id TEXT NOT NULL UNIQUE,
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
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                user_id INTEGER NOT NULL DEFAULT 1,
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
            """
        )

        # Daha önce oluşturulmuş veritabanına
        # yeni gizleme sütunlarını ekler.
        if not column_exists(
            connection,
            "emails",
            "is_hidden",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN is_hidden
                INTEGER NOT NULL DEFAULT 0
                """
            )

        if not column_exists(
            connection,
            "emails",
            "hidden_at",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN hidden_at TEXT
                """
            )

        if not column_exists(
            connection,
            "emails",
            "is_favorite",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN is_favorite
                INTEGER NOT NULL DEFAULT 0
                """
            )

        if not column_exists(
            connection,
            "emails",
            "favorited_at",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN favorited_at TEXT
                """
            )

        if not column_exists(
            connection,
            "emails",
            "follow_up_at",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN follow_up_at TEXT
                """
            )

        if not column_exists(
            connection,
            "emails",
            "follow_up_completed_at",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN follow_up_completed_at TEXT
                """
            )

        if not column_exists(
            connection,
            "emails",
            "user_id",
        ):
            connection.execute(
                """
                ALTER TABLE emails
                ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1
                """
            )

        if not column_exists(
            connection,
            "app_settings",
            "user_id",
        ):
            connection.execute(
                """
                ALTER TABLE app_settings
                ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1
                """
            )

        connection.execute(
            "UPDATE emails SET user_id = ? WHERE user_id IS NULL",
            (LOCAL_USER_ID,),
        )

        connection.execute(
            "UPDATE app_settings SET user_id = ? WHERE user_id IS NULL",
            (LOCAL_USER_ID,),
        )

        connection.commit()


def email_exists(gmail_id: str) -> bool:
    """
    E-posta gizlenmiş olsa bile veritabanında varsa
    yeniden analiz edilmesini engeller.
    """
    with get_connection() as connection:
        result = connection.execute(
            """
            SELECT 1
            FROM emails
            WHERE gmail_id = ?
            LIMIT 1
            """,
            (gmail_id,),
        ).fetchone()

    return result is not None


def save_analyzed_email(
    email: dict,
    analysis: dict,
):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO emails (
                gmail_id,
                thread_id,
                sender,
                subject,
                email_date,
                internal_date,
                snippet,
                summary,
                category,
                importance_score,
                urgency,
                recommended_action,
                reply_needed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(gmail_id) DO UPDATE SET
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
                email.get("gmail_id", ""),
                email.get("thread_id", ""),
                email.get("from", "Bilinmiyor"),
                email.get("subject", "Konu yok"),
                email.get("date", "Tarih yok"),
                email.get("internal_date", 0),
                email.get("snippet", ""),
                analysis.get(
                    "summary",
                    "Özet oluşturulamadı.",
                ),
                analysis.get(
                    "category",
                    "Diğer",
                ),
                analysis.get(
                    "importance_score",
                    1,
                ),
                analysis.get(
                    "urgency",
                    "Düşük",
                ),
                analysis.get(
                    "recommended_action",
                    "E-postayı manuel olarak inceleyin.",
                ),
                int(
                    bool(
                        analysis.get(
                            "reply_needed",
                            False,
                        )
                    )
                ),
            ),
        )

        connection.commit()


def get_saved_emails(
    limit: int = 200,
    include_hidden: bool = False,
) -> list[dict]:
    """
    Varsayılan olarak gizlenmiş e-postaları getirmez.
    """
    where_clause = ""

    if not include_hidden:
        where_clause = "WHERE is_hidden = 0"

    query = f"""
        SELECT
            gmail_id,
            thread_id,
            sender,
            subject,
            email_date,
            internal_date,
            snippet,
            summary,
            category,
            importance_score,
            urgency,
            recommended_action,
            reply_needed,
            reply_draft,
            is_favorite,
            favorited_at,
            follow_up_at,
            follow_up_completed_at,
            is_hidden,
            hidden_at,
            analyzed_at
        FROM emails
        {where_clause}
        ORDER BY internal_date DESC
        LIMIT ?
    """

    with get_connection() as connection:
        rows = connection.execute(
            query,
            (limit,),
        ).fetchall()

    results = []

    for row in rows:
        email = dict(row)

        email["date"] = email.pop("email_date")
        email["reply_needed"] = bool(
            email["reply_needed"]
        )
        email["is_favorite"] = bool(
            email["is_favorite"]
        )
        email["is_hidden"] = bool(
            email["is_hidden"]
        )

        results.append(email)

    return results


def set_email_favorite(
    gmail_id: str,
    is_favorite: bool,
) -> bool:
    """E-postanın favori durumunu kalıcı olarak günceller."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails
            SET
                is_favorite = ?,
                favorited_at = CASE
                    WHEN ? = 1 THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END
            WHERE gmail_id = ?
            """,
            (
                int(bool(is_favorite)),
                int(bool(is_favorite)),
                gmail_id,
            ),
        )
        connection.commit()

    return cursor.rowcount > 0



def set_email_follow_up(
    gmail_id: str,
    follow_up_at: str,
) -> bool:
    """E-postaya takip tarihi ekler veya tarihini günceller."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails
            SET
                follow_up_at = ?,
                follow_up_completed_at = NULL
            WHERE gmail_id = ?
            """,
            (follow_up_at, gmail_id),
        )
        connection.commit()

    return cursor.rowcount > 0


def complete_email_follow_up(gmail_id: str) -> bool:
    """Aktif takibi tamamlar ve geçmiş bilgisini korur."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails
            SET follow_up_completed_at = CURRENT_TIMESTAMP
            WHERE gmail_id = ?
              AND follow_up_at IS NOT NULL
              AND follow_up_completed_at IS NULL
            """,
            (gmail_id,),
        )
        connection.commit()

    return cursor.rowcount > 0

def hide_email(gmail_id: str) -> bool:
    """
    E-postayı Gmail'den silmeden dashboard'dan gizler.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails
            SET
                is_hidden = 1,
                hidden_at = CURRENT_TIMESTAMP
            WHERE gmail_id = ?
            """,
            (gmail_id,),
        )

        connection.commit()

    return cursor.rowcount > 0


def restore_email(gmail_id: str) -> bool:
    """
    Gizlenen e-postayı yeniden dashboard'a getirir.
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE emails
            SET
                is_hidden = 0,
                hidden_at = NULL
            WHERE gmail_id = ?
            """,
            (gmail_id,),
        )

        connection.commit()

    return cursor.rowcount > 0


def get_hidden_email_count() -> int:
    with get_connection() as connection:
        result = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM emails
            WHERE is_hidden = 1
            """
        ).fetchone()

    return int(result["total"])


def save_reply_draft(
    gmail_id: str,
    reply_draft: str,
):
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE emails
            SET reply_draft = ?
            WHERE gmail_id = ?
            """,
            (
                reply_draft,
                gmail_id,
            ),
        )

        connection.commit()


def get_setting(
    setting_key: str,
    default_value: str | None = None,
):
    with get_connection() as connection:
        result = connection.execute(
            """
            SELECT setting_value
            FROM app_settings
            WHERE setting_key = ?
            """,
            (setting_key,),
        ).fetchone()

    if result is None:
        return default_value

    return result["setting_value"]


def save_setting(
    setting_key: str,
    setting_value: str,
):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (
                setting_key,
                setting_value
            )
            VALUES (?, ?)

            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value
            """,
            (
                setting_key,
                setting_value,
            ),
        )

        connection.commit()