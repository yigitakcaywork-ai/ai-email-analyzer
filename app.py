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
from services.gmail_service import (
    archive_email as archive_gmail_email,
    get_recent_emails,
    move_email_to_inbox,
)
from services.gemini_service import (
    analyze_emails,
    generate_reply,
)


app = Flask(__name__)

init_database()

NEW_EMAIL_LIMIT = 10
GMAIL_SCAN_LIMIT = 50
LOCAL_TIMEZONE = ZoneInfo("Europe/Istanbul")

REPLY_TONE_INSTRUCTIONS = {
    "professional": (
        "Profesyonel, dengeli, güven veren ve doğal bir üslup kullan. "
        "Gereksiz resmiyetten ve uzun anlatımdan kaçın."
    ),
    "formal": (
        "Resmî, ciddi ve saygılı bir üslup kullan. Hitap ve kapanış "
        "ifadeleri kurumsal yazışmaya uygun olsun."
    ),
    "friendly": (
        "Samimi, sıcak ve doğal bir üslup kullan; ancak profesyonel "
        "sınırları koru ve aşırı gündelik ifadeler kullanma."
    ),
    "short": (
        "Çok kısa, net ve doğrudan bir cevap yaz. Cevap en fazla üç "
        "kısa cümleden oluşsun."
    ),
}


def group_emails_by_date(
    emails: list[dict],
) -> list[dict]:
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

    for group in group_emails_by_date(visible_emails):
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
    dashboard_data = create_dashboard_data(
        show_hidden=show_hidden
    )
    dashboard_data.update(extra_data)

    return render_template(
        "index.html",
        **dashboard_data,
    )


def get_gmail_id_from_request() -> str:
    data = request.get_json(silent=True) or {}
    return str(data.get("gmail_id", "")).strip()


@app.route("/")
def home():
    return render_dashboard(show_hidden=False)


@app.route("/hidden")
def hidden_emails_page():
    return render_dashboard(show_hidden=True)


@app.route("/analyze")
def analyze():
    try:
        gmail_emails = get_recent_emails(
            max_results=GMAIL_SCAN_LIMIT,
        )

        new_emails = [
            email
            for email in gmail_emails
            if email.get("gmail_id")
            and not email_exists(email["gmail_id"])
        ]

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
            len(new_emails) - len(emails_to_analyze),
            0,
        )

        return render_dashboard(
            show_hidden=False,
            status_message=status_message,
            analyzed_count=len(emails_to_analyze),
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
    data = request.get_json(silent=True) or {}

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
    tone = str(
        data.get("tone", "professional")
    ).strip().lower()

    if tone not in REPLY_TONE_INSTRUCTIONS:
        return jsonify(
            {
                "success": False,
                "error": "Geçersiz cevap tonu seçildi.",
            }
        ), 400

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
        tone_instruction = REPLY_TONE_INSTRUCTIONS[tone]
        summary_with_tone = (
            f"{summary}\n\n"
            "ÖNEMLİ CEVAP TONU TALİMATI: "
            f"{tone_instruction}"
        ).strip()

        reply = generate_reply(
            sender=sender,
            subject=subject,
            snippet=snippet,
            summary=summary_with_tone,
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
                "tone": tone,
            }
        )

    except Exception as error:
        error_message = str(error)
        lowered_error = error_message.lower()

        if "kota" in lowered_error:
            status_code = 429
        elif (
            "yoğun" in lowered_error
            or "kullanılamıyor" in lowered_error
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
    gmail_id = get_gmail_id_from_request()

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
                "Gmail hesabındaki mesaja dokunulmadı."
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
    E-postayı yalnızca uygulama paneline geri getirir.
    Gmail etiketlerine dokunmaz.
    """
    gmail_id = get_gmail_id_from_request()

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
                "E-posta yalnızca dashboard'a "
                "geri getirildi."
            ),
            "hidden_count": get_hidden_email_count(),
        }
    )


@app.route(
    "/archive-email",
    methods=["POST"],
)
def archive_email_in_gmail():
    """
    E-postayı Gmail'de arşivler ve panelden gizler.
    """
    gmail_id = get_gmail_id_from_request()

    if not gmail_id:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Arşivlenecek e-posta kimliği "
                    "bulunamadı."
                ),
            }
        ), 400

    try:
        archive_gmail_email(gmail_id)
        panel_hidden = hide_email(gmail_id)

        message = (
            "E-posta Gmail'de arşivlendi ve "
            "panelden gizlendi."
        )

        if not panel_hidden:
            message = (
                "E-posta Gmail'de arşivlendi ancak "
                "panel kaydı gizlenemedi."
            )

        return jsonify(
            {
                "success": True,
                "message": message,
                "hidden_count": get_hidden_email_count(),
            }
        )

    except Exception as error:
        error_message = str(error)
        lowered_error = error_message.lower()

        if (
            "insufficient" in lowered_error
            or "permission" in lowered_error
            or "scope" in lowered_error
        ):
            status_code = 403
            clean_message = (
                "Gmail arşivleme izni bulunamadı. "
                "token.json dosyasını yenileyip "
                "Google iznini tekrar onaylayın."
            )
        else:
            status_code = 500
            clean_message = (
                "E-posta Gmail'de arşivlenemedi: "
                f"{error_message}"
            )

        return jsonify(
            {
                "success": False,
                "error": clean_message,
            }
        ), status_code


@app.route(
    "/restore-to-inbox",
    methods=["POST"],
)
def restore_email_to_gmail_inbox():
    """
    Mesajı Gmail Gelen Kutusu'na ve uygulama
    dashboard'una birlikte geri getirir.
    """
    gmail_id = get_gmail_id_from_request()

    if not gmail_id:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Gelen Kutusu'na taşınacak "
                    "e-posta kimliği bulunamadı."
                ),
            }
        ), 400

    try:
        move_email_to_inbox(gmail_id)
        panel_restored = restore_email(gmail_id)

        message = (
            "E-posta Gmail Gelen Kutusu'na ve "
            "dashboard'a geri getirildi."
        )

        if not panel_restored:
            message = (
                "E-posta Gmail Gelen Kutusu'na "
                "geri getirildi ancak panel kaydı "
                "güncellenemedi."
            )

        return jsonify(
            {
                "success": True,
                "message": message,
                "hidden_count": get_hidden_email_count(),
            }
        )

    except Exception as error:
        error_message = str(error)
        lowered_error = error_message.lower()

        if (
            "insufficient" in lowered_error
            or "permission" in lowered_error
            or "scope" in lowered_error
        ):
            status_code = 403
            clean_message = (
                "Gmail değiştirme izni bulunamadı. "
                "token.json dosyasını yenileyip "
                "Google iznini tekrar onaylayın."
            )
        else:
            status_code = 500
            clean_message = (
                "E-posta Gmail Gelen Kutusu'na "
                f"geri getirilemedi: {error_message}"
            )

        return jsonify(
            {
                "success": False,
                "error": clean_message,
            }
        ), status_code


if __name__ == "__main__":
    app.run(debug=True)
