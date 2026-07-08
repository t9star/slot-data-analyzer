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

    # 5. 予測モデルパラメータテーブル
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS model_parameters (
        key TEXT PRIMARY KEY,
        value REAL
    )
    """)
    
    # デフォルトの初期重みを投入 (存在しない場合のみ)
    default_params = [
        ('weight_slot_avg', 0.4),
        ('weight_machine_avg', 0.3),
        ('bonus_matching_digit', 250.0),
        ('bonus_zoro_digit', 80.0),
        ('bonus_raise_target', 100.0)
    ]
    for key, val in default_params:
        cursor.execute("INSERT OR IGNORE INTO model_parameters (key, value) VALUES (?, ?)", (key, val))

    conn.commit()
    conn.close()
    print("Database initialization completed successfully.")

if __name__ == "__main__":
    init_db()
