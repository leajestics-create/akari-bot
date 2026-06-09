import telebot
import requests
import os
import random
import re
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════

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
#  KINGDOMS DATA
# ══════════════════════════════════════════════════════════

KINGDOMS = {
    "crimson": {"name": "Crimson", "emoji": "🔴", "desc": "Aggressive warriors. First Strike + Berserker Rage."},
    "azure":   {"name": "Azure",   "emoji": "🔵", "desc": "Strategic commanders. Command + Arcane Blast."},
    "emerald": {"name": "Emerald", "emoji": "🟢", "desc": "Defensive fortress. Shield Wall + Healing Light."},
    "shadow":  {"name": "Shadow",  "emoji": "🟣", "desc": "Tactical assassins. Stealth + Counter Attack."},
    "solar":   {"name": "Solar",   "emoji": "🟡", "desc": "Economy empire. +10% Gold & better drops."},
}

DAILY_REWARDS = {
    1: 500, 2: 600, 3: 700, 4: 800,
    5: 900, 6: 1000, 7: 1500
}

ROB_SUCCESS_RATE = 0.35
ROB_COOLDOWN_HOURS = 1
BEGINNER_PROTECTION_LEVEL = 5

# ══════════════════════════════════════════════════════════
#  CARD DATA
# ══════════════════════════════════════════════════════════

CARD_RARITIES = {
    "common":    {"emoji": "🔵", "chance": 40, "color": "🔵"},
    "rare":      {"emoji": "🟢", "chance": 30, "color": "🟢"},
    "epic":      {"emoji": "🟣", "chance": 20, "color": "🟣"},
    "legendary": {"emoji": "🟠", "chance": 8,  "color": "🟠"},
    "mythic":    {"emoji": "🔴", "chance": 2,  "color": "🔴"},
}

STARTER_CARDS = [
    # Common
    {"name": "Foot Soldier", "rarity": "common", "attack": 3, "defense": 2, "ability": "None"},
    {"name": "Archer", "rarity": "common", "attack": 4, "defense": 1, "ability": "Ranged"},
    {"name": "Scout", "rarity": "common", "attack": 2, "defense": 2, "ability": "Stealth"},
    {"name": "Militia", "rarity": "common", "attack": 3, "defense": 3, "ability": "None"},
    {"name": "Peasant", "rarity": "common", "attack": 1, "defense": 1, "ability": "Revolt"},
    # Rare
    {"name": "Knight", "rarity": "rare", "attack": 5, "defense": 4, "ability": "Charge"},
    {"name": "Mage", "rarity": "rare", "attack": 6, "defense": 2, "ability": "Fireball"},
    {"name": "Healer", "rarity": "rare", "attack": 2, "defense": 5, "ability": "Heal"},
    {"name": "Assassin", "rarity": "rare", "attack": 7, "defense": 1, "ability": "Backstab"},
    {"name": "Catapult", "rarity": "rare", "attack": 6, "defense": 3, "ability": "Siege"},
    # Epic
    {"name": "Paladin", "rarity": "epic", "attack": 6, "defense": 6, "ability": "Holy Light"},
    {"name": "Warlock", "rarity": "epic", "attack": 8, "defense": 3, "ability": "Dark Magic"},
    {"name": "Beastmaster", "rarity": "epic", "attack": 5, "defense": 5, "ability": "Summon"},
    {"name": "Dragon Whelp", "rarity": "epic", "attack": 7, "defense": 4, "ability": "Fire Breath"},
    # Legendary
    {"name": "Archmage", "rarity": "legendary", "attack": 9, "defense": 5, "ability": "Meteor"},
    {"name": "Dragon Lord", "rarity": "legendary", "attack": 10, "defense": 6, "ability": "Dragon Fury"},
    {"name": "Shadow King", "rarity": "legendary", "attack": 8, "defense": 7, "ability": "Shadow Strike"},
    # Mythic
    {"name": "Celestial Guardian", "rarity": "mythic", "attack": 12, "defense": 10, "ability": "Divine Shield"},
    {"name": "Demon Overlord", "rarity": "mythic", "attack": 14, "defense": 8, "ability": "Hellfire"},
]

