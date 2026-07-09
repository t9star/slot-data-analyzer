import sqlite3
import pandas as pd
from jinja2 import Environment, FileSystemLoader
import os
from datetime import datetime, timedelta
import analyzer

PROJECT_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(PROJECT_DIR, "slot_data.db")
TEMPLATE_DIR = os.path.join(PROJECT_DIR, "templates")
OUTPUT_PATH = os.path.join(PROJECT_DIR, "index.html")

def get_next_special_date(from_date_str):
    """
    指定日から最も近い「0のつく日」または「5のつく日」を計算する
    """
    current_dt = datetime.strptime(from_date_str, "%Y-%m-%d")
    
    # 最大30日先まで探索
    for i in range(1, 31):
        check_dt = current_dt + timedelta(days=i)
        day = check_dt.day
        if day % 10 == 0 or day % 10 == 5:
            return check_dt.strftime("%Y-%m-%d")
            
    return (current_dt + timedelta(days=2)).strftime("%Y-%m-%d")

def generate_dashboard():
    print("Generating analysis dashboard...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. データの開始日と終了日、および総取得日数を確認
    cursor.execute("SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM daily_summary")
    row = cursor.fetchone()
    if not row or not row[0]:
        print("No data found in database. Please run scraper.py first.")
        conn.close()
        return
        
    start_date = row[0]
    end_date = row[1]
    total_days = row[2]
    
    # 2. 各種指標の計算
    # 0のつく日の平均
    cursor.execute("""
        SELECT AVG(average_diff) FROM daily_summary 
        WHERE strftime('%d', date) LIKE '%0'
    """)
    avg_diff_zero = cursor.fetchone()[0]
    avg_diff_zero = int(round(avg_diff_zero)) if avg_diff_zero is not None else 0
    
    # 5のつく日の平均
    cursor.execute("""
        SELECT AVG(average_diff) FROM daily_summary 
        WHERE strftime('%d', date) LIKE '%5'
    """)
    avg_diff_five = cursor.fetchone()[0]
    avg_diff_five = int(round(avg_diff_five)) if avg_diff_five is not None else 0
    
    # 通常営業日の平均 (0と5以外)
    cursor.execute("""
        SELECT AVG(average_diff) FROM daily_summary 
        WHERE strftime('%d', date) NOT LIKE '%0' AND strftime('%d', date) NOT LIKE '%5'
    """)
    avg_diff_normal = cursor.fetchone()[0]
    avg_diff_normal = int(round(avg_diff_normal)) if avg_diff_normal is not None else 0
    
    # カレンダー用データ取得 (直近90日分)
    cursor.execute("""
        SELECT date, average_diff, winning_rate, total_diff, total_machines 
        FROM daily_summary 
        ORDER BY date DESC LIMIT 90
    """)
    calendar_data = []
    for r in cursor.fetchall():
        dt = datetime.strptime(r[0], "%Y-%m-%d")
        calendar_data.append({
            "date": r[0],
            "year": dt.year,
            "month": dt.month,
            "day": dt.day,
            "avg_diff": r[1],
            "win_rate": round(r[2] * 100, 1) if r[2] is not None else 0.0,
            "total_diff": r[3],
            "total_machines": r[4]
        })
    calendar_data.reverse() # 日付順（古い順）にする
    
    # 2-2. ユニークな機種名リストの取得
    cursor.execute("SELECT DISTINCT machine_name FROM slot_details ORDER BY machine_name")
    machines = [r[0] for r in cursor.fetchall()]
    
    # 2-3. 全台の個別データ履歴 (直近10日分) の取得
    cursor.execute("""
        WITH ranked_history AS (
            SELECT 
                slot_number, 
                machine_name,
                date, 
                games, 
                diff, 
                ROW_NUMBER() OVER (PARTITION BY slot_number ORDER BY date DESC) as rn
            FROM slot_details
        )
        SELECT slot_number, machine_name, date, games, diff 
        FROM ranked_history 
        WHERE rn <= 10
        ORDER BY slot_number, date DESC
    """)
    
    slot_history_data = {}
    for row in cursor.fetchall():
        slot_num = row[0]
        if slot_num not in slot_history_data:
            slot_history_data[slot_num] = []
        
        slot_history_data[slot_num].append({
            "machine_name": row[1],
            "date": row[2],
            "games": row[3] if row[3] is not None else 0,
            "diff": row[4] if row[4] is not None else 0,
            "winning": True if row[4] is not None and row[4] > 0 else False
        })
        
    conn.close()
    
    # 2-4. カレンダーに存在する全日程の3モデル分の予測データを事前構築
    all_predictions_data = {}
    target_dates = [c["date"] for c in calendar_data]
    next_date = get_next_special_date(end_date)
    if next_date not in target_dates:
        target_dates.append(next_date)
        
    for t_date in target_dates:
        all_predictions_data[t_date] = {}
        for m_type in ["default", "raise", "trend"]:
            preds = analyzer.predict_next_hot_slots(t_date, model_type=m_type)
            if preds is not None and not preds.empty:
                # pandas DataFrame を dict のリストに変換
                all_predictions_data[t_date][m_type] = preds.to_dict(orient="records")
            else:
                all_predictions_data[t_date][m_type] = []
    
    # 3. 各種分析データの取得 (from analyzer.py)
    day_stats = analyzer.analyze_special_days()
    machine_stats = analyzer.analyze_machines(min_records=1) # 1回でもデータがあれば表示
    digit_stats = analyzer.analyze_last_digits()
    
    # 塊検出、曜日癖、設定変更癖、オススメ機種の分析
    detected_blocks = analyzer.detect_high_confidence_blocks()
    weekday_trends = analyzer.analyze_weekday_machine_trends()
    setting_habits = analyzer.analyze_setting_change_habits()
    recommendations = analyzer.analyze_recommended_machines()
    
    # 複数モデルパラメータと精度検証データの取得
    params_default = analyzer.load_prediction_parameters("default")
    params_raise = analyzer.load_prediction_parameters("raise")
    params_trend = analyzer.load_prediction_parameters("trend")
    accuracy_report = analyzer.get_prediction_accuracy_report(limit=5)
    
    # 順位ソートなどを調整
    if machine_stats is not None:
        machine_stats = machine_stats.head(20) # トップ20
    else:
        machine_stats = pd.DataFrame()
        
    if digit_stats is not None:
        digit_stats = digit_stats.sort_values(by='last_digit')
    else:
        digit_stats = pd.DataFrame()
        
    if day_stats is None:
        day_stats = pd.DataFrame()
        
    # 4. 次回の期待台予測 (3モデル分個別に取得)
    predict_date = get_next_special_date(end_date)
    predict_day_dt = datetime.strptime(predict_date, "%Y-%m-%d")
    predict_day_type = "0のつく日" if predict_day_dt.day % 10 == 0 else "5のつく日"
    
    predictions_default = analyzer.predict_next_hot_slots(predict_date, model_type="default")
    if predictions_default is None:
        predictions_default = pd.DataFrame()
        
    predictions_raise = analyzer.predict_next_hot_slots(predict_date, model_type="raise")
    if predictions_raise is None:
        predictions_raise = pd.DataFrame()
        
    predictions_trend = analyzer.predict_next_hot_slots(predict_date, model_type="trend")
    if predictions_trend is None:
        predictions_trend = pd.DataFrame()
        
    # 最近の出玉傾向および高設定濃厚台の集計結果を取得
    recent_trends = analyzer.get_recent_trends()
        
    # 5. Jinja2 テンプレートのレンダリング
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR, encoding="utf-8"))
    template = env.get_template("dashboard.html")
    
    rendered_html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        start_date=start_date,
        end_date=end_date,
        total_days=total_days,
        avg_diff_zero=f"+{avg_diff_zero:,}" if avg_diff_zero >= 0 else f"{avg_diff_zero:,}",
        avg_diff_five=f"+{avg_diff_five:,}" if avg_diff_five >= 0 else f"{avg_diff_five:,}",
        avg_diff_normal=avg_diff_normal,
        day_stats=day_stats,
        machine_stats=machine_stats,
        digit_stats=digit_stats,
        predict_date=predict_date,
        predict_day_type=predict_day_type,
        
        # 3つの予測結果とパラメータ
        predictions_default=predictions_default,
        predictions_raise=predictions_raise,
        predictions_trend=predictions_trend,
        params_default=params_default,
        params_raise=params_raise,
        params_trend=params_trend,
        
        recent_trends=recent_trends,
        calendar_data=calendar_data,
        detected_blocks=detected_blocks,
        weekday_trends=weekday_trends,
        setting_habits=setting_habits,
        recommendations=recommendations,
        accuracy_report=accuracy_report,
        machines=machines,
        slot_history_data=slot_history_data,
        all_predictions_data=all_predictions_data
    )
    
    # ファイルに書き出し
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(rendered_html)
        
    print(f"Dashboard generated successfully at: {OUTPUT_PATH}")

if __name__ == "__main__":
    generate_dashboard()
