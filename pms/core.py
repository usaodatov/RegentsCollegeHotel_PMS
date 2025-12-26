import sqlite3
import datetime
import hashlib
import binascii
import os
import pymysql
from zoneinfo import ZoneInfo

# paths + main config, keep here so easy find later
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_NAME = os.path.join(PROJECT_ROOT, "pms.db")  # sqlite file for local dev

APP_NAME = "Regent College Hotel PMS"
HOTEL_NAME = "Regent College Hotel"
BASE_RATE = 100.00  # default room price
CURRENCY = "GBP"
MAX_STAY_DAYS = 1  # only single night now
MAX_BOOKING_WINDOW_DAYS = 5  # today + 4 days
TIMEZONE = "Europe/London"  # important for dates

SUPERUSER_USERNAME = "superuser"
SUPERUSER_DEFAULT_PASSWORD = "password"  # temp only
SUPERUSER_EMAIL = "saodatov@gmail.com"

SES_SENDER_EMAIL = "noreply@saodatov.com"
SES_REGION = "eu-west-1"


# decide which db to use (mysql on aws or local sqlite)
def is_mysql() -> bool:
    # if DB_HOST set, assume mysql
    return bool(os.getenv("DB_HOST"))


def now_sql() -> str:
    # sqlite and mysql use diff now syntax
    return "NOW()" if is_mysql() else "datetime('now')"


def placeholder() -> str:
    # sql param symbol depends on db
    return "%s" if is_mysql() else "?"


def ph(n: int) -> str:
    # helper for multiple placeholders
    return ", ".join([placeholder()] * n)


