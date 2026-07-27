import json
import os
import random
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError(
        "GEMINI_API_KEY .env dosyasında bulunamadı."
    )


client = genai.Client(api_key=API_KEY)

MODEL_NAME = "gemini-3-flash-preview"

ALLOWED_CATEGORIES = {
    "İş",
    "Kişisel",
    "Reklam",
    "Sosyal Medya",
    "Güvenlik",
    "Fatura",
    "Diğer",
}

ALLOWED_URGENCIES = {
    "Düşük",
    "Orta",
    "Yüksek",
}


def is_daily_quota_error(error: Exception) -> bool:
    """
    Günlük ücretsiz istek kotasının dolup dolmadığını kontrol eder.
    Günlük kota dolduysa tekrar denemek fayda sağlamaz.
    """
    error_text = str(error).lower()

    daily_quota_phrases = (
        "perday",
        "per_day",
        "requestsperday",
        "generate requests per day",
        "daily quota",
    )

    return (
        "429" in error_text
        and any(
            phrase in error_text
            for phrase in daily_quota_phrases
        )
    )


def is_temporary_error(error: Exception) -> bool:
    """
    Bir süre bekledikten sonra düzelebilecek hataları belirler.
    """
    error_text = str(error).lower()

    temporary_phrases = (
        "503",
        "unavailable",
        "high demand",
        "temporarily unavailable",
        "service unavailable",
        "429",
        "resource_exhausted",
        "rate limit",
        "retrydelay",
        "retry delay",
    )

    return any(
        phrase in error_text
        for phrase in temporary_phrases
    )


def generate_content_with_retry(
    prompt: str,
    config: types.GenerateContentConfig | None = None,
    max_attempts: int = 4,
):
    """
    Gemini isteğini gönderir.

    503 veya geçici hız sınırı hatalarında sırasıyla
    yaklaşık 2, 5 ve 10 saniye bekleyerek yeniden dener.
    """
    retry_delays = [2, 5, 10]

    for attempt in range(max_attempts):
        try:
            return client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )

        except Exception as error:
            if is_daily_quota_error(error):
                raise RuntimeError(
                    "Gemini günlük kullanım kotasına ulaşıldı. "
                    "Kota yenilendikten sonra tekrar deneyin."
                ) from error

            last_attempt = attempt == max_attempts - 1

            if not is_temporary_error(error):
                raise RuntimeError(
                    "Gemini isteği sırasında beklenmeyen "
                    "bir hata oluştu."
                ) from error

            if last_attempt:
                raise RuntimeError(
                    "Gemini şu anda yoğun veya geçici olarak "
                    "kullanılamıyor. E-postalarınız kaybolmadı; "
                    "kısa süre sonra tekrar deneyin."
                ) from error

            delay_index = min(
                attempt,
                len(retry_delays) - 1,
            )

            wait_time = (
                retry_delays[delay_index]
                + random.uniform(0, 1)
            )

            time.sleep(wait_time)

    raise RuntimeError(
        "Gemini isteği tamamlanamadı."
    )


