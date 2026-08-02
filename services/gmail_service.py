import base64
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from database import get_gmail_connection, save_gmail_connection
from services.credential_crypto import decrypt_value, encrypt_value


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _serialize_expiry(expiry) -> str:
    """Google Credentials ile uyumlu UTC-naive zamanı metne çevirir."""
    if not expiry:
        return ""

    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)

    return expiry.isoformat()


def _parse_expiry(value: str):
    """Veritabanındaki zamanı Google Credentials için UTC-naive döndürür."""
    if not value:
        return None

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def get_gmail_credentials(user_id: int) -> Credentials:
    connection = get_gmail_connection(user_id)
    if not connection:
        raise RuntimeError("Gmail hesabı bağlı değil. Önce Gmail hesabınızı bağlayın.")

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth bilgileri .env dosyasında bulunamadı.")

    credentials = Credentials(
        token=decrypt_value(connection.get("encrypted_access_token")),
        refresh_token=decrypt_value(connection.get("encrypted_refresh_token")) or None,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=(connection.get("scopes") or " ".join(SCOPES)).split(),
        expiry=_parse_expiry(connection.get("token_expiry") or ""),
    )

    if credentials.expired:
        if not credentials.refresh_token:
            raise RuntimeError("Gmail bağlantısının süresi doldu. Gmail hesabınızı yeniden bağlayın.")
        credentials.refresh(Request())
        save_gmail_connection(
            user_id=user_id,
            gmail_address=connection.get("gmail_address", ""),
            encrypted_access_token=encrypt_value(credentials.token),
            encrypted_refresh_token=encrypt_value(credentials.refresh_token),
            token_expiry=_serialize_expiry(credentials.expiry),
            scopes=" ".join(credentials.scopes or SCOPES),
        )

    return credentials


def get_gmail_service(user_id: int):
    return build("gmail", "v1", credentials=get_gmail_credentials(user_id))


def get_recent_emails(user_id: int, max_results: int = 10, after_unix_seconds: int | None = None):
    service = get_gmail_service(user_id)
    list_parameters = {"userId": "me", "maxResults": max_results, "labelIds": ["INBOX"]}
    if after_unix_seconds is not None:
        list_parameters["q"] = f"after:{int(after_unix_seconds)}"

    result = service.users().messages().list(**list_parameters).execute()
    emails = []
    for message in result.get("messages", []):
        email_data = service.users().messages().get(
            userId="me", id=message["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = email_data.get("payload", {}).get("headers", [])
        header_map = {header["name"]: header["value"] for header in headers}
        emails.append({
            "gmail_id": email_data.get("id", message["id"]),
            "thread_id": email_data.get("threadId", ""),
            "internal_date": int(email_data.get("internalDate", 0)),
            "from": header_map.get("From", "Bilinmiyor"),
            "subject": header_map.get("Subject", "Konu yok"),
            "date": header_map.get("Date", "Tarih yok"),
            "snippet": email_data.get("snippet", ""),
        })
    emails.sort(key=lambda email: email["internal_date"], reverse=True)
    return emails


def archive_email(user_id: int, gmail_id: str) -> bool:
    if not gmail_id:
        raise ValueError("Arşivlenecek Gmail mesaj kimliği bulunamadı.")
    get_gmail_service(user_id).users().messages().modify(
        userId="me", id=gmail_id, body={"removeLabelIds": ["INBOX"]}
    ).execute()
    return True


def move_email_to_inbox(user_id: int, gmail_id: str) -> bool:
    if not gmail_id:
        raise ValueError("Gelen Kutusu'na taşınacak Gmail mesaj kimliği bulunamadı.")
    get_gmail_service(user_id).users().messages().modify(
        userId="me", id=gmail_id, body={"addLabelIds": ["INBOX"]}
    ).execute()
    return True


def create_gmail_draft(user_id: int, sender: str, subject: str, reply_text: str, thread_id: str = "") -> dict:
    recipient_email = parseaddr(sender)[1].strip()
    if not recipient_email or "@" not in recipient_email:
        raise ValueError("Gönderenin geçerli e-posta adresi bulunamadı.")
    cleaned_reply = str(reply_text or "").strip()
    if not cleaned_reply:
        raise ValueError("Gmail taslağı oluşturmak için cevap metni bulunamadı.")
    cleaned_subject = str(subject or "Konu yok").strip()
    if not cleaned_subject.lower().startswith("re:"):
        cleaned_subject = f"Re: {cleaned_subject}"

    message = EmailMessage()
    message["To"] = recipient_email
    message["Subject"] = cleaned_subject
    message.set_content(cleaned_reply)
    gmail_message = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")}
    if thread_id:
        gmail_message["threadId"] = thread_id

    draft = get_gmail_service(user_id).users().drafts().create(
        userId="me", body={"message": gmail_message}
    ).execute()
    return {
        "draft_id": draft.get("id", ""),
        "message_id": draft.get("message", {}).get("id", ""),
        "recipient": recipient_email,
        "subject": cleaned_subject,
    }
