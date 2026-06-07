import telebot
import requests
import os
import random
import re
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DB_PATH = "kingdom_wars.db"

bot = telebot.TeleBot(BOT_TOKEN)
chat_histories = {}

bot_info = bot.get_me()
BOT_USERNAME = bot_info.username
BOT_ID = bot_info.id

# ══════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            kingdom TEXT DEFAULT NULL,
            kingdom_locked INTEGER DEFAULT 0,
            gold INTEGER DEFAULT 1000,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            battles INTEGER DEFAULT 0,
            current_streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily TEXT DEFAULT NULL,
            protection_until TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS kingdom_stats (
            kingdom TEXT PRIMARY KEY,
            member_count INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0
        )
    """)
    for k in ["crimson", "azure", "emerald", "shadow", "solar"]:
        c.execute("INSERT OR IGNORE INTO kingdom_stats (kingdom) VALUES (?)", (k,))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(user_id, username, display_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, username, display_name)
        VALUES (?, ?, ?)
    """, (user_id, username, display_name))
    conn.commit()
    conn.close()
    return get_user(user_id)

def get_or_create_user(user_id, username, display_name):
    user = get_user(user_id)
    if not user:
        user = create_user(user_id, username, display_name)
    return user

def set_kingdom(user_id, kingdom):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE users SET kingdom = ?, kingdom_locked = 1
        WHERE user_id = ?
    """, (kingdom, user_id))
    c.execute("""
        UPDATE kingdom_stats SET member_count = member_count + 1
        WHERE kingdom = ?
    """, (kingdom,))
    conn.commit()
    conn.close()

def get_smallest_kingdom():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT kingdom FROM kingdom_stats ORDER BY member_count ASC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else "solar"

def get_kingdom_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM kingdom_stats ORDER BY member_count DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ══════════════════════════════════════════════════════════
#  KINGDOMS DATA
# ══════════════════════════════════════════════════════════

KINGDOMS = {
    "crimson": {"name": "Crimson", "emoji": "🔴", "desc": "Aggressive warriors. First Strike + Berserker Rage."},
    "azure":   {"name": "Azure",   "emoji": "🔵", "desc": "Strategic commanders. Command + Arcane Blast."},
    "emerald": {"name": "Emerald", "emoji": "🟢", "desc": "Defensive fortress. Shield Wall + Healing Light."},
    "shadow":  {"name": "Shadow",  "emoji": "🟣", "desc": "Tactical assassins. Stealth + Counter Attack."},
    "solar":   {"name": "Solar",   "emoji": "🟡", "desc": "Economy empire. +10% Gold & better drops."},
}

def kingdom_badge(kingdom):
    if not kingdom:
        return "⚔️ Mercenary"
    k = KINGDOMS.get(kingdom)
    return f"{k['emoji']} {k['name']}" if k else "⚔️ Mercenary"

# ══════════════════════════════════════════════════════════
#  GAME COMMANDS
# ══════════════════════════════════════════════════════════

GAME_COMMANDS = ["/start", "/kingdom", "/profile", "/help", "/adminstats"]

def is_game_command(text):
    if not text:
        return False
    for cmd in GAME_COMMANDS:
        if text.startswith(cmd):
            return True
    return False

def get_display(tg_user):
    name = tg_user.first_name or ""
    if tg_user.last_name:
        name += f" {tg_user.last_name}"
    return name.strip() or tg_user.username or str(tg_user.id)

# ── /start ─────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if db_user.get("kingdom"):
        k = kingdom_badge(db_user["kingdom"])
        bot.reply_to(message,
            f"⚔️ Welcome back, {display}!\n"
            f"🏰 Kingdom: {k}\n\n"
            f"Use /profile to see your stats.\n"
            f"Use /help for all commands."
        )
    else:
        bot.reply_to(message,
            f"🏰 Welcome to Kingdom Wars!\n\n"
            f"Greetings, {display}!\n"
            f"You have been granted 1,000 Gold.\n\n"
            f"Choose your kingdom with /kingdom\n"
            f"⚠️ Kingdom choice is permanent!"
        )

# ── /kingdom ───────────────────────────────────────────────
@bot.message_handler(commands=["kingdom"])
def cmd_kingdom(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if db_user.get("kingdom_locked"):
        k = kingdom_badge(db_user["kingdom"])
        bot.reply_to(message,
            f"🔒 Already pledged to {k}\n"
            f"Kingdom loyalty cannot be changed."
        )
        return

    smallest = get_smallest_kingdom()
    text = "🏰 Choose Your Kingdom\n\n"
    for key, data in KINGDOMS.items():
        extra = ""
        if key == "solar":
            extra = " | +10% Gold"
        if key == smallest:
            extra += " 🎯 +15% Daily"
        text += f"{data['emoji']} {data['name']}{extra}\n{data['desc']}\n\n"
    text += "Reply with kingdom name:\ncrimson / azure / emerald / shadow / solar"
    bot.reply_to(message, text)

# ── Kingdom selection reply ────────────────────────────────
@bot.message_handler(func=lambda m: m.text and m.text.lower().strip() in KINGDOMS)
def select_kingdom(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if db_user.get("kingdom_locked"):
        return

    kingdom_key = message.text.lower().strip()
    set_kingdom(user.id, kingdom_key)

    k_data = KINGDOMS[kingdom_key]
    smallest = get_smallest_kingdom()
    bonus = ""
    if kingdom_key == "solar":
        bonus = "\n🌟 Bonus: +10% Gold | +10% Drop Rate"
    if kingdom_key == smallest:
        bonus += "\n🎯 Bonus: +15% Daily (Lowest Population)"

    bot.reply_to(message,
        f"⚔️ Kingdom Pledged!\n\n"
        f"You joined {k_data['emoji']} {k_data['name']}!\n"
        f"{k_data['desc']}{bonus}\n\n"
        f"Your journey begins now!\n"
        f"Use /profile to see your stats."
    )

# ── /profile ───────────────────────────────────────────────
@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message,
            "⚠️ No kingdom yet!\nUse /kingdom to pledge loyalty."
        )
        return

    k = kingdom_badge(db_user["kingdom"])
    battles = db_user["battles"]
    win_rate = round((db_user["wins"] / battles) * 100) if battles > 0 else 0

    text = (
        f"👤 {db_user['display_name']}\n"
        f"🏰 {k}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⭐ Level: {db_user['level']}\n"
        f"💰 Gold: {db_user['gold']:,}\n"
        f"✨ XP: {db_user['xp']:,}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚔️ Wins: {db_user['wins']}\n"
        f"💀 Losses: {db_user['losses']}\n"
        f"🎯 Win Rate: {win_rate}%\n"
        f"🔥 Streak: {db_user['current_streak']}\n"
        f"🏆 Best: {db_user['best_streak']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 Daily Streak: {db_user['daily_streak']} days"
    )
    bot.reply_to(message, text)

# ── /help ──────────────────────────────────────────────────
@bot.message_handler(commands=["help"])
def cmd_help(message):
    text = (
        "⚔️ Kingdom Wars Commands\n\n"
        "🏰 Setup\n"
        "/start — Register\n"
        "/kingdom — Choose kingdom\n"
        "/profile — Your stats\n\n"
        "💰 Economy (Coming Soon)\n"
        "/daily — Daily gold\n"
        "/rob — Rob a player\n"
        "/protect — Buy protection\n\n"
        "⚔️ Battle (Coming Soon)\n"
        "/battle — Start war\n"
        "/join — Join battle\n"
        "/draft — Pick cards\n\n"
        "🏆 Rankings (Coming Soon)\n"
        "/leaderboard — Top players"
    )
    bot.reply_to(message, text)

# ── /adminstats ────────────────────────────────────────────
@bot.message_handler(commands=["adminstats"])
def cmd_adminstats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE kingdom IS NULL")
    no_kingdom = c.fetchone()[0]
    c.execute("SELECT SUM(gold), AVG(gold) FROM users")
    gold_row = c.fetchone()
    conn.close()

    kingdom_data = get_kingdom_stats()
    k_lines = ""
    for k in kingdom_data:
        kname = KINGDOMS.get(k["kingdom"], {})
        emoji = kname.get("emoji", "⚔️")
        k_lines += f"{emoji} {k['kingdom'].capitalize()}: {k['member_count']} players\n"

    text = (
        f"🛡️ Admin Dashboard\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Total Users: {total}\n"
        f"❓ No Kingdom: {no_kingdom}\n\n"
        f"🏰 Kingdoms\n{k_lines}\n"
        f"💰 Economy\n"
        f"Total Gold: {int(gold_row[0] or 0):,}\n"
        f"Avg Gold: {int(gold_row[1] or 0):,}"
    )
    bot.reply_to(message, text)

# ══════════════════════════════════════════════════════════
#  AKARI AI CHATBOT
# ══════════════════════════════════════════════════════════

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
User: "Kya tum ladki ho" → "haan toh! kyun? 😄"
User: "Sad hoon" → "kya hua yaar? bolo na 🥺"

KABHI MAT KARO:
- Masculine words apne liye
- Lambi speeches
- Robot jaisi language
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
                mentioned = text[entity.offset:entity.offset + entity.length].lower()
                if BOT_USERNAME.lower() in mentioned:
                    return True
    if message.reply_to_message:
        if message.reply_to_message.from_user and \
           message.reply_to_message.from_user.id == BOT_ID:
            return True
    return False

def clean_message(text: str) -> str:
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
        "presence_penalty": 0.5,
        "frequency_penalty": 0.4,
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

# ── Main message handler — AI chatbot ─────────────────────
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not message.text:
        return
    user_text = message.text.strip()
    if not user_text:
        return
    # Game commands alag handle ho chuke hain upar
    if is_game_command(user_text):
        return
    # Group check
    if not should_reply_in_group(message):
        return
    clean_text = clean_message(user_text)
    bot.send_chat_action(message.chat.id, 'typing')
    reply = get_ai_response(message.chat.id, clean_text)
    bot.reply_to(message, reply)

# ══════════════════════════════════════════════════════════
#  RENDER HEALTH SERVER
# ══════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kingdom Wars + Akari Bot Running!")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ══════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    print("Kingdom Wars + Akari bot chal rahi hai...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
