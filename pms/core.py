import sqlite3
import datetime
import hashlib
import binascii
import os
import pymysql
from zoneinfo import ZoneInfo


# -----------------------------
# basic config + paths
# -----------------------------
# keep all main settings here so i dont search later

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_NAME = os.path.join(PROJECT_ROOT, "pms.db")  # local sqlite db

APP_NAME = "Regent College Hotel PMS"
HOTEL_NAME = "Regent College Hotel"
BASE_RATE = 100.00
CURRENCY = "GBP"

MAX_STAY_DAYS = 1              # only 1 night bookings
MAX_BOOKING_WINDOW_DAYS = 5    # today + next 4 days
TIMEZONE = "Europe/London"     # hotel timezone, not server

SUPERUSER_USERNAME = "superuser"
SUPERUSER_DEFAULT_PASSWORD = "password"  # temp, change later
SUPERUSER_EMAIL = "saodatov@gmail.com"


# -----------------------------
# db helpers
# -----------------------------

def is_mysql() -> bool:
    # if env var exists -> using mysql
    return bool(os.getenv("DB_HOST"))


def now_sql() -> str:
    # mysql and sqlite use diff syntax
    return "NOW()" if is_mysql() else "datetime('now')"


def placeholder() -> str:
    # sql placeholder depends on db type
    return "%s" if is_mysql() else "?"


def ph(n: int) -> str:
    # helper to repeat placeholders
    return ", ".join([placeholder()] * n)


def get_db_connection():
    # mysql (aws rds etc)
    if is_mysql():
        return pymysql.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    # sqlite for local dev
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def fetchone_dict(row):
    # make sqlite row look like mysql dict
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return row


def fetchall_dict(rows):
    # same but for many rows
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(r) for r in rows]
    return rows


# -----------------------------
# passwords (safe version)
# -----------------------------

def hash_password(plain_password: str) -> str:
    # hash + salt password before saving
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        100_000,
    )
    return binascii.hexlify(salt + key).decode("utf-8")


def verify_password(plain_password: str, stored_hash) -> bool:
    # fix: mysql may return bytes, strip spaces too
    if isinstance(stored_hash, (bytes, bytearray)):
        stored_hash = stored_hash.decode("utf-8")

    stored_hash = stored_hash.strip()  # important fix

    raw = binascii.unhexlify(stored_hash)
    salt = raw[:32]
    stored_key = raw[32:]

    key = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        100_000,
    )
    return key == stored_key


# -----------------------------
# db init (sqlite only)
# -----------------------------

