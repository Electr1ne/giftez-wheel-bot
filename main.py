import asyncio
import hashlib
import hmac
import json
import os
import random
import sqlite3
import time
import uuid
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

# ==========================================
# НАСТРОЙКИ ОКРУЖЕНИЯ
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
_raw_vercel_url = (os.getenv("VERCEL_APP_URL") or "").strip().rstrip("/")
VERCEL_APP_URL = _raw_vercel_url.removesuffix("/admin.html").removesuffix("/index.html")

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
CHANNEL_CHAT_ID = os.getenv("CHANNEL_CHAT_ID")

_env_admins = {int(x.strip()) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x.strip().isdigit()}
ADMIN_IDS = _env_admins | {963968579}

PORT = int(os.getenv("PORT") or 3000)
DB_PATH = os.getenv("DB_PATH") or "roulette.db"

COOLDOWN_SEC = 24 * 60 * 60
SUB_CACHE_TTL_SEC = 60

# Старт зимнего ивента: 1 декабря 2026, 00:00:00 МСК (UTC+3) == 30 ноября 2026, 21:00:00 UTC
EVENT_START_TS = 1796072400
EVENT_END_TS = 1798750800  # 1 января 2027, 00:00:00 МСК

# Параметры общего цикла игры «Лавина»
AV_WAIT_SEC = 5.0
AV_CRASH_PAUSE_SEC = 3.0
AV_SLOT_LEN = 24.0

WITHDRAW_PACKS = [
    {"cost": 15,  "payout": 13, "gift": "bear",   "name": "Мишка (15 ★ → 13 ★)"},
    {"cost": 25,  "payout": 21, "gift": "rose",   "gift_alt": "gift", "name": "Роза (25 ★ → 21 ★)"},
    {"cost": 50,  "payout": 43, "gift": "rocket", "name": "Ракета / Торт / Напиток (50 ★ → 43 ★)"},
    {"cost": 100, "payout": 85, "gift": "ring",   "name": "Кольцо (100 ★ → 85 ★)"},
]

GIFTS_CATALOG = {
    "bear":   {"id": "bear",   "name": "Мишка",   "stars": 15,  "payout": 13,  "icon": "bear.png"},
    "heart":  {"id": "heart",  "name": "Сердце",  "stars": 15,  "payout": 13,  "icon": "heart.png"},
    "rose":   {"id": "rose",   "name": "Роза",    "stars": 25,  "payout": 21,  "icon": "rose.png"},
    "gift":   {"id": "gift",   "name": "Коробка", "stars": 25,  "payout": 21,  "icon": "gift.png"},
    "bottle": {"id": "bottle", "name": "Напиток", "stars": 50,  "payout": 43,  "icon": "bottle.png"},
    "cake":   {"id": "cake",   "name": "Торт",    "stars": 50,  "payout": 43,  "icon": "cake.png"},
    "rocket": {"id": "rocket", "name": "Ракета",  "stars": 50,  "payout": 43,  "icon": "rocket.png"},
    "ring":   {"id": "ring",   "name": "Кольцо",  "stars": 100, "payout": 85,  "icon": "ring.png"},
}

# Ежедневный: сильно урезанные шансы
DAILY_POOL = [
    {"type": "nothing", "weight": 83.5, "label": "Ничего",       "icon": "nothing.png"},
    {"type": "stars",   "min": 1, "max": 1,  "weight": 14.5, "label": "1 ★",          "icon": "star"},
    {"type": "stars",   "min": 2, "max": 3,  "weight": 1.75, "label": "2–3 ★",        "icon": "star"},
    {"type": "gift",    "gift": "bear",      "weight": 0.20, "label": "Мишка (15 ★)", "icon": "bear.png"},
    {"type": "gift",    "gift": "rose",      "weight": 0.05, "label": "Роза (25 ★)",  "icon": "rose.png"},
]

# Усложнённый ивент: больше снежинок на этап, простые награды в звёздах
EVENT_STAGES = [
    {"stage": 1, "points": 60,   "reward_stars": 2,  "title": "Первый иней"},
    {"stage": 2, "points": 180,  "reward_stars": 5,  "title": "Холодный ветер"},
    {"stage": 3, "points": 420,  "reward_stars": 12, "title": "Ледяной рубеж"},
    {"stage": 4, "points": 850,  "reward_stars": 25, "title": "Полярная ночь"},
    {"stage": 5, "points": 1600, "reward_stars": 50, "title": "Повелитель вьюги"},
]

