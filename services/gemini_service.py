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
    raise RuntimeError(
        "GEMINI_API_KEY bulunamadı. "
        ".env dosyanızı kontrol edin."
    )


client = genai.Client(
    api_key=API_KEY
)


MODEL_NAME = "gemini-3-flash-preview"


ALLOWED_CATEGORIES = [
    "İş",
    "Müşteri",
    "Finans",
    "Fatura",
    "Toplantı",
    "Destek",
    "Kişisel",
    "Sosyal",
    "Reklam",
    "Bildirim",
    "Güvenlik",
    "Diğer",
]


ALLOWED_URGENCY_LEVELS = [
    "Düşük",
    "Orta",
    "Yüksek",
]


REPLY_TONE_INSTRUCTIONS = {
    "professional": (
        "Profesyonel, güven veren, doğal ve açık bir dil kullan. "
        "Gereksiz resmiyetten kaçın."
    ),
    "formal": (
        "Resmî, ciddi ve saygılı bir dil kullan. "
        "Hitap ve kapanış ifadelerini resmî biçimde yaz."
    ),
    "friendly": (
        "Samimi, sıcak ve doğal bir dil kullan. "
        "Ancak profesyonellik sınırlarını koru."
    ),
    "short": (
        "Kısa ve net yaz. En fazla 3 kısa cümle kullan. "
        "Gereksiz açıklama ekleme."
    ),
}


def is_daily_quota_error(
    error_message: str,
) -> bool:
    """
    Günlük kota hatasını tespit eder.
    """
    lowered_message = error_message.lower()

    quota_keywords = [
        "quota exceeded",
        "daily quota",
        "per day",
        "resource_exhausted",
        "limit: 0",
        "requests per day",
    ]

    return any(
        keyword in lowered_message
        for keyword in quota_keywords
    )


def is_temporary_error(
    error_message: str,
) -> bool:
    """
    Geçici yoğunluk ve hız sınırı
    hatalarını tespit eder.
    """
    lowered_message = error_message.lower()

    temporary_keywords = [
        "429",
        "503",
        "resource_exhausted",
        "unavailable",
        "overloaded",
        "temporarily",
        "rate limit",
        "too many requests",
        "service unavailable",
    ]

    return any(
        keyword in lowered_message
        for keyword in temporary_keywords
    )


def generate_content_with_retry(
    contents: str,
    config: types.GenerateContentConfig,
    max_attempts: int = 4,
):
    """
    Gemini isteğini geçici hatalarda
    kontrollü biçimde tekrarlar.
    """
    retry_delays = [
        2,
        5,
        10,
    ]

    last_error = None

    for attempt in range(max_attempts):
        try:
            return client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )

        except Exception as error:
            last_error = error
            error_message = str(error)

            if is_daily_quota_error(
                error_message
            ):
                raise RuntimeError(
                    "Gemini günlük kullanım kotası doldu. "
                    "Kota yenilendiğinde tekrar deneyin."
                ) from error

            is_last_attempt = (
                attempt == max_attempts - 1
            )

            if (
                not is_temporary_error(
                    error_message
                )
                or is_last_attempt
            ):
                raise

            delay_index = min(
                attempt,
                len(retry_delays) - 1,
            )

            delay = (
                retry_delays[delay_index]
                + random.uniform(0.2, 1.0)
            )

            time.sleep(delay)

    raise RuntimeError(
        "Gemini isteği tamamlanamadı: "
        f"{last_error}"
    )


def extract_json_from_response(
    response_text: str,
) -> Any:
    """
    Gemini cevabındaki JSON metnini
    güvenli biçimde ayrıştırır.
    """
    cleaned_text = (
        response_text
        .strip()
        .replace("```json", "")
        .replace("```JSON", "")
        .replace("```", "")
        .strip()
    )

    try:
        return json.loads(
            cleaned_text
        )

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Gemini geçerli JSON döndürmedi."
        ) from error


