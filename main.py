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
            winner_kingdom TEXT DEFAULT NULL,
            current_round INTEGER DEFAULT 0,
            team1_wins INTEGER DEFAULT 0,
            team2_wins INTEGER DEFAULT 0,
            team1_total_power REAL DEFAULT 0,
            team2_total_power REAL DEFAULT 0,
            team1_bonus REAL DEFAULT 0,
            team2_bonus REAL DEFAULT 0,
            team1_last_result TEXT DEFAULT NULL,
            team2_last_result TEXT DEFAULT NULL
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS battle_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER,
            user_id INTEGER,
            dealt_cards TEXT,
            drafted_cards TEXT DEFAULT NULL,
            confirmed INTEGER DEFAULT 0,
            UNIQUE(battle_id, user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS battle_round_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER,
            round_number INTEGER,
            user_id INTEGER,
            card_power INTEGER,
            UNIQUE(battle_id, round_number, user_id)
        )
    """)
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(battles)").fetchall()]
    new_cols = {
        "current_round": "INTEGER DEFAULT 0",
        "team1_wins": "INTEGER DEFAULT 0",
        "team2_wins": "INTEGER DEFAULT 0",
        "team1_total_power": "REAL DEFAULT 0",
        "team2_total_power": "REAL DEFAULT 0",
        "team1_bonus": "REAL DEFAULT 0",
        "team2_bonus": "REAL DEFAULT 0",
        "team1_last_result": "TEXT DEFAULT NULL",
        "team2_last_result": "TEXT DEFAULT NULL",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE battles ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
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

# ── Phase 4: Draft DB functions ────────────────────────────

def deal_cards(battle_id, user_id):
    """Deal 6 unique random power cards (1-10) to a player."""
    cards = random.sample(range(1, 11), 6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO battle_drafts (battle_id, user_id, dealt_cards, drafted_cards, confirmed)
        VALUES (?, ?, ?, NULL, 0)
    """, (battle_id, user_id, ",".join(map(str, cards))))
    conn.commit()
    conn.close()
    return cards

def get_draft(battle_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM battle_drafts WHERE battle_id = ? AND user_id = ?", (battle_id, user_id))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["dealt_cards"] = [int(x) for x in d["dealt_cards"].split(",")] if d["dealt_cards"] else []
    d["drafted_cards"] = [int(x) for x in d["drafted_cards"].split(",")] if d["drafted_cards"] else []
    return d

def set_drafted_cards(battle_id, user_id, cards):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE battle_drafts SET drafted_cards = ?, confirmed = 0 WHERE battle_id = ? AND user_id = ?",
              (",".join(map(str, cards)), battle_id, user_id))
    conn.commit()
    conn.close()

def confirm_draft(battle_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE battle_drafts SET confirmed = 1 WHERE battle_id = ? AND user_id = ?",
              (battle_id, user_id))
    conn.commit()
    conn.close()

