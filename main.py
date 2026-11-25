import asyncio
import sqlite3
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)
from aiohttp import web

from api_routes import notify_user_withdraw_done, register_api_routes
from config import (
    ADMIN_IDS,
    BOT_TOKEN,
    CHANNEL_USERNAME,
    COOLDOWN_SEC,
    DB_PATH,
    PORT,
    VERCEL_APP_URL,
)
from db import (
    ensure_user,
    get_system_modes,
    init_db,
    mark_request_done,
    set_system_mode,
    set_ui_version,
)

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


async def reminder_worker() -> None:
    while True:
        try:
            now = int(time.time())
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT user_id FROM users
                WHERE last_free_spin > 0
                  AND (? - last_free_spin) >= ?
                  AND reminded_24h = 0
                """,
                (now, COOLDOWN_SEC),
            )
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
        await notify_user_withdraw_done(bot, req_id, uid, cost_s, pay_s, bdown, uname)
    await callback.message.edit_text(
        f"✅ Выполнено #{req_id}\n"
        f"Списано: {cost_s} ★ → Выдано: {pay_s} ★\n"
        f"Пакеты: {bdown}\n"
        f"Получатель: @{uname} (ID: {uid})"
    )
    await callback.answer("Статус обновлён: Выполнено")


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

    register_api_routes(app, bot)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