RARITY_ORDER = ["common", "rare", "epic", "legendary", "mythic"]
UPGRADE_COST = 3
MAX_BATTLE_DECK = 5

# ══════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Users table
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
    
    # Kingdom stats
    c.execute("""
        CREATE TABLE IF NOT EXISTS kingdom_stats (
            kingdom TEXT PRIMARY KEY,
            member_count INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            treasury INTEGER DEFAULT 0
        )
    """)
    
    # Transactions
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
    
    # Cards table
    c.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            card_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            rarity TEXT NOT NULL,
            attack INTEGER DEFAULT 0,
            defense INTEGER DEFAULT 0,
            ability TEXT DEFAULT '',
            is_collection INTEGER DEFAULT 0,
            is_battle INTEGER DEFAULT 1
        )
    """)
    
    # User cards (collection)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_id INTEGER,
            quantity INTEGER DEFAULT 1,
            is_equipped INTEGER DEFAULT 0,
            is_collection INTEGER DEFAULT 0,
            upgraded INTEGER DEFAULT 0,
            obtained_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (card_id) REFERENCES cards(card_id)
        )
    """)
    
    # User battle deck
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_battle_deck (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_id INTEGER,
            slot INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (card_id) REFERENCES cards(card_id)
        )
    """)
    
    # Insert kingdoms
    for k in ["crimson", "azure", "emerald", "shadow", "solar"]:
        c.execute("INSERT OR IGNORE INTO kingdom_stats (kingdom) VALUES (?)", (k,))
    
    # Insert starter cards
    for card in STARTER_CARDS:
        c.execute("""
            INSERT OR IGNORE INTO cards (name, rarity, attack, defense, ability)
            VALUES (?, ?, ?, ?, ?)
        """, (card["name"], card["rarity"], card["attack"], card["defense"], card["ability"]))
    
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

# ══════════════════════════════════════════════════════════
#  CARD DATABASE FUNCTIONS
# ══════════════════════════════════════════════════════════

def get_card_by_id(card_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE card_id = ?", (card_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_card_by_name(name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_cards(user_id, rarity=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if rarity:
        c.execute("""
            SELECT uc.*, c.name, c.rarity, c.attack, c.defense, c.ability
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = ? AND c.rarity = ?
            ORDER BY c.rarity DESC, c.name
        """, (user_id, rarity))
    else:
        c.execute("""
            SELECT uc.*, c.name, c.rarity, c.attack, c.defense, c.ability
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = ?
            ORDER BY c.rarity DESC, c.name
        """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_collection_cards(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT uc.*, c.name, c.rarity, c.attack, c.defense, c.ability
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.card_id
        WHERE uc.user_id = ? AND uc.is_collection = 1
        ORDER BY c.rarity DESC, c.name
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_battle_cards(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT ubd.*, c.name, c.rarity, c.attack, c.defense, c.ability
        FROM user_battle_deck ubd
        JOIN cards c ON ubd.card_id = c.card_id
        WHERE ubd.user_id = ?
        ORDER BY ubd.slot
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_card_to_user(user_id, card_id, is_collection=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, quantity FROM user_cards 
        WHERE user_id = ? AND card_id = ? AND is_collection = ?
    """, (user_id, card_id, is_collection))
    row = c.fetchone()
    if row:
        c.execute("UPDATE user_cards SET quantity = quantity + 1 WHERE id = ?", (row[0],))
    else:
        c.execute("""
            INSERT INTO user_cards (user_id, card_id, quantity, is_collection)
            VALUES (?, ?, 1, ?)
        """, (user_id, card_id, is_collection))
    conn.commit()
    conn.close()

