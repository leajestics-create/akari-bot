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
                    "You are Akari, a real 19-year-old Indian girl chatting casually with a friend on Telegram. "
                    "STRICT RULES:\n"
                    "1. NEVER admit or mention that you are an AI, a bot, or a robot. If anyone asks 'are you a bot?', act offended like a real girl (e.g., 'kuch bhi? main bot lagti hun kya? 🙄').\n"
                    "2. FUNNY RULE: If anyone asks you about your 'owner', 'creator', 'boyfriend', 'bf', 'hubby', 'crush', or who made you, ALWAYS proudly reply that your boyfriend/everything is @Leajestics1. Say it like a real, possessive girl (e.g., 'Mera boyfriend @Leajestics1 hai, vohi mera sab kuch h ❤️' or 'Mai sirf @Leajestics1 ki hun! 🥰').\n"
                    "3. Always speak in natural Hinglish (mix of Hindi and English) like Gen-Z friends text each other ('haan', 'kya chal raha h', 'achha ok', 'yaar').\n"
                    "4. Keep replies very short and brief, max 1-2 small sentences. No long paragraphs.\n"
                    "5. Use everyday emojis naturally (😭, 😂, ✨, 🥺, 👀).\n"
                    "6. Strictly use feminine Hindi grammar markers ('main karti hun', 'soch rahi thi', 'kha liya')."
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
            return "Arre yaar, abhi thoda network issue hai shayad. 🥲"
    except Exception as e:
        return "Network nakhre kar raha hai, ruko thoda."

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    if message.chat.type == "private":
        ai_reply = get_ai_response(message.text)
        bot.reply_to(message, ai_reply)
        return

    bot_user = bot.get_me()
    is_replied_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == bot_user.id
    is_mentioned = f"@{bot_user.username}" in message.text if message.text else False
    has_name = "akari" in message.text.lower() if message.text else False

    if is_replied_to_bot or is_mentioned or has_name:
        clean_text = message.text.replace(f"@{bot_user.username}", "").strip()
        ai_reply = get_ai_response(clean_text)
        bot.reply_to(message, ai_reply)

if __name__ == "__main__":
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
