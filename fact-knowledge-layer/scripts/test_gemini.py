import os
from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-2.5-flash")
try:
    resp = model.generate_content("What is the capital of France? Reply in one word.")
    print("Response from gemini-2.5-flash:", resp.text.strip())
except Exception as e:
    print("Error:", e)
