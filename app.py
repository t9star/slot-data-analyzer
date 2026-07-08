from flask import Flask, jsonify, render_template, send_from_directory, request
import threading
import os
import json
from datetime import datetime
import scraper
import dashboard_generator
import analyzer

app = Flask(__name__, template_folder="templates")
PROJECT_DIR = os.path.dirname(__file__)
PROGRESS_PATH = os.path.join(PROJECT_DIR, "progress.json")
import time

LOCK = threading.Lock()

def schedule_worker():
    """
    毎日深夜 AM 3:00 に自動データ回収 (直近8日分の通常営業日データ) を実行するバックグラウンドタスク
    """
    print("[Scheduler] 定期自動回収タスクが起動しました (毎日 AM 3:00 実行予定)")
    last_run_date = None
    
    while True:
        try:
            now = datetime.now()
            # 毎日 AM 3:00 に実行
            if now.hour == 3 and now.minute == 0 and last_run_date != now.date():
                progress = get_progress()
                if progress.get("status") != "running":
                    print(f"[Scheduler] {now.strftime('%Y-%m-%d %H:%M:%S')} - 定期データ回収を開始します。")
                    t = threading.Thread(target=async_goraggio_task, args=(8,))
                    t.daemon = True
                    t.start()
                    last_run_date = now.date()
                else:
                    print("[Scheduler] 別の更新処理が実行中のため、定期回収をスキップします。")
            
            # 30秒ごとに時刻をチェック
            time.sleep(30)
        except Exception as e:
            print(f"[Scheduler] エラーが発生しました: {str(e)}")
            time.sleep(60)

# デーモンスレッドとしてスケジューラを起動
scheduler_thread = threading.Thread(target=schedule_worker)
scheduler_thread.daemon = True
scheduler_thread.start()

def get_progress():
    """
    progress.json から現在の進捗を読み取る
    """
    if not os.path.exists(PROGRESS_PATH):
        return {"status": "idle", "current": 0, "total": 0, "message": "待機中"}
    
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "idle", "current": 0, "total": 0, "message": "待機中"}

def set_progress(status, current, total, message):
    """
    進捗を progress.json に書き出す
    """
    scraper.update_progress(status, current, total, message)

def async_update_task(limit):
    """
    バックグラウンドでスクレイピングとダッシュボード更新を行うスレッド関数
    """
    with LOCK:
        try:
            # 1. スクレイパー実行（バックフィルモード）
            # 新しい日付の取得と、過去データ最大 limit 日分を遡って収集
            scraper.run_scraper(limit=limit)
            
            # 2. ダッシュボードの再生成
            set_progress("running", limit, limit, "ダッシュボードを再生成しています...")
            dashboard_generator.generate_dashboard()
            
            set_progress("done", limit, limit, "データ更新が完了しました！")
        except Exception as e:
            print(f"Error in background update: {e}")
            set_progress("error", 0, 0, f"更新中にエラーが発生しました: {e}")

def async_goraggio_task(limit):
    """
    バックグラウンドでゴラッジョ（台データオンライン）のスクレイピングとダッシュボード更新を行うスレッド関数
    """
    with LOCK:
        try:
            # 1. ゴラッジョスクレイパーの実行
            scraper.run_goraggio_scraper(limit=limit)
            
            # 2. ダッシュボードの再生成
            set_progress("running", limit, limit, "ダッシュボードを再生成しています...")
            dashboard_generator.generate_dashboard()
            
            set_progress("done", limit, limit, "通常営業日のデータ回収が完了しました！")
        except Exception as e:
            print(f"Error in goraggio background update: {e}")
            set_progress("error", 0, 0, f"データ回収中にエラーが発生しました: {e}")

@app.route('/')
def index():
    # 常に最新の index.html を返すようにする
    # もし index.html が存在しない場合は、その場で一度生成する
    index_path = os.path.join(PROJECT_DIR, "index.html")
    if not os.path.exists(index_path):
        try:
            dashboard_generator.generate_dashboard()
        except Exception as e:
            return f"ダッシュボードの初回生成に失敗しました: {e}", 500
            
    return send_from_directory(PROJECT_DIR, "index.html")

