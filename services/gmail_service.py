import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json",
            SCOPES,
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build(
        "gmail",
        "v1",
        credentials=creds,
    )


def get_recent_emails(
    max_results: int = 10,
    after_unix_seconds: int | None = None,
):
    service = get_gmail_service()

    list_parameters = {
        "userId": "me",
        "maxResults": max_results,
        "labelIds": ["INBOX"],
    }

    if after_unix_seconds is not None:
        list_parameters["q"] = f"after:{int(after_unix_seconds)}"

    result = (
        service.users()
        .messages()
        .list(**list_parameters)
        .execute()
    )

    messages = result.get("messages", [])
    emails = []

    for message in messages:
        email_data = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject",
                    "Date",
                ],
            )
            .execute()
        )

        headers = (
            email_data
            .get("payload", {})
            .get("headers", [])
        )

        header_map = {
            header["name"]: header["value"]
            for header in headers
        }

        emails.append(
            {
                "gmail_id": email_data.get("id", message["id"]),
                "thread_id": email_data.get("threadId", ""),
                "internal_date": int(
                    email_data.get("internalDate", 0)
                ),
                "from": header_map.get("From", "Bilinmiyor"),
                "subject": header_map.get("Subject", "Konu yok"),
                "date": header_map.get("Date", "Tarih yok"),
                "snippet": email_data.get("snippet", ""),
            }
        )

    emails.sort(
        key=lambda email: email["internal_date"],
        reverse=True,
    )

    return emails


def archive_email(gmail_id: str) -> bool:
    """
    Gmail mesajından INBOX etiketini kaldırır.
    Mesaj silinmez ve Tüm Postalar bölümünde kalır.
    """
    if not gmail_id:
        raise ValueError(
            "Arşivlenecek Gmail mesaj kimliği bulunamadı."
        )

    service = get_gmail_service()

    service.users().messages().modify(
        userId="me",
        id=gmail_id,
        body={
            "removeLabelIds": ["INBOX"],
        },
    ).execute()

    return True


def move_email_to_inbox(gmail_id: str) -> bool:
    """
    Gmail mesajına INBOX etiketini yeniden ekler.
    Arşivlenmiş mesajı Gelen Kutusu'na geri taşır.
    """
    if not gmail_id:
        raise ValueError(
            "Gelen Kutusu'na taşınacak Gmail mesaj kimliği bulunamadı."
        )

    service = get_gmail_service()

    service.users().messages().modify(
        userId="me",
        id=gmail_id,
        body={
            "addLabelIds": ["INBOX"],
        },
    ).execute()

    return True
