from services.gmail_service import get_recent_emails
from services.gemini_service import analyze_email


def main():
    print("📥 Son e-postalar alınıyor...\n")

    emails = get_recent_emails(5)

    if not emails:
        print("Gelen kutusunda e-posta bulunamadı.")
        return

    for index, email in enumerate(emails, start=1):
        print("=" * 60)
        print(f"📧 E-posta {index}")
        print(f"Kimden: {email['from']}")
        print(f"Konu: {email['subject']}")
        print("\n🤖 AI analizi hazırlanıyor...\n")

        try:
            analysis = analyze_email(email)
            print(analysis)
        except Exception as error:
            print(f"Analiz sırasında hata oluştu: {error}")

        print()


if __name__ == "__main__":
    main()