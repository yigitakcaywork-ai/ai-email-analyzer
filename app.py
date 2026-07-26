from flask import Flask, render_template

from services.gmail_service import get_recent_emails
from services.gemini_service import analyze_email

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/analyze")
def analyze():
    results = []

    try:
        emails = get_recent_emails(5)

        for email in emails:
            try:
                analysis = analyze_email(email)

                results.append(
                    {
                        "sender": email.get("from", "Bilinmeyen Gönderen"),
                        "subject": email.get("subject", "Konu Yok"),
                        "date": email.get("date", ""),
                        "summary": analysis.get("summary", ""),
                        "category": analysis.get("category", ""),
                        "importance_score": analysis.get("importance_score", 0),
                        "urgency": analysis.get("urgency", ""),
                        "recommended_action": analysis.get("recommended_action", ""),
                        "reply_needed": analysis.get("reply_needed", False),
                    }
                )

            except Exception as error:
                results.append(
                    {
                        "sender": email.get("from", "Bilinmeyen Gönderen"),
                        "subject": email.get("subject", "Konu Yok"),
                        "date": email.get("date", ""),
                        "summary": f"Hata: {error}",
                        "category": "Hata",
                        "importance_score": 0,
                        "urgency": "-",
                        "recommended_action": "-",
                        "reply_needed": False,
                    }
                )

        return render_template(
            "index.html",
            results=results,
        )

    except Exception as error:
        return render_template(
            "index.html",
            error=f"E-postalar alınırken hata oluştu: {error}",
        )


if __name__ == "__main__":
    app.run(debug=True)