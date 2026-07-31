from datetime import datetime

from flask import Blueprint, jsonify, request

from database import (
    complete_email_follow_up,
    set_email_follow_up,
)
from .dashboard import LOCAL_TIMEZONE
from .gmail_actions import get_gmail_id_from_request


follow_ups_bp = Blueprint("follow_ups", __name__)


@follow_ups_bp.route(
    "/set-follow-up",
    methods=["POST"],
)
def set_follow_up():
    data = request.get_json(silent=True) or {}
    gmail_id = str(data.get("gmail_id", "")).strip()
    follow_up_at = str(data.get("follow_up_at", "")).strip()

    if not gmail_id or not follow_up_at:
        return jsonify({
            "success": False,
            "error": "E-posta ve takip tarihi zorunludur.",
        }), 400

    try:
        follow_date = datetime.fromisoformat(follow_up_at).date()
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Geçersiz takip tarihi.",
        }), 400

    if follow_date < datetime.now(LOCAL_TIMEZONE).date():
        return jsonify({
            "success": False,
            "error": "Geçmiş bir tarih seçilemez.",
        }), 400

    updated = set_email_follow_up(gmail_id, follow_date.isoformat())
    if not updated:
        return jsonify({
            "success": False,
            "error": "E-posta bulunamadı veya takip eklenemedi.",
        }), 404

    return jsonify({
        "success": True,
        "message": "E-posta takip listesine eklendi.",
        "follow_up_at": follow_date.isoformat(),
    })

@follow_ups_bp.route(
    "/complete-follow-up",
    methods=["POST"],
)
def complete_follow_up():
    gmail_id = get_gmail_id_from_request()
    if not gmail_id:
        return jsonify({
            "success": False,
            "error": "Tamamlanacak takip bulunamadı.",
        }), 400

    completed = complete_email_follow_up(gmail_id)
    if not completed:
        return jsonify({
            "success": False,
            "error": "Aktif takip bulunamadı.",
        }), 404

    return jsonify({
        "success": True,
        "message": "Takip tamamlandı.",
    })

