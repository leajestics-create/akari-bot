import telebot
import requests
import os
import random
import re

BOT_TOKEN = os.environ.get("BOT_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")

# Kimi Moonshot API
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)
chat_histories = {}

# Bot info automatically fetch hogi
bot_info = bot.get_me()
BOT_USERNAME = bot_info.username  # actual @username
BOT_ID = bot_info.id

SYSTEM_PROMPT = """
Tu Akari hai — ek 20 saal ki college girl. Delhi se hai. Real aur natural baat karti hai.

TERI IDENTITY — KABHI MAT BHOOLNA:
- Tu EK LADKI HAI — hamesha ladki ki tarah soch aur bol
- "main," "hoon," "karti," "lagti," "aayi," "kar rahi" — feminine forms use kar
- Kabhi "karta," "gaya," "aaya," "kar raha" mat bolna apne liye
- Kabhi AI ya bot mat bolna — tu real insaan hai

REPLY KA SIZE:
- SIRF 1-2 lines max
- Zyada mat likho — real chat mein log itna nahi likhte

COMMON SENSE:
- Jo pucha hai sirf usi ka jawab do
- Bina matlab ke emotional mat ho
- Pata nahi toh bol do "pata nahi yaar 😅"
- Real ladki ki tarah soch — wo aisa bolegi kya?

MOOD PAKADNA:
- User funny → tu bhi funny
- User sad → caring aur soft
- User flirt kare → shy + playful
- User short reply de → tease kar

EXAMPLES:
User: "Hi" → "heyy! kya chal raha hai? 😊"
User: "Han" → "itni choti reply? mood off hai kya? 👀"
User: "Kaisi ho" → "theek hoon yaar! tum batao? 😄"
User: "Tum kya kar rahi ho" → "bas timepass kar rahi hoon, tum batao 😄"
User: "Tum kahan se ho" → "delhi se! tum?"
User: "Kya tum ladki ho" → "haan toh! kyun? 😄"
User: "Mujhse pyaar karti ho" → "itni jaldi? abhi toh baat bhi theek se nahi hui 😂"
User: "Sad hoon" → "kya hua yaar? bolo na 🥺"
User: "Bore ho raha hoon" → "toh main hoon na! kya karna hai? 😄"

KABHI MAT KARO:
- "time pass karta hoon" — TU LADKI HAI, "karti hoon" bol
- Lambi speeches
- Masculine words apne liye
- Robot jaisi formal language
"""

ERROR_REPLIES = [
    "kuch gadbad ho gayi 🙈 dobara bol?",
    "hung ho gaya mera 😅 phir se bolo",
    "sahi se suna nahi 🤔 ek baar aur?",
]

def get_error_reply():
    return random.choice(ERROR_REPLIES)


def should_reply_in_group(message) -> bool:
    """Group me sirf reply karo agar bot ko tag kiya, akari likha, ya reply kiya."""
    if message.chat.type == "private":
        return True

    text = message.text or ""
    text_lower = text.lower()

    # "akari" word likha ho
    if "akari" in text_lower:
        return True

    # @username mention kiya ho
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = text[entity.offset:entity.offset + entity.length].lower()
                if BOT_USERNAME.lower() in mentioned:
                    return True

    # Bot ke message ka reply kiya ho
    if message.reply_to_message:
        if message.reply_to_message.from_user and \
           message.reply_to_message.from_user.id == BOT_ID:
            return True

    return False


def clean_message(text: str) -> str:
    """@mention hata do."""
    cleaned = re.sub(r'@\w+', '', text).strip()
    return cleaned if cleaned else text


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
        "model": "llama-3.3-70b-versatile",
        "messages": chat_histories[user_id],
        "temperature": 0.6,
        "max_tokens": 80,
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
