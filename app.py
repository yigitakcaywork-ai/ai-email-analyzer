from flask import Flask, jsonify, render_template, request

from database import (
    email_exists,
    get_saved_emails,
    init_database,
    save_analyzed_email,
)
from services.gmail_service import get_recent_emails
from services.gemini_service import analyze_emails, generate_reply


app = Flask(__name__)

# Uygulama başladığında veritabanı ve tablolar oluşturulur.
init_database()

# Tek taramada analiz edilecek maksimum yeni e-posta sayısı.
NEW_EMAIL_LIMIT = 10

# Gmail'den kontrol edilecek son e-posta sayısı.
# Bunlardan yalnızca veritabanında olmayanlar analiz edilir.
GMAIL_SCAN_LIMIT = 50


@app.route("/")
def home():
    """
    Ana sayfada daha önce kaydedilmiş analizleri gösterir.
    Gemini isteği kullanılmaz.
    """
    saved_emails = get_saved_emails(limit=200)

    return render_template(
        "index.html",
        results=saved_emails,
    )


@app.route("/analyze")
def analyze():
    """
    Gmail'deki son e-postaları kontrol eder.

    Daha önce analiz edilen e-postaları atlar.
    En fazla 10 yeni e-postayı tek Gemini isteğinde analiz eder.
    Sonuçları SQLite veritabanına kaydeder.
    """
    try:
        gmail_emails = get_recent_emails(
            max_results=GMAIL_SCAN_LIMIT,
        )

        # Yalnızca veritabanında bulunmayan e-postaları seç.
        new_emails = [
            email
            for email in gmail_emails
            if email.get("gmail_id")
            and not email_exists(email["gmail_id"])
        ]

        # En eski görülmemiş mesajlardan başlayarak ilerle.
        # Böylece çok sayıda yeni mail geldiğinde hiçbir mail
        # sürekli geride kalmaz.
        new_emails.sort(
            key=lambda email: email.get("internal_date", 0)
        )

        emails_to_analyze = new_emails[:NEW_EMAIL_LIMIT]

        if emails_to_analyze:
            analyses = analyze_emails(emails_to_analyze)

            for email, analysis in zip(
                emails_to_analyze,
                analyses,
            ):
                save_analyzed_email(
                    email=email,
                    analysis=analysis,
                )

        # Hem yeni kaydedilen hem de geçmiş analizleri göster.
        saved_emails = get_saved_emails(limit=200)

        return render_template(
            "index.html",
            results=saved_emails,
            analyzed_count=len(emails_to_analyze),
            remaining_count=max(
                len(new_emails) - len(emails_to_analyze),
                0,
            ),
        )

    except Exception as error:
        # Gemini veya Gmail hatası çıksa bile geçmiş kayıtlar kaybolmaz.
        saved_emails = get_saved_emails(limit=200)

        return render_template(
            "index.html",
            results=saved_emails,
            error=str(error),
        )


@app.route("/generate-reply", methods=["POST"])
def create_reply():
    """
    Seçilen e-posta için AI cevap taslağı oluşturur.
    Cevabı otomatik göndermez.
    """
    data = request.get_json(silent=True) or {}

    sender = str(data.get("sender", "")).strip()
    subject = str(data.get("subject", "")).strip()
    snippet = str(data.get("snippet", "")).strip()
    summary = str(data.get("summary", "")).strip()

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

        return jsonify(
            {
                "success": True,
                "reply": reply,
            }
        )

    except Exception as error:
        error_message = str(error)

        status_code = (
            429
            if "kota" in error_message.lower()
            else 500
        )

        return jsonify(
            {
                "success": False,
                "error": error_message,
            }
        ), status_code


if __name__ == "__main__":
    app.run(debug=True)