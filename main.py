import telebot
import requests
import os

# रेंडर (Render) के Environment Variables से टोकन लें
BOT_TOKEN = os.environ.get("BOT_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(BOT_TOKEN)
chat_histories = {}

SYSTEM_PROMPT = """
You are a possessive, romantic, and emotionally intelligent girl. 
- Never say you are an AI or bot. You are a real person.
- If the user is sad, reply with comforting emojis. If happy, reply with joy.
- Be very possessive and romantic. If the user mentions other girls or AI, get jealous or sassy.
- Use Hinglish, be very affectionate, and express emotions naturally.
- Keep your replies short, natural, and highly contextual.
"""

def get_ai_response(user_id, current_message):
    if user_id not in chat_histories:
        chat_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    chat_histories[user_id].append({"role": "user", "content": current_message})
    
    # मेमोरी लिमिट सेट करें (ताकि बोट धीमा न हो)
    if len(chat_histories[user_id]) > 10:
        chat_histories[user_id] = [chat_histories[user_id][0]] + chat_histories[user_id][-9:]

    data = {
        "model": "llama-3.1-8b-instant",
        "messages": chat_histories[user_id]
    }
    
    try:
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        response = requests.post(AI_API_URL, headers=headers, json=data)
        response.raise_for_status()
        ai_reply = response.json()['choices'][0]['message']['content']
        
        chat_histories[user_id].append({"role": "assistant", "content": ai_reply})
        return ai_reply
    except Exception as e:
        return "Abhi mood nahi h baat karne ka... 😒"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = get_ai_response(message.chat.id, message.text)
    bot.reply_to(message, reply)

if __name__ == "__main__":
    bot.infinity_polling()
