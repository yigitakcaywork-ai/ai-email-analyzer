import os

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from google.auth.transport.requests import (
    Request as GoogleRequest,
)
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from database import upsert_google_user


auth_bp = Blueprint(
    "auth",
    __name__,
)


IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def build_flow(
    state: str | None = None,
    code_verifier: str | None = None,
) -> Flow:
    """
    Google OAuth Flow nesnesini oluşturur.

    OAuth başlangıcında oluşturulan PKCE code_verifier,
    callback aşamasında aynı değerle tekrar kullanılır.
    """
    client_id = os.getenv(
        "GOOGLE_CLIENT_ID",
        "",
    ).strip()

    client_secret = os.getenv(
        "GOOGLE_CLIENT_SECRET",
        "",
    ).strip()

    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID veya "
            "GOOGLE_CLIENT_SECRET .env "
            "dosyasında bulunamadı."
        )

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": (
                "https://accounts.google.com/"
                "o/oauth2/v2/auth"
            ),
            "token_uri": (
                "https://oauth2.googleapis.com/token"
            ),
            "redirect_uris": [
                (
                    "http://127.0.0.1:5000/"
                    "oauth/callback"
                ),
                (
                    "http://localhost:5000/"
                    "oauth/callback"
                ),
            ],
        }
    }

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=IDENTITY_SCOPES,
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=(
            code_verifier is None
        ),
    )

    flow.redirect_uri = url_for(
        "auth.oauth_callback",
        _external=True,
    )

    return flow


@auth_bp.route("/login")
def login():
    """
    Kullanıcı giriş yaptıysa dashboard'a,
    yapmadıysa giriş ekranına yönlendirir.
    """
    if session.get("user_id"):
        return redirect(
            url_for("dashboard.home")
        )

    return render_template(
        "login.html"
    )


@auth_bp.route("/oauth/start")
def oauth_start():
    """
    Google OAuth giriş akışını başlatır.
    """
    # Yalnızca yerel geliştirmede HTTP kullanımına izin verir.
    # Yayın ortamında HTTPS kullanılacak.
    os.environ.setdefault(
        "OAUTHLIB_INSECURE_TRANSPORT",
        "1",
    )

    # Önceki yarım kalmış OAuth verilerini temizler.
    session.pop(
        "oauth_state",
        None,
    )

    session.pop(
        "oauth_code_verifier",
        None,
    )

    flow = build_flow()

    authorization_url, state = (
        flow.authorization_url(
            access_type="online",

            # Önceden verilmiş gmail.modify izninin
            # kimlik girişine eklenmesini engeller.
            include_granted_scopes="false",

            prompt="select_account",
        )
    )

    session["oauth_state"] = state

    # authorization_url oluşturulduktan sonra
    # PKCE code_verifier oluşmuş olur.
    session["oauth_code_verifier"] = (
        flow.code_verifier
    )

    return redirect(
        authorization_url
    )


@auth_bp.route("/oauth/callback")
def oauth_callback():
    """
    Google'dan dönen OAuth cevabını doğrular
    ve kullanıcı oturumunu başlatır.
    """
    os.environ.setdefault(
        "OAUTHLIB_INSECURE_TRANSPORT",
        "1",
    )

    returned_state = request.args.get(
        "state",
        "",
    )

    saved_state = session.get(
        "oauth_state",
        "",
    )

    saved_code_verifier = session.get(
        "oauth_code_verifier",
        "",
    )

    if (
        not saved_state
        or returned_state != saved_state
    ):
        clear_oauth_session()

        return render_template(
            "login.html",
            error=(
                "Google giriş doğrulaması başarısız "
                "oldu. Lütfen tekrar deneyin."
            ),
        ), 400

    if not saved_code_verifier:
        clear_oauth_session()

        return render_template(
            "login.html",
            error=(
                "Google giriş güvenlik bilgisi "
                "bulunamadı. Lütfen tekrar deneyin."
            ),
        ), 400

    if request.args.get("error"):
        clear_oauth_session()

        return render_template(
            "login.html",
            error=(
                "Google giriş izni verilmedi."
            ),
        ), 400

    try:
        flow = build_flow(
            state=saved_state,
            code_verifier=(
                saved_code_verifier
            ),
        )

        flow.fetch_token(
            authorization_response=request.url
        )

        credentials = flow.credentials

        if not credentials.id_token:
            raise RuntimeError(
                "Google kimlik jetonu döndürmedi."
            )

        token_data = (
            id_token.verify_oauth2_token(
                credentials.id_token,
                GoogleRequest(),
                os.getenv(
                    "GOOGLE_CLIENT_ID"
                ),

                # Bilgisayar ile Google sunucusu arasında
                # birkaç saniyelik saat farkını tolere eder.
                clock_skew_in_seconds=10,
            )
        )

        google_sub = str(
            token_data.get(
                "sub",
                "",
            )
        ).strip()

        email = str(
            token_data.get(
                "email",
                "",
            )
        ).strip().lower()

        display_name = str(
            token_data.get(
                "name",
                "",
            )
        ).strip()

        profile_picture = str(
            token_data.get(
                "picture",
                "",
            )
        ).strip()

        email_verified = bool(
            token_data.get(
                "email_verified",
                False,
            )
        )

        if not google_sub or not email:
            raise RuntimeError(
                "Google hesap bilgileri "
                "eksik döndü."
            )

        if not email_verified:
            raise RuntimeError(
                "Google e-posta adresi "
                "doğrulanmamış."
            )

        user = upsert_google_user(
            google_sub=google_sub,
            email=email,
            display_name=display_name,
            profile_picture=profile_picture,
        )

        # OAuth geçici bilgileri ve eski oturumu temizler.
        session.clear()

        session["user_id"] = user["id"]

        session["user"] = {
            "id": user["id"],
            "email": user["email"],
            "display_name": (
                user["display_name"]
            ),
            "profile_picture": (
                user["profile_picture"]
            ),
        }

        return redirect(
            url_for("dashboard.home")
        )

    except Exception as error:
        clear_oauth_session()

        return render_template(
            "login.html",
            error=(
                "Google ile giriş "
                f"tamamlanamadı: {error}"
            ),
        ), 500


@auth_bp.route("/logout")
def logout():
    """
    Kullanıcı oturumunu sonlandırır.
    """
    session.clear()

    return redirect(
        url_for("auth.login")
    )


def clear_oauth_session():
    """
    Yarım kalmış OAuth giriş bilgilerini temizler.
    """
    session.pop(
        "oauth_state",
        None,
    )

    session.pop(
        "oauth_code_verifier",
        None,
    )