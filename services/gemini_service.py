import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY .env dosyasında bulunamadı.")

client = genai.Client(api_key=api_key)


def analyze_email(email: dict) -> dict:
    prompt = f"""
Aşağıdaki e-postayı Türkçe analiz et.

Gönderen: {email.get("from", "")}
Konu: {email.get("subject", "")}
Tarih: {email.get("date", "")}
İçerik önizlemesi: {email.get("snippet", "")}

Yalnızca geçerli JSON döndür.
Markdown, kod bloğu veya açıklama ekleme.

Şu yapıyı birebir kullan:

{{
  "summary": "En fazla 2 cümlelik kısa özet",
  "category": "İş",
  "importance_score": 5,
  "urgency": "Orta",
  "recommended_action": "Kullanıcının yapması gereken işlem",
  "reply_needed": false
}}

Kurallar:

- category alanı yalnızca şu değerlerden biri olsun:
  İş, Kişisel, Reklam, Sosyal Medya, Güvenlik, Fatura, Diğer

- importance_score 1 ile 10 arasında tam sayı olsun.

- urgency yalnızca şu değerlerden biri olsun:
  Düşük, Orta, Yüksek

- reply_needed yalnızca true veya false olsun.
"""

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
    )

    if not response.text:
        raise ValueError("Gemini boş yanıt döndürdü.")

    raw_text = response.text.strip()

    if raw_text.startswith("```"):
        raw_text = (
            raw_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

    analysis = json.loads(raw_text)

    return {
        "summary": analysis.get("summary", "Özet oluşturulamadı."),
        "category": analysis.get("category", "Diğer"),
        "importance_score": analysis.get("importance_score", 1),
        "urgency": analysis.get("urgency", "Düşük"),
        "recommended_action": analysis.get(
            "recommended_action",
            "Herhangi bir işlem önerilmedi.",
        ),
        "reply_needed": analysis.get("reply_needed", False),
    }