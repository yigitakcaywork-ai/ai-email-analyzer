import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

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

    return build("gmail", "v1", credentials=creds)


def get_recent_emails(max_results: int = 5):
    service = get_gmail_service()

    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            maxResults=max_results,
            labelIds=["INBOX"],
        )
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
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )

        headers = email_data.get("payload", {}).get("headers", [])
        header_map = {
            header["name"]: header["value"]
            for header in headers
        }

        emails.append(
            {
                "from": header_map.get("From", "Bilinmiyor"),
                "subject": header_map.get("Subject", "Konu yok"),
                "date": header_map.get("Date", "Tarih yok"),
                "snippet": email_data.get("snippet", ""),
            }
        )

    return emails