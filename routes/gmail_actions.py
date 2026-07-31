from flask import Blueprint, jsonify, request

from database import (
    get_hidden_email_count,
    hide_email,
    restore_email,
    set_email_favorite,
)
from services.gmail_service import (
    archive_email as archive_gmail_email,
    move_email_to_inbox,
)


gmail_actions_bp = Blueprint("gmail_actions", __name__)


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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

@gmail_actions_bp.route(
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