def clean_json_response(raw_text: str) -> Any:
    """
    Olası Markdown kod bloklarını kaldırıp JSON'u çözümler.
    """
    cleaned_text = raw_text.strip()

    if cleaned_text.startswith("```"):
        cleaned_text = (
            cleaned_text
            .replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

    try:
        return json.loads(cleaned_text)

    except json.JSONDecodeError as error:
        raise ValueError(
            "Gemini geçerli bir JSON yanıtı döndürmedi."
        ) from error


def normalize_analysis(analysis: dict) -> dict:
    """
    Gemini analizindeki değerleri doğrular ve standartlaştırır.
    """
    category = str(
        analysis.get("category", "Diğer")
    ).strip()

    if category not in ALLOWED_CATEGORIES:
        category = "Diğer"

    urgency = str(
        analysis.get("urgency", "Düşük")
    ).strip()

    if urgency not in ALLOWED_URGENCIES:
        urgency = "Düşük"

    try:
        importance_score = int(
            analysis.get("importance_score", 1)
        )

    except (TypeError, ValueError):
        importance_score = 1

    importance_score = max(
        1,
        min(importance_score, 10),
    )

    reply_needed = analysis.get(
        "reply_needed",
        False,
    )

    if not isinstance(reply_needed, bool):
        reply_needed = (
            str(reply_needed).strip().lower()
            == "true"
        )

    summary = str(
        analysis.get(
            "summary",
            "Özet oluşturulamadı.",
        )
    ).strip()

    recommended_action = str(
        analysis.get(
            "recommended_action",
            "E-postayı manuel olarak inceleyin.",
        )
    ).strip()

    return {
        "summary": (
            summary
            or "Özet oluşturulamadı."
        ),
        "category": category,
        "importance_score": importance_score,
        "urgency": urgency,
        "recommended_action": (
            recommended_action
            or "E-postayı manuel olarak inceleyin."
        ),
        "reply_needed": reply_needed,
    }


def create_default_analysis() -> dict:
    """
    Gemini bir e-posta için sonuç döndürmezse
    kullanılacak güvenli varsayılan analiz.
    """
    return {
        "summary": (
            "Bu e-posta için analiz oluşturulamadı."
        ),
        "category": "Diğer",
        "importance_score": 1,
        "urgency": "Düşük",
        "recommended_action": (
            "E-postayı manuel olarak inceleyin."
        ),
        "reply_needed": False,
    }


def analyze_emails(
    emails: list[dict],
) -> list[dict]:
    """
    Birden fazla e-postayı tek Gemini isteğinde analiz eder.

    Dönen analizlerin sırası, gönderilen e-postaların
    sırasıyla aynı tutulur.
    """
    if not emails:
        return []

    email_items = []

    for index, email in enumerate(emails):
        email_items.append(
            {
                "email_index": index,
                "sender": email.get(
                    "from",
                    "",
                ),
                "subject": email.get(
                    "subject",
                    "",
                ),
                "date": email.get(
                    "date",
                    "",
                ),
                "snippet": email.get(
                    "snippet",
                    "",
                ),
            }
        )

    prompt = f"""
Aşağıdaki e-postaları Türkçe analiz et.

E-postalar:
{json.dumps(
    email_items,
    ensure_ascii=False,
    indent=2,
)}

Her e-posta için:

- En fazla iki kısa cümlelik özet oluştur.
- Uygun kategoriyi belirle.
- Önem puanını 1 ile 10 arasında değerlendir.
- Aciliyeti Düşük, Orta veya Yüksek olarak belirle.
- Kısa ve uygulanabilir bir işlem öner.
- Cevap gerekip gerekmediğini belirle.
- Bilmediğin bilgi, tarih veya taahhüt uydurma.
- email_index değerini değiştirme.
- Sonuçları email_index sırasına göre döndür.
"""

    response_schema = {
        "type": "object",
        "properties": {
            "analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "email_index": {
                            "type": "integer",
                        },
                        "summary": {
                            "type": "string",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "İş",
                                "Kişisel",
                                "Reklam",
                                "Sosyal Medya",
                                "Güvenlik",
                                "Fatura",
                                "Diğer",
                            ],
                        },
                        "importance_score": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                        "urgency": {
                            "type": "string",
                            "enum": [
                                "Düşük",
                                "Orta",
                                "Yüksek",
                            ],
                        },
                        "recommended_action": {
                            "type": "string",
                        },
                        "reply_needed": {
                            "type": "boolean",
                        },
                    },
                    "required": [
                        "email_index",
                        "summary",
                        "category",
                        "importance_score",
                        "urgency",
                        "recommended_action",
                        "reply_needed",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": [
            "analyses",
        ],
        "additionalProperties": False,
    }

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=response_schema,
        temperature=0.2,
    )

    response = generate_content_with_retry(
        prompt=prompt,
        config=config,
    )

    if not response.text:
        raise ValueError(
            "Gemini boş analiz yanıtı döndürdü."
        )

    parsed_response = clean_json_response(
        response.text
    )

    if not isinstance(parsed_response, dict):
        raise ValueError(
            "Gemini analiz yanıtı beklenen "
            "yapıda değil."
        )

    raw_analyses = parsed_response.get(
        "analyses",
        [],
    )

    if not isinstance(raw_analyses, list):
        raise ValueError(
            "Gemini analiz listesi oluşturamadı."
        )

    analyses_by_index = {}

    for raw_analysis in raw_analyses:
        if not isinstance(raw_analysis, dict):
            continue

        try:
            email_index = int(
                raw_analysis.get("email_index")
            )

        except (TypeError, ValueError):
            continue

        if not 0 <= email_index < len(emails):
            continue

        analyses_by_index[email_index] = (
            normalize_analysis(raw_analysis)
        )

    final_analyses = []

    for index in range(len(emails)):
        final_analyses.append(
            analyses_by_index.get(
                index,
                create_default_analysis(),
            )
        )

    return final_analyses


def generate_reply(
    sender: str,
    subject: str,
    snippet: str,
    summary: str = "",
) -> str:
    """
    Seçilen e-posta için profesyonel bir
    Türkçe cevap taslağı oluşturur.
    """
    prompt = f"""
Aşağıdaki e-postaya gönderilebilecek kısa,
doğal ve profesyonel bir Türkçe cevap taslağı oluştur.

Gönderen:
{sender}

Konu:
{subject}

E-posta içeriği:
{snippet}

E-posta özeti:
{summary}

Kurallar:

- Yalnızca gönderilebilir cevap metnini yaz.
- Markdown veya açıklama ekleme.
- Bilmediğin bilgi, tarih veya taahhüt uydurma.
- Kullanıcının adına kesin karar verme.
- Eksik bilgiler için [isim], [tarih] veya
  [uygun saat] gibi köşeli parantezli alanlar kullan.
- Profesyonel fakat doğal bir dil kullan.
- Uygun bir selamlama ve kapanış ekle.
- Gereksiz şekilde uzun yazma.
- E-posta cevap gerektirmiyor gibi görünse bile,
  kullanıcı butona bastığı için kısa ve nazik
  bir cevap taslağı oluştur.
"""

    config = types.GenerateContentConfig(
        temperature=0.4,
        max_output_tokens=600,
    )

    response = generate_content_with_retry(
        prompt=prompt,
        config=config,
    )

    if not response.text:
        raise ValueError(
            "Gemini cevap taslağı oluşturamadı."
        )

    reply_text = response.text.strip()

    if not reply_text:
        raise ValueError(
            "Gemini boş cevap taslağı döndürdü."
        )

    return reply_text