"""Kullanıcının onayladığı güvenli otomasyon kurallarını uygular."""

from database import (
    get_matching_automation_rules,
    hide_email,
    mark_automation_rule_used,
    record_behavior,
    set_email_favorite,
)
from services.gmail_service import archive_email as archive_gmail_email


SAFE_ACTIONS = {"archive", "hide", "favorite"}


def apply_automation_rules(
    user_id: int,
    email: dict,
    analysis: dict,
) -> dict:
    """Yeni analiz edilen bir e-postaya aktif kuralları güvenli biçimde uygular.

    Bir e-posta için aynı işlem yalnızca bir kez uygulanır. Arşivleme zaten
    panelden gizlemeyi içerdiği için, arşivleme başarılı olursa ayrıca gizleme
    kuralı çalıştırılmaz. Hatalar taramanın tamamını durdurmaz; sonuçta raporlanır.
    """
    gmail_id = str(email.get("gmail_id", "") or "").strip()
    sender = str(email.get("from", "") or "").strip()
    category = str(analysis.get("category", "") or "").strip()

    if not gmail_id:
        return {"applied": [], "failed": []}

    rules = get_matching_automation_rules(
        user_id=user_id,
        sender=sender,
        category=category,
    )

    applied: list[dict] = []
    failed: list[dict] = []
    completed_actions: set[str] = set()

    for rule in rules:
        action = str(rule.get("action_type", "") or "").strip().lower()
        if action not in SAFE_ACTIONS or action in completed_actions:
            continue
        if action == "hide" and "archive" in completed_actions:
            continue

        try:
            if action == "archive":
                archive_gmail_email(user_id, gmail_id)
                if not hide_email(user_id, gmail_id):
                    raise RuntimeError(
                        "Gmail'de arşivlendi ancak panel kaydı gizlenemedi."
                    )
                message = f"{sender or 'Bir e-posta'} kuralına göre Gmail’de arşivlendi."
            elif action == "hide":
                if not hide_email(user_id, gmail_id):
                    raise RuntimeError("Panel kaydı otomatik gizlenemedi.")
                message = f"{sender or 'Bir e-posta'} kuralına göre panelden gizlendi."
            else:
                if not set_email_favorite(user_id, gmail_id, True):
                    raise RuntimeError("E-posta otomatik favorilenemedi.")
                message = f"{sender or 'Bir e-posta'} kuralına göre favorilere eklendi."

            completed_actions.add(action)
            mark_automation_rule_used(user_id, int(rule["id"]))
            record_behavior(
                user_id=user_id,
                action_type="automation",
                gmail_id=gmail_id,
                metadata={
                    "message": message,
                    "rule_id": int(rule["id"]),
                    "rule_name": rule.get("rule_name", ""),
                    "automated_action": action,
                    "dimension_type": rule.get("dimension_type", ""),
                    "dimension_value": rule.get("dimension_value", ""),
                },
            )
            applied.append({
                "rule_id": int(rule["id"]),
                "action_type": action,
                "message": message,
            })

        except Exception as error:  # Bir kural hatası tüm taramayı durdurmamalı.
            clean_error = str(error)
            record_behavior(
                user_id=user_id,
                action_type="automation_failed",
                gmail_id=gmail_id,
                metadata={
                    "message": (
                        f"{sender or 'Bir e-posta'} için otomatik işlem uygulanamadı: "
                        f"{clean_error}"
                    ),
                    "rule_id": int(rule["id"]),
                    "rule_name": rule.get("rule_name", ""),
                    "automated_action": action,
                    "error": clean_error,
                },
            )
            failed.append({
                "rule_id": int(rule["id"]),
                "action_type": action,
                "error": clean_error,
            })

    return {"applied": applied, "failed": failed}