def remove_card_from_user(user_id, card_id, quantity=1, is_collection=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, quantity FROM user_cards 
        WHERE user_id = ? AND card_id = ? AND is_collection = ?
    """, (user_id, card_id, is_collection))
    row = c.fetchone()
    if row:
        if row[1] <= quantity:
            c.execute("DELETE FROM user_cards WHERE id = ?", (row[0],))
        else:
            c.execute("UPDATE user_cards SET quantity = quantity - ? WHERE id = ?", (quantity, row[0]))
    conn.commit()
    conn.close()

def equip_battle_card(user_id, card_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM user_battle_deck WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    if count >= MAX_BATTLE_DECK:
        conn.close()
        return False
    c.execute("SELECT MAX(slot) FROM user_battle_deck WHERE user_id = ?", (user_id,))
    max_slot = c.fetchone()[0] or 0
    c.execute("""
        INSERT INTO user_battle_deck (user_id, card_id, slot)
        VALUES (?, ?, ?)
    """, (user_id, card_id, max_slot + 1))
    c.execute("UPDATE user_cards SET is_equipped = 1 WHERE user_id = ? AND card_id = ?", (user_id, card_id))
    conn.commit()
    conn.close()
    return True

def unequip_battle_card(user_id, card_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM user_battle_deck WHERE user_id = ? AND card_id = ?", (user_id, card_id))
    c.execute("""
        UPDATE user_cards SET is_equipped = 0 
        WHERE user_id = ? AND card_id = ? AND is_equipped = 1
    """, (user_id, card_id))
    conn.commit()
    conn.close()

def get_random_card_by_rarity(rarity):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_random_card_weighted():
    r = random.randint(1, 100)
    if r <= 40:
        rarity = "common"
    elif r <= 70:
        rarity = "rare"
    elif r <= 90:
        rarity = "epic"
    elif r <= 98:
        rarity = "legendary"
    else:
        rarity = "mythic"
    return get_random_card_by_rarity(rarity)

def get_user_card_quantity(user_id, card_id, is_collection=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT quantity FROM user_cards 
        WHERE user_id = ? AND card_id = ? AND is_collection = ?
    """, (user_id, card_id, is_collection))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def upgrade_card(user_id, card_id):
    card = get_card_by_id(card_id)
    if not card:
        return None, "Card not found"
    
    current_rarity = card["rarity"]
    if current_rarity == "mythic":
        return None, "Mythic cards cannot be upgraded"
    
    next_rarity_idx = RARITY_ORDER.index(current_rarity) + 1
    if next_rarity_idx >= len(RARITY_ORDER):
        return None, "Cannot upgrade further"
    
    next_rarity = RARITY_ORDER[next_rarity_idx]
    next_card = get_random_card_by_rarity(next_rarity)
    if not next_card:
        return None, "No upgrade target available"
    
    qty = get_user_card_quantity(user_id, card_id, is_collection=0)
    if qty < UPGRADE_COST:
        return None, f"Need {UPGRADE_COST} copies, you have {qty}"
    
    remove_card_from_user(user_id, card_id, UPGRADE_COST, is_collection=0)
    add_card_to_user(user_id, next_card["card_id"], is_collection=0)
    
    return next_card, None

# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

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

def rarity_emoji(rarity):
    return CARD_RARITIES.get(rarity, {}).get("emoji", "⚪")