# Единый каталог кейсов
ALL_CASES_CONFIG = {
    "starter": {
        "id": "starter",
        "name": "Стартовый",
        "price": 5,
        "reroll_price": 3,
        "reroll_allowed": True,
        "category": "snowflakes",
        "availability": "permanent",
        "is_winter_new": False,
        "badge": "КЛАССИКА",
        "icon": "starter.png",
        "pool": [
            {"type": "stars", "min": 1, "max": 2, "weight": 89.5, "label": "1–2 ★",        "icon": "star"},
            {"type": "stars", "min": 3, "max": 4, "weight": 9.4,  "label": "3–4 ★",        "icon": "star"},
            {"type": "gift",  "gift": "bear",     "weight": 0.85, "label": "Мишка (15 ★)", "icon": "bear.png"},
            {"type": "gift",  "gift": "rose",     "weight": 0.25, "label": "Роза (25 ★)",  "icon": "rose.png"},
        ],
    },
    "morozniy": {
        "id": "morozniy",
        "name": "Морозный",
        "price": 12,
        "reroll_price": 7,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "permanent",
        "is_winter_new": False,
        "badge": "КЛАССИКА",
        "icon": "morozniy.png",
        "pool": [
            {"type": "stars", "min": 2, "max": 4,  "weight": 88.5, "label": "2–4 ★",          "icon": "star"},
            {"type": "stars", "min": 5, "max": 9,  "weight": 9.8,  "label": "5–9 ★",          "icon": "star"},
            {"type": "gift",  "gift": "heart",     "weight": 1.15, "label": "Сердце (15 ★)",  "icon": "heart.png"},
            {"type": "gift",  "gift": "gift",      "weight": 0.40, "label": "Коробка (25 ★)", "icon": "gift.png"},
            {"type": "gift",  "gift": "bottle",    "weight": 0.15, "label": "Напиток (50 ★)", "icon": "bottle.png"},
        ],
    },
    "sever": {
        "id": "sever",
        "name": "Северный",
        "price": 25,
        "reroll_price": 15,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "permanent",
        "is_winter_new": False,
        "badge": "КЛАССИКА",
        "icon": "sever.png",
        "pool": [
            {"type": "stars", "min": 4,  "max": 10, "weight": 88.5, "label": "4–10 ★",         "icon": "star"},
            {"type": "stars", "min": 11, "max": 18, "weight": 9.9,  "label": "11–18 ★",        "icon": "star"},
            {"type": "gift",  "gift": "cake",       "weight": 0.95, "label": "Торт (50 ★)",    "icon": "cake.png"},
            {"type": "gift",  "gift": "rocket",     "weight": 0.50, "label": "Ракета (50 ★)",  "icon": "rocket.png"},
            {"type": "gift",  "gift": "ring",       "weight": 0.15, "label": "Кольцо (100 ★)", "icon": "ring.png"},
        ],
    },
    "newyear": {
        "id": "newyear",
        "name": "Новогодний",
        "price": 50,
        "reroll_price": 30,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "permanent",
        "is_winter_new": False,
        "badge": "КЛАССИКА",
        "icon": "newyear.png",
        "pool": [
            {"type": "stars", "min": 18,  "max": 35,  "weight": 85.0, "label": "18–35 ★",           "icon": "star"},
            {"type": "stars", "min": 38,  "max": 62,  "weight": 12.2, "label": "38–62 ★",           "icon": "star"},
            {"type": "stars", "min": 70,  "max": 95,  "weight": 1.9,  "label": "70–95 ★",           "icon": "star"},
            {"type": "gift",  "gift": "ring",         "weight": 0.75, "label": "Кольцо (100 ★)",    "icon": "ring.png"},
            {"type": "stars", "min": 140, "max": 190, "weight": 0.15, "label": "Джекпот 140–190 ★", "icon": "star"},
        ],
    },
    "iney": {
        "id": "iney",
        "name": "Иней",
        "price": 3,
        "reroll_price": 2,
        "reroll_allowed": True,
        "category": "snowflakes",
        "availability": "permanent",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "badge": "ДО 10 ★",
        "icon": "iney.png",
        "pool": [
            {"type": "stars", "min": 1, "max": 1, "weight": 84.0, "label": "1 ★",          "icon": "star"},
            {"type": "stars", "min": 2, "max": 3, "weight": 15.3, "label": "2–3 ★",        "icon": "star"},
            {"type": "gift",  "gift": "bear",     "weight": 0.70, "label": "Мишка (15 ★)", "icon": "bear.png"},
        ],
    },
    "icicle": {
        "id": "icicle",
        "name": "Сосулька",
        "price": 8,
        "reroll_price": 5,
        "reroll_allowed": True,
        "category": "snowflakes",
        "availability": "permanent",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "badge": "ЗИМА",
        "icon": "icicle.png",
        "pool": [
            {"type": "stars", "min": 2, "max": 4, "weight": 88.5, "label": "2–4 ★",         "icon": "star"},
            {"type": "stars", "min": 5, "max": 7, "weight": 10.3, "label": "5–7 ★",         "icon": "star"},
            {"type": "gift",  "gift": "heart",    "weight": 0.90, "label": "Сердце (15 ★)", "icon": "heart.png"},
            {"type": "gift",  "gift": "rose",     "weight": 0.30, "label": "Роза (25 ★)",   "icon": "rose.png"},
        ],
    },
    "ldinka": {
        "id": "ldinka",
        "name": "Льдинка",
        "price": 10,
        "reroll_price": 6,
        "reroll_allowed": True,
        "category": "snowflakes",
        "availability": "permanent",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "badge": "ЗИМА",
        "icon": "ldinka.png",
        "pool": [
            {"type": "stars", "min": 2, "max": 5, "weight": 87.8, "label": "2–5 ★",          "icon": "star"},
            {"type": "stars", "min": 6, "max": 9, "weight": 10.7, "label": "6–9 ★",          "icon": "star"},
            {"type": "gift",  "gift": "bear",     "weight": 1.05, "label": "Мишка (15 ★)",   "icon": "bear.png"},
            {"type": "gift",  "gift": "gift",     "weight": 0.45, "label": "Коробка (25 ★)", "icon": "gift.png"},
        ],
    },
    "first_snow": {
        "id": "first_snow",
        "name": "Первый снег",
        "price": 15,
        "reroll_price": 9,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "timed",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "ends_at": EVENT_START_TS + 14 * 86400,
        "badge": "ВРЕМЕННЫЙ",
        "icon": "first_snow.png",
        "pool": [
            {"type": "stars", "min": 3, "max": 7,  "weight": 87.0, "label": "3–7 ★",       "icon": "star"},
            {"type": "stars", "min": 8, "max": 13, "weight": 11.4, "label": "8–13 ★",      "icon": "star"},
            {"type": "gift",  "gift": "rose",      "weight": 1.20, "label": "Роза (25 ★)", "icon": "rose.png"},
            {"type": "gift",  "gift": "cake",      "weight": 0.40, "label": "Торт (50 ★)", "icon": "cake.png"},
        ],
    },
    "snow_chest": {
        "id": "snow_chest",
        "name": "Снежный сундук",
        "price": 20,
        "reroll_price": 12,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "limited",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "default_max_opens": 150,
        "badge": "ЛИМИТ",
        "icon": "snow_chest.png",
        "pool": [
            {"type": "stars", "min": 4,  "max": 10, "weight": 86.2, "label": "4–10 ★",         "icon": "star"},
            {"type": "stars", "min": 11, "max": 19, "weight": 11.8, "label": "11–19 ★",        "icon": "star"},
            {"type": "gift",  "gift": "gift",       "weight": 1.40, "label": "Коробка (25 ★)", "icon": "gift.png"},
            {"type": "gift",  "gift": "rocket",     "weight": 0.60, "label": "Ракета (50 ★)",  "icon": "rocket.png"},
        ],
    },
    "blizzard": {
        "id": "blizzard",
        "name": "Метель",
        "price": 35,
        "reroll_price": 21,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "permanent",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "badge": "ПОСТОЯННЫЙ",
        "icon": "blizzard.png",
        "pool": [
            {"type": "stars", "min": 9,  "max": 18, "weight": 86.0, "label": "9–18 ★",         "icon": "star"},
            {"type": "stars", "min": 19, "max": 31, "weight": 12.1, "label": "19–31 ★",        "icon": "star"},
            {"type": "gift",  "gift": "cake",       "weight": 1.40, "label": "Торт (50 ★)",    "icon": "cake.png"},
            {"type": "gift",  "gift": "ring",       "weight": 0.50, "label": "Кольцо (100 ★)", "icon": "ring.png"},
        ],
    },
    "winter_safe": {
        "id": "winter_safe",
        "name": "Зимний сейф",
        "price": 45,
        "reroll_price": 27,
        "reroll_allowed": True,
        "category": "drifts",
        "availability": "limited",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "default_max_opens": 80,
        "badge": "ЛИМИТ",
        "icon": "winter_safe.png",
        "pool": [
            {"type": "stars", "min": 13, "max": 24, "weight": 85.4, "label": "13–24 ★",        "icon": "star"},
            {"type": "stars", "min": 25, "max": 42, "weight": 12.3, "label": "25–42 ★",        "icon": "star"},
            {"type": "gift",  "gift": "bottle",     "weight": 1.55, "label": "Напиток (50 ★)", "icon": "bottle.png"},
            {"type": "gift",  "gift": "ring",       "weight": 0.75, "label": "Кольцо (100 ★)", "icon": "ring.png"},
        ],
    },
    "pre_newyear": {
        "id": "pre_newyear",
        "name": "Предновогодний",
        "price": 60,
        "reroll_price": 36,
        "reroll_allowed": True,
        "category": "aurora",
        "availability": "timed",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "ends_at": EVENT_END_TS,
        "badge": "СЕЗОН",
        "icon": "pre_newyear.png",
        "pool": [
            {"type": "stars", "min": 20, "max": 36,  "weight": 85.0, "label": "20–36 ★",        "icon": "star"},
            {"type": "stars", "min": 38, "max": 58,  "weight": 12.6, "label": "38–58 ★",        "icon": "star"},
            {"type": "gift",  "gift": "ring",        "weight": 1.90, "label": "Кольцо (100 ★)", "icon": "ring.png"},
            {"type": "stars", "min": 90, "max": 120, "weight": 0.50, "label": "90–120 ★",       "icon": "star"},
        ],
    },
    "abs_zero": {
        "id": "abs_zero",
        "name": "Абсолютный ноль",
        "price": 75,
        "reroll_price": 45,
        "reroll_allowed": True,
        "category": "aurora",
        "availability": "permanent",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "badge": "VIP",
        "icon": "abs_zero.png",
        "pool": [
            {"type": "stars", "min": 26,  "max": 46,  "weight": 84.5, "label": "26–46 ★",        "icon": "star"},
            {"type": "stars", "min": 48,  "max": 74,  "weight": 12.9, "label": "48–74 ★",        "icon": "star"},
            {"type": "gift",  "gift": "ring",         "weight": 2.00, "label": "Кольцо (100 ★)", "icon": "ring.png"},
            {"type": "stars", "min": 110, "max": 150, "weight": 0.60, "label": "110–150 ★",      "icon": "star"},
        ],
    },
    "winter_crown": {
        "id": "winter_crown",
        "name": "Корона зимы",
        "price": 100,
        "reroll_price": 60,
        "reroll_allowed": True,
        "category": "aurora",
        "availability": "limited",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "default_max_opens": 35,
        "badge": "ЛИМИТ",
        "icon": "winter_crown.png",
        "pool": [
            {"type": "stars", "min": 36,  "max": 64,  "weight": 84.2, "label": "36–64 ★",        "icon": "star"},
            {"type": "stars", "min": 66,  "max": 98,  "weight": 13.0, "label": "66–98 ★",        "icon": "star"},
            {"type": "gift",  "gift": "ring",         "weight": 2.15, "label": "Кольцо (100 ★)", "icon": "ring.png"},
            {"type": "stars", "min": 145, "max": 200, "weight": 0.65, "label": "145–200 ★",      "icon": "star"},
        ],
    },
    "ice_throne": {
        "id": "ice_throne",
        "name": "Ледяной трон",
        "price": 150,
        "reroll_price": 90,
        "reroll_allowed": True,
        "category": "aurora",
        "availability": "limited",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "default_max_opens": 20,
        "badge": "150 ★ MAX",
        "icon": "ice_throne.png",
        "pool": [
            {"type": "stars", "min": 55,  "max": 92,  "weight": 83.8, "label": "55–92 ★",        "icon": "star"},
            {"type": "stars", "min": 95,  "max": 142, "weight": 13.2, "label": "95–142 ★",       "icon": "star"},
            {"type": "gift",  "gift": "ring",         "weight": 2.25, "label": "Кольцо (100 ★)", "icon": "ring.png"},
            {"type": "stars", "min": 200, "max": 270, "weight": 0.75, "label": "200–270 ★",      "icon": "star"},
        ],
    },
    "thin_ice": {
        "id": "thin_ice",
        "name": "Тонкий лёд",
        "price": 50,
        "reroll_price": 0,
        "reroll_allowed": False,
        "special_mode": "thin_ice",
        "category": "thin_ice",
        "availability": "limited",
        "is_winter_new": True,
        "starts_at": EVENT_START_TS,
        "default_max_opens": 60,
        "badge": "БЕЗ ПЕРЕКРУТА",
        "icon": "thin_ice.png",
        "pool": [
            {"type": "nothing", "weight": 76.0, "label": "Ничего",     "icon": "nothing.png"},
            {"type": "stars",   "min": 1,   "max": 1,   "weight": 18.5, "label": "1 ★",        "icon": "star"},
            {"type": "stars",   "min": 100, "max": 100, "weight": 5.5,  "label": "100 ★ (x2)", "icon": "star"},
        ],
    },
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_free_spin INTEGER DEFAULT 0,
            reminded_24h INTEGER DEFAULT 1,
            stars_balance INTEGER DEFAULT 0,
            wager_left INTEGER DEFAULT 0,
            total_spins INTEGER DEFAULT 0,
            sub_cached INTEGER DEFAULT 0,
            sub_checked_at INTEGER DEFAULT 0,
            event_points INTEGER DEFAULT 0,
            event_claimed_stage INTEGER DEFAULT 0
        )
    """)

    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}
    for col_sql in [
        "ALTER TABLE users ADD COLUMN stars_balance INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN wager_left INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_spins INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN sub_cached INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN sub_checked_at INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN event_points INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN event_claimed_stage INTEGER DEFAULT 0",
    ]:
        col_name = col_sql.split("ADD COLUMN ")[1].split()[0]
        if col_name not in existing_cols:
            cur.execute(col_sql)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('maintenance_mode', '0')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('update_mode', '0')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('ui_public_version', 'v1')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('ui_admin_version', 'v2')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('event_snowflakes_enabled', '1')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('avalanche_history_reset_at', '0')")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS case_stock (
            case_id TEXT PRIMARY KEY,
            opens_count INTEGER DEFAULT 0,
            max_opens INTEGER DEFAULT 50
        )
    """)
    for cid, cfg in ALL_CASES_CONFIG.items():
        if cfg.get("availability") == "limited":
            cur.execute(
                "INSERT OR IGNORE INTO case_stock (case_id, opens_count, max_opens) VALUES (?, 0, ?)",
                (cid, int(cfg.get("default_max_opens", 50))),
            )

    # Бесплатные открытия кейсов у игроков
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_free_cases (
            user_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, case_id)
        )
    """)

    # Общие раунды игры «Лавина»
    cur.execute("""
        CREATE TABLE IF NOT EXISTS avalanche_shared_rounds (
            round_id TEXT PRIMARY KEY,
            epoch_idx INTEGER NOT NULL,
            crash_mult REAL NOT NULL,
            started_at INTEGER NOT NULL,
            finalized INTEGER DEFAULT 0
        )
    """)

    # Ставки реальных игроков в раундах «Лавины»
    cur.execute("""
        CREATE TABLE IF NOT EXISTS avalanche_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            bet_stars INTEGER NOT NULL,
            auto_mult REAL DEFAULT 0,
            status TEXT DEFAULT 'playing',
            cashout_mult REAL DEFAULT 0,
            payout INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            UNIQUE(round_id, user_id)
        )
    """)

    # История завершённых иксов «Лавины»
    cur.execute("""
        CREATE TABLE IF NOT EXISTS avalanche_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id TEXT UNIQUE NOT NULL,
            crash_mult REAL NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            cost_stars INTEGER NOT NULL,
            payout_stars INTEGER NOT NULL,
            breakdown TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            status TEXT DEFAULT 'processing'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward_stars INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER NOT NULL DEFAULT 1,
            uses_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            reward_type TEXT DEFAULT 'stars',
            case_id TEXT DEFAULT '',
            reward_cases INTEGER DEFAULT 0
        )
    """)
    cur.execute("PRAGMA table_info(promocodes)")
    promo_cols = {row[1] for row in cur.fetchall()}
    for col_sql in [
        "ALTER TABLE promocodes ADD COLUMN reward_type TEXT DEFAULT 'stars'",
        "ALTER TABLE promocodes ADD COLUMN case_id TEXT DEFAULT ''",
        "ALTER TABLE promocodes ADD COLUMN reward_cases INTEGER DEFAULT 0",
    ]:
        col_name = col_sql.split("ADD COLUMN ")[1].split()[0]
        if col_name not in promo_cols:
            cur.execute(col_sql)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            activated_at INTEGER NOT NULL,
            UNIQUE(code, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_drops (
            drop_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            drop_type TEXT NOT NULL,
            gift_id TEXT DEFAULT '',
            stars_amount INTEGER DEFAULT 0,
            label TEXT DEFAULT '',
            icon TEXT DEFAULT '',
            rerolled INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def get_system_modes() -> dict:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT key, value FROM app_settings
        WHERE key IN (
            'maintenance_mode', 'update_mode', 'ui_public_version',
            'ui_admin_version', 'event_snowflakes_enabled', 'avalanche_history_reset_at'
        )
        """
    )
    rows = dict(cur.fetchall())
    conn.close()
    return {
        "maintenance": rows.get("maintenance_mode", "0") == "1",
        "update": rows.get("update_mode", "0") == "1",
        "ui_public_version": rows.get("ui_public_version", "v1"),
        "ui_admin_version": rows.get("ui_admin_version", "v2"),
        "event_snowflakes_enabled": rows.get("event_snowflakes_enabled", "1") == "1",
        "avalanche_history_reset_at": int(rows.get("avalanche_history_reset_at", "0") or "0"),
    }


