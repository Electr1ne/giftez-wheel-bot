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
VERCEL_APP_URL = os.getenv("VERCEL_APP_URL")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
CHANNEL_CHAT_ID = os.getenv("CHANNEL_CHAT_ID")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS").split(",") if x.strip().isdigit()}
PORT = int(os.getenv("PORT"))
DB_PATH = os.getenv("DB_PATH")

COOLDOWN_SEC = 24 * 60 * 60

TIER_CHANCES = {
    "free":   {"bear": 0.035, "rose": 0.015},  # 5% приз / 95% ничего
    "std1":   {"bear": 0.035, "rose": 0.015},  # 1 ★ — как обычный
    "boost5": {"bear": 0.05,  "rose": 0.05},   # 5 ★ — 10% приз / 90% ничего
    "top10":  {"bear": 0.12,  "rose": 0.08},   # 10 ★ — 20% приз / 80% ничего
}

TIER_PRICES = {
    "std1": 1,
    "boost5": 5,
    "top10": 10,
}

PRIZE_INFO = {
    "bear": {"name": "Мишка", "stars": 15, "exchange": 13},
    "rose": {"name": "Роза",   "stars": 25, "exchange": 21},
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==========================================
# CORS MIDDLEWARE ДЛЯ ЗАПРОСОВ С VERCEL
# ==========================================
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


# ==========================================
# БАЗА ДАННЫХ (SQLite3)
# ==========================================
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            device_fp TEXT DEFAULT '',
            last_free_spin INTEGER DEFAULT 0,
            reminded_24h INTEGER DEFAULT 1,
            is_twin INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fingerprints (
            device_fp TEXT PRIMARY KEY,
            first_user_id INTEGER NOT NULL,
            flagged_twin INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            won_at INTEGER NOT NULL,
            status TEXT DEFAULT 'inventory'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS claim_requests (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            prize TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            status TEXT DEFAULT 'processing'
        )
    """)
    conn.commit()
    conn.close()


def ensure_user_and_check_twin(user_id: int, username: str, first_name: str, device_fp: str) -> bool:
    fp_clean = (device_fp or "").strip()[:128]
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT user_id, is_twin FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, device_fp, last_free_spin, reminded_24h, is_twin) VALUES (?, ?, ?, ?, 0, 1, 0)",
            (user_id, username, first_name, fp_clean),
        )
        current_twin = 0
    else:
        current_twin = int(row[1] or 0)
        cur.execute(
            "UPDATE users SET username = ?, first_name = ?, device_fp = COALESCE(NULLIF(?, ''), device_fp) WHERE user_id = ?",
            (username, first_name, fp_clean, user_id),
        )

    if fp_clean:
        cur.execute("SELECT first_user_id, flagged_twin FROM fingerprints WHERE device_fp = ?", (fp_clean,))
        fp_row = cur.fetchone()
        if not fp_row:
            cur.execute(
                "INSERT INTO fingerprints (device_fp, first_user_id, flagged_twin) VALUES (?, ?, ?)",
                (fp_clean, user_id, current_twin),
            )
        else:
            first_uid, fp_flagged = int(fp_row[0]), int(fp_row[1])
            if first_uid != user_id or fp_flagged == 1:
                current_twin = 1
                cur.execute("UPDATE fingerprints SET flagged_twin = 1 WHERE device_fp = ?", (fp_clean,))
                cur.execute("UPDATE users SET is_twin = 1 WHERE user_id IN (?, ?)", (first_uid, user_id))

    conn.commit()
    conn.close()
    return bool(current_twin)


# ==========================================
# ВАЛИДАЦИЯ initData И ПРОВЕРКА ПОДПИСКИ
# ==========================================
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
    if time.time() - auth_date > 86400:
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except Exception:
        return None


async def is_channel_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_CHAT_ID, user_id=user_id)
        return member.status in {"member", "administrator", "creator"}
    except Exception:
        return False


# ==========================================
# НАПОМИНАНИЕ В ЛС ТОЛЬКО ПОСЛЕ 24Ч БЕСПЛАТНОГО КУЛДАУНА
# ==========================================
async def reminder_worker() -> None:
    while True:
        try:
            now = int(time.time())
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT user_id FROM users
                WHERE is_twin = 0
                  AND last_free_spin > 0
                  AND (? - last_free_spin) >= ?
                  AND reminded_24h = 0
            """, (now, COOLDOWN_SEC))
            rows = cur.fetchall()
            conn.close()

            for (uid,) in rows:
                try:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="Крутить рулетку", web_app=WebAppInfo(url=VERCEL_APP_URL))]
                        ]
                    )
                    await bot.send_message(
                        chat_id=uid,
                        text="Бесплатный спин в рулетке снова доступен!",
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


# ==========================================
# ХЕНДЛЕРЫ БОТА
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = message.from_user
    ensure_user_and_check_twin(u.id, u.username or "", u.first_name or "", "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть рулетку", web_app=WebAppInfo(url=VERCEL_APP_URL))],
            [InlineKeyboardButton(text="Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME}")],
        ]
    )
    await message.answer(
        f"Привет, {u.first_name or 'игрок'}!\nПодпишись на @{CHANNEL_USERNAME} и крути рулетку.",
        reply_markup=kb,
    )