def normalize_analysis(
    analysis: dict,
) -> dict:
    """
    Model çıktısını uygulamanın beklediği
    güvenli biçime dönüştürür.
    """
    category = str(
        analysis.get(
            "category",
            "Diğer",
        )
    ).strip()

    if category not in ALLOWED_CATEGORIES:
        category = "Diğer"

    urgency = str(
        analysis.get(
            "urgency",
            "Düşük",
        )
    ).strip()

    if urgency not in ALLOWED_URGENCY_LEVELS:
        urgency = "Düşük"

    try:
        importance_score = int(
            analysis.get(
                "importance_score",
                1,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        importance_score = 1

    importance_score = max(
        1,
        min(
            importance_score,
            10,
        ),
    )

    reply_needed_value = analysis.get(
        "reply_needed",
        False,
    )

    if isinstance(
        reply_needed_value,
        str,
    ):
        reply_needed = (
            reply_needed_value
            .strip()
            .lower()
            in {
                "true",
                "evet",
                "yes",
                "1",
            }
        )

    else:
        reply_needed = bool(
            reply_needed_value
        )

    summary = str(
        analysis.get(
            "summary",
            "",
        )
    ).strip()

    if not summary:
        summary = (
            "E-posta özeti oluşturulamadı."
        )

    recommended_action = str(
        analysis.get(
            "recommended_action",
            "",
        )
    ).strip()

    if not recommended_action:
        recommended_action = (
            "E-postayı manuel olarak inceleyin."
        )

    return {
        "summary": summary,
        "category": category,
        "importance_score": (
            importance_score
        ),
        "urgency": urgency,
        "recommended_action": (
            recommended_action
        ),
        "reply_needed": reply_needed,
    }


def analyze_emails(
    emails: list[dict],
) -> list[dict]:
    """
    Birden fazla e-postayı tek Gemini
    isteğinde analiz eder.
    """
    if not emails:
        return []

    email_payload = []

    for index, email in enumerate(
        emails,
        start=1,
    ):
        email_payload.append(
            {
                "email_index": index,
                "sender": email.get(
                    "from",
                    "Bilinmiyor",
                ),
                "subject": email.get(
                    "subject",
                    "Konu yok",
                ),
                "date": email.get(
                    "date",
                    "Tarih yok",
                ),
                "snippet": email.get(
                    "snippet",
                    "",
                ),
            }
        )

    prompt = f"""
Aşağıdaki e-postaları Türkçe olarak analiz et.

Her e-posta için aşağıdaki alanları üret:

- email_index
- summary
- category
- importance_score
- urgency
- recommended_action
- reply_needed

KURALLAR:

1. summary:
   E-postanın amacını 1 veya 2 kısa cümlede açıkla.

2. category:
   Yalnızca şu kategorilerden birini kullan:
   {", ".join(ALLOWED_CATEGORIES)}

3. importance_score:
   1 ile 10 arasında tam sayı kullan.

4. urgency:
   Yalnızca Düşük, Orta veya Yüksek yaz.

5. recommended_action:
   Kullanıcının ne yapması gerektiğini
   tek ve açık bir cümleyle belirt.

6. reply_needed:
   Yalnızca true veya false kullan.

7. Reklam, otomatik bildirim, bülten ve
   tanıtım mesajlarında genellikle
   reply_needed false olmalıdır.

8. Güvenlik uyarıları, ödeme sorunları,
   müşteri şikâyetleri ve zaman sınırlı
   işlemler daha yüksek önem taşıyabilir.

9. Tam olarak {len(emails)} sonuç döndür.

10. Sonuçları e-postaların sırasını
    değiştirmeden döndür.

Yalnızca geçerli bir JSON dizisi döndür.
Markdown veya ek açıklama kullanma.

E-POSTALAR:

{json.dumps(
    email_payload,
    ensure_ascii=False,
    indent=2,
)}
""".strip()

    config = types.GenerateContentConfig(
        response_mime_type=(
            "application/json"
        ),
        temperature=0.2,
        max_output_tokens=4096,
        thinking_config=types.ThinkingConfig(
            thinking_level="minimal",
        ),
    )

    response = generate_content_with_retry(
        contents=prompt,
        config=config,
    )

    response_text = (
        response.text or ""
    ).strip()

    if not response_text:
        raise RuntimeError(
            "Gemini boş analiz cevabı döndürdü."
        )

    parsed_response = extract_json_from_response(
        response_text
    )

    if isinstance(
        parsed_response,
        dict,
    ):
        possible_results = (
            parsed_response.get("results")
            or parsed_response.get("emails")
            or parsed_response.get(
                "analyses"
            )
        )

        if isinstance(
            possible_results,
            list,
        ):
            parsed_response = (
                possible_results
            )

    if not isinstance(
        parsed_response,
        list,
    ):
        raise RuntimeError(
            "Gemini analiz sonuçlarını "
            "liste biçiminde döndürmedi."
        )

    normalized_results = []

    for analysis in parsed_response:
        if not isinstance(
            analysis,
            dict,
        ):
            continue

        normalized_results.append(
            normalize_analysis(
                analysis
            )
        )

    if len(normalized_results) != len(
        emails
    ):
        raise RuntimeError(
            "Gemini tüm e-postaları "
            "eksiksiz analiz edemedi."
        )

    return normalized_results


def get_reply_tone_instruction(
    tone: str,
) -> str:
    """
    Arayüzden gelen ton değerini
    güvenli bir talimata dönüştürür.
    """
    normalized_tone = (
        str(tone or "professional")
        .strip()
        .lower()
    )

    return REPLY_TONE_INSTRUCTIONS.get(
        normalized_tone,
        REPLY_TONE_INSTRUCTIONS[
            "professional"
        ],
    )


def get_finish_reason(
    response,
) -> str:
    """
    Gemini yanıtının bitiş nedenini
    güvenli biçimde okur.
    """
    candidates = getattr(
        response,
        "candidates",
        None,
    )

    if not candidates:
        return ""

    first_candidate = candidates[0]

    finish_reason = getattr(
        first_candidate,
        "finish_reason",
        "",
    )

    return str(
        finish_reason or ""
    ).upper()


def looks_incomplete(
    reply: str,
) -> bool:
    """
    Görünürde yarım kalan cevapları
    tespit etmek için ek kontrol.
    """
    cleaned_reply = reply.strip()

    if not cleaned_reply:
        return True

    if len(cleaned_reply) < 15:
        return True

    unfinished_endings = (
        ",",
        ":",
        ";",
        "-",
        "—",
        "(",
        "/",
    )

    if cleaned_reply.endswith(
        unfinished_endings
    ):
        return True

    last_line = (
        cleaned_reply
        .splitlines()[-1]
        .strip()
    )

    # Son satır tek ve çok kısa bir kelimeyse
    # cevap kesilmiş olabilir.
    if (
        len(last_line.split()) == 1
        and len(last_line) <= 4
    ):
        return True

    return False


def generate_reply(
    sender: str,
    subject: str,
    snippet: str,
    summary: str,
    tone: str = "professional",
) -> str:
    """
    Seçilen tonda eksiksiz bir
    e-posta cevap taslağı oluşturur.

    Yanıt çıktı sınırında kesilirse daha
    yüksek token sınırıyla tekrar denenir.
    """
    tone_instruction = (
        get_reply_tone_instruction(
            tone
        )
    )

    prompt = f"""
Aşağıdaki e-postaya gönderilebilecek
eksiksiz bir Türkçe cevap taslağı hazırla.

GÖNDEREN:
{sender}

KONU:
{subject}

E-POSTA İÇERİĞİ:
{snippet}

AI ÖZETİ:
{summary}

SEÇİLEN CEVAP TONU:
{tone_instruction}

KURALLAR:

- Yalnızca gönderilecek cevap metnini yaz.
- Başlık, açıklama, analiz veya Markdown yazma.
- E-postada olmayan bilgi, tarih, fiyat,
  karar veya vaat uydurma.
- Seçilen tona kesinlikle uy.
- Uygun bir hitapla başla.
- Cevabı doğal ve anlaşılır yaz.
- Hiçbir kelimeyi veya cümleyi yarım bırakma.
- Mesajı anlamlı bir kapanışla tamamla.
- Gönderenin ismini bilmiyorsan güvenli
  ve genel bir hitap kullan.
- Reklam veya otomatik tanıtım mesajına
  cevap hazırlanıyorsa gereksiz taahhütte
  bulunma.
- Kısa ve net ton seçildiyse en fazla
  3 kısa cümle kullan.
""".strip()

    token_limits = [
        1024,
        2048,
    ]

    last_error = None

    for attempt_index, max_tokens in enumerate(
        token_limits,
    ):
        try:
            config = types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=max_tokens,
                thinking_config=(
                    types.ThinkingConfig(
                        thinking_level=(
                            "minimal"
                        ),
                    )
                ),
            )

            response = (
                generate_content_with_retry(
                    contents=prompt,
                    config=config,
                    max_attempts=3,
                )
            )

            reply = (
                response.text or ""
            ).strip()

            finish_reason = (
                get_finish_reason(
                    response
                )
            )

            hit_token_limit = (
                "MAX_TOKENS"
                in finish_reason
            )

            incomplete_reply = (
                looks_incomplete(
                    reply
                )
            )

            if (
                reply
                and not hit_token_limit
                and not incomplete_reply
            ):
                return reply

            has_another_attempt = (
                attempt_index
                < len(token_limits) - 1
            )

            if has_another_attempt:
                time.sleep(1)
                continue

            raise RuntimeError(
                "AI cevap taslağını "
                "eksiksiz tamamlayamadı."
            )

        except Exception as error:
            last_error = error

            has_another_attempt = (
                attempt_index
                < len(token_limits) - 1
            )

            if has_another_attempt:
                time.sleep(2)
                continue

    raise RuntimeError(
        "Cevap taslağı oluşturulamadı: "
        f"{last_error}"
    )