def set_system_mode(mode: str, enabled: bool) -> dict:
    key_map = {"maintenance": "maintenance_mode", "update": "update_mode"}
    if mode not in key_map:
        raise ValueError("Invalid mode")
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
        (key_map[mode], "1" if enabled else "0"),
    )
    conn.commit()
    conn.close()
    return get_system_modes()


def set_ui_version(scope: str, version: str) -> dict:
    if scope not in ("public", "admin") or version not in ("v1", "v2"):
        raise ValueError("Invalid ui version params")
    db_key = "ui_public_version" if scope == "public" else "ui_admin_version"
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (db_key, version))
    conn.commit()
    conn.close()
    return get_system_modes()


def resolve_user_ui_version(uid: int, modes: dict | None = None) -> str:
    m = modes or get_system_modes()
    if uid in ADMIN_IDS:
        return m.get("ui_admin_version", "v2")
    return m.get("ui_public_version", "v1")


def is_event_unlocked_for_user(uid: int, now_ts: int | None = None) -> bool:
    now = now_ts if now_ts is not None else int(time.time())
    if now >= EVENT_START_TS:
        return True
    if uid in ADMIN_IDS and resolve_user_ui_version(uid) == "v2":
        return True
    return False


def is_case_visible_for_user(cfg: dict, uid: int, now_ts: int) -> bool:
    if not cfg.get("is_winter_new"):
        return True
    ends_at = int(cfg.get("ends_at", 0) or 0)
    if ends_at > 0 and now_ts >= ends_at:
        return False
    return is_event_unlocked_for_user(uid, now_ts)


def ensure_user(user_id: int, username: str, first_name: str) -> None:
    clean_uname = (username or "").lstrip("@").strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_free_spin, reminded_24h, stars_balance, wager_left, total_spins, sub_cached, sub_checked_at, event_points, event_claimed_stage)
            VALUES (?, ?, ?, 0, 1, 0, 0, 0, 0, 0, 0, 0)
            """,
            (user_id, clean_uname, first_name),
        )
    else:
        cur.execute(
            "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
            (clean_uname, first_name, user_id),
        )
    conn.commit()
    conn.close()


def get_all_user_ids() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = [int(r[0]) for r in cur.fetchall()]
    conn.close()
    return rows


def verify_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = int(parsed.get("auth_date", "0") or "0")
    if time.time() - auth_date > 86400 * 3:
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except Exception:
        return None


async def is_channel_subscribed(user_id: int, force_refresh: bool = False) -> bool:
    now = int(time.time())
    if not force_refresh:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT sub_cached, sub_checked_at FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row and (now - int(row[1] or 0)) < SUB_CACHE_TTL_SEC:
            return bool(row[0])

    targets = []
    if CHANNEL_CHAT_ID and str(CHANNEL_CHAT_ID).strip():
        targets.append(str(CHANNEL_CHAT_ID).strip())
    if CHANNEL_USERNAME and str(CHANNEL_USERNAME).strip():
        uname = f"@{str(CHANNEL_USERNAME).lstrip('@').strip()}"
        if uname not in targets:
            targets.append(uname)

    is_sub = False
    for chat_ref in targets:
        try:
            chat_id_arg: int | str = int(chat_ref) if chat_ref.lstrip("-").isdigit() else chat_ref
            member = await bot.get_chat_member(chat_id=chat_id_arg, user_id=user_id)
            if member.status in {"member", "administrator", "creator"}:
                is_sub = True
                break
        except Exception as e:
            print(f"[check_sub] Ошибка проверки {chat_ref} для user_id={user_id}: {e}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE users SET sub_cached = ?, sub_checked_at = ? WHERE user_id = ?",
        (1 if is_sub else 0, now, user_id),
    )
    conn.commit()
    conn.close()
    return is_sub


def decompose_withdraw_amount(cost: int) -> dict | None:
    if cost < 15:
        return None
    best = None
    for c100 in range(cost // 100, -1, -1):
        rem100 = cost - c100 * 100
        for c50 in range(rem100 // 50, -1, -1):
            rem50 = rem100 - c50 * 50
            for c25 in range(rem50 // 25, -1, -1):
                rem25 = rem50 - c25 * 25
                if rem25 % 15 == 0:
                    c15 = rem25 // 15
                    total_items = c100 + c50 + c25 + c15
                    if best is None or total_items < best["total_items"]:
                        payout = c100 * 85 + c50 * 43 + c25 * 21 + c15 * 13
                        parts = []
                        if c100:
                            parts.append(f"{c100}× Кольцо (100→85 ★)")
                        if c50:
                            parts.append(f"{c50}× Пакет 50★ (Ракета/Торт/Напиток 50→43 ★)")
                        if c25:
                            parts.append(f"{c25}× Роза/Коробка (25→21 ★)")
                        if c15:
                            parts.append(f"{c15}× Мишка/Сердце (15→13 ★)")
                        best = {
                            "cost": cost,
                            "payout": payout,
                            "total_items": total_items,
                            "counts": {"100": c100, "50": c50, "25": c25, "15": c15},
                            "breakdown": ", ".join(parts),
                        }
    return best


def suggest_nearest_withdraw_amounts(raw_amount: int, max_available: int) -> list[dict]:
    valid = []
    upper = max(120, raw_amount + 60)
    for x in range(15, upper + 1, 5):
        dec = decompose_withdraw_amount(x)
        if dec:
            valid.append(dec)
    valid.sort(key=lambda d: (abs(d["cost"] - raw_amount), d["cost"]))
    return valid[:4]


async def reminder_worker() -> None:
    while True:
        try:
            now = int(time.time())
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id FROM users
                WHERE last_free_spin > 0
                  AND (? - last_free_spin) >= ?
                  AND reminded_24h = 0
            """, (now, COOLDOWN_SEC))
            rows = cur.fetchall()
            conn.close()

            for (uid,) in rows:
                try:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="Открыть GiftezUp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))]
                        ]
                    )
                    await bot.send_message(
                        chat_id=uid,
                        text="Ежедневный бесплатный кейс в GiftezUp снова доступен!",
                        reply_markup=kb,
                    )
                    c2 = sqlite3.connect(DB_PATH)
                    c2.execute("UPDATE users SET reminded_24h = 1 WHERE user_id = ?", (uid,))
                    c2.commit()
                    c2.close()
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(30)


async def notify_user_withdraw_done(req_id: str, uid: int, cost_stars: int, payout_stars: int, breakdown: str, uname: str) -> None:
    text = (
        f"❄️ Заявка на вывод #{req_id} выполнена!\n"
        f"Списано: {cost_stars} ★ → Выдано: {payout_stars} ★\n"
        f"Состав: {breakdown}\n"
        f"Получатель: @{uname}\n\n"
        f"Пусть зимний дроп приносит жаркий профит!\n"
        f"@giftezup_bot"
    )
    kb = None
    if VERCEL_APP_URL:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть GiftezUp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))]
            ]
        )
    try:
        await bot.send_message(chat_id=uid, text=text, reply_markup=kb)
    except Exception as e:
        print(f"[notify_done] Не удалось отправить уведомление пользователю {uid}: {e}")


def build_admin_kb(modes: dict) -> InlineKeyboardMarkup:
    adm_v = modes.get("ui_admin_version", "v2")
    pub_v = modes.get("ui_public_version", "v1")
    adm_label = "👁 Мой вид: Новый (v2)" if adm_v == "v2" else "👁 Мой вид: Старый (v1)"
    pub_label = "🌍 Для всех: Новый (v2)" if pub_v == "v2" else "🌍 Для всех: Старый (v1)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=adm_label, callback_data="toggle_ui:admin")],
            [InlineKeyboardButton(text=pub_label, callback_data="toggle_ui:public")],
            [InlineKeyboardButton(text="Открыть WebApp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))],
        ]
    )


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = message.from_user
    ensure_user(u.id, u.username or "", u.first_name or "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть GiftezUp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))],
            [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{(CHANNEL_USERNAME or '').lstrip('@')}")],
        ]
    )
    await message.answer(
        f"Привет, {u.first_name or 'игрок'}!\n"
        f"Добро пожаловать в GiftezUp — открывай кейсы, прокачивай звёзды в апгрейдере и выводи награды.\n"
        f"Не забудь подписаться на @{(CHANNEL_USERNAME or '').lstrip('@')}.",
        reply_markup=kb,
    )


