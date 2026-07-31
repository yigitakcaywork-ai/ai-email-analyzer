from flask import Blueprint, jsonify, request

from database import save_reply_draft
from services.gmail_service import create_gmail_draft
from services.gemini_service import generate_reply


replies_bp = Blueprint("replies", __name__)

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


@replies_bp.route(
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

@replies_bp.route(
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

