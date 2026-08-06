from flask import Blueprint, jsonify, request, session

from database import (
    create_automation_rule,
    delete_automation_rule,
    set_automation_rule_enabled,
)


automation_rules_bp = Blueprint("automation_rules", __name__)


@automation_rules_bp.route("/automation-rules", methods=["POST"])
def create_rule():
    data = request.get_json(silent=True) or {}
    try:
        rule = create_automation_rule(
            user_id=int(session["user_id"]),
            dimension_type=data.get("dimension_type", ""),
            dimension_value=data.get("dimension_value", ""),
            action_type=data.get("action_type", ""),
        )
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    return jsonify({
        "success": True,
        "message": "Otomasyon kuralı oluşturuldu. Motor sonraki sürümde bu kuralı uygulayacak.",
        "rule": rule,
    })


@automation_rules_bp.route("/automation-rules/<int:rule_id>/toggle", methods=["POST"])
def toggle_rule(rule_id: int):
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("is_enabled", False))
    updated = set_automation_rule_enabled(int(session["user_id"]), rule_id, enabled)
    if not updated:
        return jsonify({"success": False, "error": "Kural bulunamadı."}), 404
    return jsonify({"success": True, "is_enabled": enabled})


@automation_rules_bp.route("/automation-rules/<int:rule_id>", methods=["DELETE"])
def remove_rule(rule_id: int):
    deleted = delete_automation_rule(int(session["user_id"]), rule_id)
    if not deleted:
        return jsonify({"success": False, "error": "Kural bulunamadı."}), 404
    return jsonify({"success": True, "message": "Otomasyon kuralı silindi."})
