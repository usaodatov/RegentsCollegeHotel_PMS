import sqlite3
from pms.core import DB_NAME  # reuse db path from core, so no mismatch later


def main() -> None:
    # just point to same db as app uses
    db_path = DB_NAME
    print("CHECK_DB PATH =", db_path)

    # open raw sqlite connection for inspection
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # list all tables found in database
    print("\nTABLES:")
    for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print("-", row[0])

    # show rooms table content (basic sanity check)
    print("\nROOMS:")
    try:
        for row in cur.execute("SELECT room_number FROM rooms ORDER BY room_number"):
            print("-", row[0])
    except sqlite3.OperationalError as e:
        # happens if table not created yet
        print("ERROR:", e)

    # show users and roles, useful to confirm superuser seed
    print("\nUSERS:")
    try:
        for row in cur.execute("SELECT username, role FROM users ORDER BY id"):
            print("-", row[0], row[1])
    except sqlite3.OperationalError as e:
        # if users table missing or schema wrong
        print("ERROR:", e)

    # always close connection, even for simple scripts
    conn.close()


if __name__ == "__main__":
    # entry point when running file directly
    main()
