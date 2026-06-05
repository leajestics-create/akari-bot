import telebot
import requests

# ================= CONFIGURATION =================
BOT_TOKEN = "8820701067:AAE2-Y-iEFd6XdNYgnRG16SQTbs5gu1mLMs"
AI_API_KEY = "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"

AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)
# =================================================

def get_ai_response(user_text):
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system", 
                "content": "You are Akari, a helpful, friendly, and extremely fast Indian AI assistant inside Telegram. Reply shortly in Hinglish and use emojis."
            },
            {"role": "user", "content": user_text}
        ]
    }
    try:
        res = requests.post(AI_API_URL, headers=headers, json=data)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        else:
            return "Sorry, abhi server thoda busy hai."
    except Exception as e:
        return "Network issue hai, thoda ruko."

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_text = message.text
    ai_reply = get_ai_response(user_text)
    bot.reply_to(message, ai_reply)

if __name__ == "__main__":
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
