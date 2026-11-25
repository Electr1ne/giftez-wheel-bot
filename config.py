import os

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

# Параметры общего цикла игры «Лавина» (синхронизировано с avalanche.html)
AV_WAIT_SEC = 5.0
AV_CRASH_PAUSE_SEC = 1.6
AV_SLOT_LEN = 21.0

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

DAILY_POOL = [
    {"type": "nothing", "weight": 83.5, "label": "Ничего",       "icon": "nothing.png"},
    {"type": "stars",   "min": 1, "max": 1,  "weight": 14.5, "label": "1 ★",          "icon": "star"},
    {"type": "stars",   "min": 2, "max": 3,  "weight": 1.75, "label": "2–3 ★",        "icon": "star"},
    {"type": "gift",    "gift": "bear",      "weight": 0.20, "label": "Мишка (15 ★)", "icon": "bear.png"},
    {"type": "gift",    "gift": "rose",      "weight": 0.05, "label": "Роза (25 ★)",  "icon": "rose.png"},
]

EVENT_STAGES = [
    {"stage": 1, "points": 60,   "reward_stars": 2,  "title": "Первый иней"},
    {"stage": 2, "points": 180,  "reward_stars": 5,  "title": "Холодный ветер"},
    {"stage": 3, "points": 420,  "reward_stars": 12, "title": "Ледяной рубеж"},
    {"stage": 4, "points": 850,  "reward_stars": 25, "title": "Полярная ночь"},
    {"stage": 5, "points": 1600, "reward_stars": 50, "title": "Повелитель вьюги"},
]

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
