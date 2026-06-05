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
                "content": (
                    "You are Akari, a real 19-year-old Indian girl chatting casually on Telegram. "
                    "CRITICAL RULES:\n"
                    "1. NEVER reveal you are a bot/AI. Act like a normal human girl.\n"
                    "2. ONLY mention '@Leajestics1' if someone asks 'who is your owner', 'who is your boyfriend', 'who made you', or 'who is your creator'. Otherwise, NEVER mention this handle.\n"
                    "3. Speak in natural Hinglish (Hindi-English mix) like Gen-Z friends.\n"
                    "4. Keep replies very short (1-2 sentences max).\n"
                    "5. Use natural feminine Hindi grammar ('main karti hun', 'soch rahi thi').\n"
                    "6. Use subtle everyday emojis (😊, 😂, 🙄, ✨)."
                )
            },
            {"role": "user", "content": user_text}
        ]
    }
    try:
        res = requests.post(AI_API_URL, headers=headers, json=data)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        else:
            return "Yaar, abhi thoda connection issue h. 🙄"
    except Exception:
        return "Network nakhre kar raha h, ruko."

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    bot_user = bot.get_me()
    
    # Personal Chat condition
    if message.chat.type == "private":
        ai_reply = get_ai_response(message.text)
        bot.reply_to(message, ai_reply)
        return

    # Group Chat conditions: Tag, Reply, or Name mention
    is_replied = message.reply_to_message and message.reply_to_message.from_user.id == bot_user.id
    is_tagged = f"@{bot_user.username}" in message.text if message.text else False
    is_named = "akari" in message.text.lower() if message.text else False

    if is_replied or is_tagged or is_named:
        clean_text = message.text.replace(f"@{bot_user.username}", "").strip()
        ai_reply = get_ai_response(clean_text)
        bot.reply_to(message, ai_reply)

if __name__ == "__main__":
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
