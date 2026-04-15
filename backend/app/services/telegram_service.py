import requests
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    requests.post(url, data=payload)
    
LAST_CHAT_ID = None

def handle_message(message):
    global LAST_CHAT_ID

    chat_id = message["chat"]["id"]
    LAST_CHAT_ID = chat_id

    print(f"✅ SAVED CHAT_ID: {chat_id}", flush=True)

    text = message.get("text", "").lower()

    if any(word in text for word in ["привет", "hello", "hi"]):
        send_message(chat_id, "Привет! Я AI ассистент Tele Scope 🚀")
        send_message(chat_id, "🚀 бот запущен")
        return