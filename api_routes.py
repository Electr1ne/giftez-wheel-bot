import asyncio
import html
import random
import sqlite3
import time
import uuid

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, WebAppInfo
from aiohttp import web

from config import (
    ADMIN_IDS,
    ALL_CASES_CONFIG,
    AV_CRASH_PAUSE_SEC,
    AV_SLOT_LEN,
    AV_WAIT_SEC,
    CHANNEL_CHAT_ID,
    CHANNEL_USERNAME,
    COOLDOWN_SEC,
    DAILY_POOL,
    DB_PATH,
    EVENT_END_TS,
    EVENT_STAGES,
    EVENT_START_TS,
    GIFTS_CATALOG,
    SCRATCH_EXTRA_ATTEMPT_PRICE,
    SUB_CACHE_TTL_SEC,
    VERCEL_APP_URL,
    WITHDRAW_PACKS,
)
from db import (
    check_admin,
    create_user_idea,
    delete_or_hide_user_idea,
    ensure_user,
    get_admin_ideas,
    get_all_user_ids,
    get_system_modes,
    get_user_idea_cooldown,
    get_user_ideas,
    is_case_visible_for_user,
    is_event_unlocked_for_user,
    mark_request_done,
    resolve_user_ui_version,
    review_user_idea,
    set_system_mode,
    set_ui_version,
    verify_init_data,
)
from game_logic import (
    add_event_points_from_stars,
    build_cases_public_list,
    compute_avalanche_duration_for_crash,
    compute_avalanche_mult_at_elapsed,
    compute_user_balances,
    decompose_withdraw_amount,
    finalize_pending_drop_in_db,
    get_or_create_scratch_ticket,
    is_snowflakes_active_in_db,
    roll_from_pool,
    roll_smart_avalanche_crash,
    scratch_decline_extra_in_db,
    scratch_reveal_cell_in_db,
    suggest_nearest_withdraw_amounts,
    sync_shared_avalanche_round,
)


async def is_channel_subscribed(bot: Bot, user_id: int, force_refresh: bool = False) -> bool:
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


async def notify_user_withdraw_done(
    bot: Bot, req_id: str, uid: int, cost_stars: int, payout_stars: int, breakdown: str, uname: str
) -> None:
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


def build_admin_idea_kb(idea_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ Принять (0 ★)", callback_data=f"idea_act:acc0:{idea_id}"),
            InlineKeyboardButton(text="⭐ Принять + ★", callback_data=f"idea_act:acc_stars:{idea_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"idea_act:rej0:{idea_id}"),
            InlineKeyboardButton(text="📝 Отклонить с причиной", callback_data=f"idea_act:rej_reason:{idea_id}"),
        ],
    ]
    if VERCEL_APP_URL:
        rows.append([
            InlineKeyboardButton(
                text="📋 Открыть страницу идей",
                web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/admin_ideas.html"),
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_user_idea_reviewed(bot: Bot, idea: dict) -> None:
    uid = int(idea["user_id"])
    idea_id = int(idea["id"])
    theme_safe = html.escape(str(idea.get("theme", "")))
    status = str(idea.get("status", ""))

    if status == "accepted":
        eta = html.escape(str(idea.get("eta_updates") or "2–4"))
        reward = int(idea.get("stars_reward") or 0)
        reward_line = (
            f"\n⭐ Начислена награда за идею: <b>+{reward} ★</b> (зачислено на баланс)."
            if reward > 0
            else "\nℹ️ Идея принята без дополнительного начисления звёзд."
        )
        text = (
            f"💡 <b>Ваша идея #{idea_id} принята!</b>\n"
            f"• Тема: <b>{theme_safe}</b>\n"
            f"• Ориентир реализации: ближайшие <b>{eta}</b> обновлений."
            f"{reward_line}\n\n"
            f"Спасибо за вклад в развитие GiftezUp!"
        )
    elif status == "rejected":
        reason = str(idea.get("reject_reason") or "").strip()
        reason_line = (
            f"\n• Причина: <i>{html.escape(reason)}</i>"
            if reason
            else "\n• Причина не указана администратором."
        )
        text = (
            f"❌ <b>Ваша идея #{idea_id} отклонена</b>\n"
            f"• Тема: <b>{theme_safe}</b>"
            f"{reason_line}\n\n"
            f"Следующую идею можно будет отправить через <b>24 часа</b>."
        )
    else:
        return

    kb = None
    if VERCEL_APP_URL:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть профиль", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/profile.html"))]
            ]
        )
    try:
        await bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        print(f"[notify_idea] Не удалось уведомить пользователя {uid}: {e}")


