import sqlite3
import datetime
import hashlib
import binascii
import os
import pymysql

from zoneinfo import ZoneInfo  # timezone support from std lib

# build absolute path for db to be at same place
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_NAME = os.path.join(PROJECT_ROOT, "pms.db")

# app constants
APP_NAME = "Regent College Hotel PMS"
HOTEL_NAME = "Regent College Hotel"
BASE_RATE = 100.00
CURRENCY = "GBP"
MAX_STAY_DAYS = 1  # single night only, maybe later change
MAX_BOOKING_WINDOW_DAYS = 5  # today + few days
TIMEZONE = "Europe/London"

SUPERUSER_USERNAME = "superuser"
SUPERUSER_DEFAULT_PASSWORD = "password"
SUPERUSER_EMAIL = "saodatov@gmail.com"

SES_SENDER_EMAIL = "noreply@saodatov.com"
SES_REGION = "eu-west-1"  # emails are fake for now


# password hash helper
def hash_password(plain_password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
    return binascii.hexlify(salt + key).decode("utf-8")


# check password against stored hash
def verify_password(plain_password: str, stored_hash: str) -> bool:
    stored_hash_bytes = binascii.unhexlify(stored_hash)
    salt = stored_hash_bytes[:32]
    stored_key = stored_hash_bytes[32:]
    key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
    return key == stored_key


# open sqlite connection with fk enabled
def get_db_connection():
    db_host = os.getenv("DB_HOST")

    # If DB_HOST exists, assume AWS / RDS (MySQL)
    if db_host:
        conn = pymysql.connect(
            host=db_host,
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        return conn

    # Fallback: local SQLite (unchanged behavior)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn



# create tables if missing

def create_tables() -> None:
# If running on MySQL (RDS), schema is managed separately
    if os.getenv("DB_HOST"):
        return
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('SUPERUSER', 'STAFF')),
            created_at DATETIME NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_number TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE', 'OUT_OF_SERVICE')),
            base_rate REAL DEFAULT 100.00
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS guests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at DATETIME NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            guest_id INTEGER NOT NULL,
            stay_date TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN (
                    'BOOKED', 'CHECKED_IN', 'CHECKED_OUT',
                    'CANCELLED', 'NO_SHOW'
                )),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY (room_id) REFERENCES rooms(id),
            FOREIGN KEY (guest_id) REFERENCES guests(id)
        )
        """
    )

    # prevent double booking for active stays only
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_room_date_active
        ON reservations(room_id, stay_date)
        WHERE status IN ('BOOKED', 'CHECKED_IN')
        """
    )

    conn.commit()
    conn.close()


