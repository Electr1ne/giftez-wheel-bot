import json
import random
import sqlite3
import time

from config import (
    ADMIN_IDS,
    ALL_CASES_CONFIG,
    AV_CRASH_PAUSE_SEC,
    AV_SLOT_LEN,
    AV_WAIT_SEC,
    DAILY_POOL,
    GIFTS_CATALOG,
    SCRATCH_CONSOLATION_MAX,
    SCRATCH_CONSOLATION_MIN,
    SCRATCH_COOLDOWN_SEC,
    SCRATCH_EXTRA_ATTEMPT_PRICE,
    SCRATCH_FREE_ATTEMPTS,
)
from db import is_case_visible_for_user, is_event_unlocked_for_user


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


def is_admin_scratch_xray_enabled(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = 'admin_scratch_xray'")
    row = cur.fetchone()
    return (row[0] if row else "0") == "1"


def add_event_points_from_stars(conn: sqlite3.Connection, uid: int, spent_stars: int) -> None:
    """Начисляет снежинки (1 снежинка за 2 ★ оборота), если ивент открыт и начисление включено."""
    pts = spent_stars // 2
    if pts <= 0 or not is_event_unlocked_for_user(uid):
        return
    if not is_snowflakes_active_in_db(conn):
        return
    conn.execute("UPDATE users SET event_points = event_points + ? WHERE user_id = ?", (pts, uid))


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
    amt = int(stars_amount or 0)
    if amt > 0:
        conn.execute(
            "UPDATE users SET stars_balance = stars_balance + ? WHERE user_id = ?",
            (amt, int(uid)),
        )
    conn.execute("DELETE FROM pending_drops WHERE drop_id = ?", (drop_id,))


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


# =========================================================
# СКРЕТЧ-БИЛЕТ 3x3 (ВКЛАДКА «БОНУСЫ»)
# =========================================================
def _roll_scratch_tier_prize(tier: str) -> int:
    r = random.random()
    if tier == "low":
        if r < 0.72:
            return random.randint(1, 5)
        if r < 0.94:
            return random.randint(6, 10)
        return random.randint(11, 18)
    if r < 0.58:
        return random.randint(8, 18)
    if r < 0.88:
        return random.randint(19, 32)
    return random.randint(33, 50)


def generate_scratch_cells() -> list[int]:
    p1 = _roll_scratch_tier_prize("low")
    p2 = _roll_scratch_tier_prize("high")
    while p2 == p1:
        p2 = random.randint(2, 50)

    cells = [p1, p1, p1, p2, p2, p2, 0, 0, 0]
    random.shuffle(cells)
    return cells


def _can_user_see_xray(conn: sqlite3.Connection, uid: int) -> bool:
    return (int(uid) in ADMIN_IDS) and is_admin_scratch_xray_enabled(conn)


def get_or_create_scratch_ticket(conn: sqlite3.Connection, uid: int, now_ts: int | None = None) -> dict:
    now = now_ts if now_ts is not None else int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT cells_json, revealed_json, extra_bought, status, prize_stars, is_consolation,
               created_at, finished_at, COALESCE(bonus_tickets, 0), COALESCE(bonus_extra_attempts, 0)
        FROM scratch_tickets
        WHERE user_id = ?
        """,
        (uid,),
    )
    row = cur.fetchone()

    need_new = False
    bonus_tickets = int(row[8]) if row else 0
    bonus_extra_attempts = int(row[9]) if row else 0

    if not row:
        need_new = True
    else:
        st = str(row[3] or "playing")
        fin_at = int(row[7] or 0)
        if st in ("won", "lost") and fin_at > 0 and (now - fin_at) >= SCRATCH_COOLDOWN_SEC:
            need_new = True

    if need_new:
        cells = generate_scratch_cells()
        revealed: list[int] = []
        cur.execute(
            """
            INSERT OR REPLACE INTO scratch_tickets (
                user_id, cells_json, revealed_json, extra_bought, status,
                prize_stars, is_consolation, created_at, finished_at, bonus_tickets, bonus_extra_attempts
            )
            VALUES (?, ?, ?, 0, 'playing', 0, 0, ?, 0, ?, ?)
            """,
            (uid, json.dumps(cells), json.dumps(revealed), now, bonus_tickets, bonus_extra_attempts),
        )
        conn.commit()
        extra_bought = 0
        status = "playing"
        prize_stars = 0
        is_consolation = 0
        finished_at = 0
    else:
        cells = json.loads(row[0])
        revealed = [int(x) for x in json.loads(row[1])]
        extra_bought = int(row[2] or 0)
        status = str(row[3] or "playing")
        prize_stars = int(row[4] or 0)
        is_consolation = int(row[5] or 0)
        finished_at = int(row[7] or 0)

    return format_scratch_public_state(
        cells=cells,
        revealed=revealed,
        extra_bought=extra_bought,
        status=status,
        prize_stars=prize_stars,
        is_consolation=is_consolation,
        finished_at=finished_at,
        bonus_tickets=bonus_tickets,
        bonus_extra_attempts=bonus_extra_attempts,
        xray_enabled=_can_user_see_xray(conn, uid),
    )


def scratch_use_bonus_ticket_in_db(conn: sqlite3.Connection, uid: int) -> tuple[bool, str, dict | None]:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        "SELECT status, COALESCE(bonus_tickets, 0), COALESCE(bonus_extra_attempts, 0) FROM scratch_tickets WHERE user_id = ?",
        (uid,),
    )
    row = cur.fetchone()
    if not row:
        t = get_or_create_scratch_ticket(conn, uid, now)
        return True, "Новый билет готов!", t

    status = str(row[0] or "playing")
    bonus_tickets = int(row[1] or 0)
    bonus_extra = int(row[2] or 0)

    if status not in ("won", "lost"):
        return False, "Сначала заверши текущий билет", get_or_create_scratch_ticket(conn, uid, now)
    if bonus_tickets <= 0:
        return False, "Нет дополнительных бесплатных билетов", get_or_create_scratch_ticket(conn, uid, now)

    new_bonus = bonus_tickets - 1
    cells = generate_scratch_cells()
    cur.execute(
        """
        UPDATE scratch_tickets
        SET cells_json = ?, revealed_json = '[]', extra_bought = 0, status = 'playing',
            prize_stars = 0, is_consolation = 0, created_at = ?, finished_at = 0,
            bonus_tickets = ?, bonus_extra_attempts = ?
        WHERE user_id = ?
        """,
        (json.dumps(cells), now, new_bonus, bonus_extra, uid),
    )
    conn.commit()
    return True, "Открыт новый бонусный билет!", get_or_create_scratch_ticket(conn, uid, now)


def scratch_use_bonus_extra_attempt_in_db(conn: sqlite3.Connection, uid: int) -> tuple[bool, str, dict | None]:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        "SELECT status, extra_bought, COALESCE(bonus_extra_attempts, 0) FROM scratch_tickets WHERE user_id = ?",
        (uid,),
    )
    row = cur.fetchone()
    if not row:
        return False, "Билет не найден", None

    status = str(row[0] or "playing")
    extra_bought = int(row[1] or 0)
    bonus_extra = int(row[2] or 0)

    if extra_bought == 1:
        return False, "4-я попытка уже активирована", get_or_create_scratch_ticket(conn, uid, now)
    if status not in ("awaiting_extra", "playing"):
        return False, "Текущий билет уже завершён", get_or_create_scratch_ticket(conn, uid, now)
    if bonus_extra <= 0:
        return False, "Нет бесплатных доп. попыток", get_or_create_scratch_ticket(conn, uid, now)

    cur.execute(
        """
        UPDATE scratch_tickets
        SET extra_bought = 1, status = 'playing', bonus_extra_attempts = ?
        WHERE user_id = ?
        """,
        (bonus_extra - 1, uid),
    )
    conn.commit()
    return True, "Бесплатная 4-я попытка активирована!", get_or_create_scratch_ticket(conn, uid, now)


def format_scratch_public_state(
    cells: list[int],
    revealed: list[int],
    extra_bought: int,
    status: str,
    prize_stars: int,
    is_consolation: int,
    finished_at: int,
    bonus_tickets: int = 0,
    bonus_extra_attempts: int = 0,
    xray_enabled: bool = False,
) -> dict:
    max_attempts = SCRATCH_FREE_ATTEMPTS + (1 if extra_bought else 0)
    used_attempts = len(revealed)
    attempts_left = max(0, max_attempts - used_attempts) if status in ("playing", "awaiting_extra") else 0

    revealed_set = set(revealed)
    reveal_all = status in ("won", "lost")
    public_cells = []
    for idx, val in enumerate(cells):
        is_rev = reveal_all or (idx in revealed_set)
        public_cells.append({
            "index": idx,
            "revealed": is_rev,
            "picked": idx in revealed_set,
            "value": int(val) if is_rev else None,
            "xray_value": int(val) if xray_enabled else None,
        })

    counts: dict[int, int] = {}
    for idx in revealed:
        v = int(cells[idx])
        if v > 0:
            counts[v] = counts.get(v, 0) + 1
    has_pair = any(c >= 2 for c in counts.values())

    next_ticket_at = (finished_at + SCRATCH_COOLDOWN_SEC) if (status in ("won", "lost") and finished_at > 0) else 0

    return {
        "status": status,  # 'playing' | 'awaiting_extra' | 'won' | 'lost'
        "cells": public_cells,
        "used_attempts": used_attempts,
        "max_attempts": max_attempts,
        "attempts_left": attempts_left,
        "extra_bought": bool(extra_bought),
        "extra_price": SCRATCH_EXTRA_ATTEMPT_PRICE,
        "has_pair": has_pair,
        "prize_stars": int(prize_stars),
        "is_consolation": bool(is_consolation),
        "next_ticket_at": next_ticket_at,
        "bonus_tickets": int(bonus_tickets),
        "bonus_extra_attempts": int(bonus_extra_attempts),
        "xray_enabled": bool(xray_enabled),
    }


def scratch_reveal_cell_in_db(conn: sqlite3.Connection, uid: int, cell_index: int) -> tuple[bool, str, dict | None]:
    if cell_index < 0 or cell_index > 8:
        return False, "Некорректная ячейка", None

    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT cells_json, revealed_json, extra_bought, status, prize_stars, is_consolation,
               created_at, finished_at, COALESCE(bonus_tickets, 0), COALESCE(bonus_extra_attempts, 0)
        FROM scratch_tickets
        WHERE user_id = ?
        """,
        (uid,),
    )
    row = cur.fetchone()
    if not row:
        get_or_create_scratch_ticket(conn, uid, now)
        cur.execute(
            """
            SELECT cells_json, revealed_json, extra_bought, status, prize_stars, is_consolation,
                   created_at, finished_at, COALESCE(bonus_tickets, 0), COALESCE(bonus_extra_attempts, 0)
            FROM scratch_tickets
            WHERE user_id = ?
            """,
            (uid,),
        )
        row = cur.fetchone()

    cells = [int(x) for x in json.loads(row[0])]
    revealed = [int(x) for x in json.loads(row[1])]
    extra_bought = int(row[2] or 0)
    status = str(row[3] or "playing")
    prize_stars = int(row[4] or 0)
    is_consolation = int(row[5] or 0)
    finished_at = int(row[7] or 0)
    bonus_tickets = int(row[8] or 0)
    bonus_extra = int(row[9] or 0)
    xray_on = _can_user_see_xray(conn, uid)

    if status == "awaiting_extra":
        return False, "Бесплатные попытки закончились", format_scratch_public_state(
            cells, revealed, extra_bought, status, prize_stars, is_consolation, finished_at, bonus_tickets, bonus_extra, xray_on
        )
    if status in ("won", "lost"):
        return False, "Этот билет уже завершён", format_scratch_public_state(
            cells, revealed, extra_bought, status, prize_stars, is_consolation, finished_at, bonus_tickets, bonus_extra, xray_on
        )

    max_attempts = SCRATCH_FREE_ATTEMPTS + (1 if extra_bought else 0)
    if len(revealed) >= max_attempts:
        return False, "Попытки исчерпаны", format_scratch_public_state(
            cells, revealed, extra_bought, status, prize_stars, is_consolation, finished_at, bonus_tickets, bonus_extra, xray_on
        )

    if cell_index in revealed:
        return True, "OK", format_scratch_public_state(
            cells, revealed, extra_bought, status, prize_stars, is_consolation, finished_at, bonus_tickets, bonus_extra, xray_on
        )

    revealed.append(cell_index)

    counts: dict[int, int] = {}
    for idx in revealed:
        v = cells[idx]
        if v > 0:
            counts[v] = counts.get(v, 0) + 1

    won_prize = 0
    for val, cnt in counts.items():
        if cnt >= 3:
            won_prize = val
            break

    if won_prize > 0:
        status = "won"
        prize_stars = won_prize
        is_consolation = 0
        finished_at = now
        cur.execute(
            "UPDATE users SET stars_balance = stars_balance + ?, wager_left = wager_left + ? WHERE user_id = ?",
            (won_prize, won_prize, uid),
        )
    elif len(revealed) >= max_attempts:
        if not extra_bought:
            status = "awaiting_extra"
        else:
            consolation = random.randint(SCRATCH_CONSOLATION_MIN, SCRATCH_CONSOLATION_MAX)
            status = "lost"
            prize_stars = consolation
            is_consolation = 1
            finished_at = now
            cur.execute(
                "UPDATE users SET stars_balance = stars_balance + ?, wager_left = wager_left + ? WHERE user_id = ?",
                (consolation, consolation, uid),
            )

    cur.execute(
        """
        UPDATE scratch_tickets
        SET revealed_json = ?, status = ?, prize_stars = ?, is_consolation = ?, finished_at = ?
        WHERE user_id = ?
        """,
        (json.dumps(revealed), status, prize_stars, is_consolation, finished_at, uid),
    )

    state_dict = format_scratch_public_state(
        cells, revealed, extra_bought, status, prize_stars, is_consolation, finished_at, bonus_tickets, bonus_extra, xray_on
    )
    return True, "OK", state_dict


