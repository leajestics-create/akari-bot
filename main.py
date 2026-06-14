import telebot
import requests
import os
import random
import re
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

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
            total_losses INTEGER DEFAULT 0,
            treasury INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount INTEGER,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS battles (
            battle_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            team1_kingdom TEXT,
            team2_kingdom TEXT,
            wager INTEGER,
            status TEXT DEFAULT 'waiting',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT DEFAULT NULL,
            winner_kingdom TEXT DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS battle_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER,
            user_id INTEGER,
            team INTEGER,
            joined_at TEXT DEFAULT (datetime('now')),
            UNIQUE(battle_id, user_id)
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
    c.execute("INSERT OR IGNORE INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
              (user_id, username, display_name))
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
    c.execute("UPDATE users SET kingdom = ?, kingdom_locked = 1 WHERE user_id = ?", (kingdom, user_id))
    c.execute("UPDATE kingdom_stats SET member_count = member_count + 1 WHERE kingdom = ?", (kingdom,))
    conn.commit()
    conn.close()

def update_gold(user_id, amount, desc=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold + ? WHERE user_id = ?", (amount, user_id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
              (user_id, "credit" if amount > 0 else "debit", abs(amount), desc))
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

def get_top_players(limit=10):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY gold DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Battle DB functions ────────────────────────────────────
def create_battle(chat_id, team1, team2, wager, created_by):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO battles (chat_id, team1_kingdom, team2_kingdom, wager, created_by)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, team1, team2, wager, created_by))
    battle_id = c.lastrowid
    conn.commit()
    conn.close()
    return battle_id

