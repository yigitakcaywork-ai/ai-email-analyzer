from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request

from database import (
    email_exists,
    get_hidden_email_count,
    get_saved_emails,
    hide_email,
    init_database,
    restore_email,
    save_analyzed_email,
    save_reply_draft,
)
from services.gmail_service import get_recent_emails
from services.gemini_service import analyze_emails, generate_reply


app = Flask(__name__)

init_database()

NEW_EMAIL_LIMIT = 10
GMAIL_SCAN_LIMIT = 50

LOCAL_TIMEZONE = ZoneInfo("Europe/Istanbul")


def group_emails_by_date(emails: list[dict]) -> list[dict]:
    """
    E-postaları Bugün, Dün ve tarih başlıkları
    altında gruplandırır.
    """
    today = datetime.now(LOCAL_TIMEZONE).date()
    yesterday = today - timedelta(days=1)

    grouped_emails = {}

    for email in emails:
        internal_date = int(
            email.get("internal_date", 0) or 0
        )

        if internal_date > 0:
            email_datetime = datetime.fromtimestamp(
                internal_date / 1000,
                tz=LOCAL_TIMEZONE,
            )

            email_day = email_datetime.date()

            if email_day == today:
                group_key = "today"
                group_title = "Bugün"

            elif email_day == yesterday:
                group_key = "yesterday"
                group_title = "Dün"

            else:
                group_key = email_day.isoformat()
                group_title = email_datetime.strftime(
                    "%d.%m.%Y"
                )

        else:
            group_key = "unknown"
            group_title = "Tarihi bilinmeyenler"

        if group_key not in grouped_emails:
            grouped_emails[group_key] = {
                "title": group_title,
                "emails": [],
            }

        grouped_emails[group_key]["emails"].append(
            email
        )

    return list(grouped_emails.values())


def create_dashboard_data(
    show_hidden: bool = False,
) -> dict:
    """
    Görünen ve gizlenen kayıtları ayırır.

    show_hidden True ise yalnızca gizlenen
    e-postalar ekranda gösterilir.
    """
    all_emails = get_saved_emails(
        limit=400,
        include_hidden=True,
    )

    visible_emails = [
        email
        for email in all_emails
        if not email.get("is_hidden", False)
    ]

    hidden_emails = [
        email
        for email in all_emails
        if email.get("is_hidden", False)
    ]

    selected_emails = (
        hidden_emails
        if show_hidden
        else visible_emails
    )

    grouped_results = group_emails_by_date(
        selected_emails
    )

    urgent_count = sum(
        1
        for email in visible_emails
        if email.get("urgency") == "Yüksek"
    )

    reply_needed_count = sum(
        1
        for email in visible_emails
        if email.get("reply_needed")
    )

    today_count = 0

    for group in group_emails_by_date(
        visible_emails
    ):
        if group["title"] == "Bugün":
            today_count = len(group["emails"])
            break

    return {
        "results": selected_emails,
        "grouped_results": grouped_results,
        "total_count": len(visible_emails),
        "today_count": today_count,
        "urgent_count": urgent_count,
        "reply_needed_count": reply_needed_count,
        "hidden_count": len(hidden_emails),
        "show_hidden": show_hidden,
    }


def render_dashboard(
    show_hidden: bool = False,
    **extra_data,
):
    """
    Dashboard verilerini hazırlar ve
    index.html şablonunu döndürür.
    """
    dashboard_data = create_dashboard_data(
        show_hidden=show_hidden
    )

    dashboard_data.update(extra_data)

    return render_template(
        "index.html",
        **dashboard_data,
    )


@app.route("/")
def home():
    """
    Normal e-posta geçmişini gösterir.
    Gemini isteği kullanılmaz.
    """
    return render_dashboard(
        show_hidden=False
    )


@app.route("/hidden")
def hidden_emails_page():
    """
    Panelden gizlenmiş e-postaları gösterir.
    """
    return render_dashboard(
        show_hidden=True
    )


