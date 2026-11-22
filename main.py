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

# Номиналы подарков-пакетов для вывода: списывается -> выдаётся звёздами
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

# Ежедневный: чаще всего "Ничего" или 1 ★, редкие призы с сильно урезанными шансами
DAILY_POOL = [
    {"type": "nothing", "weight": 74.0, "label": "Ничего",       "icon": "nothing.png"},
    {"type": "stars",   "min": 1, "max": 1,  "weight": 20.0, "label": "1 ★",          "icon": "star"},
    {"type": "stars",   "min": 2, "max": 5,  "weight": 5.0,  "label": "2–5 ★",        "icon": "star"},
    {"type": "gift",    "gift": "bear",      "weight": 0.75, "label": "Мишка (15 ★)", "icon": "bear.png"},
    {"type": "gift",    "gift": "rose",      "weight": 0.25, "label": "Роза (25 ★)",  "icon": "rose.png"},
]

# У каждого кейса своя цена перекрута (всегда дешевле самого кейса) и урезанные шансы на топ-дроп
CASES_CONFIG = {
    "starter": {
        "id": "starter",
        "name": "Стартовый",
        "price": 5,
        "reroll_price": 3,
        "badge": "ЗИМА",
        "icon": "starter.png",
        "pool": [
            {"type": "stars", "min": 1, "max": 2, "weight": 82.0, "label": "1–2 ★",        "icon": "star"},
            {"type": "stars", "min": 3, "max": 5, "weight": 15.0, "label": "3–5 ★",        "icon": "star"},
            {"type": "gift",  "gift": "bear",     "weight": 2.2,  "label": "Мишка (15 ★)", "icon": "bear.png"},
            {"type": "gift",  "gift": "rose",     "weight": 0.8,  "label": "Роза (25 ★)",  "icon": "rose.png"},
        ],
    },
    "morozniy": {
        "id": "morozniy",
        "name": "Морозный",
        "price": 12,
        "reroll_price": 7,
        "badge": "ТОП",
        "icon": "morozniy.png",
        "pool": [
            {"type": "stars", "min": 2, "max": 5,  "weight": 80.0, "label": "2–5 ★",          "icon": "star"},
            {"type": "stars", "min": 6, "max": 11, "weight": 16.0, "label": "6–11 ★",         "icon": "star"},
            {"type": "gift",  "gift": "heart",     "weight": 2.5,  "label": "Сердце (15 ★)",  "icon": "heart.png"},
            {"type": "gift",  "gift": "gift",      "weight": 1.1,  "label": "Коробка (25 ★)", "icon": "gift.png"},
            {"type": "gift",  "gift": "bottle",    "weight": 0.4,  "label": "Напиток (50 ★)", "icon": "bottle.png"},
        ],
    },
    "sever": {
        "id": "sever",
        "name": "Северный",
        "price": 25,
        "reroll_price": 15,
        "badge": "NEW",
        "icon": "sever.png",
        "pool": [
            {"type": "stars", "min": 5,  "max": 12, "weight": 80.0, "label": "5–12 ★",         "icon": "star"},
            {"type": "stars", "min": 13, "max": 22, "weight": 16.2, "label": "13–22 ★",        "icon": "star"},
            {"type": "gift",  "gift": "cake",       "weight": 2.2,  "label": "Торт (50 ★)",    "icon": "cake.png"},
            {"type": "gift",  "gift": "rocket",     "weight": 1.2,  "label": "Ракета (50 ★)",  "icon": "rocket.png"},
            {"type": "gift",  "gift": "ring",       "weight": 0.4,  "label": "Кольцо (100 ★)", "icon": "ring.png"},
        ],
    },
    "newyear": {
        "id": "newyear",
        "name": "Новогодний",
        "price": 50,
        "reroll_price": 30,
        "badge": "VIP",
        "icon": "newyear.png",
        "pool": [
            {"type": "stars", "min": 25,  "max": 45,  "weight": 74.0, "label": "25–45 ★",            "icon": "star"},
            {"type": "stars", "min": 55,  "max": 85,  "weight": 19.5, "label": "55–85 ★",            "icon": "star"},
            {"type": "stars", "min": 100, "max": 140, "weight": 4.2,  "label": "100–140 ★",          "icon": "star"},
            {"type": "gift",  "gift": "ring",         "weight": 1.8,  "label": "Кольцо (100 ★)",     "icon": "ring.png"},
            {"type": "stars", "min": 200, "max": 250, "weight": 0.5,  "label": "Джекпот 200–250 ★",  "icon": "star"},
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
    """Мягкая инициализация и миграция без потери существующих данных пользователей."""
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
            sub_checked_at INTEGER DEFAULT 0
        )
    """)

    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "stars_balance" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN stars_balance INTEGER DEFAULT 0")
    if "wager_left" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN wager_left INTEGER DEFAULT 0")
    if "total_spins" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN total_spins INTEGER DEFAULT 0")
    if "sub_cached" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN sub_cached INTEGER DEFAULT 0")
    if "sub_checked_at" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN sub_checked_at INTEGER DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('maintenance_mode', '0')")
    cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('update_mode', '0')")

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
            reward_stars INTEGER NOT NULL,
            max_uses INTEGER NOT NULL,
            uses_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

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
    cur.execute("SELECT key, value FROM app_settings WHERE key IN ('maintenance_mode', 'update_mode')")
    rows = dict(cur.fetchall())
    conn.close()
    return {
        "maintenance": rows.get("maintenance_mode", "0") == "1",
        "update": rows.get("update_mode", "0") == "1",
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


def ensure_user(user_id: int, username: str, first_name: str) -> None:
    clean_uname = (username or "").lstrip("@").strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_free_spin, reminded_24h, stars_balance, wager_left, total_spins, sub_cached, sub_checked_at)
            VALUES (?, ?, ?, 0, 1, 0, 0, 0, 0, 0)
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
        f"✅ Заявка на вывод #{req_id} выполнена!\n"
        f"Списано: {cost_stars} ★ → Выдано: {payout_stars} ★\n"
        f"Состав: {breakdown}\n"
        f"Получатель: @{uname}"
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
                f"Для вывода пополненных звёзд их нужно отыграть в кейсах или апгрейдере."
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
            "label": f"{amt} ★",
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

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT last_free_spin, stars_balance, wager_left, total_spins FROM users WHERE user_id = ?",
        (uid,),
    )
    r_user = cur.fetchone()
    last_free = int(r_user[0]) if r_user else 0
    raw_bal = int(r_user[1]) if r_user else 0
    raw_wag = int(r_user[2]) if r_user else 0
    total_spins = int(r_user[3]) if r_user else 0

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
    conn.close()

    cases_public = [
        {
            "id": "daily",
            "name": "Ежедневный",
            "price": 0,
            "is_daily": True,
            "badge": "24Ч",
            "icon": "daily.png",
            "reroll_price": 0,
            "items": [
                {"label": x["label"], "type": x["type"], "gift": x.get("gift", ""), "icon": x.get("icon", "star")}
                for x in DAILY_POOL
            ],
        }
    ]
    for cid, cfg in CASES_CONFIG.items():
        cases_public.append({
            "id": cfg["id"],
            "name": cfg["name"],
            "price": cfg["price"],
            "is_daily": False,
            "badge": cfg["badge"],
            "icon": cfg["icon"],
            "reroll_price": int(cfg["reroll_price"]),
            "items": [
                {"label": x["label"], "type": x["type"], "gift": x.get("gift", ""), "icon": x.get("icon", "star")}
                for x in cfg["pool"]
            ],
        })

    return web.json_response({
        "ok": True,
        "is_subscribed": sub_ok,
        "is_admin": uid in ADMIN_IDS,
        "system_modes": modes,
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
    ensure_user(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
    )
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

    ensure_user(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
    )

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
    ensure_user(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
    )

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
    cfg = CASES_CONFIG.get(case_id)
    if not cfg:
        return web.json_response({"ok": False, "message": "Кейс не найден"})

    ensure_user(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
    )

    price = int(cfg["price"])
    reroll_price = int(cfg["reroll_price"])
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT * FROM pending_drops WHERE user_id = ?", (uid,))
    for old_drop in cur.fetchall():
        finalize_pending_drop_in_db(conn, old_drop)

    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    bal = int(row[0]) if row else 0
    wag = int(row[1]) if row else 0
    if bal < price:
        conn.commit()
        conn.close()
        return web.json_response({"ok": False, "message": f"Недостаточно звёзд (нужно {price} ★)"})

    new_bal = bal - price
    new_wag = max(0, wag - price)
    cur.execute(
        "UPDATE users SET stars_balance = ?, wager_left = ?, total_spins = total_spins + 1 WHERE user_id = ?",
        (new_bal, new_wag, uid),
    )

    drop = roll_from_pool(cfg["pool"])
    drop_id = f"drop_{uuid.uuid4().hex[:10]}"
    cur.execute(
        """
        INSERT INTO pending_drops (drop_id, user_id, case_id, drop_type, gift_id, stars_amount, label, icon, rerolled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (drop_id, uid, case_id, drop["drop_type"], drop["gift_id"], int(drop["stars_amount"]), drop["label"], drop["icon"], now),
    )

    conn.commit()
    conn.close()

    balances = compute_user_balances(new_bal, new_wag)
    return web.json_response({
        "ok": True,
        "drop_id": drop_id,
        "case_id": case_id,
        "drop": drop,
        "can_reroll": True,
        "reroll_price": reroll_price,
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
    cfg = CASES_CONFIG.get(case_id)
    if not cfg:
        conn.close()
        return web.json_response({"ok": False, "message": "Кейс не найден"})

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

    chance = min(75.0, max(1.0, round((bet_stars / max(1, target_stars)) * 84.0, 2)))
    roll = round(random.uniform(0.0, 100.0), 2)
    won = roll <= chance

    new_bal = bal - bet_stars
    new_wag = max(0, wag - bet_stars)

    if won:
        new_bal += target_stars

    cur.execute("UPDATE users SET stars_balance = ?, wager_left = ? WHERE user_id = ?", (new_bal, new_wag, uid))
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
        "SELECT reward_stars, max_uses, uses_count, active FROM promocodes WHERE code = ?",
        (code,),
    )
    promo = cur.fetchone()
    if not promo or int(promo[3]) != 1:
        conn.close()
        return web.json_response({"ok": False, "message": "Промокод не найден или отключён"})

    reward_stars, max_uses, uses_count = int(promo[0]), int(promo[1]), int(promo[2])
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
    cur.execute(
        "UPDATE users SET stars_balance = stars_balance + ?, wager_left = wager_left + ? WHERE user_id = ?",
        (reward_stars, reward_stars, uid),
    )
    cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
    r_u = cur.fetchone() or (0, 0)

    conn.commit()
    conn.close()

    balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
    return web.json_response({
        "ok": True,
        "reward_stars": reward_stars,
        "stars_balance": balances["stars_balance"],
        "wager_left": balances["wager_left"],
        "withdrawable_stars": balances["withdrawable_stars"],
        "message": f"Промокод активирован: +{reward_stars} ★",
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
    reward_stars = int(body.get("reward_stars", 0) or 0)
    max_uses = int(body.get("max_uses", 1) or 1)
    if not code or reward_stars < 1 or max_uses < 1:
        return web.json_response({"ok": False, "message": "Заполни код, сумму ★ и лимит"})

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO promocodes (code, reward_stars, max_uses, uses_count, active)
        VALUES (?, ?, ?, 0, 1)
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
    app.router.add_post("/api/promo_redeem", api_promo_redeem)
    app.router.add_post("/api/withdraw_stars", api_withdraw_stars)

    app.router.add_post("/api/admin/mode", api_admin_mode)
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