def get_db_connection():
    # mysql connection (aws rds)
    db_host = os.getenv("DB_HOST")
    if db_host:
        return pymysql.connect(
            host=db_host,
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    # sqlite for local testing
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def fetchone_dict(row):
    # unify sqlite + mysql row format
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


# password hashing, standard approach
def hash_password(plain_password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
    return binascii.hexlify(salt + key).decode("utf-8")


def verify_password(plain_password: str, stored_hash: str) -> bool:
    # extract salt + hash
    raw = binascii.unhexlify(stored_hash)
    salt = raw[:32]
    stored_key = raw[32:]
    key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
    return key == stored_key


# sqlite schema setup (mysql handled elsewhere)
def create_tables():
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

    # guests table
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

    # reservations table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER,
            guest_id INTEGER,
            stay_date TEXT,
            status TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)

    conn.commit()
    conn.close()


def init_superuser_and_rooms():
    if is_mysql():
        return

    conn = get_db_connection()
    cur = conn.cursor()

    # create admin user once
    cur.execute("SELECT 1 FROM users WHERE username=?", (SUPERUSER_USERNAME,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (username,password_hash,role,created_at) VALUES (?,?, 'SUPERUSER', datetime('now'))",
            (SUPERUSER_USERNAME, hash_password(SUPERUSER_DEFAULT_PASSWORD)),
        )

    # seed rooms if empty
    cur.execute("SELECT COUNT(*) as c FROM rooms")
    if cur.fetchone()["c"] == 0:
        for i in range(101, 106):
            cur.execute(
                "INSERT INTO rooms (room_number,status,base_rate) VALUES (?,?,?)",
                (str(i), "ACTIVE", BASE_RATE),
            )

    conn.commit()
    conn.close()


def init_db():
    # init only affects sqlite
    create_tables()
    init_superuser_and_rooms()


# custom errors used by api
class Unauthorized(Exception): pass
class Forbidden(Exception): pass
class BadRequest(Exception): pass
class NotFound(Exception): pass


def require_role(current_user, allowed):
    # simple role gate
    if not current_user:
        raise Unauthorized("Unauthorized")
    if current_user.get("role") not in allowed:
        raise Forbidden("Forbidden")


def authenticate_user(username, password):
    # check login against users table
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
    # login endpoint logic
    user = authenticate_user(username, password)
    if not user:
        raise Unauthorized("Invalid credentials")
    return {
        "token": "simulated_token",
        "username": user["username"],
        "role": user["role"],
    }


# date helper, always hotel timezone
def get_today_in_hotel_timezone():
    tz = ZoneInfo(TIMEZONE)
    return datetime.datetime.now(tz).date()


def is_date_within_booking_window(stay_date):
    # enforce booking window
    today = get_today_in_hotel_timezone()
    return today <= stay_date <= today + datetime.timedelta(days=MAX_BOOKING_WINDOW_DAYS - 1)


def find_free_room_for_date(stay_date):
    # pick first free room
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rooms WHERE status='ACTIVE' ORDER BY room_number")
    rooms = fetchall_dict(cur.fetchall())

    cur.execute(
        "SELECT room_number FROM reservations WHERE stay_date=? AND status IN ('BOOKED','CHECKED_IN')",
        (stay_date.isoformat(),),
    )
    busy = {r["room_number"] for r in fetchall_dict(cur.fetchall())}

    for r in rooms:
        if r["room_number"] not in busy:
            conn.close()
            return r

    conn.close()
    return None


def api_grid(current_user):
    # grid visible for staff + admin
    require_role(current_user, ["STAFF", "SUPERUSER"])
    today = get_today_in_hotel_timezone()
    dates = [today + datetime.timedelta(days=i) for i in range(MAX_BOOKING_WINDOW_DAYS)]

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rooms WHERE status='ACTIVE'")
    rooms = fetchall_dict(cur.fetchall())
    conn.close()

    # grid not fully dynamic yet
    return {
        "rooms": [{"id": r["id"], "room_number": r["room_number"]} for r in rooms],
        "dates": [str(d) for d in dates],
        "grid": [["FREE"] * len(dates) for _ in rooms],
    }


def api_users_list(current_user):
    # list users, admin only
    require_role(current_user, ["SUPERUSER"])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
    users = fetchall_dict(cur.fetchall())
    conn.close()
    return {"users": users}


def api_users_create(current_user, username, password, role="STAFF"):
    # create new user
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

    cur.execute(
        f"SELECT id FROM users WHERE id={placeholder()}",
        (user_id,)
    )
    if not cur.fetchone():
        conn.close()
        raise NotFound("User not found")

    cur.execute(
        f"DELETE FROM users WHERE id={placeholder()}",
        (user_id,)
    )
    conn.commit()
    conn.close()
    return {"deleted_user_id": user_id}

def api_guest_reservations(
    current_user,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    stay_date_str: str
) -> dict:
    require_role(current_user, ["STAFF", "SUPERUSER"])

    # basic field check
    if not all([first_name, last_name, email, phone, stay_date_str]):
        raise BadRequest("Missing required fields")

    # date must be YYYY-MM-DD
    try:
        stay_date = datetime.date.fromisoformat(stay_date_str)
    except ValueError:
        raise BadRequest("Invalid date format, expected YYYY-MM-DD")

    conn = get_db_connection()
    cur = conn.cursor()

    # pick first active room (simple logic for now)
    cur.execute("SELECT room_number FROM rooms WHERE status='ACTIVE' LIMIT 1")
    room = fetchone_dict(cur.fetchone())

    if not room:
        conn.close()
        raise BadRequest("No rooms available")

    # mysql reservations table is flat, so store guest info directly there
    cur.execute(
        f"""
        INSERT INTO reservations
            (first_name, last_name, email, phone, stay_date, room_number, status)
        VALUES ({ph(7)})
        """,
        (
            first_name,
            last_name,
            email,
            phone,
            stay_date.isoformat(),
            int(room["room_number"]),
            "BOOKED",
        ),
    )

    reservation_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "reservation_id": reservation_id,
        "status": "BOOKED",
        "room_number": room["room_number"],
        "stay_date": stay_date.isoformat(),
    }