@dp.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, username, prize FROM claim_requests WHERE status = 'processing' ORDER BY created_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("Активных заявок в обработке нет.")
        return

    for req_id, uid, uname, prize in rows:
        meta = PRIZE_INFO.get(prize, {"name": prize, "stars": 0, "exchange": 0})
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Выдано", callback_data=f"done_claim:{req_id}")]]
        )
        await message.answer(
            f"🎁 Заявка #{req_id}\n"
            f"Подарок: {meta['name']} ({meta['stars']} ★ → {meta['exchange']} ★ при обмене)\n"
            f"Пользователь: @{uname} (ID: {uid})\n"
            f"Выдача: от 10 минут до 14 дней",
            reply_markup=kb,
        )


@dp.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


def mark_request_done(req_id: str) -> tuple[bool, tuple | None]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, prize, username, status FROM claim_requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, None
    uid, prize, uname, st = int(row[0]), row[1], row[2], row[3]
    if st != "done":
        cur.execute("UPDATE claim_requests SET status = 'done' WHERE id = ?", (req_id,))
        conn.commit()
    conn.close()
    return True, (uid, prize, uname)


@dp.callback_query(F.data.startswith("done_claim:"))
async def on_admin_done_claim(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    req_id = callback.data.split(":", 1)[1]
    ok, info = mark_request_done(req_id)
    if not ok or not info:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    uid, prize, uname = info
    meta = PRIZE_INFO.get(prize, {"name": prize, "stars": 0, "exchange": 0})
    await callback.message.edit_text(
        f"✅ Выполнено\n"
        f"Подарок: {meta['name']} ({meta['stars']} ★ → {meta['exchange']} ★)\n"
        f"Получатель: @{uname} (ID: {uid})"
    )
    await callback.answer("Статус обновлён: Выполнено")


# ==========================================
# HTTP API ДЛЯ ФРОНТЕНДА НА VERCEL
# ==========================================
async def api_state(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    is_twin = ensure_user_and_check_twin(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
        body.get("device_fp", ""),
    )
    sub_ok = await is_channel_subscribed(uid)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_free_spin FROM users WHERE user_id = ?", (uid,))
    r_user = cur.fetchone()
    last_free = int(r_user[0]) if r_user else 0

    cur.execute(
        "SELECT id, prize, won_at FROM inventory WHERE user_id = ? AND status = 'inventory' ORDER BY won_at DESC",
        (uid,),
    )
    inv_rows = [{"id": r[0], "prize": r[1], "won_at": int(r[2])} for r in cur.fetchall()]

    cur.execute(
        "SELECT id, prize, username, status, created_at FROM claim_requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
        (uid,),
    )
    my_reqs = [
        {"id": r[0], "prize": r[1], "username": r[2], "status": r[3], "created_at": int(r[4])}
        for r in cur.fetchall()
    ]
    conn.close()

    return web.json_response({
        "ok": True,
        "is_subscribed": sub_ok,
        "is_twin": is_twin,
        "is_admin": uid in ADMIN_IDS,
        "next_spin_at": (last_free + COOLDOWN_SEC) if last_free > 0 else 0,
        "inventory_items": inv_rows,
        "my_requests": my_reqs,
        "chances": TIER_CHANCES["free"],
        "boost_chances": TIER_CHANCES["boost5"],
        "top10_chances": TIER_CHANCES["top10"],
    })


async def api_check_sub(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False}, status=401)

    uid = int(tg_user["id"])
    is_twin = ensure_user_and_check_twin(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
        body.get("device_fp", ""),
    )
    sub_ok = await is_channel_subscribed(uid)
    return web.json_response({"ok": True, "is_subscribed": sub_ok, "is_twin": is_twin})


async def api_create_star_invoice(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    is_twin = ensure_user_and_check_twin(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
        body.get("device_fp", ""),
    )
    if is_twin:
        return web.json_response({"ok": False, "error": "twin_detected", "message": "Твинку спины недоступны"}, status=403)

    if not await is_channel_subscribed(uid):
        return web.json_response({"ok": False, "error": "not_subscribed", "message": "Нужна подписка на канал"})

    tier = str(body.get("tier", "std1"))
    stars = TIER_PRICES.get(tier, 1)

    payload = f"spin:{tier}:{uid}:{uuid.uuid4().hex[:8]}"
    link = await bot.create_invoice_link(
        title=f"Спин в рулетке ({stars} ★)",
        description="Дополнительный прокрут рулетки",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} ★ Спин", amount=stars)],
    )
    return web.json_response({"ok": True, "invoice_link": link, "payload": payload})


def roll_prize_server(tier: str, exclude_nothing: bool) -> str:
    pool = TIER_CHANCES.get(tier, TIER_CHANCES["free"])
    b = pool["bear"]
    r = pool["rose"]
    if exclude_nothing:
        total = max(1e-9, b + r)
        return "bear" if (random.random() * total) < b else "rose"
    x = random.random()
    if x < b:
        return "bear"
    if x < b + r:
        return "rose"
    return "nothing"


async def api_spin(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

    uid = int(tg_user["id"])
    tier = str(body.get("tier", "free"))
    if tier not in TIER_CHANCES:
        tier = "free"
    is_paid_star = bool(body.get("paid_star", False)) and tier != "free"
    exclude_nothing = bool(body.get("exclude_nothing", False))

    is_twin = ensure_user_and_check_twin(
        uid,
        (tg_user.get("username") or "").lstrip("@"),
        tg_user.get("first_name") or "",
        body.get("device_fp", ""),
    )
    if is_twin:
        return web.json_response({
            "ok": False,
            "error": "twin_detected",
            "message": "Твинку нельзя крутить ни бесплатно, ни за Stars",
        })

    if not await is_channel_subscribed(uid):
        return web.json_response({
            "ok": False,
            "error": "not_subscribed",
            "message": "Подпишись на канал перед прокрутом",
        })

    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_free_spin FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    last_free = int(row[0]) if row else 0

    if not is_paid_star:
        if last_free > 0 and (now - last_free) < COOLDOWN_SEC:
            conn.close()
            return web.json_response({
                "ok": False,
                "error": "cooldown",
                "next_spin_at": last_free + COOLDOWN_SEC,
                "message": "24-часовой спин ещё не готов",
            })
        last_free = now
        cur.execute(
            "UPDATE users SET last_free_spin = ?, reminded_24h = 0 WHERE user_id = ?",
            (last_free, uid),
        )

    prize = roll_prize_server(tier, exclude_nothing)
    item_id = None
    if prize in PRIZE_INFO:
        item_id = f"item_{uuid.uuid4().hex[:10]}"
        cur.execute(
            "INSERT INTO inventory (id, user_id, prize, won_at, status) VALUES (?, ?, ?, ?, 'inventory')",
            (item_id, uid, prize, now),
        )

    conn.commit()
    conn.close()

    return web.json_response({
        "ok": True,
        "prize": prize,
        "item_id": item_id,
        "next_spin_at": (last_free + COOLDOWN_SEC) if last_free > 0 else 0,
    })


async def api_claim_request(request: web.Request) -> web.Response:
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
            "message": "В Telegram не указан @username — забрать подарок нельзя",
        })

    item_id = str(body.get("item_id", "")).strip()
    now = int(time.time())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT prize FROM inventory WHERE id = ? AND user_id = ? AND status = 'inventory'",
        (item_id, uid),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return web.json_response({"ok": False, "message": "Предмет уже забран или не найден"})

    prize = row[0]
    req_id = f"req_{uuid.uuid4().hex[:10]}"

    cur.execute("DELETE FROM inventory WHERE id = ? AND user_id = ?", (item_id, uid))
    cur.execute(
        "INSERT INTO claim_requests (id, item_id, user_id, username, prize, created_at, status) VALUES (?, ?, ?, ?, ?, ?, 'processing')",
        (req_id, item_id, uid, final_uname, prize, now),
    )
    conn.commit()
    conn.close()

    meta = PRIZE_INFO.get(prize, {"name": prize, "stars": 0, "exchange": 0})
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Выдано", callback_data=f"done_claim:{req_id}")]]
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🎁 Новая заявка на выдачу\n"
                    f"Подарок: {meta['name']} ({meta['stars']} ★ → {meta['exchange']} ★ при обмене)\n"
                    f"Пользователь: @{final_uname} (ID: {uid})\n"
                    f"Выдача: от 10 минут до 14 дней"
                ),
                reply_markup=kb,
            )
        except Exception:
            pass

    return web.json_response({"ok": True, "request_id": req_id, "status": "processing"})