# seed superuser and base rooms
def init_superuser_and_rooms() -> None:
    if os.getenv("DB_HOST"):
        return

    # If running on MySQL (RDS), skip seeding entirely
    if os.getenv("DB_HOST"):
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM users WHERE username = ?",
        (SUPERUSER_USERNAME,),
    )
    superuser_exists = cursor.fetchone() is not None

    if not superuser_exists:
        hashed = hash_password(SUPERUSER_DEFAULT_PASSWORD)
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at)
            VALUES (?, ?, 'SUPERUSER', datetime('now'))
            """,
            (SUPERUSER_USERNAME, hashed),
        )

    cursor.execute("SELECT COUNT(*) AS c FROM rooms")
    rooms_count = cursor.fetchone()["c"]

    if rooms_count == 0:
        for i in range(1, 6):
            cursor.execute(
                """
                INSERT INTO rooms (room_number, status, base_rate)
                VALUES (?, 'ACTIVE', ?)
                """,
                (str(i + 100), BASE_RATE),
            )

    conn.commit()
    conn.close()


def init_db() -> None:
    create_tables()
    init_superuser_and_rooms()


# login check
def authenticate_user(username: str, password: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    conn.close()

    if user is None:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


# current date in hotel timezone
def get_today_in_hotel_timezone() -> datetime.date:
    tz = ZoneInfo(TIMEZONE)
    return datetime.datetime.now(tz).date()


# limit booking window
def is_date_within_booking_window(stay_date: datetime.date) -> bool:
    today = get_today_in_hotel_timezone()
    max_date = today + datetime.timedelta(days=MAX_BOOKING_WINDOW_DAYS - 1)
    return today <= stay_date <= max_date


# find first free room
def find_free_room_for_date(stay_date: datetime.date):
    stay_date_iso = stay_date.isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM rooms WHERE status = 'ACTIVE' ORDER BY room_number")
    active_rooms = cursor.fetchall()

    cursor.execute(
        """
        SELECT room_id FROM reservations
        WHERE stay_date = ?
          AND status IN ('BOOKED', 'CHECKED_IN')
        """,
        (stay_date_iso,),
    )
    reserved_room_ids = {row["room_id"] for row in cursor.fetchall()}

    for room in active_rooms:
        if room["id"] not in reserved_room_ids:
            conn.close()
            return room

    conn.close()
    return None


# build availability matrix for ui
def build_availability_grid():
    today = get_today_in_hotel_timezone()
    dates_list = [today + datetime.timedelta(days=offset) for offset in range(MAX_BOOKING_WINDOW_DAYS)]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM rooms WHERE status = 'ACTIVE' ORDER BY room_number")
    rooms = cursor.fetchall()

    min_date = min(dates_list).isoformat()
    max_date = max(dates_list).isoformat()
    cursor.execute(
        """
        SELECT room_id, stay_date, status
        FROM reservations
        WHERE stay_date BETWEEN ? AND ?
          AND status IN ('BOOKED', 'CHECKED_IN')
        """,
        (min_date, max_date),
    )
    reservations = cursor.fetchall()

    status_map = {}
    for res in reservations:
        stay_date_obj = datetime.date.fromisoformat(res["stay_date"])
        key = (res["room_id"], stay_date_obj)
        status_map[key] = res["status"]

    grid = []
    for room in rooms:
        row = []
        for date in dates_list:
            key = (room["id"], date)
            row.append(status_map.get(key, "FREE"))
        grid.append(row)

    conn.close()
    return rooms, dates_list, grid


# fake email sender
def send_email(to_email: str, subject: str, body: str) -> None:
    print(f"SIMULATED EMAIL:\nTo: {to_email}\nSubject: {subject}\nBody:\n{body}\n")


def send_reservation_created_email(guest, reservation, room) -> None:
    subject = f"Reservation Created - {HOTEL_NAME}"
    body = f"""
Dear {guest['first_name']} {guest['last_name']},

Your reservation at {HOTEL_NAME} has been created.

Stay date: {reservation['stay_date']}
Room: {room['room_number']}
Rate: {BASE_RATE} {CURRENCY}
Status: BOOKED
"""
    send_email(guest["email"], subject, body)


def send_reservation_cancelled_email(guest, reservation, room) -> None:
    subject = f"Reservation Cancelled - {HOTEL_NAME}"
    body = f"""
Dear {guest['first_name']} {guest['last_name']},

Your reservation at {HOTEL_NAME} on {reservation['stay_date']} has been cancelled.

Room: {room['room_number']}

Regards,
{HOTEL_NAME}
"""
    send_email(guest["email"], subject, body)


def send_superuser_password_reminder() -> None:
    subject = f"Superuser Password Reminder - {HOTEL_NAME}"
    body = f"""
