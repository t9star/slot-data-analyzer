import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "slot_data.db")

def init_db():
    print(f"Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. 日別サマリーテーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        total_machines INTEGER,
        total_diff INTEGER,
        average_diff INTEGER,
        winning_machines INTEGER,
        winning_rate REAL
    )
    """)

    # 2. 機種別集計テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS machine_stats (
        date TEXT,
        machine_name TEXT,
        count INTEGER,
        total_diff INTEGER,
        average_diff INTEGER,
        winning_machines INTEGER,
        winning_rate REAL,
        PRIMARY KEY (date, machine_name)
    )
    """)

    # 3. 台別詳細テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS slot_details (
        date TEXT,
        slot_number INTEGER,
        machine_name TEXT,
        diff INTEGER,
        games INTEGER,
        winning INTEGER,
        last_digit INTEGER,
        PRIMARY KEY (date, slot_number)
    )
    """)

    # 4. オススメ機種管理テーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recommended_machines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_name TEXT,
        start_date TEXT,
        end_date TEXT,
        label TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()
    print("Database initialization completed successfully.")

if __name__ == "__main__":
    init_db()
