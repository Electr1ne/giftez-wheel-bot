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