The default superuser password is: {SUPERUSER_DEFAULT_PASSWORD}
"""
    send_email(SUPERUSER_EMAIL, subject, body)


# simple error types
class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class BadRequest(Exception):
    pass


class NotFound(Exception):
    pass


# role gate check
def require_role(current_user, allowed_roles):
    if current_user is None:
        raise Unauthorized("Unauthorized")
    if current_user["role"] not in allowed_roles:
        raise Forbidden("Forbidden")


# login api
def api_login(username: str, password: str) -> dict:
    user = authenticate_user(username, password)
    if user is None:
        raise Unauthorized("Invalid credentials")
    return {"token": "simulated_token", "role": user["role"], "username": user["username"]}


def api_superuser_forgot_password() -> dict:
    send_superuser_password_reminder()
    return {"message": f"Password reminder has been emailed to {SUPERUSER_EMAIL}"}


def api_grid(current_user) -> dict:
    require_role(current_user, ["STAFF", "SUPERUSER"])
    rooms, dates_list, grid = build_availability_grid()
    return {
        "rooms": [{"id": r["id"], "room_number": r["room_number"]} for r in rooms],
        "dates": [str(d) for d in dates_list],
        "grid": grid,
    }


def api_guest_reservations(
    current_user,
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    stay_date_str: str
) -> dict:
    require_role(current_user, ["STAFF", "SUPERUSER"])

    stay_date = datetime.date.fromisoformat(stay_date_str)
    if not is_date_within_booking_window(stay_date):
        raise BadRequest("Date must be within next 5 days")

    free_room = find_free_room_for_date(stay_date)
    if free_room is None:
        raise BadRequest("No rooms available on this date")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO guests (first_name, last_name, email, phone, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        """,
        (first_name, last_name, email, phone),
    )
    guest_id = cursor.lastrowid

    try:
        cursor.execute(
            """
            INSERT INTO reservations
                (room_id, guest_id, stay_date, status, created_at, updated_at)
            VALUES (?, ?, ?, 'BOOKED', datetime('now'), datetime('now'))
            """,
            (free_room["id"], guest_id, stay_date.isoformat()),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        raise BadRequest("No rooms available on this date")

    reservation_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM guests WHERE id = ?", (guest_id,))
    guest = cursor.fetchone()
    cursor.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,))
    reservation = cursor.fetchone()
    conn.close()

    send_reservation_created_email(guest, reservation, free_room)

    return {
        "reservation_id": reservation_id,
        "room_number": free_room["room_number"],
        "stay_date": stay_date.isoformat(),
        "status": "BOOKED",
    }


def load_reservation_with_relations(res_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            r.id AS res_id,
            r.room_id AS res_room_id,
            r.guest_id AS res_guest_id,
            r.stay_date AS res_stay_date,
            r.status AS res_status,
            r.created_at AS res_created_at,
            r.updated_at AS res_updated_at,
            g.first_name, g.last_name, g.email, g.phone,
            rm.room_number
        FROM reservations r
        JOIN guests g ON r.guest_id = g.id
        JOIN rooms rm ON r.room_id = rm.id
        WHERE r.id = ?
        """,
        (res_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        raise NotFound("Reservation not found")

    reservation = {
        "id": row["res_id"],
        "room_id": row["res_room_id"],
        "guest_id": row["res_guest_id"],
        "stay_date": row["res_stay_date"],
        "status": row["res_status"],
        "created_at": row["res_created_at"],
        "updated_at": row["res_updated_at"],
    }
    guest = {"first_name": row["first_name"], "last_name": row["last_name"], "email": row["email"], "phone": row["phone"]}
    room = {"room_number": row["room_number"]}
    return reservation, guest, room


def api_cancel(current_user, res_id: int) -> dict:
    require_role(current_user, ["STAFF", "SUPERUSER"])
    reservation, guest, room = load_reservation_with_relations(res_id)

    if reservation["status"] not in ("BOOKED", "CHECKED_IN"):
        raise BadRequest("Only active reservations can be cancelled")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE reservations
        SET status = 'CANCELLED', updated_at = datetime('now')
        WHERE id = ?
        """,
        (res_id,),
    )
    conn.commit()
    conn.close()

    send_reservation_cancelled_email(guest, reservation, room)
    return {"message": "Cancelled", "status": "CANCELLED"}


# init db on import
init_db()

if __name__ == "__main__":
    print("CORE DB PATH =", DB_NAME)
    print("DB initialised (tables + seed).")