def get_active_battle_for_user(user_id):
    """Find a battle the user is part of that is in drafting or battle status."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT b.* FROM battles b
        JOIN battle_players bp ON b.battle_id = bp.battle_id
        WHERE bp.user_id = ? AND b.status IN ('drafting', 'battle')
        ORDER BY b.battle_id DESC LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def all_players_confirmed(battle_id):
    players = get_battle_players(battle_id)
    for p in players:
        d = get_draft(battle_id, p["user_id"])
        if not d or not d["confirmed"] or len(d["drafted_cards"]) != 4:
            return False
    return True

# ── Phase 4: Round play DB functions ───────────────────────

def play_card(battle_id, round_number, user_id, card_power):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO battle_round_plays (battle_id, round_number, user_id, card_power)
            VALUES (?, ?, ?, ?)
        """, (battle_id, round_number, user_id, card_power))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_round_play(battle_id, round_number, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT card_power FROM battle_round_plays
        WHERE battle_id = ? AND round_number = ? AND user_id = ?
    """, (battle_id, round_number, user_id))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def all_players_played_round(battle_id, round_number):
    players = get_battle_players(battle_id)
    for p in players:
        if get_round_play(battle_id, round_number, p["user_id"]) is None:
            return False
    return True

def get_played_powers(battle_id, user_id):
    """Get list of card powers this player has already played (any round)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT card_power FROM battle_round_plays
        WHERE battle_id = ? AND user_id = ?
    """, (battle_id, user_id))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def update_battle_round_state(battle_id, **kwargs):
    if not kwargs:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [battle_id]
    c.execute(f"UPDATE battles SET {cols} WHERE battle_id = ?", vals)
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
DRAFT_TIMEOUT = 180   # 3 minutes to draft
ROUND_TIMEOUT = 120   # 2 minutes per round

# ══════════════════════════════════════════════════════════
#  PHASE 4 — CARD DATA & ABILITIES
# ══════════════════════════════════════════════════════════

# Each power level (1-10) maps to a unit name and an ability key.
CARD_DATA = {
    1:  {"name": "Footman",      "ability": None},
    2:  {"name": "Archer",       "ability": "first_strike"},
    3:  {"name": "Spearman",     "ability": None},
    4:  {"name": "Swordsman",    "ability": "counter_attack"},
    5:  {"name": "Knight",       "ability": "healing_light"},
    6:  {"name": "Shield Guard", "ability": "shield_wall"},
    7:  {"name": "Giant",        "ability": "berserker_rage"},
    8:  {"name": "Battle Mage",  "ability": "arcane_blast"},
    9:  {"name": "Elite Guard",  "ability": "stealth"},
    10: {"name": "Grand General","ability": "command"},
}

ABILITY_INFO = {
    "command":        {"emoji": "👑", "name": "Command", "desc": "+1 team power"},
    "first_strike":   {"emoji": "⚡", "name": "First Strike", "desc": "+0.5 power, tiebreaker"},
    "shield_wall":    {"emoji": "🛡️", "name": "Shield Wall", "desc": "-1.5 enemy power"},
    "healing_light":  {"emoji": "✨", "name": "Healing Light", "desc": "+1 team power"},
    "counter_attack": {"emoji": "🔄", "name": "Counter Attack", "desc": "+1 power next round if lost"},
    "berserker_rage": {"emoji": "💢", "name": "Berserker Rage", "desc": "+2 power if lost last round"},
    "arcane_blast":   {"emoji": "🔮", "name": "Arcane Blast", "desc": "Ignores Shield Wall"},
    "stealth":        {"emoji": "🌑", "name": "Stealth", "desc": "Ignores enemy's lowest card"},
}

def card_label(kingdom, power):
    """Returns a display label like '🔴 Giant (7) - Berserker Rage'"""
    k = KINGDOMS.get(kingdom, {})
    emoji = k.get("emoji", "⚔️")
    info = CARD_DATA.get(power, {"name": "Unknown", "ability": None})
    label = f"{emoji} {info['name']} ({power})"
    if info["ability"]:
        ab = ABILITY_INFO[info["ability"]]
        label += f" — {ab['emoji']} {ab['name']}"
    return label

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
        "/cancel — Cancel battle\n"
        "/battlestatus — Lobby status\n\n"
        "📋 Draft (DM only)\n"
        "/draft 1 2 3 4 — Pick 4 cards\n"
        "/redraft — Re-pick before confirm\n"
        "/confirm — Lock in draft\n"
        "/mycards — View your cards\n"
        "/playcard 1-4 — Play a card"
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
        f"🎴 Cards sent to DM!\n"
        f"📋 Each player: pick 4 of 6 cards with /draft\n"
        f"⏰ Draft ends in 3 minutes"
    )
    bot.send_message(chat_id, msg)

    # Deal cards to all players and send via DM
    all_players = team1_players + team2_players
    for p in all_players:
        kingdom = p["kingdom"]
        cards = deal_cards(battle_id, p["user_id"])
        send_draft_cards_dm(p["user_id"], kingdom, cards)

    # Start draft timeout timer
    timer = threading.Timer(DRAFT_TIMEOUT, draft_timeout, args=[battle_id, chat_id])
    timer.start()
    battle_timers[f"draft_{battle_id}"] = timer


def send_draft_cards_dm(user_id, kingdom, cards):
    """Send dealt cards to player's DM with draft instructions."""
    text = "🎴 Your Battle Cards!\n\n"
    for i, power in enumerate(cards, start=1):
        text += f"{i}. {card_label(kingdom, power)}\n"
    text += (
        "\n━━━━━━━━━━━━━━\n"
        "Pick 4 cards by their numbers:\n"
        "/draft 1 3 4 6\n\n"
        "Then lock it in:\n"
        "/confirm\n\n"
        "Change your mind before confirming:\n"
        "/redraft"
    )
    try:
        bot.send_message(user_id, text)
    except Exception as e:
        print(f"DM Error to {user_id}: {e}")


def draft_timeout(battle_id, chat_id):
    """If draft phase times out, auto-draft for players who didn't confirm."""
    battle = get_battle(battle_id)
    if not battle or battle["status"] != "drafting":
        return

    players = get_battle_players(battle_id)
    for p in players:
        d = get_draft(battle_id, p["user_id"])
        if not d or not d["confirmed"]:
            # Auto-pick first 4 dealt cards
            dealt = d["dealt_cards"] if d else random.sample(range(1, 11), 6)
            auto_cards = dealt[:4]
            set_drafted_cards(battle_id, p["user_id"], auto_cards)
            confirm_draft(battle_id, p["user_id"])
            try:
                bot.send_message(p["user_id"],
                    f"⏰ Time's up! Auto-drafted: {', '.join(map(str, auto_cards))}"
                )
            except:
                pass

    bot.send_message(chat_id, "⏰ Draft phase ended! Starting Round 1...")
    start_round(battle_id, 1, chat_id)


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
#  PHASE 4 — DRAFT, ROUNDS, BATTLE RESOLUTION
# ══════════════════════════════════════════════════════════

# ── /draft (DM) ─────────────────────────────────────────────
@bot.message_handler(commands=["draft"])
def cmd_draft(message):
    user = message.from_user
    battle = get_active_battle_for_user(user.id)
    if not battle or battle["status"] != "drafting":
        bot.reply_to(message, "❌ No active draft for you right now.")
        return

    draft = get_draft(battle["battle_id"], user.id)
    if not draft:
        bot.reply_to(message, "❌ Cards not dealt yet! Wait for the lobby to close.")
        return

    if draft["confirmed"]:
        bot.reply_to(message, "🔒 Already confirmed!\nUse /redraft to re-pick before round 1 starts.")
        return

    parts = message.text.split()[1:]
    if len(parts) != 4:
        bot.reply_to(message, "❌ Pick exactly 4 cards!\nExample: /draft 1 2 3 4")
        return

    try:
        positions = [int(p) for p in parts]
    except ValueError:
        bot.reply_to(message, "❌ Use numbers only!\nExample: /draft 1 2 3 4")
        return

    if len(set(positions)) != 4 or any(p < 1 or p > 6 for p in positions):
        bot.reply_to(message, "❌ Pick 4 DIFFERENT numbers between 1-6!")
        return

    drafted_powers = [draft["dealt_cards"][p - 1] for p in positions]
    set_drafted_cards(battle["battle_id"], user.id, drafted_powers)

    db_user = get_user(user.id)
    kingdom = db_user["kingdom"]
    text = "✅ Draft Selected!\n\n"
    for power in drafted_powers:
        text += f"{card_label(kingdom, power)}\n"
    text += "\n🔒 Lock it in: /confirm\n🔄 Change picks: /redraft"
    bot.reply_to(message, text)


# ── /redraft (DM) ───────────────────────────────────────────
@bot.message_handler(commands=["redraft"])
def cmd_redraft(message):
    user = message.from_user
    battle = get_active_battle_for_user(user.id)
    if not battle or battle["status"] != "drafting":
        bot.reply_to(message, "❌ No active draft for you right now.")
        return

    draft = get_draft(battle["battle_id"], user.id)
    if not draft:
        bot.reply_to(message, "❌ Cards not dealt yet!")
        return

    if draft["confirmed"]:
        bot.reply_to(message, "🔒 Already confirmed! Cannot redraft now.")
        return

    db_user = get_user(user.id)
    send_draft_cards_dm(user.id, db_user["kingdom"], draft["dealt_cards"])
    bot.reply_to(message, "🔄 Pick again with /draft 1 2 3 4")


# ── /confirm (DM) ───────────────────────────────────────────
@bot.message_handler(commands=["confirm"])
def cmd_confirm(message):
    user = message.from_user
    battle = get_active_battle_for_user(user.id)
    if not battle or battle["status"] != "drafting":
        bot.reply_to(message, "❌ Nothing to confirm right now.")
        return

    draft = get_draft(battle["battle_id"], user.id)
    if not draft or len(draft["drafted_cards"]) != 4:
        bot.reply_to(message, "❌ Pick 4 cards first!\n/draft 1 2 3 4")
        return

    if draft["confirmed"]:
        bot.reply_to(message, "✅ Already confirmed!\nWaiting for other players...")
        return

    confirm_draft(battle["battle_id"], user.id)
    bot.reply_to(message, "🔒 Draft confirmed!\nWaiting for other players...")

    if all_players_confirmed(battle["battle_id"]):
        key = f"draft_{battle['battle_id']}"
        if key in battle_timers:
            battle_timers[key].cancel()
            del battle_timers[key]
        bot.send_message(battle["chat_id"], "✅ All players drafted!\n⚔️ Round 1 begins now!")
        start_round(battle["battle_id"], 1, battle["chat_id"])


# ── /mycards (DM) ───────────────────────────────────────────
@bot.message_handler(commands=["mycards"])
def cmd_mycards(message):
    user = message.from_user
    battle = get_active_battle_for_user(user.id)
    if not battle:
        bot.reply_to(message, "❌ You're not in an active battle.")
        return

    draft = get_draft(battle["battle_id"], user.id)
    db_user = get_user(user.id)
    kingdom = db_user["kingdom"]

    if not draft:
        bot.reply_to(message, "❌ Cards not dealt yet!")
        return

    if battle["status"] == "drafting":
        text = "🎴 Your Dealt Cards\n\n"
        for i, power in enumerate(draft["dealt_cards"], 1):
            text += f"{i}. {card_label(kingdom, power)}\n"
        if draft["drafted_cards"]:
            text += "\n✅ Drafted:\n"
            for power in draft["drafted_cards"]:
                text += f"  {card_label(kingdom, power)}\n"
            text += "🔒 Confirmed!" if draft["confirmed"] else "\nUse /confirm to lock in"
        else:
            text += "\nPick 4: /draft 1 2 3 4"
    else:
        played = get_played_powers(battle["battle_id"], user.id)
        text = f"🎴 Your Cards — Round {battle['current_round']}/4\n\n"
        for i, power in enumerate(draft["drafted_cards"], 1):
            status = " ✅ played" if power in played else ""
            text += f"{i}. {card_label(kingdom, power)}{status}\n"
    bot.reply_to(message, text)


# ── /playcard (DM) ──────────────────────────────────────────
@bot.message_handler(commands=["playcard"])
def cmd_playcard(message):
    user = message.from_user
    battle = get_active_battle_for_user(user.id)
    if not battle or battle["status"] != "battle":
        bot.reply_to(message, "❌ No active round for you right now.")
        return

    parts = message.text.split()[1:]
    if len(parts) != 1 or parts[0] not in ["1", "2", "3", "4"]:
        bot.reply_to(message, "❌ Use /playcard 1, 2, 3, or 4")
        return

    pos = int(parts[0])
    round_number = battle["current_round"]

    if get_round_play(battle["battle_id"], round_number, user.id) is not None:
        bot.reply_to(message, "✅ You already played this round!\nWait for results...")
        return

    draft = get_draft(battle["battle_id"], user.id)
    power = draft["drafted_cards"][pos - 1]

    played = get_played_powers(battle["battle_id"], user.id)
    if power in played:
        bot.reply_to(message, "❌ You already used this card in a previous round!")
        return

    play_card(battle["battle_id"], round_number, user.id, power)
    db_user = get_user(user.id)
    bot.reply_to(message,
        f"✅ Played: {card_label(db_user['kingdom'], power)}\n"
        f"⏳ Waiting for other players..."
    )

    if all_players_played_round(battle["battle_id"], round_number):
        key = f"round_{battle['battle_id']}_{round_number}"
        if key in battle_timers:
            battle_timers[key].cancel()
            del battle_timers[key]
        resolve_round(battle["battle_id"], round_number, battle["chat_id"])


# ── Round Management ────────────────────────────────────────

def send_round_prompt_dm(battle_id, user_id, kingdom, round_number):
    draft = get_draft(battle_id, user_id)
    played = get_played_powers(battle_id, user_id)
    text = f"⚔️ Round {round_number}/4 — Your Turn!\n\n"
    for i, power in enumerate(draft["drafted_cards"], start=1):
        status = " ✅ (played)" if power in played else ""
        text += f"{i}. {card_label(kingdom, power)}{status}\n"
    text += "\nPlay a card:\n/playcard 1\n/playcard 2\n/playcard 3\n/playcard 4"
    try:
        bot.send_message(user_id, text)
    except Exception as e:
        print(f"DM error to {user_id}: {e}")


def start_round(battle_id, round_number, chat_id):
    battle = get_battle(battle_id)
    if not battle or battle["status"] == "finished":
        return

    if round_number == 1:
        update_battle_status(battle_id, "battle")

    update_battle_round_state(battle_id, current_round=round_number)
    players = get_battle_players(battle_id)

    bot.send_message(chat_id,
        f"⚔️ Round {round_number}/4 has begun!\n"
        f"📩 Check your DM and play a card!\n"
        f"⏰ {ROUND_TIMEOUT // 60} minutes to play"
    )

    for p in players:
        send_round_prompt_dm(battle_id, p["user_id"], p["kingdom"], round_number)

    timer = threading.Timer(ROUND_TIMEOUT, round_timeout, args=[battle_id, round_number, chat_id])
    timer.start()
    battle_timers[f"round_{battle_id}_{round_number}"] = timer


def round_timeout(battle_id, round_number, chat_id):
    battle = get_battle(battle_id)
    if not battle or battle["current_round"] != round_number or battle["status"] == "finished":
        return

    players = get_battle_players(battle_id)
    for p in players:
        if get_round_play(battle_id, round_number, p["user_id"]) is None:
            draft = get_draft(battle_id, p["user_id"])
            played = get_played_powers(battle_id, p["user_id"])
            available = [c for c in draft["drafted_cards"] if c not in played]
            if available:
                auto_power = available[0]
                play_card(battle_id, round_number, p["user_id"], auto_power)
                try:
                    bot.send_message(p["user_id"],
                        f"⏰ Time's up! Auto-played: {card_label(p['kingdom'], auto_power)}")
                except:
                    pass

    resolve_round(battle_id, round_number, chat_id)


def calc_team_power(own_cards, enemy_cards, battle, team_num):
    """
    own_cards / enemy_cards: list of (user_id, kingdom, power)
    Returns (final_power: float, log: list of strings)
    """
    own_powers = [c[2] for c in own_cards]
    enemy_powers = [c[2] for c in enemy_cards]

    own_abilities = set(CARD_DATA[p]["ability"] for p in own_powers if CARD_DATA[p]["ability"])
    enemy_abilities = set(CARD_DATA[p]["ability"] for p in enemy_powers if CARD_DATA[p]["ability"])

    base = float(sum(own_powers))
    log = []

    # Stealth — enemy ignores our lowest card
    if "stealth" in enemy_abilities and own_powers:
        lowest = min(own_powers)
        base -= lowest
        log.append(f"🌑 Enemy Stealth ignores -{lowest}")

    # Command — +1 team power
    if "command" in own_abilities:
        base += 1
        log.append("👑 Command +1")

    # Healing Light — +1 team power
    if "healing_light" in own_abilities:
        base += 1
        log.append("✨ Healing Light +1")

    # First Strike — +0.5
    if "first_strike" in own_abilities:
        base += 0.5
        log.append("⚡ First Strike +0.5")

    # Berserker Rage — +2 if lost last round
    last_result_key = "team1_last_result" if team_num == 1 else "team2_last_result"
    if "berserker_rage" in own_abilities and battle.get(last_result_key) == "loss":
        base += 2
        log.append("💢 Berserker Rage +2")

    # Counter Attack — carried bonus from previous round
    bonus_key = "team1_bonus" if team_num == 1 else "team2_bonus"
    carry_bonus = battle.get(bonus_key, 0) or 0
    if carry_bonus:
        base += carry_bonus
        log.append(f"🔄 Counter Attack +{carry_bonus}")

    # Shield Wall — enemy reduces our power, unless we have Arcane Blast
    if "shield_wall" in enemy_abilities and "arcane_blast" not in own_abilities:
        base -= 1.5
        log.append("🛡️ Enemy Shield Wall -1.5")
    elif "shield_wall" in enemy_abilities and "arcane_blast" in own_abilities:
        log.append("🔮 Arcane Blast negates Shield Wall")

    return base, log


def resolve_round(battle_id, round_number, chat_id):
    battle = get_battle(battle_id)
    team1 = get_team_players(battle_id, 1)
    team2 = get_team_players(battle_id, 2)

    def build_cards(team):
        cards = []
        for p in team:
            power = get_round_play(battle_id, round_number, p["user_id"])
            if power is None:
                power = 1
            cards.append({"user_id": p["user_id"], "kingdom": p["kingdom"],
                           "power": power, "name": p["display_name"]})
        return cards

    t1_cards = build_cards(team1)
    t2_cards = build_cards(team2)

    t1_tuples = [(c["user_id"], c["kingdom"], c["power"]) for c in t1_cards]
    t2_tuples = [(c["user_id"], c["kingdom"], c["power"]) for c in t2_cards]

    t1_power, t1_log = calc_team_power(t1_tuples, t2_tuples, battle, 1)
    t2_power, t2_log = calc_team_power(t2_tuples, t1_tuples, battle, 2)

    if t1_power > t2_power:
        winner = 1
    elif t2_power > t1_power:
        winner = 2
    else:
        winner = random.choice([1, 2])

    k1 = KINGDOMS[battle["team1_kingdom"]]
    k2 = KINGDOMS[battle["team2_kingdom"]]

    t1_lines = "\n".join([f"  {card_label(c['kingdom'], c['power'])} — {c['name']}" for c in t1_cards])
    t2_lines = "\n".join([f"  {card_label(c['kingdom'], c['power'])} — {c['name']}" for c in t2_cards])

    t1_bonus_text = "\n".join(f"  {l}" for l in t1_log) if t1_log else "  (none)"
    t2_bonus_text = "\n".join(f"  {l}" for l in t2_log) if t2_log else "  (none)"

    def fmt_power(p):
        return str(int(p)) if p == int(p) else str(p)

    winner_name = k1["name"] if winner == 1 else k2["name"]
    winner_emoji = k1["emoji"] if winner == 1 else k2["emoji"]

    msg = (
        f"🎴 Round {round_number} — Cards Revealed!\n\n"
        f"{k1['emoji']} {k1['name']}\n{t1_lines}\n"
        f"Bonuses:\n{t1_bonus_text}\n"
        f"⚡ Total Power: {fmt_power(t1_power)}\n\n"
        f"{k2['emoji']} {k2['name']}\n{t2_lines}\n"
        f"Bonuses:\n{t2_bonus_text}\n"
        f"⚡ Total Power: {fmt_power(t2_power)}\n\n"
        f"🏆 {winner_emoji} {winner_name} wins Round {round_number}!"
    )
    bot.send_message(chat_id, msg)

    t1_wins = battle["team1_wins"] + (1 if winner == 1 else 0)
    t2_wins = battle["team2_wins"] + (1 if winner == 2 else 0)
    t1_total = (battle["team1_total_power"] or 0) + t1_power
    t2_total = (battle["team2_total_power"] or 0) + t2_power

    # Counter Attack — sets up bonus for next round if team loses
    t1_has_counter = any(CARD_DATA[c["power"]]["ability"] == "counter_attack" for c in t1_cards)
    t2_has_counter = any(CARD_DATA[c["power"]]["ability"] == "counter_attack" for c in t2_cards)
    new_t1_bonus = 1 if (winner == 2 and t1_has_counter) else 0
    new_t2_bonus = 1 if (winner == 1 and t2_has_counter) else 0

    update_battle_round_state(
        battle_id,
        team1_wins=t1_wins, team2_wins=t2_wins,
        team1_total_power=t1_total, team2_total_power=t2_total,
        team1_last_result=("loss" if winner == 2 else "win"),
        team2_last_result=("loss" if winner == 1 else "win"),
        team1_bonus=new_t1_bonus, team2_bonus=new_t2_bonus,
    )

    if round_number < 4:
        timer = threading.Timer(6, start_round, args=[battle_id, round_number + 1, chat_id])
        timer.start()
    else:
        timer = threading.Timer(6, finish_battle, args=[battle_id, chat_id])
        timer.start()


def finish_battle(battle_id, chat_id):
    battle = get_battle(battle_id)
    team1 = get_team_players(battle_id, 1)
    team2 = get_team_players(battle_id, 2)

    t1_wins = battle["team1_wins"]
    t2_wins = battle["team2_wins"]

    if t1_wins > t2_wins:
        winner_team = 1
    elif t2_wins > t1_wins:
        winner_team = 2
    else:
        t1_total = battle["team1_total_power"] or 0
        t2_total = battle["team2_total_power"] or 0
        if t1_total > t2_total:
            winner_team = 1
        elif t2_total > t1_total:
            winner_team = 2
        else:
            winner_team = random.choice([1, 2])

    winners = team1 if winner_team == 1 else team2
    losers = team2 if winner_team == 1 else team1
    winner_kingdom = battle["team1_kingdom"] if winner_team == 1 else battle["team2_kingdom"]
    loser_kingdom = battle["team2_kingdom"] if winner_team == 1 else battle["team1_kingdom"]

    wager = battle["wager"]
    total_pool = wager * (len(team1) + len(team2))
    share = total_pool // len(winners) if winners else 0

    XP_WIN = 50
    XP_LOSS = 20

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for p in winners:
        c.execute("""
            UPDATE users SET gold = gold + ?, wins = wins + 1, battles = battles + 1,
                xp = xp + ?, current_streak = current_streak + 1
            WHERE user_id = ?
        """, (share, XP_WIN, p["user_id"]))
        c.execute("""
            UPDATE users SET best_streak = current_streak
            WHERE user_id = ? AND current_streak > best_streak
        """, (p["user_id"],))
        c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                  (p["user_id"], "credit", share, f"Battle #{battle_id} win"))
    for p in losers:
        c.execute("""
            UPDATE users SET losses = losses + 1, battles = battles + 1,
                xp = xp + ?, current_streak = 0
            WHERE user_id = ?
        """, (XP_LOSS, p["user_id"]))

    # Simple level-up: level = xp // 200 + 1
    for p in winners + losers:
        c.execute("SELECT xp FROM users WHERE user_id = ?", (p["user_id"],))
        xp_row = c.fetchone()
        if xp_row:
            new_level = xp_row[0] // 200 + 1
            c.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, p["user_id"]))

    c.execute("UPDATE kingdom_stats SET total_wins = total_wins + 1 WHERE kingdom = ?", (winner_kingdom,))
    c.execute("UPDATE kingdom_stats SET total_losses = total_losses + 1 WHERE kingdom = ?", (loser_kingdom,))

    conn.commit()
    conn.close()

    update_battle_status(battle_id, "finished")
    update_battle_round_state(battle_id, winner_kingdom=winner_kingdom)

    k1 = KINGDOMS[battle["team1_kingdom"]]
    k2 = KINGDOMS[battle["team2_kingdom"]]
    wk = KINGDOMS[winner_kingdom]

    winner_names = ", ".join([p["display_name"] for p in winners]) or "(no one)"

    msg = (
        f"🏆 BATTLE FINISHED!\n\n"
        f"{k1['emoji']} {k1['name']}  {t1_wins} - {t2_wins}  {k2['emoji']} {k2['name']}\n\n"
        f"👑 Winner: {wk['emoji']} {wk['name']}!\n"
        f"🎉 {winner_names}\n\n"
        f"💰 Each winner: +{share:,} Gold\n"
        f"✨ Winners +{XP_WIN} XP | Losers +{XP_LOSS} XP"
    )
    bot.send_message(chat_id, msg)

    # Cleanup any leftover timers for this battle
    for key in list(battle_timers.keys()):
        if f"_{battle_id}_" in key or key.endswith(f"_{battle_id}"):
            try:
                battle_timers[key].cancel()
            except:
                pass
            del battle_timers[key]


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
