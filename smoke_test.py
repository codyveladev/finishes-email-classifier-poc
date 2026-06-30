from dotenv import load_dotenv; load_dotenv()
from google import genai
client = genai.Client()
print(client.models.generate_content(model="gemini-2.5-flash", contents="say ok").text)
