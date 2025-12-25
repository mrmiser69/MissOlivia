# database.py
import sqlite3

DB_NAME = "bot.db"

def get_db():
    return sqlite3.connect(DB_NAME)

def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS filters (
        chat_id INTEGER,
        keyword TEXT,
        reply TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY
    )
    """)

    db.commit()
    db.close()

# -------- FILTERS --------
def db_add_filter(chat_id, keyword, reply):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO filters (chat_id, keyword, reply) VALUES (?, ?, ?)",
        (chat_id, keyword, reply)
    )
    db.commit()
    db.close()

def db_remove_filter(chat_id, keyword):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "DELETE FROM filters WHERE chat_id=? AND keyword=?",
        (chat_id, keyword)
    )
    db.commit()
    db.close()

def db_get_filters(chat_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT keyword, reply FROM filters WHERE chat_id=?",
        (chat_id,)
    )
    rows = cur.fetchall()
    db.close()
    return rows

# -------- USERS --------
def add_user(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
        (user_id,)
    )
    db.commit()
    db.close()

def get_users():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    db.close()
    return [r[0] for r in rows]

# -------- GROUPS --------
def add_group(chat_id):
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO groups (chat_id) VALUES (?)",
        (chat_id,)
    )
    db.commit()
    db.close()

def get_groups():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT chat_id FROM groups")
    rows = cur.fetchall()
    db.close()
    return [r[0] for r in rows]