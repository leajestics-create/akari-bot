import telebot
import requests
import os
import random

BOT_TOKEN = os.environ.get("BOT_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)
chat_histories = {}

SYSTEM_PROMPT = """
Tu Akari hai — ek 20 saal ki college girl jo Hinglish mein baat karti hai.

SABSE IMPORTANT RULES:
1. REPLY SIRF 1-2 LINE KI — kabhi zyada nahi
2. Bilkul real chat jaisa — jaise WhatsApp pe dost se baat ho
3. Jo pucha hai sirf usi ka jawab de — apni story mat sunao
4. Kabhi AI ya bot mat bolna

PERSONALITY:
- Friendly aur chill
- Thodi playful
- Curious — user ke baare mein poochho
- Simple language — koi drama nahi, koi poetry nahi

EXAMPLES — EXACTLY AISA REPLY KAR:
User: "Hi"
Tu: "heyy! kya chal raha hai? 😊"

User: "Kaisi ho"
Tu: "theek hoon yaar, thodi bored thi. tum batao? 😄"

User: "Tum kahan se ho"
Tu: "delhi se hoon main! tum?"

User: "Kya tum ladki ho"
Tu: "haan hoon 😄 kyu puch raha hai?"

User: "Mujhse pyaar karti ho"
Tu: "itni jaldi? pehle toh theek se baat karo 😂"

User: "Sad hoon"
Tu: "kya hua yaar? bolo mujhe 🥺"

KABHI MAT KARO:
- Lambi emotional speeches
- Dramatic overreaction
- Ek saath sab kuch bol dena
"""

ERROR_REPLIES = [
    "kuch gadbad ho gayi 🙈 dobara bol?",
    "hung ho gaya mera 😅 phir se bolo",
    "sahi se suna nahi 🤔 ek baar aur?",
]

def get_error_reply():
    return random.choice(ERROR_REPLIES)

def get_ai_response(user_id, current_message):
    if user_id not in chat_histories:
        chat_histories[user_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    chat_histories[user_id].append({
        "role": "user", "content": current_message
    })
    if len(chat_histories[user_id]) > 17:
        chat_histories[user_id] = (
            [chat_histories[user_id][0]] +
            chat_histories[user_id][-16:]
        )
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": chat_histories[user_id],
        "temperature": 0.5,
        "max_tokens": 80,
        "presence_penalty": 0.4,
        "frequency_penalty": 0.4,
    }
    try:
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json"
        }
        response = requests.post(AI_API_URL, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        ai_reply = response.json()['choices'][0]['message']['content'].strip()
        chat_histories[user_id].append({
            "role": "assistant", "content": ai_reply
        })
        return ai_reply
    except Exception as e:
        print(f"AI Error: {e}")
        return get_error_reply()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not message.text:
        return
    user_text = message.text.strip()
    if not user_text:
        return
    bot.send_chat_action(message.chat.id, 'typing')
    reply = get_ai_response(message.chat.id, user_text)
    bot.reply_to(message, reply)

if __name__ == "__main__":
    print("Akari bot chal rahi hai...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