def get_active_battle(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM battles
        WHERE chat_id = ? AND status = 'waiting'
        ORDER BY created_at DESC LIMIT 1
    """, (chat_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_battle(battle_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM battles WHERE battle_id = ?", (battle_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def join_battle(battle_id, user_id, team):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO battle_players (battle_id, user_id, team)
            VALUES (?, ?, ?)
        """, (battle_id, user_id, team))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_battle_players(battle_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT bp.*, u.display_name, u.kingdom, u.username
        FROM battle_players bp
        JOIN users u ON bp.user_id = u.user_id
        WHERE bp.battle_id = ?
    """, (battle_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_team_players(battle_id, team):
    players = get_battle_players(battle_id)
    return [p for p in players if p["team"] == team]

def remove_player_from_battle(battle_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM battle_players WHERE battle_id = ? AND user_id = ?",
              (battle_id, user_id))
    conn.commit()
    conn.close()

def update_battle_status(battle_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE battles SET status = ? WHERE battle_id = ?", (status, battle_id))
    conn.commit()
    conn.close()

# Active battle timers
battle_timers = {}

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

KINGDOM_ALIASES = {
    "red": "crimson", "crimson": "crimson",
    "blue": "azure", "azure": "azure",
    "green": "emerald", "emerald": "emerald",
    "purple": "shadow", "shadow": "shadow",
    "yellow": "solar", "solar": "solar",
}

DAILY_REWARDS = {1: 500, 2: 600, 3: 700, 4: 800, 5: 900, 6: 1000, 7: 1500}
ROB_SUCCESS_RATE = 0.35
BEGINNER_PROTECTION_LEVEL = 5
MAX_TEAM_SIZE = 5
LOBBY_DURATION = 120  # 2 minutes

def kingdom_badge(kingdom):
    if not kingdom:
        return "⚔️ Mercenary"
    k = KINGDOMS.get(kingdom)
    return f"{k['emoji']} {k['name']}" if k else "⚔️ Mercenary"

def get_display(tg_user):
    name = tg_user.first_name or ""
    if tg_user.last_name:
        name += f" {tg_user.last_name}"
    return name.strip() or tg_user.username or str(tg_user.id)

# ══════════════════════════════════════════════════════════
#  PHASE 1 — PROFILE
# ══════════════════════════════════════════════════════════

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
            f"/profile — Your stats\n"
            f"/daily — Claim gold\n"
            f"/help — All commands"
        )
    else:
        bot.reply_to(message,
            f"🏰 Welcome to Kingdom Wars!\n\n"
            f"Greetings, {display}!\n"
            f"💰 Starting Gold: 1,000\n\n"
            f"Use /kingdom to choose your side!\n"
            f"⚠️ Choice is permanent!"
        )

@bot.message_handler(commands=["kingdom"])
def cmd_kingdom(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)
    if db_user.get("kingdom_locked"):
        k = kingdom_badge(db_user["kingdom"])
        bot.reply_to(message, f"🔒 Already pledged to {k}\nCannot change kingdom.")
        return
    smallest = get_smallest_kingdom()
    text = "🏰 Choose Your Kingdom\n\n"
    for key, data in KINGDOMS.items():
        extra = ""
        if key == "solar":
            extra = " | +10% Gold"
        if key == smallest:
            extra += " 🎯+15% Daily"
        text += f"{data['emoji']} {data['name']}{extra}\n{data['desc']}\n\n"
    text += "Reply: crimson / azure / emerald / shadow / solar"
    bot.reply_to(message, text)

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)
    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ No kingdom yet!\nUse /kingdom first.")
        return
    k = kingdom_badge(db_user["kingdom"])
    battles = db_user["battles"]
    win_rate = round((db_user["wins"] / battles) * 100) if battles > 0 else 0
    prot = ""
    if db_user.get("protection_until"):
        try:
            pt = datetime.fromisoformat(db_user["protection_until"])
            if pt > datetime.now():
                prot = f"\n🛡️ Protected: {pt.strftime('%d %b %H:%M')}"
        except:
            pass
    bot.reply_to(message,
        f"👤 {db_user['display_name']}\n"
        f"🏰 {k}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⭐ Level: {db_user['level']}\n"
        f"💰 Gold: {db_user['gold']:,}\n"
        f"✨ XP: {db_user['xp']:,}\n"
        f"━━━━━━━━━━━━━━\n"
        f"⚔️ Wins: {db_user['wins']} | 💀 Losses: {db_user['losses']}\n"
        f"🎯 Win Rate: {win_rate}%\n"
        f"🔥 Streak: {db_user['current_streak']} | 🏆 Best: {db_user['best_streak']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 Daily Streak: {db_user['daily_streak']} days{prot}"
    )

@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.reply_to(message,
        "⚔️ Kingdom Wars Commands\n\n"
        "🏰 Setup\n"
        "/start — Register\n"
        "/kingdom — Choose kingdom\n"
        "/profile — Your stats\n\n"
        "💰 Economy\n"
        "/daily — Daily gold\n"
        "/rob @user — Rob player\n"
        "/protect 1h/24h/7d — Protection\n"
        "/leaderboard — Rankings\n\n"
        "⚔️ Battle\n"
        "/battle crimson vs azure 5000\n"
        "/join crimson — Join battle\n"
        "/cancel — Cancel battle\n\n"
        "📋 Draft (Coming Phase 4)\n"
        "/draft — Pick cards\n"
        "/playcard — Play card"
    )

@bot.message_handler(commands=["adminstats"])
def cmd_adminstats(message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE kingdom IS NULL")
    no_kingdom = c.fetchone()[0]
    c.execute("SELECT SUM(gold), AVG(gold), MAX(gold) FROM users")
    gold_row = c.fetchone()
    c.execute("SELECT COUNT(*) FROM battles")
    total_battles = c.fetchone()[0]
    conn.close()
    kingdom_data = get_kingdom_stats()
    k_lines = ""
    for k in kingdom_data:
        kname = KINGDOMS.get(k["kingdom"], {})
        emoji = kname.get("emoji", "⚔️")
        k_lines += f"{emoji} {k['kingdom'].capitalize()}: {k['member_count']} players\n"
    bot.reply_to(message,
        f"🛡️ Admin Dashboard\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Total: {total} | No Kingdom: {no_kingdom}\n"
        f"⚔️ Total Battles: {total_battles}\n\n"
        f"🏰 Kingdoms\n{k_lines}\n"
        f"💰 Economy\n"
        f"Total: {int(gold_row[0] or 0):,}\n"
        f"Avg: {int(gold_row[1] or 0):,} | Max: {int(gold_row[2] or 0):,}"
    )

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
        bonus = "\n🌟 +10% Gold | +10% Drop Rate"
    if kingdom_key == smallest:
        bonus += "\n🎯 +15% Daily (Lowest Population)"
    bot.reply_to(message,
        f"⚔️ Kingdom Pledged!\n\n"
        f"You joined {k_data['emoji']} {k_data['name']}!\n"
        f"{k_data['desc']}{bonus}\n\n"
        f"Use /profile to see your stats!"
    )

# ══════════════════════════════════════════════════════════
#  PHASE 2 — ECONOMY
# ══════════════════════════════════════════════════════════

@bot.message_handler(commands=["daily"])
def cmd_daily(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)
    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return
    now = datetime.now()
    last_daily = db_user.get("last_daily")
    daily_streak = db_user.get("daily_streak", 0)
    if last_daily:
        try:
            last_dt = datetime.fromisoformat(last_daily)
            diff = now - last_dt
            if diff.total_seconds() < 86400:
                remaining = timedelta(seconds=86400) - diff
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                bot.reply_to(message, f"⏰ Already claimed!\nNext in: {hours}h {mins}m")
                return
            if diff.total_seconds() > 172800:
                daily_streak = 0
        except:
            daily_streak = 0
    daily_streak = (daily_streak % 7) + 1
    day_key = daily_streak if daily_streak <= 7 else 7
    base_reward = DAILY_REWARDS.get(day_key, 500)
    bonus_pct = 0
    kingdom = db_user.get("kingdom", "")
    if kingdom == "solar":
        bonus_pct += 10
    if kingdom == get_smallest_kingdom():
        bonus_pct += 15
    bonus_amount = int(base_reward * bonus_pct / 100)
    total_reward = base_reward + bonus_amount
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold + ?, daily_streak = ?, last_daily = ? WHERE user_id = ?",
              (total_reward, daily_streak, now.isoformat(), user.id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
              (user.id, "credit", total_reward, f"Daily reward day {daily_streak}"))
    conn.commit()
    conn.close()
    db_user = get_user(user.id)
    bonus_text = f"\n🎁 Bonus: +{bonus_amount} ({bonus_pct}%)" if bonus_pct > 0 else ""
    streak_text = "\n🎴 +1 Rare Card!" if daily_streak == 7 else ""
    bot.reply_to(message,
        f"🎁 Daily Reward!\n\n"
        f"Day {daily_streak}/7\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 +{base_reward} Gold{bonus_text}{streak_text}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Total: {db_user['gold']:,}\n\n"
        f"{'🔥' * daily_streak} Come back tomorrow!"
    )

@bot.message_handler(commands=["protect"])
def cmd_protect(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)
    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!")
        return
    PROTECTION_OPTIONS = {
        "1h":  {"hours": 1,   "cost": 100,  "label": "1 Hour"},
        "24h": {"hours": 24,  "cost": 500,  "label": "24 Hours"},
        "7d":  {"hours": 168, "cost": 2000, "label": "7 Days"},
    }
    args = message.text.split()
    if len(args) < 2 or args[1] not in PROTECTION_OPTIONS:
        current_prot = ""
        if db_user.get("protection_until"):
            try:
                pt = datetime.fromisoformat(db_user["protection_until"])
                if pt > datetime.now():
                    current_prot = f"\n🛡️ Active: {pt.strftime('%d %b %H:%M')}\n"
            except:
                pass
        bot.reply_to(message,
            f"🛡️ Protection{current_prot}\n"
            f"━━━━━━━━━━━━━━\n"
            f"/protect 1h  — 100 Gold\n"
            f"/protect 24h — 500 Gold\n"
            f"/protect 7d  — 2,000 Gold\n\n"
            f"💰 Your Gold: {db_user['gold']:,}"
        )
        return
    opt = PROTECTION_OPTIONS[args[1]]
    if db_user["gold"] < opt["cost"]:
        bot.reply_to(message, f"❌ Not enough gold!\nNeed: {opt['cost']:,} | Have: {db_user['gold']:,}")
        return
    until = datetime.now() + timedelta(hours=opt["hours"])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold - ?, protection_until = ? WHERE user_id = ?",
              (opt["cost"], until.isoformat(), user.id))
    conn.commit()
    conn.close()
    db_user = get_user(user.id)
    bot.reply_to(message,
        f"🛡️ Protected!\n\n"
        f"Duration: {opt['label']}\n"
        f"Until: {until.strftime('%d %b %H:%M')}\n"
        f"Cost: -{opt['cost']:,}\n"
        f"💰 Remaining: {db_user['gold']:,}"
    )

@bot.message_handler(commands=["rob"])
def cmd_rob(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    robber = get_or_create_user(user.id, username, display)
    if not robber.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!")
        return
    if robber["level"] <= BEGINNER_PROTECTION_LEVEL:
        bot.reply_to(message, f"🔰 Beginner protection!\nRob unlocks at Level {BEGINNER_PROTECTION_LEVEL + 1}.")
        return
    if robber.get("protection_until"):
        try:
            pt = datetime.fromisoformat(robber["protection_until"])
            if pt > datetime.now():
                bot.reply_to(message, "🛡️ Protected players cannot rob!")
                return
        except:
            pass
    target_user = None
    if message.reply_to_message:
        target_tg = message.reply_to_message.from_user
        target_user = get_user(target_tg.id)
    elif message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                mentioned = message.text[entity.offset:entity.offset + entity.length].lstrip("@")
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username = ?", (mentioned,))
                row = c.fetchone()
                conn.close()
                if row:
                    target_user = dict(row)
    if not target_user:
        bot.reply_to(message, "❌ No target!\n/rob @username\nOr reply to message with /rob")
        return
    if target_user["user_id"] == user.id:
        bot.reply_to(message, "😂 Rob yourself?")
        return
    if target_user.get("protection_until"):
        try:
            pt = datetime.fromisoformat(target_user["protection_until"])
            if pt > datetime.now():
                bot.reply_to(message, f"🛡️ {target_user['display_name']} is protected!\nUntil: {pt.strftime('%d %b %H:%M')}")
                return
        except:
            pass
    if target_user["level"] <= BEGINNER_PROTECTION_LEVEL:
        bot.reply_to(message, f"🔰 {target_user['display_name']} is a beginner! Cannot rob.")
        return
    if target_user["gold"] < 100:
        bot.reply_to(message, f"💸 {target_user['display_name']} is too poor!")
        return
    success = random.random() < ROB_SUCCESS_RATE
    if success:
        steal_pct = random.uniform(0.10, 0.30)
        stolen = int(target_user["gold"] * steal_pct)
        stolen = max(50, min(stolen, 5000))
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET gold = gold - ? WHERE user_id = ?", (stolen, target_user["user_id"]))
        c.execute("UPDATE users SET gold = gold + ? WHERE user_id = ?", (stolen, user.id))
        conn.commit()
        conn.close()
        robber = get_user(user.id)
        bot.reply_to(message,
            f"✅ Rob Successful!\n\n"
            f"🦹 Robbed: {target_user['display_name']}\n"
            f"💰 Stolen: {stolen:,} Gold\n"
            f"💰 Your Gold: {robber['gold']:,}"
        )
        try:
            bot.send_message(target_user["user_id"],
                f"🚨 Robbed!\n{display} stole {stolen:,} Gold!\nUse /protect to stay safe.")
        except:
            pass
    else:
        fine = min(200, robber["gold"] // 10)
        if fine > 0:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE users SET gold = gold - ? WHERE user_id = ?", (fine, user.id))
            conn.commit()
            conn.close()
        robber = get_user(user.id)
        bot.reply_to(message,
            f"❌ Caught!\n\nFine: -{fine:,} Gold\n💰 Your Gold: {robber['gold']:,}"
        )

@bot.message_handler(commands=["leaderboard"])
def cmd_leaderboard(message):
    players = get_top_players(10)
    kingdom_data = get_kingdom_stats()
    text = "🏆 Leaderboard\n\n💰 Top Players\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(players):
        medal = medals[i] if i < 3 else f"{i+1}."
        emoji = KINGDOMS.get(p.get("kingdom", ""), {}).get("emoji", "⚔️")
        text += f"{medal} {emoji} {p['display_name']}: {p['gold']:,}\n"
    text += "\n🏰 Kingdoms\n"
    for i, k in enumerate(kingdom_data):
        emoji = KINGDOMS.get(k["kingdom"], {}).get("emoji", "⚔️")
        text += f"{i+1}. {emoji} {k['kingdom'].capitalize()}: {k['member_count']} members\n"
    bot.reply_to(message, text)

# ══════════════════════════════════════════════════════════
#  PHASE 3 — BATTLE LOBBY
# ══════════════════════════════════════════════════════════

def battle_lobby_timeout(battle_id, chat_id):
    """Called after 2 minutes — balance teams and start or cancel."""
    battle = get_battle(battle_id)
    if not battle or battle["status"] != "waiting":
        return

    team1_players = get_team_players(battle_id, 1)
    team2_players = get_team_players(battle_id, 2)

    t1 = len(team1_players)
    t2 = len(team2_players)

    # Need at least 1 player per team
    if t1 == 0 or t2 == 0:
        update_battle_status(battle_id, "cancelled")
        # Refund all
        all_players = get_battle_players(battle_id)
        for p in all_players:
            update_gold(p["user_id"], battle["wager"], "Battle cancelled - refund")
        bot.send_message(chat_id,
            f"❌ Battle Cancelled!\n\n"
            f"Not enough players joined.\n"
            f"💰 Wager refunded to all players."
        )
        return

    # Balance teams — trim larger team
    refunded = []
    while len(team1_players) > len(team2_players):
        removed = team1_players.pop()
        remove_player_from_battle(battle_id, removed["user_id"])
        update_gold(removed["user_id"], battle["wager"], "Battle balance - refund")
        refunded.append(removed["display_name"])

    while len(team2_players) > len(team1_players):
        removed = team2_players.pop()
        remove_player_from_battle(battle_id, removed["user_id"])
        update_gold(removed["user_id"], battle["wager"], "Battle balance - refund")
        refunded.append(removed["display_name"])

    # Limit to 5v5
    while len(team1_players) > MAX_TEAM_SIZE:
        removed = team1_players.pop()
        remove_player_from_battle(battle_id, removed["user_id"])
        update_gold(removed["user_id"], battle["wager"], "Battle overflow - refund")
        refunded.append(removed["display_name"])

    while len(team2_players) > MAX_TEAM_SIZE:
        removed = team2_players.pop()
        remove_player_from_battle(battle_id, removed["user_id"])
        update_gold(removed["user_id"], battle["wager"], "Battle overflow - refund")
        refunded.append(removed["display_name"])

    update_battle_status(battle_id, "drafting")

    k1 = KINGDOMS.get(battle["team1_kingdom"], {})
    k2 = KINGDOMS.get(battle["team2_kingdom"], {})

    t1_names = " | ".join([p["display_name"] for p in team1_players])
    t2_names = " | ".join([p["display_name"] for p in team2_players])

    refund_text = ""
    if refunded:
        refund_text = f"\n♻️ Refunded: {', '.join(refunded)}"

    msg = (
        f"⚔️ BATTLE STARTING!\n\n"
        f"{k1.get('emoji','🔴')} {k1.get('name','Team1')} vs {k2.get('emoji','🔵')} {k2.get('name','Team2')}\n"
        f"💰 Wager: {battle['wager']:,} Gold\n"
        f"━━━━━━━━━━━━━━\n"
        f"{k1.get('emoji','🔴')} Team ({len(team1_players)})\n{t1_names}\n\n"
        f"{k2.get('emoji','🔵')} Team ({len(team2_players)})\n{t2_names}"
        f"{refund_text}\n\n"
        f"🎴 Cards being sent to DM...\n"
        f"Check your DM! (Phase 4)"
    )
    bot.send_message(chat_id, msg)


@bot.message_handler(commands=["battle"])
def cmd_battle(message):
    # Only in groups
    if message.chat.type == "private":
        bot.reply_to(message, "⚔️ Battle can only be started in groups!")
        return

    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    # Check existing battle
    existing = get_active_battle(message.chat.id)
    if existing:
        bot.reply_to(message, "⚔️ A battle is already active!\nUse /join to participate.")
        return

    # Parse: /battle crimson vs azure 5000
    text = message.text.strip()
    parts = text.split()

    # Format check
    try:
        # /battle team1 vs team2 wager
        if len(parts) != 5 or parts[2].lower() != "vs":
            raise ValueError
        t1_key = KINGDOM_ALIASES.get(parts[1].lower())
        t2_key = KINGDOM_ALIASES.get(parts[3].lower())
        wager = int(parts[4])
        if not t1_key or not t2_key:
            raise ValueError
        if t1_key == t2_key:
            raise ValueError
        if wager < 100:
            raise ValueError
    except:
        bot.reply_to(message,
            "❌ Wrong format!\n\n"
            "Use:\n/battle crimson vs azure 5000\n\n"
            "Kingdoms: crimson, azure, emerald, shadow, solar\n"
            "Min wager: 100 Gold"
        )
        return

    if db_user["gold"] < wager:
        bot.reply_to(message, f"❌ Not enough gold!\nNeed: {wager:,} | Have: {db_user['gold']:,}")
        return

    # Determine creator's team
    creator_kingdom = db_user.get("kingdom")
    if creator_kingdom == t1_key:
        creator_team = 1
    elif creator_kingdom == t2_key:
        creator_team = 2
    else:
        # Mercenary or other kingdom — ask
        bot.reply_to(message,
            f"⚠️ Your kingdom ({kingdom_badge(creator_kingdom)}) is not in this battle!\n"
            f"Only {kingdom_badge(t1_key)} and {kingdom_badge(t2_key)} can join."
        )
        return

    # Deduct wager
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold - ? WHERE user_id = ?", (wager, user.id))
    conn.commit()
    conn.close()

    # Create battle
    battle_id = create_battle(message.chat.id, t1_key, t2_key, wager, user.id)

    # Add creator
    join_battle(battle_id, user.id, creator_team)

    k1 = KINGDOMS[t1_key]
    k2 = KINGDOMS[t2_key]

    bot.reply_to(message,
        f"⚔️ Battle Created!\n\n"
        f"{k1['emoji']} {k1['name']} vs {k2['emoji']} {k2['name']}\n"
        f"💰 Wager: {wager:,} Gold\n"
        f"⏰ Lobby: 2 Minutes\n"
        f"👥 Max: {MAX_TEAM_SIZE}v{MAX_TEAM_SIZE}\n"
        f"━━━━━━━━━━━━━━\n"
        f"Join with:\n"
        f"/join {t1_key}\n"
        f"/join {t2_key}\n\n"
        f"💰 Cost: {wager:,} Gold per player"
    )

    # Start 2 min timer
    timer = threading.Timer(
        LOBBY_DURATION,
        battle_lobby_timeout,
        args=[battle_id, message.chat.id]
    )
    timer.start()
    battle_timers[battle_id] = timer


@bot.message_handler(commands=["join"])
def cmd_join(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚔️ Join battles in the group!")
        return

    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    battle = get_active_battle(message.chat.id)
    if not battle:
        bot.reply_to(message, "❌ No active battle!\nCreate one with /battle")
        return

    # Parse kingdom from command
    parts = message.text.split()
    if len(parts) < 2:
        k1 = KINGDOMS[battle["team1_kingdom"]]
        k2 = KINGDOMS[battle["team2_kingdom"]]
        bot.reply_to(message,
            f"Which team?\n"
            f"/join {battle['team1_kingdom']} — {k1['emoji']} {k1['name']}\n"
            f"/join {battle['team2_kingdom']} — {k2['emoji']} {k2['name']}"
        )
        return

    join_kingdom = KINGDOM_ALIASES.get(parts[1].lower())

    if join_kingdom == battle["team1_kingdom"]:
        team = 1
    elif join_kingdom == battle["team2_kingdom"]:
        team = 2
    else:
        bot.reply_to(message,
            f"❌ Wrong kingdom!\n"
            f"Join: {battle['team1_kingdom']} or {battle['team2_kingdom']}"
        )
        return

    # Kingdom match check
    if db_user["kingdom"] != join_kingdom:
        bot.reply_to(message,
            f"❌ You belong to {kingdom_badge(db_user['kingdom'])}!\n"
            f"You can only join your kingdom's team."
        )
        return

    # Check gold
    if db_user["gold"] < battle["wager"]:
        bot.reply_to(message, f"❌ Not enough gold!\nNeed: {battle['wager']:,} | Have: {db_user['gold']:,}")
        return

    # Check team size
    team_players = get_team_players(battle["battle_id"], team)
    if len(team_players) >= MAX_TEAM_SIZE:
        bot.reply_to(message, f"❌ Team is full! ({MAX_TEAM_SIZE}/{MAX_TEAM_SIZE})")
        return

    # Join
    success = join_battle(battle["battle_id"], user.id, team)
    if not success:
        bot.reply_to(message, "⚠️ Already in this battle!")
        return

    # Deduct wager
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold - ? WHERE user_id = ?", (battle["wager"], user.id))
    conn.commit()
    conn.close()

    # Show updated player counts
    t1_players = get_team_players(battle["battle_id"], 1)
    t2_players = get_team_players(battle["battle_id"], 2)
    k1 = KINGDOMS[battle["team1_kingdom"]]
    k2 = KINGDOMS[battle["team2_kingdom"]]

    bot.reply_to(message,
        f"✅ Joined {kingdom_badge(join_kingdom)}!\n\n"
        f"{k1['emoji']} {k1['name']}: {len(t1_players)}/{MAX_TEAM_SIZE}\n"
        f"{k2['emoji']} {k2['name']}: {len(t2_players)}/{MAX_TEAM_SIZE}\n\n"
        f"💰 -{battle['wager']:,} Gold\n"
        f"⏰ Battle starts when timer ends!"
    )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    if message.chat.type == "private":
        return

    user = message.from_user
    battle = get_active_battle(message.chat.id)

    if not battle:
        bot.reply_to(message, "❌ No active battle to cancel!")
        return

    if battle["created_by"] != user.id:
        bot.reply_to(message, "❌ Only the battle creator can cancel!")
        return

    # Cancel timer
    if battle["battle_id"] in battle_timers:
        battle_timers[battle["battle_id"]].cancel()
        del battle_timers[battle["battle_id"]]

    # Refund all players
    all_players = get_battle_players(battle["battle_id"])
    for p in all_players:
        update_gold(p["user_id"], battle["wager"], "Battle cancelled - refund")

    update_battle_status(battle["battle_id"], "cancelled")

    bot.reply_to(message,
        f"❌ Battle Cancelled!\n"
        f"💰 Wager refunded to all {len(all_players)} players."
    )


@bot.message_handler(commands=["battlestatus"])
def cmd_battlestatus(message):
    battle = get_active_battle(message.chat.id)
    if not battle:
        bot.reply_to(message, "❌ No active battle!")
        return

    t1_players = get_team_players(battle["battle_id"], 1)
    t2_players = get_team_players(battle["battle_id"], 2)
    k1 = KINGDOMS[battle["team1_kingdom"]]
    k2 = KINGDOMS[battle["team2_kingdom"]]

    t1_names = "\n".join([f"  • {p['display_name']}" for p in t1_players]) or "  (empty)"
    t2_names = "\n".join([f"  • {p['display_name']}" for p in t2_players]) or "  (empty)"

    bot.reply_to(message,
        f"⚔️ Battle Status\n\n"
        f"{k1['emoji']} {k1['name']} ({len(t1_players)}/{MAX_TEAM_SIZE})\n{t1_names}\n\n"
        f"{k2['emoji']} {k2['name']} ({len(t2_players)}/{MAX_TEAM_SIZE})\n{t2_names}\n\n"
        f"💰 Wager: {battle['wager']:,} Gold\n"
        f"Use /join {battle['team1_kingdom']} or /join {battle['team2_kingdom']}"
    )

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

MOOD PAKADNA:
- User funny → tu bhi funny
- User sad → caring aur soft
- User flirt kare → shy + playful
- User short reply de → tease kar

EXAMPLES:
User: "Hi" → "heyy! kya chal raha hai? 😊"
User: "Han" → "itni choti reply? mood off hai kya? 👀"
User: "Kaisi ho" → "theek hoon yaar! tum batao? 😄"
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

def should_reply_in_group(message):
    if message.chat.type == "private":
        return True
    text = message.text or ""
    if "akari" in text.lower():
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

def clean_message(text):
    cleaned = re.sub(r'@\w+', '', text).strip()
    return cleaned if cleaned else text

def get_ai_response(user_id, current_message):
    if user_id not in chat_histories:
        chat_histories[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    chat_histories[user_id].append({"role": "user", "content": current_message})
    if len(chat_histories[user_id]) > 17:
        chat_histories[user_id] = [chat_histories[user_id][0]] + chat_histories[user_id][-16:]
    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": chat_histories[user_id],
        "temperature": 0.6,
        "max_tokens": 80,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.4,
    }
    try:
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        response = requests.post(AI_API_URL, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        ai_reply = response.json()['choices'][0]['message']['content'].strip()
        chat_histories[user_id].append({"role": "assistant", "content": ai_reply})
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

# ══════════════════════════════════════════════════════════
#  RENDER HEALTH SERVER
# ══════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kingdom Wars + Akari Running!")
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
    print("Kingdom Wars Phase 1+2+3 + Akari running...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