def register_api_routes(app: web.Application, bot: Bot) -> None:
    async def api_state(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

        uid = int(tg_user["id"])
        ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")
        sub_ok = await is_channel_subscribed(bot, uid, force_refresh=False)
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
        sub_ok = await is_channel_subscribed(bot, uid, force_refresh=True)
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

    # ======================== СКРЕТЧ-БИЛЕТ (БОНУСЫ) ========================
    async def api_bonus_scratch_state(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])
        ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")

        conn = sqlite3.connect(DB_PATH)
        ticket = get_or_create_scratch_ticket(conn, uid)
        cur = conn.cursor()
        cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
        r_u = cur.fetchone() or (0, 0)
        conn.close()

        balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
        return web.json_response({
            "ok": True,
            "ticket": ticket,
            "stars_balance": balances["stars_balance"],
            "wager_left": balances["wager_left"],
            "withdrawable_stars": balances["withdrawable_stars"],
        })

    async def api_bonus_scratch_reveal(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])
        cell_index = int(body.get("cell_index", -1))

        conn = sqlite3.connect(DB_PATH)
        conn.isolation_level = None
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            ok, msg, ticket = scratch_reveal_cell_in_db(conn, uid, cell_index)
            cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
            r_u = cur.fetchone() or (0, 0)
            if conn.in_transaction:
                cur.execute("COMMIT")
        except Exception as e:
            if conn.in_transaction:
                cur.execute("ROLLBACK")
            conn.close()
            return web.json_response({"ok": False, "message": f"Ошибка билета: {e}"})

        conn.close()
        balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
        return web.json_response({
            "ok": ok,
            "message": msg,
            "ticket": ticket,
            "stars_balance": balances["stars_balance"],
            "wager_left": balances["wager_left"],
            "withdrawable_stars": balances["withdrawable_stars"],
        })

    async def api_bonus_scratch_buy_extra(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])
        ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")

        conn = sqlite3.connect(DB_PATH)
        ticket = get_or_create_scratch_ticket(conn, uid)
        conn.close()

        if ticket["extra_bought"]:
            return web.json_response({"ok": False, "message": "Дополнительная попытка уже активна"})
        if ticket["status"] not in ("awaiting_extra", "playing"):
            return web.json_response({"ok": False, "message": "Текущий билет уже завершён"})

        price = int(SCRATCH_EXTRA_ATTEMPT_PRICE)
        payload = f"scratch_extra:{uid}:{price}:{uuid.uuid4().hex[:8]}"
        link = await bot.create_invoice_link(
            title=f"Дополнительная попытка ({price} ★)",
            description="Открыть ещё 1 ячейку в текущем скретч-билете GiftezUp",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=f"Доп. попытка ({price} ★)", amount=price)],
        )
        return web.json_response({"ok": True, "invoice_link": link, "payload": payload})

    async def api_bonus_scratch_decline(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])

        conn = sqlite3.connect(DB_PATH)
        ok, msg, ticket = scratch_decline_extra_in_db(conn, uid)
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
        r_u = cur.fetchone() or (0, 0)
        conn.close()

        balances = compute_user_balances(int(r_u[0]), int(r_u[1]))
        return web.json_response({
            "ok": ok,
            "message": msg,
            "ticket": ticket,
            "stars_balance": balances["stars_balance"],
            "wager_left": balances["wager_left"],
            "withdrawable_stars": balances["withdrawable_stars"],
        })

    async def api_spin_daily(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])
        ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")

        if not await is_channel_subscribed(bot, uid, force_refresh=True):
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
        balances = compute_user_balances(stars_balance + int(drop["stars_amount"]), wager_left)
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
                    if conn.in_transaction:
                        cur.execute("ROLLBACK")
                    conn.close()
                    return web.json_response({"ok": False, "message": "Кейс раскуплен (запас закончился)"})

            cur.execute("SELECT count FROM user_free_cases WHERE user_id = ? AND case_id = ?", (uid, case_id))
            fc_row = cur.fetchone()
            free_opens_left = int(fc_row[0]) if fc_row else 0
            used_free_open = free_opens_left > 0

            cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
            row = cur.fetchone()
            bal = int(row[0]) if row else 0
            wag = int(row[1]) if row else 0

            if not used_free_open and bal < price:
                if conn.in_transaction:
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

            if conn.in_transaction:
                cur.execute("COMMIT")
        except Exception as e:
            if conn.in_transaction:
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

        new_bal = bal - bet_stars + (target_stars if won else 0)
        new_wag = max(0, wag - bet_stars)
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
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        conn = sqlite3.connect(DB_PATH)
        state = sync_shared_avalanche_round(conn, auto_commit=True)
        conn.close()
        return web.json_response({"ok": True, **state})

    async def api_avalanche_start(request: web.Request) -> web.Response:
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
            state = sync_shared_avalanche_round(conn, auto_commit=False)
            round_id = state["round_id"]

            if state["phase"] != "waiting":
                if conn.in_transaction:
                    cur.execute("ROLLBACK")
                conn.close()
                return web.json_response({"ok": False, "message": "Раунд уже идёт — дождитесь следующего"})

            cur.execute("SELECT 1 FROM avalanche_bets WHERE round_id = ? AND user_id = ?", (round_id, uid))
            if cur.fetchone():
                if conn.in_transaction:
                    cur.execute("ROLLBACK")
                conn.close()
                return web.json_response({"ok": False, "message": "Вы уже поставили в этот раунд"})

            cur.execute("SELECT stars_balance, wager_left FROM users WHERE user_id = ?", (uid,))
            r_u = cur.fetchone() or (0, 0)
            bal, wag = int(r_u[0]), int(r_u[1])
            if bal < bet:
                if conn.in_transaction:
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

            new_crash = roll_smart_avalanche_crash(conn, round_id)
            cur.execute("UPDATE avalanche_shared_rounds SET crash_mult = ? WHERE round_id = ?", (new_crash, round_id))
            add_event_points_from_stars(conn, uid, bet)
            if conn.in_transaction:
                cur.execute("COMMIT")
        except Exception as e:
            if conn.in_transaction:
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
                if conn.in_transaction:
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

            if target_round_id != cur_round_id or effective_crash <= 0.0:
                cur.execute("UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE id = ?", (bet_id,))
                if conn.in_transaction:
                    cur.execute("COMMIT")
                conn.close()
                return web.json_response({"ok": False, "message": "Лавина сошла раньше!"})

            flight_elapsed = max(0.0, slot_offset - AV_WAIT_SEC)
            server_mult_with_grace = compute_avalanche_mult_at_elapsed(flight_elapsed + 0.5)

            if claim_mult < 0.05 or claim_mult > effective_crash or claim_mult > server_mult_with_grace:
                if claim_mult > effective_crash:
                    cur.execute("UPDATE avalanche_bets SET status = 'lost', cashout_mult = 0, payout = 0 WHERE id = ?", (bet_id,))
                    if conn.in_transaction:
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
            if conn.in_transaction:
                cur.execute("COMMIT")
        except Exception as e:
            if conn.in_transaction:
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

        cur.execute("INSERT INTO promo_activations (code, user_id, activated_at) VALUES (?, ?, ?)", (code, uid, now))
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
            return web.json_response({"ok": False, "message": "Укажи @username в профиле Telegram для вывода звёзд"})

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
            return web.json_response({"ok": False, "message": f"Доступно к выводу: {balances['withdrawable_stars']} ★"})

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

    # ======================== USER IDEAS ENDPOINTS ========================
    async def api_ideas_list(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)
        uid = int(tg_user["id"])
        ensure_user(uid, (tg_user.get("username") or "").lstrip("@"), tg_user.get("first_name") or "")
        ideas = get_user_ideas(uid, limit=40)
        cd = get_user_idea_cooldown(uid)
        return web.json_response({
            "ok": True,
            "ideas": ideas,
            "cooldown": cd,
        })

    async def api_ideas_create(request: web.Request) -> web.Response:
        body = await request.json()
        tg_user = verify_init_data(body.get("initData", ""))
        if not tg_user:
            return web.json_response({"ok": False, "message": "Ошибка авторизации"}, status=401)

        uid = int(tg_user["id"])
        uname = (tg_user.get("username") or "").lstrip("@").strip()
        first_name = (tg_user.get("first_name") or "").strip()
        ensure_user(uid, uname, first_name)

        cd = get_user_idea_cooldown(uid)
        if not cd["can_submit"]:
            msg = (
                "После отклонения идею можно отправить через 24 часа."
                if cd["cooldown_reason"] == "rejected_24h"
                else "Отправлять новую идею можно раз в 30 минут."
            )
            return web.json_response({"ok": False, "message": msg, "cooldown": cd})

        theme = str(body.get("theme", "")).strip()[:100]
        description = str(body.get("description", "")).strip()[:800]
        implementation_logic = str(body.get("implementation_logic", "")).strip()[:800]

        if len(theme) < 3:
            return web.json_response({"ok": False, "message": "Укажи тему идеи (минимум 3 символа)"})
        if len(description) < 10:
            return web.json_response({"ok": False, "message": "Опиши идею подробнее (минимум 10 символов)"})
        if len(implementation_logic) < 10:
            return web.json_response({"ok": False, "message": "Опиши, как видишь реализацию (минимум 10 символов)"})

        idea = create_user_idea(
            user_id=uid,
            username=uname or first_name,
            theme=theme,
            description=description,
            implementation_logic=implementation_logic,
        )

        author_tag = f"@{uname}" if uname else f"{html.escape(first_name or 'Игрок')}"
        admin_text = (
            f"💡 <b>Новая идея #{idea['id']}</b>\n"
            f"• Автор: {author_tag} (ID: <code>{uid}</code>)\n"
            f"• Тема: <b>{html.escape(theme)}</b>\n\n"
            f"<b>Описание:</b>\n{html.escape(description)}\n\n"
            f"<b>Как видит реализацию:</b>\n{html.escape(implementation_logic)}"
        )
        kb = build_admin_idea_kb(int(idea["id"]))
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                print(f"[idea_notify_admin] Ошибка отправки админу {admin_id}: {e}")

        new_cd = get_user_idea_cooldown(uid)
        return web.json_response({
            "ok": True,
            "idea": idea,
            "cooldown": new_cd,
            "message": f"Идея #{idea['id']} отправлена на рассмотрение!",
        })

    # ======================== ADMIN ENDPOINTS ========================
    async def api_admin_ideas_list(request: web.Request) -> web.Response:
        body = await request.json()
        if not check_admin(body):
            return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)
        status_filter = str(body.get("status", "all")).strip()
        ideas = get_admin_ideas(status_filter=status_filter, limit=120)
        return web.json_response({"ok": True, "ideas": ideas})

    async def api_admin_ideas_review(request: web.Request) -> web.Response:
        body = await request.json()
        if not check_admin(body):
            return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

        idea_id = int(body.get("idea_id", 0) or 0)
        decision = str(body.get("decision", "")).strip()
        stars_reward = int(body.get("stars_reward", 0) or 0)
        eta_updates = str(body.get("eta_updates", "2–4")).strip() or "2–4"
        reject_reason = str(body.get("reject_reason", "")).strip()

        ok, msg, updated_idea = review_user_idea(
            idea_id=idea_id,
            decision=decision,
            stars_reward=stars_reward,
            eta_updates=eta_updates,
            reject_reason=reject_reason,
        )
        if not ok or not updated_idea:
            return web.json_response({"ok": False, "message": msg})

        await notify_user_idea_reviewed(bot, updated_idea)
        return web.json_response({
            "ok": True,
            "idea": updated_idea,
            "message": "Идея принята" if decision == "accepted" else "Идея отклонена",
        })

    async def api_admin_ideas_delete(request: web.Request) -> web.Response:
        body = await request.json()
        if not check_admin(body):
            return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)

        idea_id = int(body.get("idea_id", 0) or 0)
        scope = str(body.get("scope", "admin")).strip()
        ok, msg = delete_or_hide_user_idea(idea_id=idea_id, scope=scope)
        if not ok:
            return web.json_response({"ok": False, "message": msg})
        return web.json_response({"ok": True, "message": msg})

    async def api_admin_mode(request: web.Request) -> web.Response:
        body = await request.json()
        if not check_admin(body):
            return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)
        try:
            modes = set_system_mode(str(body.get("mode", "")), bool(body.get("enabled", False)))
            return web.json_response({"ok": True, "system_modes": modes})
        except ValueError:
            return web.json_response({"ok": False, "message": "Неверный режим"}, status=400)

    async def api_admin_ui_version(request: web.Request) -> web.Response:
        body = await request.json()
        uid = check_admin(body)
        if not uid:
            return web.json_response({"ok": False, "message": "Нет прав админа"}, status=403)
        try:
            modes = set_ui_version(str(body.get("scope", "")).strip(), str(body.get("version", "")).strip())
            return web.json_response({"ok": True, "system_modes": modes, "ui_version": resolve_user_ui_version(uid, modes)})
        except ValueError:
            return web.json_response({"ok": False, "message": "Неверные параметры версии"}, status=400)

    async def api_admin_event_toggle(request: web.Request) -> web.Response:
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
        return web.json_response({
            "ok": True,
            "system_modes": get_system_modes(),
            "message": "Начисление снежинок ОТКРЫТО" if enabled else "Начисление снежинок ЗАКРЫТО",
        })

    async def api_admin_reset_games_history(request: web.Request) -> web.Response:
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
        return web.json_response({"ok": True, "history_reset_at": now_ts, "message": "История игр полностью очищена"})

    async def api_admin_user_free_cases(request: web.Request) -> web.Response:
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
        new_count = max(0, (int(fc_row[0]) if fc_row else 0) + delta)
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
        cur.execute("UPDATE users SET event_points = 0, event_claimed_stage = 0 WHERE lower(username) = ?", (target_uname,))
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
            await notify_user_withdraw_done(bot, req_id, uid, cost_s, pay_s, bdown, uname)
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

        return web.json_response({"ok": True, "message": f"Баланс @{target_uname} обновлён: {new_bal} ★", "stars_balance": new_bal})

    async def api_admin_reset_user_timer(request: web.Request) -> web.Response:
        body = await request.json()
        if not check_admin(body):
            return web.json_response({"ok": False, "message": "Доступ запрещён"}, status=403)
        target_uname = str(body.get("username", "")).lstrip("@").strip().lower()
        if not target_uname:
            return web.json_response({"ok": False, "message": "Укажи @username игрока"})
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_free_spin = 0, reminded_24h = 1 WHERE lower(username) = ?", (target_uname,))
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
            return web.json_response({"ok": True, "message": f"Промокод {code} на {reward_cases} откр. кейса «{cfg['name']}» создан"})

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
                inline_keyboard=[[InlineKeyboardButton(text="Открыть GiftezUp", web_app=WebAppInfo(url=f"{VERCEL_APP_URL}/index.html"))]]
            )
        for uid in user_ids:
            try:
                await bot.send_message(chat_id=uid, text=text, reply_markup=kb)
                sent_count += 1
                await asyncio.sleep(0.04)
            except Exception:
                failed_count += 1
        return web.json_response({"ok": True, "sent": sent_count, "failed": failed_count, "total": len(user_ids)})

    app.router.add_post("/api/state", api_state)
    app.router.add_post("/api/check_sub", api_check_sub)
    app.router.add_post("/api/create_topup_invoice", api_create_topup_invoice)
    app.router.add_post("/api/bonus/scratch/state", api_bonus_scratch_state)
    app.router.add_post("/api/bonus/scratch/reveal", api_bonus_scratch_reveal)
    app.router.add_post("/api/bonus/scratch/buy_extra", api_bonus_scratch_buy_extra)
    app.router.add_post("/api/bonus/scratch/decline", api_bonus_scratch_decline)
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

    app.router.add_post("/api/ideas", api_ideas_list)
    app.router.add_post("/api/ideas/create", api_ideas_create)
    app.router.add_post("/api/admin/ideas", api_admin_ideas_list)
    app.router.add_post("/api/admin/ideas/review", api_admin_ideas_review)
    app.router.add_post("/api/admin/ideas/delete", api_admin_ideas_delete)

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