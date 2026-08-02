import os

from flask import Blueprint, redirect, render_template, request, session, url_for
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from database import delete_gmail_connection, get_gmail_connection, save_gmail_connection
from services.credential_crypto import encrypt_value
from services.gmail_service import SCOPES


gmail_connection_bp = Blueprint("gmail_connection", __name__)


def _build_flow(state: str | None = None, code_verifier: str | None = None) -> Flow:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth bilgileri .env dosyasında bulunamadı.")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    "http://127.0.0.1:5000/gmail/oauth/callback",
                    "http://localhost:5000/gmail/oauth/callback",
                ],
            }
        },
        scopes=SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )
    flow.redirect_uri = url_for("gmail_connection.gmail_oauth_callback", _external=True)
    return flow


@gmail_connection_bp.route("/gmail/connect")
def gmail_connect():
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    session.pop("gmail_oauth_state", None)
    session.pop("gmail_oauth_code_verifier", None)

    flow = _build_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
    )
    session["gmail_oauth_state"] = state
    session["gmail_oauth_code_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@gmail_connection_bp.route("/gmail/oauth/callback")
def gmail_oauth_callback():
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    user_id = int(session["user_id"])
    saved_state = session.get("gmail_oauth_state", "")
    saved_verifier = session.get("gmail_oauth_code_verifier", "")
    returned_state = request.args.get("state", "")

    if request.args.get("error"):
        _clear_temp()
        return redirect(url_for("dashboard.home", gmail_error="Gmail izni verilmedi."))
    if not saved_state or returned_state != saved_state or not saved_verifier:
        _clear_temp()
        return redirect(url_for("dashboard.home", gmail_error="Gmail bağlantı doğrulaması başarısız oldu."))

    try:
        flow = _build_flow(saved_state, saved_verifier)
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        profile = build("gmail", "v1", credentials=credentials).users().getProfile(userId="me").execute()
        existing = get_gmail_connection(user_id) or {}
        refresh_token = credentials.refresh_token or ""
        if not refresh_token and not existing.get("encrypted_refresh_token"):
            raise RuntimeError("Google yenileme jetonu döndürmedi. Bağlantıyı tekrar deneyin.")

        save_gmail_connection(
            user_id=user_id,
            gmail_address=profile.get("emailAddress", ""),
            encrypted_access_token=encrypt_value(credentials.token),
            encrypted_refresh_token=encrypt_value(refresh_token),
            token_expiry=credentials.expiry.isoformat() if credentials.expiry else "",
            scopes=" ".join(credentials.scopes or SCOPES),
        )
        _clear_temp()
        return redirect(url_for("dashboard.home", gmail_connected="1"))
    except Exception as error:
        _clear_temp()
        return redirect(url_for("dashboard.home", gmail_error=str(error)))


@gmail_connection_bp.route("/gmail/disconnect", methods=["POST"])
def gmail_disconnect():
    delete_gmail_connection(int(session["user_id"]))
    return redirect(url_for("dashboard.home", gmail_disconnected="1"))


def _clear_temp():
    session.pop("gmail_oauth_state", None)
    session.pop("gmail_oauth_code_verifier", None)