def scratch_decline_extra_in_db(conn: sqlite3.Connection, uid: int) -> tuple[bool, str, dict | None]:
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT cells_json, revealed_json, extra_bought, status, prize_stars, is_consolation,
               finished_at, COALESCE(bonus_tickets, 0), COALESCE(bonus_extra_attempts, 0)
        FROM scratch_tickets
        WHERE user_id = ?
        """,
        (uid,),
    )
    row = cur.fetchone()
    if not row:
        return False, "Билет не найден", None

    cells = [int(x) for x in json.loads(row[0])]
    revealed = [int(x) for x in json.loads(row[1])]
    extra_bought = int(row[2] or 0)
    status = str(row[3] or "playing")
    bonus_tickets = int(row[7] or 0)
    bonus_extra = int(row[8] or 0)
    xray_on = _can_user_see_xray(conn, uid)

    if status in ("won", "lost"):
        return True, "OK", format_scratch_public_state(
            cells, revealed, extra_bought, status, int(row[4] or 0), int(row[5] or 0), int(row[6] or 0), bonus_tickets, bonus_extra, xray_on
        )

    cur.execute(
        """
        UPDATE scratch_tickets
        SET status = 'lost', prize_stars = 0, is_consolation = 0, finished_at = ?
        WHERE user_id = ?
        """,
        (now, uid),
    )
    state_dict = format_scratch_public_state(
        cells, revealed, extra_bought, "lost", 0, 0, now, bonus_tickets, bonus_extra, xray_on
    )
    return True, "OK", state_dict


def scratch_grant_extra_attempt_in_db(conn: sqlite3.Connection, uid: int) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT status, extra_bought FROM scratch_tickets WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    if not row:
        return False
    status, extra_bought = str(row[0]), int(row[1] or 0)
    if extra_bought == 1:
        return True
    if status not in ("awaiting_extra", "playing"):
        return False
    cur.execute(
        "UPDATE scratch_tickets SET extra_bought = 1, status = 'playing' WHERE user_id = ?",
        (uid,),
    )
    return True


# =========================================================
# ИГРА «ЛАВИНА»: БЫСТРЫЙ РАЗГОН ДО 1.00x + ЗАКОН ПОДЛОСТИ
# =========================================================
def compute_avalanche_mult_at_elapsed(sec: float) -> float:
    if sec <= 0:
        return 0.0
    val = 0.24 * sec + 0.032 * (sec ** 2) + 0.0022 * (sec ** 3)
    return round(min(100.0, val), 2)


def compute_avalanche_duration_for_crash(target_crash: float) -> float:
    if target_crash <= 0.0:
        return 0.4
    lo, hi = 0.0, 60.0
    for _ in range(32):
        mid = (lo + hi) * 0.5
        if compute_avalanche_mult_at_elapsed(mid) < target_crash:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


def roll_smart_avalanche_crash(conn: sqlite3.Connection, round_id: str) -> float:
    cur = conn.cursor()
    cur.execute(
        "SELECT bet_stars, auto_mult FROM avalanche_bets WHERE round_id = ? AND status = 'playing'",
        (round_id,),
    )
    bets = cur.fetchall()

    r = random.random()

    if not bets:
        if r < 0.10:
            return 0.00
        if r < 0.65:
            return round(random.uniform(1.25, 2.25), 2)
        if r < 0.90:
            return round(random.uniform(2.25, 4.80), 2)
        return round(random.uniform(4.80, 12.00), 2)

    if r < 0.14:
        return 0.00

    auto_targets = [float(b[1]) for b in bets if float(b[1] or 0) > 1.05]
    if auto_targets and random.random() < 0.62:
        min_auto = min(auto_targets)
        if min_auto <= 2.40:
            tease = max(1.01, round(min_auto - random.uniform(0.02, 0.11), 2))
            return tease

    if r < 0.74:
        return round(random.uniform(1.06, 1.98), 2)
    if r < 0.94:
        return round(random.uniform(2.01, 3.40), 2)
    return round(random.uniform(3.40, 9.50), 2)


def sync_shared_avalanche_round(conn: sqlite3.Connection, auto_commit: bool = True) -> dict:
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

    if auto_commit:
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