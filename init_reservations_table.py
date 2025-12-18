import sqlite3

DB_PATH = "pms_old.db"  # old db file, kept separate from main one

# open sqlite db, it will create file if missing
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# basic reservations table, simple version
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT NOT NULL,
        stay_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
)

# save changes before closing
conn.commit()
conn.close()

# quick confirmation for terminal run
print("table is ready in DB")
