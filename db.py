import hashlib
import hmac
import json
import sqlite3
import time
from urllib.parse import parse_qsl

from config import (
    ADMIN_IDS,
    ALL_CASES_CONFIG,
    BOT_TOKEN,
    DB_PATH,
    EVENT_START_TS,
)

IDEA_COOLDOWN_NORMAL_SEC = 30 * 60
IDEA_COOLDOWN_REJECTED_SEC = 24 * 60 * 60


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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_free_cases (
            user_id INTEGER NOT NULL,
            case_id TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, case_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS avalanche_shared_rounds (
            round_id TEXT PRIMARY KEY,
            epoch_idx INTEGER NOT NULL,
            crash_mult REAL NOT NULL,
            started_at INTEGER NOT NULL,
            finalized INTEGER DEFAULT 0
        )
    """)

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            theme TEXT NOT NULL,
            description TEXT NOT NULL,
            implementation_logic TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            stars_reward INTEGER DEFAULT 0,
            eta_updates TEXT DEFAULT '',
            reject_reason TEXT DEFAULT '',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER DEFAULT 0
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
            INSERT INTO users (
                user_id, username, first_name, last_free_spin, reminded_24h,
                stars_balance, wager_left, total_spins, sub_cached, sub_checked_at,
                event_points, event_claimed_stage
            )
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


def check_admin(body: dict) -> int | None:
    tg_user = verify_init_data(body.get("initData", ""))
    if not tg_user:
        return None
    uid = int(tg_user["id"])
    return uid if uid in ADMIN_IDS else None


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


# ======================== ИДЕИ ИГРОКОВ ========================
def _row_to_idea_dict(r: tuple) -> dict:
    return {
        "id": int(r[0]),
        "user_id": int(r[1]),
        "username": r[2] or "",
        "theme": r[3] or "",
        "description": r[4] or "",
        "implementation_logic": r[5] or "",
        "status": r[6] or "pending",
        "stars_reward": int(r[7] or 0),
        "eta_updates": r[8] or "",
        "reject_reason": r[9] or "",
        "created_at": int(r[10] or 0),
        "reviewed_at": int(r[11] or 0),
    }


def get_user_idea_cooldown(user_id: int, now_ts: int | None = None) -> dict:
    now = now_ts if now_ts is not None else int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, created_at, reviewed_at
        FROM user_ideas
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"can_submit": True, "next_allowed_at": 0, "cooldown_reason": ""}

    last_status = str(row[0] or "pending")
    created_at = int(row[1] or 0)
    reviewed_at = int(row[2] or 0)

    if last_status == "rejected":
        base_ts = reviewed_at if reviewed_at > 0 else created_at
        next_at = base_ts + IDEA_COOLDOWN_REJECTED_SEC
        if now < next_at:
            return {
                "can_submit": False,
                "next_allowed_at": next_at,
                "cooldown_reason": "rejected_24h",
            }
    else:
        next_at = created_at + IDEA_COOLDOWN_NORMAL_SEC
        if now < next_at:
            return {
                "can_submit": False,
                "next_allowed_at": next_at,
                "cooldown_reason": "normal_30m",
            }

    return {"can_submit": True, "next_allowed_at": 0, "cooldown_reason": ""}


def create_user_idea(
    user_id: int,
    username: str,
    theme: str,
    description: str,
    implementation_logic: str,
) -> dict:
    now = int(time.time())
    clean_uname = (username or "").lstrip("@").strip()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_ideas (
            user_id, username, theme, description, implementation_logic,
            status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', 0, '', '', ?, 0)
        """,
        (user_id, clean_uname, theme, description, implementation_logic, now),
    )
    idea_id = int(cur.lastrowid)
    cur.execute(
        """
        SELECT id, user_id, username, theme, description, implementation_logic,
               status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
        FROM user_ideas WHERE id = ?
        """,
        (idea_id,),
    )
    idea = _row_to_idea_dict(cur.fetchone())
    conn.commit()
    conn.close()
    return idea


def get_user_ideas(user_id: int, limit: int = 30) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, theme, description, implementation_logic,
               status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
        FROM user_ideas
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = [_row_to_idea_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_idea_by_id(idea_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, theme, description, implementation_logic,
               status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
        FROM user_ideas
        WHERE id = ?
        """,
        (idea_id,),
    )
    row = cur.fetchone()
    conn.close()
    return _row_to_idea_dict(row) if row else None


def get_admin_ideas(status_filter: str = "all", limit: int = 100) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if status_filter in ("pending", "accepted", "rejected"):
        cur.execute(
            """
            SELECT id, user_id, username, theme, description, implementation_logic,
                   status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
            FROM user_ideas
            WHERE status = ?
            ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC
            LIMIT ?
            """,
            (status_filter, limit),
        )
    else:
        cur.execute(
            """
            SELECT id, user_id, username, theme, description, implementation_logic,
                   status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
            FROM user_ideas
            ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC
            LIMIT ?
            """,
            (limit,),
        )
    rows = [_row_to_idea_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def review_user_idea(
    idea_id: int,
    decision: str,
    stars_reward: int = 0,
    eta_updates: str = "2–4",
    reject_reason: str = "",
) -> tuple[bool, str, dict | None]:
    if decision not in ("accepted", "rejected"):
        return False, "Неверное решение", None

    now = int(time.time())
    stars_val = max(0, min(10000, int(stars_reward or 0)))
    eta_val = (eta_updates or "2–4").strip() if decision == "accepted" else ""
    reason_val = (reject_reason or "").strip()[:400] if decision == "rejected" else ""

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")

    try:
        cur.execute(
            """
            SELECT id, user_id, username, theme, description, implementation_logic,
                   status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
            FROM user_ideas WHERE id = ?
            """,
            (idea_id,),
        )
        row = cur.fetchone()
        if not row:
            if conn.in_transaction:
                cur.execute("ROLLBACK")
            conn.close()
            return False, "Идея не найдена", None

        cur_status = str(row[6] or "pending")
        if cur_status != "pending":
            if conn.in_transaction:
                cur.execute("ROLLBACK")
            conn.close()
            return False, "Эта идея уже рассмотрена", _row_to_idea_dict(row)

        target_uid = int(row[1])
        reward_to_grant = stars_val if decision == "accepted" else 0

        cur.execute(
            """
            UPDATE user_ideas
            SET status = ?,
                stars_reward = ?,
                eta_updates = ?,
                reject_reason = ?,
                reviewed_at = ?
            WHERE id = ?
            """,
            (decision, reward_to_grant, eta_val, reason_val, now, idea_id),
        )

        if reward_to_grant > 0:
            cur.execute(
                """
                UPDATE users
                SET stars_balance = stars_balance + ?,
                    wager_left = wager_left + ?
                WHERE user_id = ?
                """,
                (reward_to_grant, reward_to_grant, target_uid),
            )

        cur.execute(
            """
            SELECT id, user_id, username, theme, description, implementation_logic,
                   status, stars_reward, eta_updates, reject_reason, created_at, reviewed_at
            FROM user_ideas WHERE id = ?
            """,
            (idea_id,),
        )
        updated_idea = _row_to_idea_dict(cur.fetchone())
        if conn.in_transaction:
            cur.execute("COMMIT")
    except Exception as e:
        if conn.in_transaction:
            cur.execute("ROLLBACK")
        conn.close()
        return False, f"Ошибка БД: {e}", None

    conn.close()
    return True, "OK", updated_idea