async def api_admin_requests(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user or int(tg_user["id"]) not in ADMIN_IDS:
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, username, prize, status, created_at FROM claim_requests ORDER BY created_at DESC LIMIT 50"
    )
    reqs = [
        {
            "id": r[0],
            "user_id": int(r[1]),
            "username": r[2],
            "prize": r[3],
            "status": r[4],
            "created_at": int(r[5]),
        }
        for r in cur.fetchall()
    ]
    conn.close()
    return web.json_response({"ok": True, "requests": reqs})


async def api_admin_complete(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user or int(tg_user["id"]) not in ADMIN_IDS:
        return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)

    req_id = str(body.get("request_id", "")).strip()
    ok, _ = mark_request_done(req_id)
    if not ok:
        return web.json_response({"ok": False, "message": "Заявка не найдена"})
    return web.json_response({"ok": True, "status": "done"})


async def api_dev_reset_cooldown(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False}, status=401)

    uid = int(tg_user["id"])
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET last_free_spin = 0, reminded_24h = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
    return web.json_response({"ok": True})


async def on_startup(app: web.Application) -> None:
    init_db()
    app["bot_task"] = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    app["rem_task"] = asyncio.create_task(reminder_worker())


async def on_cleanup(app: web.Application) -> None:
    for name in ("bot_task", "rem_task"):
        t = app.get(name)
        if t:
            t.cancel()
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_route("OPTIONS", "/{tail:.*}", lambda r: web.Response(status=204))
    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/check_sub", api_check_sub)
    app.router.add_post("/api/create_star_invoice", api_create_star_invoice)
    app.router.add_post("/api/spin", api_spin)
    app.router.add_post("/api/claim_request", api_claim_request)
    app.router.add_post("/api/admin/requests", api_admin_requests)
    app.router.add_post("/api/admin/complete", api_admin_complete)
    app.router.add_post("/api/dev/reset_cooldown", api_dev_reset_cooldown)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)