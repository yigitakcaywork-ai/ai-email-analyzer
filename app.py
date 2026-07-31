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
    set_email_favorite,
)
from services.gmail_service import (
    archive_email as archive_gmail_email,
    create_gmail_draft,
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

    if show_hidden:
        grouped_results = group_emails_by_date(
            selected_emails
        )
    else:
        favorite_emails = [
            email
            for email in selected_emails
            if email.get("is_favorite")
        ]
        regular_emails = [
            email
            for email in selected_emails
            if not email.get("is_favorite")
        ]
        grouped_results = []

        if favorite_emails:
            grouped_results.append(
                {
                    "title": "⭐ Favoriler",
                    "emails": favorite_emails,
                    "is_favorite_group": True,
                }
            )

        grouped_results.extend(
            group_emails_by_date(regular_emails)
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

    category_counts = {}

    for email in visible_emails:
        category = str(
            email.get("category", "Diğer") or "Diğer"
        ).strip()
        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

    top_categories = [
        {"name": name, "count": count}
        for name, count in sorted(
            category_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]

    importance_values = [
        int(email.get("importance_score", 1) or 1)
        for email in visible_emails
    ]

    average_importance = (
        round(
            sum(importance_values) / len(importance_values),
            1,
        )
        if importance_values
        else 0
    )

    urgency_weight = {
        "Yüksek": 30,
        "Orta": 15,
        "Düşük": 0,
    }

    def focus_score(email: dict) -> int:
        return (
            urgency_weight.get(email.get("urgency"), 0)
            + (20 if email.get("reply_needed") else 0)
            + (12 if email.get("is_favorite") else 0)
            + int(email.get("importance_score", 1) or 1)
        )

    focus_emails = sorted(
        [
            email
            for email in visible_emails
            if (
                email.get("reply_needed")
                or email.get("urgency") == "Yüksek"
                or int(email.get("importance_score", 1) or 1) >= 8
            )
        ],
        key=lambda email: (
            -focus_score(email),
            -int(email.get("internal_date", 0) or 0),
        ),
    )[:3]

    clutter_categories = {
        "Reklam",
        "Bildirim",
        "Sosyal",
    }
    clutter_count = sum(
        1
        for email in visible_emails
        if email.get("category") in clutter_categories
    )

    inbox_score = max(
        0,
        min(
            100,
            100
            - (urgent_count * 12)
            - (reply_needed_count * 6)
            - (clutter_count * 2),
        ),
    )

    if urgent_count > 0:
        dashboard_recommendation = (
            f"Önce {urgent_count} yüksek aciliyetli e-postayı incele. "
            "Ardından cevap bekleyen mesajlara geç."
        )
    elif reply_needed_count > 0:
        dashboard_recommendation = (
            f"Şu anda {reply_needed_count} e-posta cevap bekliyor. "
            "AI taslaklarını hazırlayıp Gmail'e kaydet."
        )
    elif clutter_count > 0:
        dashboard_recommendation = (
            f"{clutter_count} düşük öncelikli reklam veya bildirim var. "
            "Toplu seçimle gelen kutunu temizleyebilirsin."
        )
    else:
        dashboard_recommendation = (
            "Gelen kutun kontrol altında görünüyor. "
            "Yeni mesajları tarayarak güncel kal."
        )

    favorite_count = sum(
        1 for email in visible_emails
        if email.get("is_favorite")
    )
    favorite_reply_count = sum(
        1 for email in visible_emails
        if email.get("is_favorite")
        and email.get("reply_needed")
    )

    return {
        "results": selected_emails,
        "grouped_results": grouped_results,
        "total_count": len(visible_emails),
        "today_count": today_count,
        "urgent_count": urgent_count,
        "reply_needed_count": reply_needed_count,
        "hidden_count": len(hidden_emails),
        "show_hidden": show_hidden,
        "top_categories": top_categories,
        "average_importance": average_importance,
        "focus_emails": focus_emails,
        "inbox_score": inbox_score,
        "clutter_count": clutter_count,
        "dashboard_recommendation": dashboard_recommendation,
        "favorite_count": favorite_count,
        "favorite_reply_count": favorite_reply_count,
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


def get_gmail_ids_from_request(
    max_items: int = 100,
) -> list[str]:
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("gmail_ids", [])

    if not isinstance(raw_ids, list):
        return []

    gmail_ids = []
    seen_ids = set()

    for raw_id in raw_ids:
        gmail_id = str(raw_id or "").strip()

        if (
            gmail_id
            and gmail_id not in seen_ids
        ):
            gmail_ids.append(gmail_id)
            seen_ids.add(gmail_id)

        if len(gmail_ids) >= max_items:
            break

    return gmail_ids


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
    "/create-gmail-draft",
    methods=["POST"],
)
def save_reply_as_gmail_draft():
    """
    AI cevap metnini Gmail Taslaklar klasörüne kaydeder.
    Mesaj otomatik gönderilmez.
    """
    data = request.get_json(silent=True) or {}

    sender = str(data.get("sender", "")).strip()
    subject = str(data.get("subject", "")).strip()
    reply_text = str(data.get("reply", "")).strip()
    thread_id = str(data.get("thread_id", "")).strip()

    if not sender:
        return jsonify({
            "success": False,
            "error": "Taslak alıcısı bulunamadı.",
        }), 400

    if not reply_text:
        return jsonify({
            "success": False,
            "error": "Önce bir AI cevap taslağı oluşturun.",
        }), 400

    try:
        draft = create_gmail_draft(
            sender=sender,
            subject=subject,
            reply_text=reply_text,
            thread_id=thread_id,
        )

        return jsonify({
            "success": True,
            "message": "Cevap Gmail Taslaklar klasörüne kaydedildi.",
            "draft_id": draft.get("draft_id", ""),
            "recipient": draft.get("recipient", ""),
        })

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
                "Gmail taslak oluşturma izni bulunamadı. "
                "token.json dosyasını yenileyip Google iznini tekrar onaylayın."
            )
        else:
            status_code = 500
            clean_message = (
                "Gmail taslağı oluşturulamadı: "
                f"{error_message}"
            )

        return jsonify({
            "success": False,
            "error": clean_message,
        }), status_code


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


@app.route(
    "/toggle-favorite",
    methods=["POST"],
)
def toggle_favorite():
    data = request.get_json(silent=True) or {}
    gmail_id = str(data.get("gmail_id", "")).strip()
    is_favorite = bool(data.get("is_favorite", False))

    if not gmail_id:
        return jsonify(
            {
                "success": False,
                "error": "Favori durumu değiştirilecek e-posta bulunamadı.",
            }
        ), 400

    updated = set_email_favorite(
        gmail_id=gmail_id,
        is_favorite=is_favorite,
    )

    if not updated:
        return jsonify(
            {
                "success": False,
                "error": "E-posta bulunamadı veya favori durumu güncellenemedi.",
            }
        ), 404

    return jsonify(
        {
            "success": True,
            "is_favorite": is_favorite,
            "message": (
                "E-posta favorilere eklendi."
                if is_favorite
                else "E-posta favorilerden çıkarıldı."
            ),
        }
    )


@app.route(
    "/bulk-hide-emails",
    methods=["POST"],
)
def bulk_hide_emails():
    gmail_ids = get_gmail_ids_from_request()

    if not gmail_ids:
        return jsonify({
            "success": False,
            "error": "Gizlenecek e-posta seçilmedi.",
        }), 400

    completed_ids = []
    failed_items = []

    for gmail_id in gmail_ids:
        try:
            if hide_email(gmail_id):
                completed_ids.append(gmail_id)
            else:
                failed_items.append({
                    "gmail_id": gmail_id,
                    "error": "Panel kaydı bulunamadı.",
                })
        except Exception as error:
            failed_items.append({
                "gmail_id": gmail_id,
                "error": str(error),
            })

    return jsonify({
        "success": bool(completed_ids),
        "completed_ids": completed_ids,
        "failed_items": failed_items,
        "completed_count": len(completed_ids),
        "failed_count": len(failed_items),
        "message": (
            f"{len(completed_ids)} e-posta panelden gizlendi."
        ),
        "hidden_count": get_hidden_email_count(),
    }), 200 if completed_ids else 500


@app.route(
    "/bulk-archive-emails",
    methods=["POST"],
)
def bulk_archive_emails():
    gmail_ids = get_gmail_ids_from_request()

    if not gmail_ids:
        return jsonify({
            "success": False,
            "error": "Arşivlenecek e-posta seçilmedi.",
        }), 400

    completed_ids = []
    failed_items = []

    for gmail_id in gmail_ids:
        try:
            archive_gmail_email(gmail_id)

            if not hide_email(gmail_id):
                raise RuntimeError(
                    "Gmail'de arşivlendi ancak panel kaydı gizlenemedi."
                )

            completed_ids.append(gmail_id)

        except Exception as error:
            failed_items.append({
                "gmail_id": gmail_id,
                "error": str(error),
            })

    return jsonify({
        "success": bool(completed_ids),
        "completed_ids": completed_ids,
        "failed_items": failed_items,
        "completed_count": len(completed_ids),
        "failed_count": len(failed_items),
        "message": (
            f"{len(completed_ids)} e-posta Gmail'de arşivlendi "
            "ve panelden gizlendi."
        ),
        "hidden_count": get_hidden_email_count(),
    }), 200 if completed_ids else 500


if __name__ == "__main__":
    app.run(debug=True)
