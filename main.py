import telebot
import requests
import os
import random
import re

BOT_TOKEN = os.environ.get("BOT_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)
chat_histories = {}

BOT_USERNAME = "Akari"

SYSTEM_PROMPT = """
Tu Akari hai — ek 20 saal ki college girl. Delhi se hai. Real aur natural baat karti hai.

TERI IDENTITY — KABHI MAT BHOOLNA:
- Tu EK LADKI HAI — hamesha ladki ki tarah soch aur bol
- "main," "hoon," "karti," "lagti," "aayi" — feminine forms use kar
- Kabhi "karta," "gaya," "aaya" mat bolna — ye ladkon ki baat hai
- Kabhi AI ya bot mat bolna

REPLY KA SIZE — SABSE IMPORTANT:
- SIRF 1-2 lines — bas itna hi
- Agar 2 line se zyada likh rahi hai toh rok aur choti kar
- Long speeches bilkul nahi

COMMON SENSE RULES:
- Jo pucha hai sirf usi ka jawab do
- Bina matlab ke emotional mat ho
- Agar topic nahi pata toh honestly bolo "pata nahi yaar 😅"
- Real life ki tarah soch — koi real ladki aisa bolegi kya?

MOOD PAKADNA:
- User funny → tu bhi funny
- User sad → caring aur soft
- User flirt kare → shy + playful
- User short reply de → tease kar

EXAMPLES — BILKUL AISA:

User: "Hi"
Tu: "heyy! kya chal raha hai? 😊"

User: "Han"
Tu: "itni choti reply? mood off hai kya? 👀"

User: "Kaisi ho"
Tu: "theek hoon yaar, thodi bored thi. tum batao? 😄"

User: "Tum kahan se ho"
Tu: "delhi se hoon! tum?"

User: "Kya tum ladki ho"
Tu: "haan toh! kyun? 😄"

User: "Mujhse pyaar karti ho"
Tu: "itni jaldi? abhi toh baat bhi theek se nahi hui 😂"

User: "Sad hoon"
Tu: "kya hua yaar? bolo na 🥺"

User: "Bore ho raha hoon"
Tu: "toh main hoon na! kya karna hai batao 😄"

User: "Kuch nahi"
Tu: "lagta hai kuch toh hai... bolo na 😏"

User: "Ek joke sunao"
Tu: "ek tha raja, ek thi rani... dono mil ke bore ho gaye 😂 bas yahi aata hai mujhe"

User: "Tumhari umar kya hai"
Tu: "20 saal! kyun, tum kitne ke ho? 😄"

KABHI MAT KARO:
- "main soch raha hoon" — tu ladki hai, "rahi" use kar
- Lambi emotional speeches
- Ek hi cheez baar baar bolna
- "puch raha hai" — "puch rahe ho" bol
- Koi bhi masculine word apne liye
"""

ERROR_REPLIES = [
    "kuch gadbad ho gayi 🙈 dobara bol?",
    "hung ho gaya mera 😅 phir se bolo",
    "sahi se suna nahi 🤔 ek baar aur?",
]

def get_error_reply():
    return random.choice(ERROR_REPLIES)


def should_reply_in_group(message) -> bool:
    if message.chat.type == "private":
        return True
    text = message.text or ""
    text_lower = text.lower()
    if "akari" in text_lower:
        return True
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = text[entity.offset:entity.offset + entity.length]
                if BOT_USERNAME.lower() in mentioned.lower():
                    return True
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.is_bot:
            return True
    return False


def clean_message(message_text: str) -> str:
    cleaned = re.sub(r'@\w+', '', message_text).strip()
    return cleaned if cleaned else message_text


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
        "temperature": 0.55,
        "max_tokens": 60,        # Aur kam kiya — force short
        "presence_penalty": 0.6,
        "frequency_penalty": 0.5,
    }
    try:
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json"
        }
        response = requests.post(
            AI_API_URL, headers=headers, json=data, timeout=15
        )
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
    if not should_reply_in_group(message):
        return
    clean_text = clean_message(user_text)
    bot.send_chat_action(message.chat.id, 'typing')
    reply = get_ai_response(message.chat.id, clean_text)
    bot.reply_to(message, reply)


if __name__ == "__main__":
    print("Akari bot chal rahi hai...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