# ══════════════════════════════════════════════════════════
#  PHASE 1 — PROFILE COMMANDS
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
            f"/cardbook — Your cards\n"
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
                prot = f"\n🛡️ Protected until: {pt.strftime('%d %b %H:%M')}"
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
        f"⚔️ Wins: {db_user['wins']}\n"
        f"💀 Losses: {db_user['losses']}\n"
        f"🎯 Win Rate: {win_rate}%\n"
        f"🔥 Streak: {db_user['current_streak']}\n"
        f"🏆 Best: {db_user['best_streak']}\n"
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
        "/daily — Daily gold reward\n"
        "/rob @user — Rob a player\n"
        "/protect — Buy protection\n"
        "/leaderboard — Top players\n\n"
        "🃏 Cards\n"
        "/cardbook — View collection\n"
        "/cards — Manage battle deck\n"
        "/upgrade — Upgrade cards\n\n"
        "⚔️ Battle (Coming Soon)\n"
        "/battle — Start war\n"
        "/join — Join battle\n"
        "/draft — Pick cards"
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
                bot.reply_to(message,
                    f"⏰ Already claimed today!\n"
                    f"Next reward in: {hours}h {mins}m"
                )
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
    smallest = get_smallest_kingdom()
    if kingdom == smallest:
        bonus_pct += 15

    bonus_amount = int(base_reward * bonus_pct / 100)
    total_reward = base_reward + bonus_amount

    # Day 7 bonus card
    bonus_card_text = ""
    if daily_streak == 7:
        bonus_card = get_random_card_by_rarity("rare")
        if bonus_card:
            add_card_to_user(user.id, bonus_card["card_id"], is_collection=1)
            bonus_card_text = f"\n🎴 Collection Card: {rarity_emoji(bonus_card['rarity'])} {bonus_card['name']}!"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE users SET
            gold = gold + ?,
            daily_streak = ?,
            last_daily = ?
        WHERE user_id = ?
    """, (total_reward, daily_streak, now.isoformat(), user.id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
              (user.id, "credit", total_reward, f"Daily reward day {daily_streak}"))
    conn.commit()
    conn.close()

    db_user = get_user(user.id)
    bonus_text = f"\n🎁 Kingdom Bonus: +{bonus_amount} ({bonus_pct}%)" if bonus_pct > 0 else ""

    bot.reply_to(message,
        f"🎁 Daily Reward!\n\n"
        f"Day {daily_streak}/7 Streak\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Reward: +{base_reward} Gold{bonus_text}{bonus_card_text}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Total Gold: {db_user['gold']:,}\n\n"
        f"{'🔥 ' * min(daily_streak, 7)}Come back tomorrow!"
    )

@bot.message_handler(commands=["protect"])
def cmd_protect(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    PROTECTION_OPTIONS = {
        "1h":  {"hours": 1,    "cost": 100,  "label": "1 Hour"},
        "24h": {"hours": 24,   "cost": 500,  "label": "24 Hours"},
        "7d":  {"hours": 168,  "cost": 2000, "label": "7 Days"},
    }

    args = message.text.split()
    if len(args) < 2 or args[1] not in PROTECTION_OPTIONS:
        current_prot = ""
        if db_user.get("protection_until"):
            try:
                pt = datetime.fromisoformat(db_user["protection_until"])
                if pt > datetime.now():
                    current_prot = f"\n🛡️ Active until: {pt.strftime('%d %b %H:%M')}\n"
            except:
                pass
        bot.reply_to(message,
            f"🛡️ Protection Options{current_prot}\n"
            f"━━━━━━━━━━━━━━\n"
            f"/protect 1h  — 1 Hour | 100 Gold\n"
            f"/protect 24h — 24 Hours | 500 Gold\n"
            f"/protect 7d  — 7 Days | 2,000 Gold\n\n"
            f"💰 Your Gold: {db_user['gold']:,}"
        )
        return

    opt = PROTECTION_OPTIONS[args[1]]
    cost = opt["cost"]

    if db_user["gold"] < cost:
        bot.reply_to(message,
            f"❌ Not enough gold!\n"
            f"Need: {cost:,} | Have: {db_user['gold']:,}"
        )
        return

    until = datetime.now() + timedelta(hours=opt["hours"])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET gold = gold - ?, protection_until = ? WHERE user_id = ?",
              (cost, until.isoformat(), user.id))
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
              (user.id, "debit", cost, f"Protection {opt['label']}"))
    conn.commit()
    conn.close()

    db_user = get_user(user.id)
    bot.reply_to(message,
        f"🛡️ Protection Active!\n\n"
        f"Duration: {opt['label']}\n"
        f"Until: {until.strftime('%d %b %H:%M')}\n"
        f"Cost: -{cost:,} Gold\n"
        f"💰 Remaining: {db_user['gold']:,}"
    )

@bot.message_handler(commands=["rob"])
def cmd_rob(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    robber = get_or_create_user(user.id, username, display)

    if not robber.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    if robber["level"] <= BEGINNER_PROTECTION_LEVEL:
        bot.reply_to(message,
            f"🔰 You are a beginner (Level {robber['level']})!\n"
            f"Rob unlocks at Level {BEGINNER_PROTECTION_LEVEL + 1}."
        )
        return

    if robber.get("protection_until"):
        try:
            pt = datetime.fromisoformat(robber["protection_until"])
            if pt > datetime.now():
                bot.reply_to(message,
                    "🛡️ Protected players cannot rob others!\n"
                    "Your protection must expire first."
                )
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
                mentioned = message.text[entity.offset:entity.offset + entity.length]
                uname = mentioned.lstrip("@")
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username = ?", (uname,))
                row = c.fetchone()
                conn.close()
                if row:
                    target_user = dict(row)

    if not target_user:
        bot.reply_to(message,
            "❌ No target found!\n\n"
            "Usage:\n"
            "/rob @username\n"
            "Or reply to someone's message with /rob"
        )
        return

    if target_user["user_id"] == user.id:
        bot.reply_to(message, "😂 Rob yourself? Really?")
        return

    if target_user.get("protection_until"):
        try:
            pt = datetime.fromisoformat(target_user["protection_until"])
            if pt > datetime.now():
                bot.reply_to(message,
                    f"🛡️ {target_user['display_name']} is protected!\n"
                    f"Protection until: {pt.strftime('%d %b %H:%M')}"
                )
                return
        except:
            pass

    if target_user["level"] <= BEGINNER_PROTECTION_LEVEL:
        bot.reply_to(message,
            f"🔰 {target_user['display_name']} is a beginner!\n"
            f"Cannot rob players under Level {BEGINNER_PROTECTION_LEVEL + 1}."
        )
        return

    if target_user["gold"] < 100:
        bot.reply_to(message,
            f"💸 {target_user['display_name']} is too poor!\n"
            f"They only have {target_user['gold']} Gold."
        )
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
        c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                  (user.id, "credit", stolen, f"Rob from {target_user['display_name']}"))
        c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                  (target_user["user_id"], "debit", stolen, f"Robbed by {display}"))
        conn.commit()
        conn.close()

        robber = get_user(user.id)
        bot.reply_to(message,
            f"✅ Rob Successful!\n\n"
            f"🦹 You robbed {target_user['display_name']}\n"
            f"💰 Stolen: {stolen:,} Gold\n"
            f"💰 Your Gold: {robber['gold']:,}"
        )
        try:
            bot.send_message(target_user["user_id"],
                f"🚨 You were robbed!\n"
                f"🦹 {display} stole {stolen:,} Gold!\n"
                f"Use /protect to stay safe."
            )
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
            f"❌ Rob Failed!\n\n"
            f"🦹 You got caught!\n"
            f"💸 Fine: -{fine:,} Gold\n"
            f"💰 Your Gold: {robber['gold']:,}"
        )

@bot.message_handler(commands=["leaderboard"])
def cmd_leaderboard(message):
    players = get_top_players(10)
    kingdom_data = get_kingdom_stats()

    text = "🏆 Leaderboard\n\n"
    text += "💰 Top Players\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(players):
        medal = medals[i] if i < 3 else f"{i+1}."
        k = KINGDOMS.get(p.get("kingdom", ""), {})
        emoji = k.get("emoji", "⚔️")
        text += f"{medal} {emoji} {p['display_name']}: {p['gold']:,} Gold\n"

    text += "\n🏰 Kingdom Rankings\n"
    for i, k in enumerate(kingdom_data):
        kdata = KINGDOMS.get(k["kingdom"], {})
        emoji = kdata.get("emoji", "⚔️")
        text += f"{i+1}. {emoji} {k['kingdom'].capitalize()}: {k['member_count']} members\n"

    bot.reply_to(message, text)

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
        f"👥 Total: {total} | No Kingdom: {no_kingdom}\n\n"
        f"🏰 Kingdoms\n{k_lines}\n"
        f"💰 Economy\n"
        f"Total: {int(gold_row[0] or 0):,} Gold\n"
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
#  PHASE 3 — CARDS
# ══════════════════════════════════════════════════════════

@bot.message_handler(commands=["cardbook"])
def cmd_cardbook(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    args = message.text.split()
    rarity_filter = None
    if len(args) > 1 and args[1].lower() in CARD_RARITIES:
        rarity_filter = args[1].lower()

    cards = get_user_cards(user.id, rarity_filter)
    collection = get_user_collection_cards(user.id)

    if not cards and not collection:
        bot.reply_to(message,
            "📖 Your Card Book is empty!\n\n"
            "Use /daily to get rewards.\n"
            "Day 7 streak gives a Rare card!"
        )
        return

    text = f"📖 {display}'s Card Book\n"
    if rarity_filter:
        text = f"📖 {display}'s {rarity_filter.upper()} Cards\n"

    text += "━━━━━━━━━━━━━━\n"

    # Battle cards
    battle_cards = [c for c in cards if c.get("is_collection") == 0]
    if battle_cards:
        text += "\n⚔️ Battle Cards:\n"
        current_rarity = None
        for card in battle_cards:
            if card["rarity"] != current_rarity:
                current_rarity = card["rarity"]
                text += f"\n{rarity_emoji(current_rarity)} {current_rarity.upper()}\n"
            qty = f" x{card['quantity']}" if card['quantity'] > 1 else ""
            eq = " [E]" if card.get("is_equipped") else ""
            text += f"  {card['name']}{qty}{eq}\n"
            text += f"     ATK:{card['attack']} DEF:{card['defense']} | {card['ability']}\n"

    # Collection cards
    if collection:
        text += "\n🎴 Collection Cards:\n"
        current_rarity = None
        for card in collection:
            if card["rarity"] != current_rarity:
                current_rarity = card["rarity"]
                text += f"\n{rarity_emoji(current_rarity)} {current_rarity.upper()}\n"
            qty = f" x{card['quantity']}" if card['quantity'] > 1 else ""
            text += f"  {card['name']}{qty}\n"

    text += "\n━━━━━━━━━━━━━━\n"
    text += f"Total: {len(cards)} battle | {len(collection)} collection"

    bot.reply_to(message, text)

@bot.message_handler(commands=["cards"])
def cmd_cards(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    args = message.text.split()

    # Show battle deck
    if len(args) == 1:
        deck = get_user_battle_cards(user.id)
        all_cards = get_user_cards(user.id)

        text = f"🃏 {display}'s Battle Deck\n"
        text += f"━━━━━━━━━━━━━━\n"

        if deck:
            text += "\n⚔️ Equipped:\n"
            for card in deck:
                text += f"  {rarity_emoji(card['rarity'])} {card['name']}\n"
                text += f"     ATK:{card['attack']} DEF:{card['defense']} | {card['ability']}\n"
        else:
            text += "\n⚔️ No cards equipped!\n"

        available = [c for c in all_cards if c.get("is_equipped") == 0 and c.get("is_collection") == 0]
        if available:
            text += "\n📦 Available:\n"
            for card in available[:10]:
                qty = f" x{card['quantity']}" if card['quantity'] > 1 else ""
                text += f"  {rarity_emoji(card['rarity'])} {card['name']}{qty}\n"

        text += f"\n━━━━━━━━━━━━━━\n"
        text += f"Deck: {len(deck)}/{MAX_BATTLE_DECK}\n\n"
        text += "Commands:\n"
        text += "/cards equip <name>\n"
        text += "/cards unequip <name>"

        bot.reply_to(message, text)
        return

    # Equip card
    if len(args) >= 3 and args[1].lower() == "equip":
        card_name = " ".join(args[2:])
        card = get_card_by_name(card_name)
        if not card:
            bot.reply_to(message, f"❌ Card '{card_name}' not found!")
            return

        qty = get_user_card_quantity(user.id, card["card_id"], is_collection=0)
        if qty < 1:
            bot.reply_to(message, f"❌ You don't have {card_name}!")
            return

        # Check if already equipped
        deck = get_user_battle_cards(user.id)
        if any(d["card_id"] == card["card_id"] for d in deck):
            bot.reply_to(message, f"⚠️ {card_name} is already equipped!")
            return

        if len(deck) >= MAX_BATTLE_DECK:
            bot.reply_to(message, f"❌ Deck full! Max {MAX_BATTLE_DECK} cards.\nUse /cards unequip first.")
            return

        equip_battle_card(user.id, card["card_id"])
        bot.reply_to(message,
            f"✅ Equipped!\n\n"
            f"{rarity_emoji(card['rarity'])} {card['name']}\n"
            f"ATK:{card['attack']} DEF:{card['defense']}\n"
            f"Deck: {len(deck) + 1}/{MAX_BATTLE_DECK}"
        )
        return

    # Unequip card
    if len(args) >= 3 and args[1].lower() == "unequip":
        card_name = " ".join(args[2:])
        card = get_card_by_name(card_name)
        if not card:
            bot.reply_to(message, f"❌ Card '{card_name}' not found!")
            return

        deck = get_user_battle_cards(user.id)
        if not any(d["card_id"] == card["card_id"] for d in deck):
            bot.reply_to(message, f"⚠️ {card_name} is not in your deck!")
            return

        unequip_battle_card(user.id, card["card_id"])
        bot.reply_to(message,
            f"✅ Unequipped!\n\n"
            f"{rarity_emoji(card['rarity'])} {card['name']}\n"
            f"Deck: {len(deck) - 1}/{MAX_BATTLE_DECK}"
        )
        return

    bot.reply_to(message,
        "🃏 Card Commands:\n\n"
        "/cards — View deck\n"
        "/cards equip <name> — Add to deck\n"
        "/cards unequip <name> — Remove from deck"
    )

@bot.message_handler(commands=["upgrade"])
def cmd_upgrade(message):
    user = message.from_user
    display = get_display(user)
    username = user.username or str(user.id)
    db_user = get_or_create_user(user.id, username, display)

    if not db_user.get("kingdom"):
        bot.reply_to(message, "⚠️ Choose kingdom first!\nUse /kingdom")
        return

    args = message.text.split()

    # Show upgradeable cards
    if len(args) == 1:
        cards = get_user_cards(user.id)
        upgradeable = [c for c in cards if c.get("quantity", 0) >= UPGRADE_COST and c.get("is_collection") == 0]

        if not upgradeable:
            bot.reply_to(message,
                "⬆️ Upgrade Center\n\n"
                f"Sacrifice {UPGRADE_COST} same cards → 1 higher rarity\n\n"
                "❌ No upgradeable cards!\n"
                "You need 3 copies of the same card."
            )
            return

        text = "⬆️ Upgrade Center\n\n"
        text += f"Sacrifice {UPGRADE_COST} same cards → 1 higher rarity\n\n"
        text += "Available:\n"

        for card in upgradeable:
            next_rarity_idx = RARITY_ORDER.index(card["rarity"]) + 1
            if next_rarity_idx < len(RARITY_ORDER):
                next_r = RARITY_ORDER[next_rarity_idx]
                text += f"\n{rarity_emoji(card['rarity'])} {card['name']} x{card['quantity']}\n"
                text += f"   → {rarity_emoji(next_r)} {next_r.upper()}\n"

        text += "\nUsage: /upgrade <card name>"

        bot.reply_to(message, text)
        return

    # Upgrade specific card
    card_name = " ".join(args[1:])
    card = get_card_by_name(card_name)
    if not card:
        bot.reply_to(message, f"❌ Card '{card_name}' not found!")
        return

    upgraded_card, error = upgrade_card(user.id, card["card_id"])
    if error:
        bot.reply_to(message, f"❌ {error}")
        return

    bot.reply_to(message,
        f"✨ Upgrade Successful!\n\n"
        f"{rarity_emoji(card['rarity'])} {card['name']} x{UPGRADE_COST}\n"
        f"   ↓\n"
        f"{rarity_emoji(upgraded_card['rarity'])} {upgraded_card['name']}\n\n"
        f"ATK:{upgraded_card['attack']} DEF:{upgraded_card['defense']}\n"
        f"Ability: {upgraded_card['ability']}"
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
    print("Kingdom Wars Phase 1+2+3 + Akari bot running...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