@app.route("/analyze")
def analyze():
    """
    Gmail'deki son mesajları kontrol eder.

    Veritabanında olmayan en fazla 10 yeni
    e-posta tek Gemini isteğinde analiz edilir.
    """
    try:
        gmail_emails = get_recent_emails(
            max_results=GMAIL_SCAN_LIMIT,
        )

        new_emails = [
            email
            for email in gmail_emails
            if email.get("gmail_id")
            and not email_exists(
                email["gmail_id"]
            )
        ]

        # En eski görülmemiş e-postadan başlanır.
        new_emails.sort(
            key=lambda email: email.get(
                "internal_date",
                0,
            )
        )

        emails_to_analyze = new_emails[
            :NEW_EMAIL_LIMIT
        ]

        if emails_to_analyze:
            analyses = analyze_emails(
                emails_to_analyze
            )

            for email, analysis in zip(
                emails_to_analyze,
                analyses,
            ):
                save_analyzed_email(
                    email=email,
                    analysis=analysis,
                )

            status_message = (
                f"{len(emails_to_analyze)} yeni "
                "e-posta başarıyla analiz edildi."
            )

        else:
            status_message = (
                "Yeni e-posta bulunamadı. "
                "Geçmiş analizler gösteriliyor."
            )

        remaining_count = max(
            len(new_emails)
            - len(emails_to_analyze),
            0,
        )

        return render_dashboard(
            show_hidden=False,
            status_message=status_message,
            analyzed_count=len(
                emails_to_analyze
            ),
            remaining_count=remaining_count,
        )

    except Exception as error:
        return render_dashboard(
            show_hidden=False,
            error=str(error),
        )


@app.route(
    "/generate-reply",
    methods=["POST"],
)
def create_reply():
    """
    Seçilen e-posta için AI cevap taslağı
    oluşturur ve veritabanına kaydeder.
    """
    data = request.get_json(
        silent=True
    ) or {}

    gmail_id = str(
        data.get("gmail_id", "")
    ).strip()

    sender = str(
        data.get("sender", "")
    ).strip()

    subject = str(
        data.get("subject", "")
    ).strip()

    snippet = str(
        data.get("snippet", "")
    ).strip()

    summary = str(
        data.get("summary", "")
    ).strip()

    if not subject and not snippet:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Cevap oluşturmak için yeterli "
                    "e-posta bilgisi bulunamadı."
                ),
            }
        ), 400

    try:
        reply = generate_reply(
            sender=sender,
            subject=subject,
            snippet=snippet,
            summary=summary,
        )

        if gmail_id:
            save_reply_draft(
                gmail_id=gmail_id,
                reply_draft=reply,
            )

        return jsonify(
            {
                "success": True,
                "reply": reply,
            }
        )

    except Exception as error:
        error_message = str(error)

        if "kota" in error_message.lower():
            status_code = 429

        elif (
            "yoğun" in error_message.lower()
            or "kullanılamıyor"
            in error_message.lower()
        ):
            status_code = 503

        else:
            status_code = 500

        return jsonify(
            {
                "success": False,
                "error": error_message,
            }
        ), status_code


@app.route(
    "/hide-email",
    methods=["POST"],
)
def hide_email_from_dashboard():
    """
    E-postayı Gmail'den silmeden
    yalnızca uygulama panelinden gizler.
    """
    data = request.get_json(
        silent=True
    ) or {}

    gmail_id = str(
        data.get("gmail_id", "")
    ).strip()

    if not gmail_id:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Gizlenecek e-posta kimliği "
                    "bulunamadı."
                ),
            }
        ), 400

    hidden = hide_email(gmail_id)

    if not hidden:
        return jsonify(
            {
                "success": False,
                "error": (
                    "E-posta bulunamadı veya "
                    "gizlenemedi."
                ),
            }
        ), 404

    return jsonify(
        {
            "success": True,
            "message": (
                "E-posta panelden gizlendi. "
                "Gmail hesabındaki asıl mesaja "
                "dokunulmadı."
            ),
            "hidden_count": get_hidden_email_count(),
        }
    )


@app.route(
    "/restore-email",
    methods=["POST"],
)
def restore_email_to_dashboard():
    """
    Gizlenmiş e-postayı yeniden
    ana dashboard'a getirir.
    """
    data = request.get_json(
        silent=True
    ) or {}

    gmail_id = str(
        data.get("gmail_id", "")
    ).strip()

    if not gmail_id:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Geri getirilecek e-posta "
                    "kimliği bulunamadı."
                ),
            }
        ), 400

    restored = restore_email(gmail_id)

    if not restored:
        return jsonify(
            {
                "success": False,
                "error": (
                    "E-posta bulunamadı veya "
                    "geri getirilemedi."
                ),
            }
        ), 404

    return jsonify(
        {
            "success": True,
            "message": (
                "E-posta yeniden dashboard'a "
                "getirildi."
            ),
            "hidden_count": get_hidden_email_count(),
        }
    )


if __name__ == "__main__":
    app.run(debug=True)