import random
import sqlite3
import time

from config import (
    ALL_CASES_CONFIG,
    AV_CRASH_PAUSE_SEC,
    AV_SLOT_LEN,
    AV_WAIT_SEC,
    DAILY_POOL,
    GIFTS_CATALOG,
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
# ИГРА «ЛАВИНА»: БЫСТРЫЙ РАЗГОН ДО 1.00x + ЗАКОН ПОДЛОСТИ
# =========================================================
def compute_avalanche_mult_at_elapsed(sec: float) -> float:
    """Ускоренный разгон от 0.00x до 1.00x (~3.2 сек) с дальнейшим прогрессивным ускорением."""
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
    """
    Хитрая логика («закон подлости»):
    - Чаще выпадает диапазон 1.05x–1.98x вместо сплошных 0.1–0.9x.
    - Присутствует шанс краша на 0.00x (~14%).
    - Если есть ставки реальных игроков с авто-выходом, часто роняет лавину за 0.02–0.11x до цели.
    """
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
    """Синхронизирует состояние общего раунда «Лавины» по мировому времени."""
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
