import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-2.5-flash")

while True:
    prompt = input("Sen: ")

    if prompt.lower() == "çık":
        break

    response = model.generate_content(prompt)

    print("\nGemini:", response.text)