def create_tables():
    # mysql schema handled elsewhere
    if is_mysql():
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('SUPERUSER','STAFF')),
            created_at DATETIME NOT NULL
        )
    """)

    # rooms table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_number TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            base_rate REAL DEFAULT 100.00
        )
    """)

    # guests table (basic info only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS guests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            created_at DATETIME NOT NULL
        )
    """)

    # reservations table (flat for simplicity)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            stay_date TEXT,
            room_number INTEGER,
            status TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)

    conn.commit()
    conn.close()


def init_superuser_and_rooms():
    # only for sqlite
    if is_mysql():
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # create default admin if missing
    cur.execute("SELECT 1 FROM users WHERE username=?", (SUPERUSER_USERNAME,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?, 'SUPERUSER', datetime('now'))",
            (SUPERUSER_USERNAME, hash_password(SUPERUSER_DEFAULT_PASSWORD)),
        )

    # seed rooms once
    cur.execute("SELECT COUNT(*) AS c FROM rooms")
    if cur.fetchone()["c"] == 0:
        for i in range(101, 106):
            cur.execute(
                "INSERT INTO rooms (room_number,status,base_rate) VALUES (?,?,?)",
                (str(i), "ACTIVE", BASE_RATE),
            )

    conn.commit()
    conn.close()


def init_db():
    # call once on startup
    create_tables()
    init_superuser_and_rooms()


# -----------------------------
# custom errors
# -----------------------------

class Unauthorized(Exception): pass
class Forbidden(Exception): pass
class BadRequest(Exception): pass
class NotFound(Exception): pass


def require_role(current_user, allowed):
    # basic role guard
    if not current_user:
        raise Unauthorized("Unauthorized")
    if current_user.get("role") not in allowed:
        raise Forbidden("Forbidden")


# -----------------------------
# auth
# -----------------------------

def authenticate_user(username, password):
    # check login against db
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE username={placeholder()}", (username,))
    user = fetchone_dict(cur.fetchone())
    conn.close()

    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def api_login(username, password):
    # login api used by flask
    user = authenticate_user(username, password)
    if not user:
        raise Unauthorized("Invalid credentials")

    return {
        "token": "simulated_token",  # fake token for demo
        "username": user["username"],
        "role": user["role"],
    }


# -----------------------------
# dates
# -----------------------------

def get_today_in_hotel_timezone():
    # always use hotel tz
    tz = ZoneInfo(TIMEZONE)
    return datetime.datetime.now(tz).date()


# -----------------------------
# grid logic
# -----------------------------

def api_grid(current_user):
    # staff + admin only
    require_role(current_user, ["STAFF", "SUPERUSER"])

    today = get_today_in_hotel_timezone()
    dates = [today + datetime.timedelta(days=i) for i in range(MAX_BOOKING_WINDOW_DAYS)]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, room_number FROM rooms WHERE status='ACTIVE' ORDER BY room_number")
    rooms = fetchall_dict(cur.fetchall())

    # get booked rooms
    cur.execute("""
        SELECT room_number, stay_date
        FROM reservations
        WHERE status IN ('BOOKED','CHECKED_IN')
    """)
    reservations = fetchall_dict(cur.fetchall())
    conn.close()

    booked = {
        (str(r["room_number"]), str(r["stay_date"])): "BOOKED"
        for r in reservations
    }

    # build grid matrix
    grid = []
    for room in rooms:
        row = []
        for d in dates:
            row.append(booked.get((str(room["room_number"]), d.isoformat()), "FREE"))
        grid.append(row)

    return {
        "rooms": rooms,
        "dates": [d.isoformat() for d in dates],
        "grid": grid,
    }


# -----------------------------
# users
# -----------------------------

def api_users_list(current_user):
    # admin only
    require_role(current_user, ["SUPERUSER"])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
    users = fetchall_dict(cur.fetchall())
    conn.close()
    return {"users": users}


def api_users_create(current_user, username, password, role="STAFF"):
    # create staff/admin user
    require_role(current_user, ["SUPERUSER"])

    if not username or not password:
        raise BadRequest("Username and password required")

    role = role.upper()
    if role not in ("SUPERUSER", "STAFF"):
        raise BadRequest("Invalid role")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            f"INSERT INTO users (username,password_hash,role,created_at) VALUES ({ph(3)}, {now_sql()})",
            (username, hash_password(password), role),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise BadRequest("Username exists")

    uid = cur.lastrowid
    conn.close()
    return {"id": uid, "username": username, "role": role}


def api_users_delete(current_user, user_id):
    # delete user by id
    require_role(current_user, ["SUPERUSER"])
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT id FROM users WHERE id={placeholder()}", (user_id,))
    if not cur.fetchone():
        conn.close()
        raise NotFound("User not found")

    cur.execute(f"DELETE FROM users WHERE id={placeholder()}", (user_id,))
    conn.commit()
    conn.close()
    return {"deleted_user_id": user_id}


# -----------------------------
# bookings
# -----------------------------

def api_guest_reservations(
    current_user,
    first_name,
    last_name,
    email,
    phone,
    stay_date_str,
):
    # staff/admin booking flow
    require_role(current_user, ["STAFF", "SUPERUSER"])

    if not all([first_name, last_name, email, phone, stay_date_str]):
        raise BadRequest("Missing required fields")

    try:
        stay_date = datetime.date.fromisoformat(stay_date_str)
    except ValueError:
        raise BadRequest("Invalid date format")

    conn = get_db_connection()
    cur = conn.cursor()

    # find active rooms
    cur.execute("SELECT room_number FROM rooms WHERE status='ACTIVE' ORDER BY room_number")
    active_rooms = [int(r["room_number"]) for r in cur.fetchall()]

    # find booked rooms for date
    cur.execute(
        f"SELECT room_number FROM reservations WHERE stay_date={placeholder()} AND status='BOOKED'",
        (stay_date.isoformat(),),
    )
    booked = {int(r["room_number"]) for r in cur.fetchall()}

    free_rooms = [r for r in active_rooms if r not in booked]
    if not free_rooms:
        conn.close()
        raise BadRequest("No rooms available for that date")

    chosen_room = free_rooms[0]  # simple first free logic

    cur.execute(
        f"""
        INSERT INTO reservations
        (first_name,last_name,email,phone,stay_date,room_number,status)
        VALUES ({ph(7)})
        """,
        (
            first_name,
            last_name,
            email,
            phone,
            stay_date.isoformat(),
            chosen_room,
            "BOOKED",
        ),
    )

    reservation_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "reservation_id": reservation_id,
        "room_number": chosen_room,
        "status": "BOOKED",
        "stay_date": stay_date.isoformat(),
    }