@app.route('/api/update', methods=['POST'])
def update_data():
    progress = get_progress()
    if progress.get("status") == "running":
        return jsonify({"status": "already_running", "message": "現在、データ更新処理が実行中です。"}), 400
        
    # 一回のボタンクリックで「最新の更新」＋「過去20日分のバックフィル」を処理する
    limit = 20
    set_progress("running", 0, limit, "データ更新を開始しています...")
    
    # 別スレッドで実行
    thread = threading.Thread(target=async_update_task, args=(limit,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "データ更新プロセスを開始しました。"}), 202

@app.route('/api/scrape/goraggio', methods=['POST'])
def scrape_goraggio():
    progress = get_progress()
    if progress.get("status") == "running":
        return jsonify({"status": "already_running", "message": "現在、他のデータ更新処理が実行中です。"}), 400
        
    # 全スロット台数（約409台）をデフォルトの上限にする
    limit = 450
    set_progress("running", 0, limit, "台データオンラインからデータ回収を開始しています...")
    
    # 別スレッドで実行
    thread = threading.Thread(target=async_goraggio_task, args=(limit,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started", "message": "通常営業日のデータ回収プロセスを開始しました。"}), 202

@app.route('/api/status', methods=['GET'])
def update_status():
    progress = get_progress()
    return jsonify(progress)

@app.route('/api/predict', methods=['GET'])
def predict():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date is required"}), 400
    try:
        # 日付フォーマットのチェック
        datetime.strptime(date_str, "%Y-%m-%d")
        predictions = analyzer.predict_next_hot_slots(date_str)
        if predictions is None or predictions.empty:
            return jsonify([])
        return jsonify(predictions.to_dict(orient='records'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/machines', methods=['GET'])
def get_machines_list():
    try:
        conn = analyzer.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT machine_name FROM slot_details ORDER BY machine_name")
        machines = [row[0] for row in cursor.fetchall() if row[0]]
        conn.close()
        return jsonify(machines)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recommend', methods=['GET'])
def get_recommendations():
    try:
        results = analyzer.analyze_recommended_machines()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recommend', methods=['POST'])
def add_recommendation():
    data = request.json or {}
    machine_name = data.get('machine_name')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    label = data.get('label', '週間オススメ')
    
    if not machine_name or not start_date or not end_date:
        return jsonify({"error": "機種名、開始日、終了日は必須です。"}), 400
        
    try:
        conn = analyzer.get_connection()
        cursor = conn.cursor()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO recommended_machines (machine_name, start_date, end_date, label, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (machine_name, start_date, end_date, label, created_at))
        conn.commit()
        conn.close()
        
        # ダッシュボード再生成
        dashboard_generator.generate_dashboard()
        return jsonify({"status": "success", "message": "オススメ機種を登録しました。"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/recommend/delete', methods=['POST'])
def delete_recommendation():
    data = request.json or {}
    rec_id = data.get('id')
    if not rec_id:
        return jsonify({"error": "IDは必須です。"}), 400
        
    try:
        conn = analyzer.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommended_machines WHERE id = ?", (rec_id,))
        conn.commit()
        conn.close()
        
        # ダッシュボード再生成
        dashboard_generator.generate_dashboard()
        return jsonify({"status": "success", "message": "登録データを削除しました。"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/predict/tune', methods=['POST'])
def tune_predictions():
    progress = get_progress()
    if progress.get("status") == "running":
        return jsonify({"status": "already_running", "message": "現在、データ更新処理が実行中です。学習を実行できません。"}), 400
        
    try:
        result = analyzer.tune_prediction_parameters()
        if result.get("status") == "success":
            dashboard_generator.generate_dashboard()
            return jsonify(result)
        else:
            return jsonify({"error": result.get("message")}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/slot/history')
def slot_history():
    slot_num = request.args.get('slot_number')
    if not slot_num:
        return jsonify({"error": "台番号は必須です。"}), 400
        
    try:
        conn = analyzer.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, machine_name, games, diff, winning 
            FROM slot_details 
            WHERE slot_number = ? 
            ORDER BY date DESC 
            LIMIT 10
        """, (slot_num,))
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for r in rows:
            history.append({
                "date": r[0],
                "machine_name": r[1],
                "games": r[2] if r[2] is not None else 0,
                "diff": r[3] if r[3] is not None else 0,
                "winning": bool(r[4])
            })
            
        return jsonify({"slot_number": slot_num, "history": history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 初期起動時に進捗を初期化
    set_progress("idle", 0, 0, "待機中")
    print("Starting Flask local server at http://127.0.0.1:5000")
    # ローカルのみアクセス可能にホストを設定
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
