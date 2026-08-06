from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, session

from database import (
    email_exists,
    get_saved_emails,
    save_analyzed_email,
    get_gmail_connection,
    get_learning_suggestions,
    get_today_behavior_counts,
    get_today_analyzed_count,
    get_today_scan_count,
    get_recent_worker_events,
    get_ai_memory,
    get_ai_memory_stats,
    record_behavior,
)
from services.gmail_service import get_recent_emails
from services.gemini_service import analyze_emails


dashboard_bp = Blueprint("dashboard", __name__)

NEW_EMAIL_LIMIT = 10
GMAIL_SCAN_LIMIT = 50
LOCAL_TIMEZONE = ZoneInfo("Europe/Istanbul")


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
    user_id: int,
    show_hidden: bool = False,
    show_followups: bool = False,
) -> dict:
    all_emails = get_saved_emails(
        user_id=user_id,
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

    active_followups = [
        email
        for email in all_emails
        if email.get("follow_up_at")
        and not email.get("follow_up_completed_at")
    ]

    selected_emails = (
        active_followups
        if show_followups
        else hidden_emails
        if show_hidden
        else visible_emails
    )

    if show_hidden or show_followups:
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

    today_iso = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    follow_up_count = len(active_followups)
    follow_up_today_count = sum(
        1 for email in active_followups
        if str(email.get("follow_up_at")) == today_iso
    )
    overdue_follow_up_count = sum(
        1 for email in active_followups
        if str(email.get("follow_up_at")) < today_iso
    )

    for email in selected_emails:
        follow_up_at = email.get("follow_up_at")
        if follow_up_at and not email.get("follow_up_completed_at"):
            if follow_up_at < today_iso:
                email["follow_up_status"] = "overdue"
                email["follow_up_label"] = "Gecikti"
            elif follow_up_at == today_iso:
                email["follow_up_status"] = "today"
                email["follow_up_label"] = "Bugün"
            else:
                follow_date = datetime.fromisoformat(follow_up_at).date()
                days_left = (follow_date - datetime.now(LOCAL_TIMEZONE).date()).days
                email["follow_up_status"] = "upcoming"
                email["follow_up_label"] = f"{days_left} gün kaldı"
        else:
            email["follow_up_status"] = ""
            email["follow_up_label"] = ""

    inbox_score = max(
        0,
        min(
            100,
            100
            - (urgent_count * 12)
            - (reply_needed_count * 6)
            - (clutter_count * 2)
            - (overdue_follow_up_count * 8),
        ),
    )

    if overdue_follow_up_count > 0:
        dashboard_recommendation = (
            f"{overdue_follow_up_count} takip gecikmiş durumda. "
            "Önce bu e-postaları tamamla veya tarihlerini güncelle."
        )
    elif urgent_count > 0:
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

    behavior_counts = get_today_behavior_counts(user_id)
    analyzed_today_count = get_today_analyzed_count(user_id)
    scan_today_count = get_today_scan_count(user_id)
    worker_events = get_recent_worker_events(user_id, limit=10)
    learning_suggestions = get_learning_suggestions(user_id)
    ai_memory = get_ai_memory(user_id, limit=8)
    ai_memory_stats = get_ai_memory_stats(user_id)
    automated_count = behavior_counts.get("automation", 0)
    completed_action_count = sum(
        behavior_counts.get(action, 0)
        for action in ("archive", "hide", "favorite", "follow_up", "gmail_draft_created")
    )

    worker_summary = (
        f"Bugün {scan_today_count} kez gelen kutunu taradım ve "
        f"{analyzed_today_count} yeni e-postayı analiz ettim. "
        f"Gelen kutunda şu anda {urgent_count} acil, "
        f"{reply_needed_count} cevap bekleyen ve "
        f"{clutter_count} temizlenebilir e-posta var."
    )

    if overdue_follow_up_count > 0:
        worker_next_step = f"Önce geciken {overdue_follow_up_count} takibi tamamla."
    elif urgent_count > 0:
        worker_next_step = f"Önce {urgent_count} acil e-postayı incele."
    elif reply_needed_count > 0:
        worker_next_step = f"Cevap bekleyen {reply_needed_count} e-posta için taslak hazırla."
    elif clutter_count > 0:
        worker_next_step = f"{clutter_count} düşük öncelikli e-postayı temizleyebilirsin."
    else:
        worker_next_step = "Gelen kutun kontrol altında. Yeni e-postaları tarayarak güncel kal."

    ai_worker_report = {
        "summary": worker_summary,
        "next_step": worker_next_step,
        "analyzed_today": analyzed_today_count,
        "scan_today": scan_today_count,
        "urgent": urgent_count,
        "reply_needed": reply_needed_count,
        "cleanable": clutter_count,
        "completed_actions": completed_action_count,
        "automated": automated_count,
    }

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
        "follow_up_count": follow_up_count,
        "follow_up_today_count": follow_up_today_count,
        "overdue_follow_up_count": overdue_follow_up_count,
        "show_followups": show_followups,
        "gmail_connection": get_gmail_connection(user_id),
        "gmail_connected": get_gmail_connection(user_id) is not None,
        "ai_worker_report": ai_worker_report,
        "behavior_counts": behavior_counts,
        "learning_suggestions": learning_suggestions,
        "worker_events": worker_events,
        "ai_memory": ai_memory,
        "ai_memory_stats": ai_memory_stats,
    }

