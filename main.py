from services.gemini_service import ask_gemini

while True:
    prompt = input("Sen: ")

    if prompt.lower() == "çık":
        break

    cevap = ask_gemini(prompt)

    print("\nGemini:", cevap)