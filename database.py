import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "email_analyzer.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)

    connection.row_factory = sqlite3.Row

    return connection


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

        connection.commit()


def email_exists(gmail_id: str) -> bool:
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
                    "E-postayı manuel inceleyin.",
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
) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
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
                analyzed_at
            FROM emails
            ORDER BY internal_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    results = []

    for row in rows:
        email = dict(row)

        email["date"] = email.pop("email_date")
        email["reply_needed"] = bool(
            email["reply_needed"]
        )

        results.append(email)

    return results


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