def render_dashboard(
    show_hidden: bool = False,
    show_followups: bool = False,
    **extra_data,
):
    user_id = int(session["user_id"])
    dashboard_data = create_dashboard_data(
        user_id=user_id,
        show_hidden=show_hidden,
        show_followups=show_followups,
    )
    dashboard_data.update(extra_data)

    if request.args.get("gmail_connected"):
        dashboard_data["status_message"] = "Gmail hesabı başarıyla bağlandı."
    if request.args.get("gmail_disconnected"):
        dashboard_data["status_message"] = "Gmail bağlantısı kaldırıldı."
    if request.args.get("gmail_error"):
        dashboard_data["error"] = request.args.get("gmail_error")

    return render_template(
        "index.html",
        **dashboard_data,
    )

@dashboard_bp.route("/")
def home():
    return render_dashboard(show_hidden=False)

@dashboard_bp.route("/hidden")
def hidden_emails_page():
    return render_dashboard(show_hidden=True)

@dashboard_bp.route("/follow-ups")
def follow_ups_page():
    return render_dashboard(show_followups=True)

@dashboard_bp.route("/analyze")
def analyze():
    try:
        user_id = int(session["user_id"])
        gmail_emails = get_recent_emails(
            user_id=user_id,
            max_results=GMAIL_SCAN_LIMIT,
        )

        new_emails = [
            email
            for email in gmail_emails
            if email.get("gmail_id")
            and not email_exists(user_id, email["gmail_id"])
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

        scan_urgent_count = 0
        scan_reply_count = 0
        scan_cleanable_count = 0

        if emails_to_analyze:
            analyses = analyze_emails(
                emails_to_analyze
            )

            for email, analysis in zip(
                emails_to_analyze,
                analyses,
            ):
                save_analyzed_email(
                    user_id=user_id,
                    email=email,
                    analysis=analysis,
                )

            scan_urgent_count = sum(
                1 for analysis in analyses
                if analysis.get("urgency") == "Yüksek"
            )
            scan_reply_count = sum(
                1 for analysis in analyses
                if bool(analysis.get("reply_needed"))
            )
            scan_cleanable_count = sum(
                1 for analysis in analyses
                if analysis.get("category") in {"Reklam", "Bildirim", "Sosyal"}
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

        # Her tarama günlükte görünür; yeni e-posta bulunmasa bile
        # AI çalışanın gelen kutusunu kontrol ettiği kaydedilir.
        record_behavior(
            user_id=user_id,
            action_type="scan_completed",
            metadata={
                "scanned_count": len(gmail_emails),
                "analyzed_count": len(emails_to_analyze),
                "urgent_count": scan_urgent_count,
                "reply_needed_count": scan_reply_count,
                "cleanable_count": scan_cleanable_count,
                "remaining_count": remaining_count,
            },
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

