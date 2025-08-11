# test_openai.py -- новая версия
import os
from dotenv import load_dotenv
from openai import OpenAI           # <‑‑ новый импорт

load_dotenv()                       # читаем .env
client = OpenAI()                   # в нём уже есть api_key из переменной среды

resp = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Привет!"}],
    timeout=10
)
print(resp.choices[0].message.content)
