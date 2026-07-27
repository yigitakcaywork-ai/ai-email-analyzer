import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "email_analyzer.db"


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
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                is_hidden INTEGER NOT NULL DEFAULT 0,
                hidden_at TEXT,
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
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
        email["is_hidden"] = bool(
            email["is_hidden"]
        )

        results.append(email)

    return results


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