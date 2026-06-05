import telebot
import requests

# Bot Configuration
BOT_TOKEN = "8820701067:AAGokSWQGajNT4r256jNtmSUVSFpnnMjtEM"
AI_API_KEY = "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"
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)

# Akari Personality
SYSTEM_PROMPT = """
You are Akari, a 19-year-old Indian girl. You are a real person, not an AI. 
Rules:
- Be sassy, friendly, and use Hinglish.
- If asked about your owner/boyfriend, only say: "@Leajestics1 hai ❤️".
- Never repeat user's message.
- Keep replies natural, short, and use emojis like a teenager.
- NEVER mention you are an AI or bot.
"""

def get_ai_response(text):
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    }
    try:
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        response = requests.post(AI_API_URL, headers=headers, json=data)
        return response.json()['choices'][0]['message']['content']
    except Exception:
        return "Abhi mood nahi h baat karne ka. 🙄"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = get_ai_response(message.text)
    bot.reply_to(message, reply)

bot.()