@dp.message(Command("maint"))
async def cmd_toggle_maint(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    cur_modes = get_system_modes()
    new_modes = set_system_mode("maintenance", not cur_modes["maintenance"])
    await message.answer(f"Техработы: {'ВКЛ' if new_modes['maintenance'] else 'ВЫКЛ'}")


@dp.message(Command("update"))
async def cmd_toggle_update(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    cur_modes = get_system_modes()
    new_modes = set_system_mode("update", not cur_modes["update"])
    await message.answer(f"Режим обновления: {'ВКЛ' if new_modes['update'] else 'ВЫКЛ'}")


@dp.message(Command("unlock"))
async def cmd_unlock_all(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    set_system_mode("maintenance", False)
    set_system_mode("update", False)
    await message.answer("✅ Все ограничения сняты: Техработы ВЫКЛ, Обновление ВЫКЛ.")


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    modes = get_system_modes()
    await message.answer(
        "⚙️ Пульт управления версиями дизайна GiftezUp:\n"
        f"• Твой вид (ADMIN): <b>{modes['ui_admin_version'].upper()}</b>\n"
        f"• Вид для всех игроков: <b>{modes['ui_public_version'].upper()}</b>\n"
        "• Новые кейсы и ивент откроются: <b>1 декабря 00:00 МСК (UTC+3)</b>",
        parse_mode="HTML",
        reply_markup=build_admin_kb(modes),
    )

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, username, cost_stars, payout_stars, breakdown FROM withdraw_requests WHERE status = 'processing' ORDER BY created_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("Активных заявок на вывод в обработке нет.")
        return

    for req_id, uid, uname, cost_s, pay_s, bdown in rows:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Выдано", callback_data=f"done_claim:{req_id}")]]
        )
        await message.answer(
            f"⭐ Заявка на вывод #{req_id}\n"
            f"Баланс: {cost_s} ★ → К выдаче: {pay_s} ★\n"
            f"Пакеты: {bdown}\n"
            f"Пользователь: @{uname} (ID: {uid})",
            reply_markup=kb,
        )


@dp.callback_query(F.data.startswith("toggle_ui:"))
async def on_toggle_ui_cb(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    scope = callback.data.split(":", 1)[1]
    modes = get_system_modes()
    key = "ui_admin_version" if scope == "admin" else "ui_public_version"
    next_ver = "v1" if modes.get(key) == "v2" else "v2"
    new_modes = set_ui_version(scope, next_ver)
    await callback.message.edit_text(
        "⚙️ Пульт управления версиями дизайна GiftezUp:\n"
        f"• Твой вид (ADMIN): <b>{new_modes['ui_admin_version'].upper()}</b>\n"
        f"• Вид для всех игроков: <b>{new_modes['ui_public_version'].upper()}</b>\n"
        "• Новые кейсы и ивент откроются: <b>1 декабря 00:00 МСК (UTC+3)</b>",
        parse_mode="HTML",
        reply_markup=build_admin_kb(new_modes),
    )
    await callback.answer(f"Переключено на {next_ver.upper()}")


@dp.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if not sp or sp.currency != "XTR":
        return

    payload = sp.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) >= 3 and parts[0] == "topup":
        try:
            uid = int(parts[1])
            stars_added = int(sp.total_amount)
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                """
                UPDATE users
                SET stars_balance = stars_balance + ?,
                    wager_left = wager_left + ?
                WHERE user_id = ?
                """,
                (stars_added, stars_added, uid),
            )
            conn.commit()
            conn.close()
            await message.answer(
                f"⭐ Баланс GiftezUp пополнен на {stars_added} ★!\n"
                f"Для вывода пополненных звёзд их нужно отыграть в играх или кейсах."
            )
        except Exception as e:
            print(f"[successful_payment] Ошибка начисления: {e}")


def mark_request_done(req_id: str) -> tuple[bool, bool, tuple | None]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, cost_stars, payout_stars, breakdown, username, status FROM withdraw_requests WHERE id = ?",
        (req_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, False, None
    uid, cost_s, pay_s, bdown, uname, st = int(row[0]), int(row[1]), int(row[2]), row[3], row[4], row[5]
    already_done = st == "done"
    if not already_done:
        cur.execute("UPDATE withdraw_requests SET status = 'done' WHERE id = ?", (req_id,))
        conn.commit()
    conn.close()
    return True, not already_done, (uid, cost_s, pay_s, bdown, uname)


@dp.callback_query(F.data.startswith("done_claim:"))
async def on_admin_done_claim(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    req_id = callback.data.split(":", 1)[1]
    ok, newly_done, info = mark_request_done(req_id)
    if not ok or not info:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    uid, cost_s, pay_s, bdown, uname = info
    if newly_done:
        await notify_user_withdraw_done(req_id, uid, cost_s, pay_s, bdown, uname)
    await callback.message.edit_text(
        f"✅ Выполнено #{req_id}\n"
        f"Списано: {cost_s} ★ → Выдано: {pay_s} ★\n"
        f"Пакеты: {bdown}\n"
        f"Получатель: @{uname} (ID: {uid})"
    )
    await callback.answer("Статус обновлён: Выполнено")


def roll_from_pool(pool: list[dict]) -> dict:
    total_w = sum(float(item["weight"]) for item in pool)
    r = random.uniform(0, total_w)
    upto = 0.0
    chosen = pool[0]
    for item in pool:
        upto += float(item["weight"])
        if r <= upto:
            chosen = item
            break

    if chosen["type"] == "nothing":
        return {
            "drop_type": "nothing",
            "gift_id": "nothing",
            "stars_amount": 0,
            "label": "Ничего",
            "icon": "nothing.png",
        }
    if chosen["type"] == "stars":
        amt = random.randint(int(chosen["min"]), int(chosen["max"]))
        return {
            "drop_type": "stars",
            "gift_id": "stars",
            "stars_amount": amt,
            "label": chosen.get("label") if amt == 100 and "x2" in str(chosen.get("label", "")) else f"{amt} ★",
            "icon": "star",
        }
    g_key = chosen["gift"]
    g_meta = GIFTS_CATALOG.get(g_key, {"name": g_key, "stars": 15, "icon": "bear.png"})
    g_stars = int(g_meta["stars"])
    return {
        "drop_type": "gift",
        "gift_id": g_key,
        "stars_amount": g_stars,
        "label": f"{g_meta['name']} ({g_stars} ★)",
        "icon": g_meta["icon"],
    }


def finalize_pending_drop_in_db(conn: sqlite3.Connection, drop_row: tuple) -> None:
    drop_id, uid, case_id, drop_type, gift_id, stars_amount, label, icon, rerolled, created_at = drop_row
    cur = conn.cursor()
    amt = int(stars_amount or 0)
    if amt > 0:
        cur.execute(
            "UPDATE users SET stars_balance = stars_balance + ? WHERE user_id = ?",
            (amt, int(uid)),
        )
    cur.execute("DELETE FROM pending_drops WHERE drop_id = ?", (drop_id,))


def compute_user_balances(stars_balance: int, wager_left: int) -> dict:
    bal = max(0, int(stars_balance))
    wag = min(bal, max(0, int(wager_left)))
    withdrawable = max(0, bal - wag)
    return {
        "stars_balance": bal,
        "wager_left": wag,
        "withdrawable_stars": withdrawable,
    }


def is_snowflakes_active_in_db(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'event_snowflakes_enabled'")
    row = cur.fetchone()
    return (row[0] if row else "1") == "1"


def add_event_points_from_stars(conn: sqlite3.Connection, uid: int, spent_stars: int) -> None:
    """Начисляет снежинки только если ивент открыт и включено начисление снежинок в админке."""
    pts = spent_stars // 2
    if pts <= 0 or not is_event_unlocked_for_user(uid):
        return
    if not is_snowflakes_active_in_db(conn):
        return
    conn.execute("UPDATE users SET event_points = event_points + ? WHERE user_id = ?", (pts, uid))


def build_cases_public_list(conn: sqlite3.Connection, uid: int) -> list[dict]:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute("SELECT case_id, opens_count, max_opens FROM case_stock")
    stock_map = {r[0]: (int(r[1]), int(r[2])) for r in cur.fetchall()}

    cur.execute("SELECT case_id, count FROM user_free_cases WHERE user_id = ? AND count > 0", (uid,))
    free_map = {r[0]: int(r[1]) for r in cur.fetchall()}

    result = [
        {
            "id": "daily",
            "name": "Ежедневный",
            "price": 0,
            "free_opens": 0,
            "is_daily": True,
            "badge": "24Ч",
            "icon": "daily.png",
            "reroll_price": 0,
            "reroll_allowed": False,
            "category": "daily",
            "availability": "permanent",
            "is_winter_new": False,
            "is_sold_out": False,
            "items": [
                {"label": x["label"], "type": x["type"], "gift": x.get("gift", ""), "icon": x.get("icon", "star")}
                for x in DAILY_POOL
            ],
        }
    ]

    for cid, cfg in ALL_CASES_CONFIG.items():
        if not is_case_visible_for_user(cfg, uid, now):
            continue

        avail = cfg.get("availability", "permanent")
        starts_at = int(cfg.get("starts_at", 0) or 0)
        ends_at = int(cfg.get("ends_at", 0) or 0)

        max_opens = None
        opens_count = 0
        remaining = None
        is_sold_out = False

        if avail == "limited":
            opens_count, max_opens = stock_map.get(cid, (0, int(cfg.get("default_max_opens", 50))))
            remaining = max(0, max_opens - opens_count)
            is_sold_out = remaining <= 0

        result.append({
            "id": cfg["id"],
            "name": cfg["name"],
            "price": int(cfg["price"]),
            "free_opens": free_map.get(cid, 0),
            "is_daily": False,
            "badge": cfg.get("badge", "ЗИМА"),
            "icon": cfg.get("icon", "starter.png"),
            "reroll_price": int(cfg.get("reroll_price", 0)),
            "reroll_allowed": bool(cfg.get("reroll_allowed", True)),
            "special_mode": cfg.get("special_mode", "wheel"),
            "category": cfg.get("category", "snowflakes"),
            "availability": avail,
            "is_winter_new": bool(cfg.get("is_winter_new", False)),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "max_opens": max_opens,
            "opens_count": opens_count,
            "remaining": remaining,
            "is_sold_out": is_sold_out,
            "items": [
                {"label": x["label"], "type": x["type"], "gift": x.get("gift", ""), "icon": x.get("icon", "star")}
                for x in cfg["pool"]
            ],
        })
    return result


# =========================================================
# ОБЩИЕ РАУНДЫ «ЛАВИНЫ» + «ЗАКОН ПОДЛОСТИ»
# =========================================================
def compute_avalanche_mult_at_elapsed(sec: float) -> float:
    """Ускоренный плавный разгон от 0.00x (совпадает с формулой на фронтенде)."""
    if sec <= 0:
        return 0.0
    val = 0.085 * sec + 0.014 * (sec ** 2) + 0.0011 * (sec ** 3)
    return round(min(100.0, val), 2)


def compute_avalanche_duration_for_crash(target_crash: float) -> float:
    if target_crash <= 0.0:
        return 0.45
    lo, hi = 0.0, 90.0
    for _ in range(36):
        mid = (lo + hi) * 0.5
        if compute_avalanche_mult_at_elapsed(mid) < target_crash:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


def roll_smart_avalanche_crash(conn: sqlite3.Connection, round_id: str) -> float:
    """
    Хитрая логика («закон подлости»):
    - Чаще выпадает диапазон 1.00x–2.00x (вместо сплошных 0.1–0.9x), чтобы хотелось забрать чуть позже.
    - Присутствует шанс 0.00x (~14%).
    - Если есть реальные ставки игроков с авто-выходом (например 2.00x), подстраивает сход
      чуть ниже целевого порога или сразу после него в зависимости от размера ставки.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT bet_stars, auto_mult FROM avalanche_bets WHERE round_id = ? AND status = 'playing'",
        (round_id,),
    )
    bets = cur.fetchall()

    r = random.random()

    # Если ставок реальных игроков нет — чаще показываем красивые иксы 1.35x .. 4.20x
    if not bets:
        if r < 0.10:
            return 0.00
        if r < 0.65:
            return round(random.uniform(1.25, 2.25), 2)
        if r < 0.90:
            return round(random.uniform(2.25, 4.80), 2)
        return round(random.uniform(4.80, 12.00), 2)

    # Есть реальные ставки игроков — включаем закон подлости
    if r < 0.14:
        return 0.00

    # Проверяем, поставил ли кто-то авто-выход
    auto_targets = [float(b[1]) for b in bets if float(b[1] or 0) > 1.05]
    if auto_targets and random.random() < 0.62:
        min_auto = min(auto_targets)
        # Обвал ровно за 0.02–0.11x до срабатывания авто-выхода игрока!
        if min_auto <= 2.40:
            tease = max(1.01, round(min_auto - random.uniform(0.02, 0.11), 2))
            return tease

    # В остальных случаях чаще держим 1.05x .. 1.98x (прямо перед психологическим порогом 2.00x)
    if r < 0.74:
        return round(random.uniform(1.06, 1.98), 2)
    if r < 0.94:
        return round(random.uniform(2.01, 3.40), 2)
    return round(random.uniform(3.40, 9.50), 2)


def sync_shared_avalanche_round(conn: sqlite3.Connection) -> dict:
    """Синхронизирует состояние текущего общего раунда «Лавины» по мировому времени."""
    now = time.time()
    epoch_idx = int(now // AV_SLOT_LEN)
    slot_offset = now - epoch_idx * AV_SLOT_LEN
    round_id = f"round_{epoch_idx}"

    cur = conn.cursor()
    cur.execute(
        "SELECT crash_mult, finalized FROM avalanche_shared_rounds WHERE round_id = ?",
        (round_id,),
    )
    row = cur.fetchone()
    if not row:
        initial_crash = roll_smart_avalanche_crash(conn, round_id)
        cur.execute(
            "INSERT OR IGNORE INTO avalanche_shared_rounds (round_id, epoch_idx, crash_mult, started_at, finalized) VALUES (?, ?, ?, ?, 0)",
            (round_id, epoch_idx, initial_crash, int(epoch_idx * AV_SLOT_LEN)),
        )
        crash_mult = initial_crash
        finalized = 0
    else:
        crash_mult = float(row[0])
        finalized = int(row[1])

    flight_duration = compute_avalanche_duration_for_crash(crash_mult)
    max_flight = AV_SLOT_LEN - AV_WAIT_SEC - AV_CRASH_PAUSE_SEC
    active_flight_len = min(max_flight, flight_duration)
    effective_crash = 0.0 if crash_mult <= 0.0 else compute_avalanche_mult_at_elapsed(active_flight_len)

    if slot_offset < AV_WAIT_SEC:
        phase = "waiting"
        current_mult = 0.0
    elif (slot_offset - AV_WAIT_SEC) < active_flight_len and effective_crash > 0.0:
        phase = "running"
        current_mult = compute_avalanche_mult_at_elapsed(slot_offset - AV_WAIT_SEC)
    else:
        phase = "crashed"
        current_mult = effective_crash
        if finalized == 0:
            cur.execute("UPDATE avalanche_shared_rounds SET finalized = 1 WHERE round_id = ?", (round_id,))
            cur.execute(
                "UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE round_id = ? AND status = 'playing'",
                (round_id,),
            )
            cur.execute(
                "INSERT OR IGNORE INTO avalanche_history (round_id, crash_mult, created_at) VALUES (?, ?, ?)",
                (round_id, effective_crash, int(now)),
            )

    # Закрываем зависшие прошлые раунды, если в них остались активные ставки
    cur.execute(
        "UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE round_id != ? AND status = 'playing'",
        (round_id,),
    )

    cur.execute(
        "SELECT user_id, username, bet_stars, status, cashout_mult, payout FROM avalanche_bets WHERE round_id = ? ORDER BY id DESC",
        (round_id,),
    )
    players = [
        {
            "user_id": int(p[0]),
            "username": p[1] or "Игрок",
            "bet_stars": int(p[2]),
            "status": p[3],
            "cashout_mult": float(p[4]),
            "payout": int(p[5]),
        }
        for p in cur.fetchall()
    ]

    cur.execute("SELECT crash_mult FROM avalanche_history ORDER BY id DESC LIMIT 15")
    history = [float(h[0]) for h in cur.fetchall()]

    cur.execute("SELECT value FROM app_settings WHERE key = 'avalanche_history_reset_at'")
    r_reset = cur.fetchone()
    reset_at = int(r_reset[0]) if r_reset else 0

    conn.commit()
    return {
        "round_id": round_id,
        "phase": phase,
        "current_mult": current_mult,
        "crash_mult": effective_crash,
        "players": players,
        "history": history,
        "history_reset_at": reset_at,
    }


async def api_state(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    ensure_user(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
    )
    sub_ok = await is_channel_subscribed(uid, force_refresh=False)
    modes = get_system_modes()
    ui_version = resolve_user_ui_version(uid, modes)
    now = int(time.time())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT last_free_spin, stars_balance, wager_left, total_spins, event_points, event_claimed_stage FROM users WHERE user_id = ?",
        (uid,),
    )
    r_user = cur.fetchone()
    last_free = int(r_user[0]) if r_user else 0
    raw_bal = int(r_user[1]) if r_user else 0
    raw_wag = int(r_user[2]) if r_user else 0
    total_spins = int(r_user[3]) if r_user else 0
    event_points = int(r_user[4]) if r_user else 0
    event_claimed_stage = int(r_user[5]) if r_user else 0

    balances = compute_user_balances(raw_bal, raw_wag)
    if balances["wager_left"] != raw_wag:
        cur.execute("UPDATE users SET wager_left = ? WHERE user_id = ?", (balances["wager_left"], uid))
        conn.commit()

    cur.execute(
        "SELECT id, cost_stars, payout_stars, breakdown, username, status, created_at FROM withdraw_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
        (uid,),
    )
    my_reqs = [
        {
            "id": r[0],
            "cost_stars": int(r[1]),
            "payout_stars": int(r[2]),
            "breakdown": r[3],
            "username": r[4],
            "status": r[5],
            "created_at": int(r[6]),
        }
        for r in cur.fetchall()
    ]

    cases_public = build_cases_public_list(conn, uid)
    conn.close()

    return web.json_response({
        "ok": True,
        "is_subscribed": sub_ok,
        "is_admin": uid in ADMIN_IDS,
        "system_modes": modes,
        "ui_version": ui_version,
        "event_start_ts": EVENT_START_TS,
        "event_end_ts": EVENT_END_TS,
        "event_unlocked": is_event_unlocked_for_user(uid, now),
        "event_points": event_points,
        "event_claimed_stage": event_claimed_stage,
        "event_stages": EVENT_STAGES,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
        "total_spins": total_spins,
        "next_spin_at": (last_free + COOLDOWN_SEC) if last_free > 0 else 0,
        "my_requests": my_reqs,
        "cases": cases_public,
        "upgrade_targets": list(GIFTS_CATALOG.values()),
        "withdraw_packs": WITHDRAW_PACKS,
    })


async def api_check_sub(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False}, status=401)

    uid = int(tg_user["id"])
    ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")
    sub_ok = await is_channel_subscribed(uid, force_refresh=True)
    return web.json_response({"ok": True, "is_subscribed": sub_ok})


async def api_create_topup_invoice(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    stars = int(body.get("stars", 1) or 1)
    if stars < 1 or stars > 10000:
        return web.json_response({"ok": False, "message": "Укажи сумму от 1 до 10 000 ★"})

    ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")
    payload = f"topup:{uid}:{stars}:{uuid.uuid4().hex[:8]}"
    link = await bot.create_invoice_link(
        title=f"Пополнение GiftezUp ({stars} ★)",
        description=f"Зачисление {stars} ★ на баланс GiftezUp",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ★ на баланс", amount=stars)],
    )
    return web.json_response({"ok": True, "invoice_link": link, "payload": payload})


async def api_spin_daily(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")

    if not await is_channel_subscribed(uid, force_refresh=True):
        return web.json_response({
            "ok": False,
            "error": "not_subscribed",
            "message": "Подпишись на канал перед открытием ежедневного кейса",
        })

    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_free_spin, stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    last_free = int(row[0]) if row else 0
    stars_balance = int(row[1]) if row else 0
    wager_left = int(row[2]) if row else 0

    if last_free > 0 and (now - last_free) < COOLDOWN_SEC:
        conn.close()
        return web.json_response({
            "ok": False,
            "error": "cooldown",
            "next_spin_at": last_free + COOLDOWN_SEC,
            "message": "Ежедневный кейс ещё на перезарядке",
        })

    drop = roll_from_pool(DAILY_POOL)
    new_balance = stars_balance + int(drop["stars_amount"])
    balances = compute_user_balances(new_balance, wager_left)

    cur.execute(
        """
        UPDATE users
        SET last_free_spin = ?, reminded_24h = 0, stars_balance = ?, wager_left = ?, total_spins = total_spins + 1
        WHERE user_id = ?
        """,
        (now, balances["stars_balance"], balances["wager_left"], uid),
    )
    if is_event_unlocked_for_user(uid, now) and is_snowflakes_active_in_db(conn):
        cur.execute("UPDATE users SET event_points = event_points + 2 WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()

    return web.json_response({
        "ok": True,
        "drop": drop,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
        "next_spin_at": now + COOLDOWN_SEC,
    })


async def api_open_paid_case(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    case_id = str(body.get("case_id", "")).strip()
    cfg = ALL_CASES_CONFIG.get(case_id)
    now = int(time.time())
    if not cfg or not is_case_visible_for_user(cfg, uid, now):
        return web.json_response({"ok": False, "message": "Кейс пока недоступен"})

    ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")

    price = int(cfg["price"])
    reroll_allowed = bool(cfg.get("reroll_allowed", True))
    reroll_price = int(cfg.get("reroll_price", 0)) if reroll_allowed else 0
    is_limited = cfg.get("availability") == "limited"

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    try:
        cur.execute("SELECT * FROM pending_drops WHERE user_id = ?", (uid,))
        for old_drop in cur.fetchall():
            finalize_pending_drop_in_db(conn, old_drop)

        remaining = None
        max_opens_val = None
        cur_opens = 0
        if is_limited:
            cur.execute("SELECT opens_count, max_opens FROM case_stock WHERE case_id = ?", (case_id,))
            st_row = cur.fetchone()
            cur_opens = int(st_row[0]) if st_row else 0
            max_opens_val = int(st_row[1]) if st_row else int(cfg.get("default_max_opens", 50))
            if cur_opens >= max_opens_val:
                cur.execute("ROLLBACK")
                conn.close()
                return web.json_response({"ok": False, "message": "Кейс раскуплен (запас закончился)"})

        # Проверяем, есть ли у игрока бесплатное открытие этого кейса (выданное админом или промокодом)
        cur.execute("SELECT count FROM user_free_cases WHERE user_id = ? AND case_id = ?", (uid, case_id))
        fc_row = cur.fetchone()
        free_opens_left = int(fc_row[0]) if fc_row else 0
        used_free_open = free_opens_left > 0

        cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
        row = cur.fetchone()
        bal = int(row[0]) if row else 0
        wag = int(row[1]) if row else 0

        if not used_free_open and bal < price:
            cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": f"Недостаточно звёзд (нужно {price} ★)"})

        if is_limited:
            cur.execute("UPDATE case_stock SET opens_count = opens_count + 1 WHERE case_id = ?", (case_id,))
            remaining = max(0, max_opens_val - (cur_opens + 1))

        if used_free_open:
            free_opens_left -= 1
            cur.execute(
                "UPDATE user_free_cases SET count = ? WHERE user_id = ? AND case_id = ?",
                (free_opens_left, uid, case_id),
            )
            new_bal = bal
            new_wag = wag
            cur.execute("UPDATE users SET total_spins = total_spins + 1 WHERE user_id = ?", (uid,))
        else:
            new_bal = bal - price
            new_wag = max(0, wag - price)
            cur.execute(
                "UPDATE users SET stars_balance = ?, wager_left = ?, total_spins = total_spins + 1 WHERE user_id = ?",
                (new_bal, new_wag, uid),
            )
            add_event_points_from_stars(conn, uid, price)

        drop = roll_from_pool(cfg["pool"])
        drop_id = f"drop_{uuid.uuid4().hex[:10]}"

        if not reroll_allowed:
            amt = int(drop["stars_amount"] or 0)
            if amt > 0:
                new_bal += amt
                cur.execute("UPDATE users SET stars_balance = ? WHERE user_id = ?", (new_bal, uid))
            drop_id = ""
        else:
            cur.execute(
                """
                INSERT INTO pending_drops (drop_id, user_id, case_id, drop_type, gift_id, stars_amount, label, icon, rerolled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (drop_id, uid, case_id, drop["drop_type"], drop["gift_id"], int(drop["stars_amount"]), drop["label"], drop["icon"], now),
            )

        cur.execute("COMMIT")
    except Exception as e:
        cur.execute("ROLLBACK")
        conn.close()
        return web.json_response({"ok": False, "message": f"Ошибка открытия: {e}"})

    conn.close()
    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "drop_id": drop_id,
        "case_id": case_id,
        "used_free_open": used_free_open,
        "free_opens_left": free_opens_left,
        "drop": drop,
        "can_reroll": reroll_allowed,
        "reroll_price": reroll_price,
        "remaining": remaining,
        "max_opens": max_opens_val,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_reroll_case_drop(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    drop_id = str(body.get("drop_id", "")).strip()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_drops WHERE drop_id = ? AND user_id = ?", (drop_id, uid))
    drow = cur.fetchone()
    if not drow:
        conn.close()
        return web.json_response({"ok": False, "message": "Дроп уже зафиксирован или не найден"})

    case_id = drow[2]
    cfg = ALL_CASES_CONFIG.get(case_id)
    if not cfg or not cfg.get("reroll_allowed", True):
        conn.close()
        return web.json_response({"ok": False, "message": "Перекрут для этого кейса отключён"})

    reroll_price = int(cfg["reroll_price"])
    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)
    bal, wag = int(r_u[0]), int(r_u[1])
    if bal < reroll_price:
        conn.close()
        return web.json_response({"ok": False, "message": f"Для перекрута нужно {reroll_price} ★"})

    new_bal = bal - reroll_price
    new_wag = max(0, wag - reroll_price)
    cur.execute("UPDATE users SET stars_balance = ?, wager_left = ? WHERE user_id = ?", (new_bal, new_wag, uid))
    add_event_points_from_stars(conn, uid, reroll_price)

    new_drop = roll_from_pool(cfg["pool"])
    cur.execute(
        """
        UPDATE pending_drops
        SET drop_type = ?, gift_id = ?, stars_amount = ?, label = ?, icon = ?, rerolled = rerolled + 1
        WHERE drop_id = ?
        """,
        (new_drop["drop_type"], new_drop["gift_id"], int(new_drop["stars_amount"]), new_drop["label"], new_drop["icon"], drop_id),
    )

    conn.commit()
    conn.close()

    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "drop_id": drop_id,
        "drop": new_drop,
        "can_reroll": True,
        "reroll_price": reroll_price,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_accept_case_drop(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    drop_id = str(body.get("drop_id", "")).strip()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM pending_drops WHERE drop_id = ? AND user_id = ?", (drop_id, uid))
    drow = cur.fetchone()
    if drow:
        finalize_pending_drop_in_db(conn, drow)
        conn.commit()

    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)
    conn.close()

    balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
    return web.json_response({
        "ok": True,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_upgrade_spin(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    bet_stars = int(body.get("bet_stars", 0) or 0)
    target_id = str(body.get("target_id", "")).strip()
    target = GIFTS_CATALOG.get(target_id)

    if not target or bet_stars < 1:
        return web.json_response({"ok": False, "message": "Укажи ставку и цель апгрейда"})

    target_stars = int(target["stars"])
    if bet_stars >= target_stars:
        return web.json_response({"ok": False, "message": "Цель должна быть дороже ставки"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)
    bal, wag = int(r_u[0]), int(r_u[1])

    if bal < bet_stars:
        conn.close()
        return web.json_response({"ok": False, "message": "Недостаточно звёзд на балансе"})

    chance = min(65.0, max(1.0, round((bet_stars / max(1, target_stars)) * 72.0, 2)))
    roll = round(random.uniform(0.0, 100.0), 2)
    won = roll <= chance

    new_bal = bal - bet_stars
    new_wag = max(0, wag - bet_stars)
    if won:
        new_bal += target_stars

    cur.execute("UPDATE users SET stars_balance = ?, wager_left = ? WHERE user_id = ?", (new_bal, new_wag, uid))
    add_event_points_from_stars(conn, uid, bet_stars)
    conn.commit()
    conn.close()

    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "won": won,
        "chance": chance,
        "roll": roll,
        "target": target,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_avalanche_state(request: web.Request) -> web.Response:
    """Возвращает состояние общего раунда «Лавины», список реальных ставок и историю иксов."""
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    conn = sqlite3.connect(DB_PATH)
    state = sync_shared_avalanche_round(conn)
    conn.close()

    return web.json_response({"ok": True, **state})


async def api_avalanche_start(request: web.Request) -> web.Response:
    """Принимает ставку игрока в общий раунд «Лавины» (с пересчётом точки краша по закону подлости)."""
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    if not is_event_unlocked_for_user(uid):
        return web.json_response({"ok": False, "message": "Игра «Лавина» откроется 1 декабря в 00:00 МСК"})

    uname = (tg_user.get("username") or "").lstrip("@").strip() or (tg_user.get("first_name") or "Игрок")
    bet = int(body.get("bet_stars", 0) or 0)
    auto_enabled = bool(body.get("auto_enabled", False))
    auto_mult = round(float(body.get("auto_mult", 1.5) or 1.5), 2) if auto_enabled else 0.0

    if bet < 1 or bet > 2000:
        return web.json_response({"ok": False, "message": "Ставка от 1 до 2000 ★"})
    if auto_enabled and (auto_mult < 1.05 or auto_mult > 25.0):
        return web.json_response({"ok": False, "message": "Авто-выход от 1.05x до 25.00x"})

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    try:
        state = sync_shared_avalanche_round(conn)
        round_id = state["round_id"]

        if state["phase"] != "waiting":
            cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": "Раунд уже идёт — дождитесь следующего"})

        cur.execute("SELECT 1 FROM avalanche_bets WHERE round_id = ? AND user_id = ?", (round_id, uid))
        if cur.fetchone():
            cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": "Вы уже поставили в этот раунд"})

        cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
        r_u = cur.fetchone() or (0, 0)
        bal, wag = int(r_u[0]), int(r_u[1])
        if bal < bet:
            cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": "Недостаточно звёзд на балансе"})

        now_int = int(time.time())
        new_bal = bal - bet
        new_wag = max(0, wag - bet)

        cur.execute("UPDATE users SET stars_balance = ?, wager_left = ? WHERE user_id = ?", (new_bal, new_wag, uid))
        cur.execute(
            """
            INSERT INTO avalanche_bets (round_id, user_id, username, bet_stars, auto_mult, status, cashout_mult, payout, created_at)
            VALUES (?, ?, ?, ?, ?, 'playing', 0, 0, ?)
            """,
            (round_id, uid, uname, bet, auto_mult, now_int),
        )

        # Пересчитываем точку схода раунда с учётом новой реальной ставки («закон подлости»)
        new_crash = roll_smart_avalanche_crash(conn, round_id)
        cur.execute(
            "UPDATE avalanche_shared_rounds SET crash_mult = ? WHERE round_id = ?",
            (new_crash, round_id),
        )

        add_event_points_from_stars(conn, uid, bet)
        cur.execute("COMMIT")
    except Exception as e:
        cur.execute("ROLLBACK")
        conn.close()
        return web.json_response({"ok": False, "message": f"Ошибка ставки: {e}"})

    conn.close()
    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "round_id": round_id,
        "crash_mult": new_crash,
        "auto_mult": auto_mult,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_avalanche_cashout(request: web.Request) -> web.Response:
    """Мгновенный вывод выигрыша игрока при нажатии «Забрать» или авто-выходе."""
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    req_round_id = str(body.get("round_id", "")).strip()
    claim_mult = round(float(body.get("mult", 0.0) or 0.0), 2)

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    try:
        now = time.time()
        epoch_idx = int(now // AV_SLOT_LEN)
        slot_offset = now - epoch_idx * AV_SLOT_LEN
        cur_round_id = f"round_{epoch_idx}"
        target_round_id = req_round_id or cur_round_id

        cur.execute(
            "SELECT id, bet_stars, status FROM avalanche_bets WHERE round_id = ? AND user_id = ?",
            (target_round_id, uid),
        )
        bet_row = cur.fetchone()
        if not bet_row or bet_row[2] != "playing":
            cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": "Ставка уже завершена или не найдена"})

        bet_id, bet_stars = int(bet_row[0]), int(bet_row[1])

        cur.execute("SELECT crash_mult FROM avalanche_shared_rounds WHERE round_id = ?", (target_round_id,))
        rnd_row = cur.fetchone()
        raw_crash = float(rnd_row[0]) if rnd_row else 0.0

        flight_duration = compute_avalanche_duration_for_crash(raw_crash)
        max_flight = AV_SLOT_LEN - AV_WAIT_SEC - AV_CRASH_PAUSE_SEC
        active_flight_len = min(max_flight, flight_duration)
        effective_crash = 0.0 if raw_crash <= 0.0 else compute_avalanche_mult_at_elapsed(active_flight_len)

        # Проверяем, не сошла ли лавина раньше
        if target_round_id != cur_round_id or effective_crash <= 0.0:
            cur.execute("UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE id = ?", (bet_id,))
            cur.execute("COMMIT")
            conn.close()
            return web.json_response({"ok": False, "message": "Лавина сошла раньше!"})

        flight_elapsed = max(0.0, slot_offset - AV_WAIT_SEC)
        # Небольшой допуск 0.45 сек на сетевой пинг
        server_mult_with_grace = compute_avalanche_mult_at_elapsed(flight_elapsed + 0.45)

        if claim_mult < 0.05 or claim_mult > effective_crash or claim_mult > server_mult_with_grace:
            if claim_mult > effective_crash:
                cur.execute("UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE id = ?", (bet_id,))
                cur.execute("COMMIT")
                conn.close()
                return web.json_response({"ok": False, "message": "Лавина накрыла раньше!"})
            claim_mult = min(effective_crash, server_mult_with_grace)

        payout = max(1, int(round(bet_stars * claim_mult)))
        cur.execute(
            "UPDATE avalanche_bets SET status = 'won', cashout_mult = ?, payout = ? WHERE id = ?",
            (claim_mult, payout, bet_id),
        )
        cur.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE user_id = ?", (payout, uid))
        cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
        r_u = cur.fetchone() or (0, 0)
        cur.execute("COMMIT")
    except Exception as e:
        cur.execute("ROLLBACK")
        conn.close()
        return web.json_response({"ok": False, "message": f"Ошибка вывода: {e}"})

    conn.close()
    balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
    return web.json_response({
        "ok": True,
        "payout": payout,
        "mult": claim_mult,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_event_claim_stage(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    if not is_event_unlocked_for_user(uid):
        return web.json_response({"ok": False, "message": "Ивент ещё не стартовал"})

    conn = sqlite3.connect(DB_PATH)
    if not is_snowflakes_active_in_db(conn):
        conn.close()
        return web.json_response({"ok": False, "message": "Начисление и награды снежинок временно закрыты"})

    cur = conn.cursor()
    cur.execute("SELECT event_points, event_claimed_stage, stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"ok": False, "message": "Пользователь не найден"})

    pts, claimed, bal, wag = int(row[0]), int(row[1]), int(row[2]), int(row[3])
    next_stage = next((s for s in EVENT_STAGES if s["stage"] == claimed + 1), None)
    if not next_stage:
        conn.close()
        return web.json_response({"ok": False, "message": "Все этапы снегопада уже забраны"})
    if pts < int(next_stage["points"]):
        conn.close()
        return web.json_response({"ok": False, "message": f"Нужно {next_stage['points']} снежинок"})

    reward = int(next_stage["reward_stars"])
    new_bal = bal + reward
    new_wag = wag + reward
    cur.execute(
        "UPDATE users SET event_claimed_stage = ?, stars_balance = ?, wager_left = ? WHERE user_id = ?",
        (claimed + 1, new_bal, new_wag, uid),
    )
    conn.commit()
    conn.close()

    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "claimed_stage": claimed + 1,
        "reward_stars": reward,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
    })


async def api_promo_redeem(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    code = str(body.get("code", "")).strip().upper()
    if not code:
        return web.json_response({"ok": False, "message": "Введи промокод"})

    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT reward_stars, max_uses, uses_count, active, reward_type, case_id, reward_cases FROM promocodes WHERE code = ?",
        (code,),
    )
    promo = cur.fetchone()
    if not promo or int(promo[3]) != 1:
        conn.close()
        return web.json_response({"ok": False, "message": "Промокод не найден или отключён"})

    reward_stars = int(promo[0] or 0)
    max_uses = int(promo[1] or 1)
    uses_count = int(promo[2] or 0)
    reward_type = str(promo[4] or "stars")
    case_id = str(promo[5] or "")
    reward_cases = int(promo[6] or 0)

    if uses_count >= max_uses:
        conn.close()
        return web.json_response({"ok": False, "message": "Лимит активаций промокода исчерпан"})

    cur.execute("SELECT 1 FROM promo_activations WHERE code = ? AND user_id = ?", (code, uid))
    if cur.fetchone():
        conn.close()
        return web.json_response({"ok": False, "message": "Ты уже активировал этот промокод"})

    cur.execute(
        "INSERT INTO promo_activations (code, user_id, activated_at) VALUES (?, ?, ?)",
        (code, uid, now),
    )
    cur.execute("UPDATE promocodes SET uses_count = uses_count + 1 WHERE code = ?", (code,))

    if reward_type == "case" and case_id and reward_cases > 0:
        cur.execute(
            """
            INSERT INTO user_free_cases (user_id, case_id, count) VALUES (?, ?, ?)
            ON CONFLICT(user_id, case_id) DO UPDATE SET count = count + ?
            """,
            (uid, case_id, reward_cases, reward_cases),
        )
        case_name = ALL_CASES_CONFIG.get(case_id, {}).get("name", case_id)
        msg = f"Промокод активирован: +{reward_cases} беспл. откр. кейса «{case_name}»!"
    else:
        cur.execute(
            "UPDATE users SET stars_balance = stars_balance + ?, wager_left = wager_left + ? WHERE user_id = ?",
            (reward_stars, reward_stars, uid),
        )
        msg = f"Промокод активирован: +{reward_stars} ★"

    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)

    conn.commit()
    conn.close()

    balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
    return web.json_response({
        "ok": True,
        "reward_type": reward_type,
        "reward_stars": reward_stars,
        "case_id": case_id,
        "reward_cases": reward_cases,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
        "message": msg,
    })


async def api_withdraw_stars(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    tg_uname = (tg_user.get("username") or "").lstrip("@")
    req_uname = (body.get("username") or "").lstrip("@").strip()
    final_uname = tg_uname or req_uname

    if not final_uname:
        return web.json_response({
            "ok": False,
            "message": "Укажи @username в профиле Telegram для вывода звёзд",
        })

    amount = int(body.get("amount", 0) or 0)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)
    balances = compute_user_balances(int(r_u[0]), int(r_u[1]))

    if balances["wager_left"] > 0 and amount > balances["withdrawable_stars"]:
        conn.close()
        return web.json_response({
            "ok": False,
            "message": f"Сначала отыграй пополненные звёзды (осталось отыграть: {balances['wager_left']} ★)",
        })

    if amount > balances["withdrawable_stars"]:
        conn.close()
        return web.json_response({
            "ok": False,
            "message": f"Доступно к выводу: {balances['withdrawable_stars']} ★",
        })

    dec = decompose_withdraw_amount(amount)
    if not dec:
        suggestions = suggest_nearest_withdraw_amounts(amount, balances["withdrawable_stars"])
        conn.close()
        return web.json_response({
            "ok": False,
            "error": "non_exact_amount",
            "message": "Сумма должна складываться из пакетов 15, 25, 50 или 100 ★",
            "suggestions": suggestions,
        })

    new_bal = balances["stars_balance"] - amount
    cur.execute("UPDATE users SET stars_balance = ? WHERE user_id = ?", (new_bal, uid))

    req_id = f"wd_{uuid.uuid4().hex[:10]}"
    now = int(time.time())
    cur.execute(
        """
        INSERT INTO withdraw_requests (id, user_id, username, cost_stars, payout_stars, breakdown, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'processing')
        """,
        (req_id, uid, final_uname, dec["cost"], dec["payout"], dec["breakdown"], now),
    )
    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Выдано", callback_data=f"done_claim:{req_id}")]]
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"⭐ Новая заявка на вывод #{req_id}\n"
                    f"Списано с баланса: {dec['cost']} ★ → К выдаче: {dec['payout']} ★\n"
                    f"Состав пакетов: {dec['breakdown']}\n"
                    f"Получатель: @{final_uname} (ID: {uid})"
                ),
                reply_markup=kb,
            )
        except Exception:
            pass

    new_balances = compute_user_balances(new_bal, balances["wager_left"])
    return web.json_response({
        "ok": True,
        "request_id": req_id,
        "cost_stars": dec["cost"],
        "payout_stars": dec["payout"],
        "breakdown": dec["breakdown"],
        "stars_balance": new_balances["stars_balance"],
        "wager_left": new_balances["wager_left"],
        "withdrawable_stars": new_balances["withdrawable_stars"],
    })


def check_admin(body: dict) -> int | None:
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return None
    uid = int(tg_user["id"])
    return uid if uid in ADMIN_IDS else None


async def api_admin_mode(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    mode = str(body.get("mode", ""))
    enabled = bool(body.get("enabled", False))
    try:
        modes = set_system_mode(mode, enabled)
        return web.json_response({"ok": True, "system_modes": modes})
    except ValueError:
        return web.json_response({"ok": False, "message": "Неверный режим"}, status=400)


async def api_admin_ui_version(request: web.Request) -> web.Response:
    body = await request.json()
    uid = check_admin(body)
    if not uid:
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    scope = str(body.get("scope", "")).strip()
    version = str(body.get("version", "")).strip()
    try:
        modes = set_ui_version(scope, version)
        return web.json_response({
            "ok": True,
            "system_modes": modes,
            "ui_version": resolve_user_ui_version(uid, modes),
        })
    except ValueError:
        return web.json_response({"ok": False, "message": "Неверные параметры версии"}, status=400)


async def api_admin_event_toggle(request: web.Request) -> web.Response:
    """Закрывает или открывает начисление снежинок ивента «Снегопад» (игры остаются доступны)."""
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    enabled = bool(body.get("enabled", True))
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('event_snowflakes_enabled', ?)",
        ("1" if enabled else "0",),
    )
    conn.commit()
    conn.close()
    modes = get_system_modes()
    return web.json_response({
        "ok": True,
        "system_modes": modes,
        "message": "Начисление снежинок ОТКРЫТО" if enabled else "Начисление снежинок ЗАКРЫТО",
    })


async def api_admin_reset_games_history(request: web.Request) -> web.Response:
    """Сбрасывает историю раундов «Лавины» перед официальным запуском ивента 1 декабря."""
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    now_ts = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM avalanche_history")
    conn.execute("DELETE FROM avalanche_bets")
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('avalanche_history_reset_at', ?)",
        (str(now_ts),),
    )
    conn.commit()
    conn.close()
    return web.json_response({
        "ok": True,
        "history_reset_at": now_ts,
        "message": "История игр полностью очищена",
    })


async def api_admin_user_free_cases(request: web.Request) -> web.Response:
    """Выдаёт или списывает бесплатные открытия выбранного кейса игроку по @username."""
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    target_uname = str(body.get("username", "")).lstrip("@").strip().lower()
    case_id = str(body.get("case_id", "")).strip()
    delta = int(body.get("delta", 0) or 0)
    cfg = ALL_CASES_CONFIG.get(case_id)

    if not target_uname or not cfg or delta == 0:
        return web.json_response({"ok": False, "message": "Укажи @username, кейс и количество"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE lower(username) = ?", (target_uname,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"ok": False, "message": f"Игрок @{target_uname} не найден"})

    target_uid = int(row[0])
    cur.execute("SELECT count FROM user_free_cases WHERE user_id = ? AND case_id = ?", (target_uid, case_id))
    fc_row = cur.fetchone()
    cur_count = int(fc_row[0]) if fc_row else 0
    new_count = max(0, cur_count + delta)

    cur.execute(
        """
        INSERT INTO user_free_cases (user_id, case_id, count) VALUES (?, ?, ?)
        ON CONFLICT(user_id, case_id) DO UPDATE SET count = ?
        """,
        (target_uid, case_id, new_count, new_count),
    )
    conn.commit()
    conn.close()

    if delta > 0:
        try:
            await bot.send_message(
                chat_id=target_uid,
                text=f"🎁 Администратор выдал вам бесплатные открытия кейса «{cfg['name']}»: +{delta} шт. (всего: {new_count} шт.)!",
            )
        except Exception:
            pass

    return web.json_response({
        "ok": True,
        "free_opens": new_count,
        "message": f"Кейс «{cfg['name']}» у @{target_uname}: теперь {new_count} беспл. откр.",
    })


async def api_admin_restock_case(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    case_id = str(body.get("case_id", "")).strip()
    action = str(body.get("action", "add")).strip()
    amount = int(body.get("amount", 0) or 0)
    cfg = ALL_CASES_CONFIG.get(case_id)
    if not cfg or cfg.get("availability") != "limited":
        return web.json_response({"ok": False, "message": "Выбери лимитированный кейс"})
    if amount < 1 or amount > 10000:
        return web.json_response({"ok": False, "message": "Укажи количество от 1 до 10 000"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO case_stock (case_id, opens_count, max_opens) VALUES (?, 0, ?)",
        (case_id, int(cfg.get("default_max_opens", 50))),
    )
    cur.execute("SELECT opens_count, max_opens FROM case_stock WHERE case_id = ?", (case_id,))
    opens_c, max_o = cur.fetchone()
    opens_c, max_o = int(opens_c), int(max_o)

    if action == "set_total":
        new_max = amount
        new_opens = min(opens_c, new_max)
        cur.execute("UPDATE case_stock SET max_opens = ?, opens_count = ? WHERE case_id = ?", (new_max, new_opens, case_id))
    else:
        new_opens = max(0, opens_c - amount)
        new_max = max_o
        cur.execute("UPDATE case_stock SET opens_count = ? WHERE case_id = ?", (new_opens, case_id))

    conn.commit()
    conn.close()

    rem = max(0, new_max - new_opens)
    return web.json_response({
        "ok": True,
        "case_id": case_id,
        "remaining": rem,
        "max_opens": new_max,
        "message": f"«{cfg['name']}»: теперь в наличии {rem} из {new_max} шт.",
    })


async def api_admin_reset_event(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

    scope = str(body.get("scope", "one")).strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if scope == "all":
        cur.execute("UPDATE users SET event_points = 0, event_claimed_stage = 0")
        updated = cur.rowcount
        conn.commit()
        conn.close()
        return web.json_response({"ok": True, "message": f"Ивент сброшен с нуля у всех ({updated} игроков)"})

    target_uname = str(body.get("username", "")).lstrip("@").strip().lower()
    if not target_uname:
        conn.close()
        return web.json_response({"ok": False, "message": "Укажи @username игрока"})

    cur.execute(
        "UPDATE users SET event_points = 0, event_claimed_stage = 0 WHERE lower(username) = ?",
        (target_uname,),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()
    if updated == 0:
        return web.json_response({"ok": False, "message": f"Игрок @{target_uname} не найден"})
    return web.json_response({"ok": True, "message": f"Ивент сброшен с нуля для @{target_uname}"})


async def api_admin_requests(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, username, cost_stars, payout_stars, breakdown, status, created_at FROM withdraw_requests ORDER BY created_at DESC LIMIT 60"
    )
    reqs = [
        {
            "id": r[0],
            "user_id": int(r[1]),
            "username": r[2],
            "cost_stars": int(r[3]),
            "payout_stars": int(r[4]),
            "breakdown": r[5],
            "status": r[6],
            "created_at": int(r[7]),
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return web.json_response({"ok": True, "requests": reqs})


async def api_admin_complete(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    req_id = str(body.get("request_id", "")).strip()
    ok, newly_done, info = mark_request_done(req_id)
    if not ok or not info:
        return web.json_response({"ok": False, "message": "Заявка не найдена"})
    uid, cost_s, pay_s, bdown, uname = info
    if newly_done:
        await notify_user_withdraw_done(req_id, uid, cost_s, pay_s, bdown, uname)
    return web.json_response({"ok": True, "status": "done"})


async def api_admin_delete_request(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    req_id = str(body.get("request_id", "")).strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM withdraw_requests WHERE id = ?", (req_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return web.json_response({"ok": True, "deleted": deleted})


async def api_admin_user_stars(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    target_uname = str(body.get("username", "")).lstrip("@").strip().lower()
    delta = int(body.get("delta", 0) or 0)
    if not target_uname or delta == 0:
        return web.json_response({"ok": False, "message": "Укажи @username и количество звёзд"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, stars_balance, wager_left FROM users WHERE lower(username) = ?", (target_uname,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"ok": False, "message": f"Пользователь @{target_uname} не найден"})

    target_uid, old_bal, old_wag = int(row[0]), int(row[1]), int(row[2])
    new_bal = max(0, old_bal + delta)
    new_wag = min(new_bal, old_wag)
    cur.execute("UPDATE users SET stars_balance = ?, wager_left = ? WHERE user_id = ?", (new_bal, new_wag, target_uid))
    conn.commit()
    conn.close()

    try:
        sign_str = f"+{delta}" if delta > 0 else f"{delta}"
        await bot.send_message(
            chat_id=target_uid,
            text=f"⭐ Администратор изменил ваш баланс GiftezUp: {sign_str} ★ (текущий баланс: {new_bal} ★).",
        )
    except Exception:
        pass

    return web.json_response({
        "ok": True,
        "message": f"Баланс @{target_uname} обновлён: {new_bal} ★",
        "stars_balance": new_bal,
    })


async def api_admin_reset_user_timer(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    target_uname = str(body.get("username", "")).lstrip("@").strip().lower()
    if not target_uname:
        return web.json_response({"ok": False, "message": "Укажи @username игрока"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_free_spin = 0, reminded_24h = 1 WHERE lower(username) = ?",
        (target_uname,),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()

    if updated == 0:
        return web.json_response({"ok": False, "message": f"Игрок @{target_uname} не найден"})

    return web.json_response({"ok": True, "message": f"24ч таймер сброшен для @{target_uname}"})


async def api_admin_reset_all_timers(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_free_spin = 0, reminded_24h = 1")
    updated = cur.rowcount
    conn.commit()
    conn.close()
    return web.json_response({"ok": True, "updated_users": updated})


async def api_admin_create_promo(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    code = str(body.get("code", "")).strip().upper()
    reward_type = str(body.get("reward_type", "stars")).strip()
    reward_stars = int(body.get("reward_stars", 0) or 0)
    case_id = str(body.get("case_id", "")).strip()
    reward_cases = int(body.get("reward_cases", 0) or 0)
    max_uses = int(body.get("max_uses", 1) or 1)

    if not code or max_uses < 1:
        return web.json_response({"ok": False, "message": "Укажи код и количество активаций"})

    if reward_type == "case":
        cfg = ALL_CASES_CONFIG.get(case_id)
        if not cfg or reward_cases < 1:
            return web.json_response({"ok": False, "message": "Выбери кейс и количество открытий за активацию"})
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT OR REPLACE INTO promocodes (code, reward_stars, max_uses, uses_count, active, reward_type, case_id, reward_cases)
            VALUES (?, 0, ?, 0, 1, 'case', ?, ?)
            """,
            (code, max_uses, case_id, reward_cases),
        )
        conn.commit()
        conn.close()
        return web.json_response({
            "ok": True,
            "message": f"Промокод {code} на {reward_cases} откр. кейса «{cfg['name']}» создан",
        })

    if reward_stars < 1:
        return web.json_response({"ok": False, "message": "Укажи сумму ★ за 1 активацию"})

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO promocodes (code, reward_stars, max_uses, uses_count, active, reward_type, case_id, reward_cases)
        VALUES (?, ?, ?, 0, 1, 'stars', '', 0)
        """,
        (code, reward_stars, max_uses),
    )
    conn.commit()
    conn.close()
    return web.json_response({"ok": True, "message": f"Промокод {code} на {reward_stars} ★ создан"})


async def api_admin_broadcast(request: web.Request) -> web.Response:
    body = await request.json()
    if not check_admin(body):
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"ok": False, "message": "Введите текст рассылки"})

    user_ids = get_all_user_ids()
    sent_count = 0
    failed_count = 0

    kb = None
    if VERCEL_APP_URL:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть GiftezUp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))]
            ]
        )

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, reply_markup=kb)
            sent_count += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed_count += 1

    return web.json_response({
        "ok": True,
        "sent": sent_count,
        "failed": failed_count,
        "total": len(user_ids),
    })


async def on_startup(app: web.Application) -> None:
    init_db()
    await bot.delete_webhook(drop_pending_updates=False)
    app["bot_task"] = asyncio.create_task(
        dp.start_polling(
            bot,
            polling_timeout=5,
            request_timeout=15,
            handle_signals=False,
        )
    )
    app["rem_task"] = asyncio.create_task(reminder_worker())


async def on_cleanup(app: web.Application) -> None:
    for name in ("bot_task", "rem_task"):
        t = app.get(name)
        if t:
            t.cancel()
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", lambda r: web.json_response({"ok": True, "service": "giftezup", "modes": get_system_modes()}))
    app.router.add_route("OPTIONS", "/{tail:.*}", lambda r: web.Response(status=204))

    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/check_sub", api_check_sub)
    app.router.add_post("/api/create_topup_invoice", api_create_topup_invoice)
    app.router.add_post("/api/spin_daily", api_spin_daily)
    app.router.add_post("/api/open_paid_case", api_open_paid_case)
    app.router.add_post("/api/reroll_case_drop", api_reroll_case_drop)
    app.router.add_post("/api/accept_case_drop", api_accept_case_drop)
    app.router.add_post("/api/upgrade_spin", api_upgrade_spin)
    app.router.add_post("/api/avalanche_state", api_avalanche_state)
    app.router.add_post("/api/avalanche_start", api_avalanche_start)
    app.router.add_post("/api/avalanche_cashout", api_avalanche_cashout)
    app.router.add_post("/api/event_claim_stage", api_event_claim_stage)
    app.router.add_post("/api/promo_redeem", api_promo_redeem)
    app.router.add_post("/api/withdraw_stars", api_withdraw_stars)

    app.router.add_post("/api/admin/mode", api_admin_mode)
    app.router.add_post("/api/admin/ui_version", api_admin_ui_version)
    app.router.add_post("/api/admin/event_toggle", api_admin_event_toggle)
    app.router.add_post("/api/admin/reset_games_history", api_admin_reset_games_history)
    app.router.add_post("/api/admin/user_free_cases", api_admin_user_free_cases)
    app.router.add_post("/api/admin/restock_case", api_admin_restock_case)
    app.router.add_post("/api/admin/reset_event", api_admin_reset_event)
    app.router.add_post("/api/admin/requests", api_admin_requests)
    app.router.add_post("/api/admin/complete", api_admin_complete)
    app.router.add_post("/api/admin/delete_request", api_admin_delete_request)
    app.router.add_post("/api/admin/user_stars", api_admin_user_stars)
    app.router.add_post("/api/admin/reset_user_timer", api_admin_reset_user_timer)
    app.router.add_post("/api/admin/reset_all_timers", api_admin_reset_all_timers)
    app.router.add_post("/api/admin/create_promo", api_admin_create_promo)
    app.router.add_post("/api/admin/broadcast", api_admin_broadcast)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)