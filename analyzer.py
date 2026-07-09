import sqlite3
import pandas as pd
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "slot_data.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def analyze_special_days():
    """
    旧イベント日（0のつく日、5のつく日）と通常営業日のパフォーマンス比較
    """
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM daily_summary", conn)
    conn.close()
    
    if df.empty:
        return None
        
    df['date_dt'] = pd.to_datetime(df['date'])
    df['day'] = df['date_dt'].dt.day
    
    def classify_day(day):
        if day % 10 == 0:
            return "0のつく日"
        elif day % 10 == 5:
            return "5のつく日"
        else:
            return "通常営業日"
            
    df['day_type'] = df['day'].apply(classify_day)
    
    summary = df.groupby('day_type').agg(
        recorded_days=('date', 'count'),
        avg_total_diff=('total_diff', 'mean'),
        avg_diff_per_machine=('average_diff', 'mean'),
        avg_winning_rate=('winning_rate', 'mean')
    ).reset_index()
    
    # 読みやすく丸める
    summary['avg_total_diff'] = summary['avg_total_diff'].round(0).astype(int)
    summary['avg_diff_per_machine'] = summary['avg_diff_per_machine'].round(0).astype(int)
    summary['avg_winning_rate'] = (summary['avg_winning_rate'] * 100).round(1)
    
    return summary

def analyze_machines(min_records=3):
    """
    強い機種ランキング
    min_records: 信頼性向上のため、最低何日分のデータがあるか
    """
    conn = get_connection()
    # 複数日の機種別統計から集計
    query = """
    SELECT 
        machine_name,
        COUNT(date) as recorded_days,
        MAX(count) as total_installed,
        SUM(total_diff) as sum_diff,
        AVG(average_diff) as avg_diff,
        SUM(winning_machines) as total_wins,
        CAST(SUM(winning_machines) AS REAL) / SUM(count) as win_rate
    FROM machine_stats
    GROUP BY machine_name
    HAVING recorded_days >= ?
    ORDER BY avg_diff DESC
    """
    df = pd.read_sql_query(query, conn, params=(min_records,))
    conn.close()
    
    if df.empty:
        return None
        
    df['win_rate'] = (df['win_rate'] * 100).round(1)
    df['avg_diff'] = df['avg_diff'].round(0).astype(int)
    return df

def analyze_last_digits(target_day_type=None):
    """
    台番号の下一桁（末尾）分析
    target_day_type: "0のつく日", "5のつく日", "通常営業日", または None (全体)
    """
    conn = get_connection()
    query = """
    SELECT 
        d.date,
        d.slot_number,
        d.diff,
        d.winning,
        d.last_digit,
        s.average_diff as daily_avg
    FROM slot_details d
    JOIN daily_summary s ON d.date = s.date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return None
        
    df['date_dt'] = pd.to_datetime(df['date'])
    df['day'] = df['date_dt'].dt.day
    
    def classify_day(day):
        if day % 10 == 0:
            return "0のつく日"
        elif day % 10 == 5:
            return "5のつく日"
        else:
            return "通常営業日"
            
    df['day_type'] = df['day'].apply(classify_day)
    
    if target_day_type:
        df = df[df['day_type'] == target_day_type]
        
    summary = df.groupby('last_digit').agg(
        total_slots=('slot_number', 'count'),
        avg_diff=('diff', 'mean'),
        win_rate=('winning', 'mean')
    ).reset_index()
    
    summary['avg_diff'] = summary['avg_diff'].round(0).astype(int)
    summary['win_rate'] = (summary['win_rate'] * 100).round(1)
    summary = summary.sort_values(by='avg_diff', ascending=False)
    
    return summary

def load_prediction_parameters(model_type="default"):
    """
    DBの model_parameters テーブルから指定モデル（default / raise / trend）の予測重み設定を読み込む
    """
    fallbacks = {
        'default': {
            'weight_slot_avg': 0.4,
            'weight_machine_avg': 0.3,
            'bonus_matching_digit': 250.0,
            'bonus_zoro_digit': 80.0,
            'bonus_raise_target': 100.0
        },
        'raise': {
            'weight_slot_avg': 0.3,
            'weight_machine_avg': 0.2,
            'bonus_matching_digit': 80.0,
            'bonus_zoro_digit': 40.0,
            'bonus_raise_target': 300.0
        },
        'trend': {
            'weight_slot_avg': 0.2,
            'weight_machine_avg': 0.2,
            'bonus_matching_digit': 450.0,
            'bonus_zoro_digit': 150.0,
            'bonus_raise_target': 50.0
        }
    }
    
    if model_type not in fallbacks:
        model_type = 'default'
        
    params = fallbacks[model_type].copy()
    
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM model_parameters")
        rows = cursor.fetchall()
        for k, v in rows:
            if k.startswith(f"{model_type}_"):
                key_name = k[len(model_type)+1:]
                if key_name in params:
                    params[key_name] = float(v)
            elif model_type == 'default' and k in params:
                params[k] = float(v)
    except Exception:
        pass
    finally:
        conn.close()
        
    return params

def predict_next_hot_slots(target_date_str, params=None, model_type="default"):
    """
    特定の日付をターゲットにして、期待値の高い台（台番号）を予測スコアリングする (モデルタイプ: default / raise / trend)
    """
    if params is None:
        params = load_prediction_parameters(model_type)
        
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
    day = target_date.day
    
    # ターゲット日の属性判定
    if day % 10 == 0:
        day_type = "0のつく日"
        matching_digit = 0
    elif day % 10 == 5:
        day_type = "5のつく日"
        matching_digit = 5
    else:
        day_type = "通常営業日"
        matching_digit = None
        
    conn = get_connection()
    
    # 1. 各台番号の過去データ（直近30営業日のデータに限定して、新台入れ替え等の挙動変化に追従させる）
    # 同一の台番号であっても、台移動や新台入替の前後でデータが混ざらないよう、
    # ターゲット日直前営業日の設置機種と同一のレコードのみに限定して集計する
    # 注: target_date_str より前のデータのみを対象とする (リーク防止)
    slot_query = """
    WITH latest_machines AS (
        SELECT slot_number, machine_name
        FROM slot_details
        WHERE date = (SELECT MAX(date) FROM daily_summary WHERE date < ?)
    ),
    filtered_slots AS (
        SELECT 
            sd.date,
            sd.slot_number,
            sd.machine_name,
            sd.diff,
            sd.winning,
            ROW_NUMBER() OVER(PARTITION BY sd.slot_number ORDER BY sd.date DESC) as rn
        FROM slot_details sd
        JOIN latest_machines lm 
          ON sd.slot_number = lm.slot_number 
         AND sd.machine_name = lm.machine_name
        WHERE sd.date < ?
    )
    SELECT 
        slot_number,
        machine_name,
        COUNT(date) as recorded_days,
        AVG(diff) as avg_diff,
        AVG(winning) as win_rate
    FROM filtered_slots
    WHERE rn <= 30
    GROUP BY slot_number, machine_name
    """
    slots_df = pd.read_sql_query(slot_query, conn, params=(target_date_str, target_date_str))
    
    # 2. 機種ごとの過去の強さ（平均差枚）
    machine_query = """
    SELECT 
        machine_name,
        AVG(average_diff) as machine_avg_diff
    FROM machine_stats
    WHERE date < ?
    GROUP BY machine_name
    """
    machines_df = pd.read_sql_query(machine_query, conn, params=(target_date_str,))
    
    # 3. 前日の最終差枚数（上げ狙い判定用）
    # 直近の営業日データを取得
    last_date_query = "SELECT MAX(date) FROM daily_summary WHERE date < ?"
    cursor = conn.cursor()
    cursor.execute(last_date_query, (target_date_str,))
    last_date = cursor.fetchone()[0]
    
    last_day_df = pd.DataFrame()
    if last_date:
        last_day_query = "SELECT slot_number, diff as last_diff, games as last_games FROM slot_details WHERE date = ?"
        last_day_df = pd.read_sql_query(last_day_query, conn, params=(last_date,))
        
    # 4. 直近3日間の累計差枚数（複数日凹み上げ狙い判定用）
    recent_dates_query = "SELECT date FROM daily_summary WHERE date < ? ORDER BY date DESC LIMIT 3"
    cursor.execute(recent_dates_query, (target_date_str,))
    recent_dates = [row[0] for row in cursor.fetchall()]
    
    sum_diff_3d_df = pd.DataFrame()
    if recent_dates:
        placeholders = ','.join('?' for _ in recent_dates)
        sum_diff_query = f"""
        SELECT slot_number, SUM(diff) as diff_3d 
        FROM slot_details 
        WHERE date IN ({placeholders})
        GROUP BY slot_number
        """
        sum_diff_3d_df = pd.read_sql_query(sum_diff_query, conn, params=recent_dates)
        
    conn.close()
    
    if slots_df.empty:
        return None
        
    # データマージ
    df = pd.merge(slots_df, machines_df, on='machine_name', how='left')
    if not last_day_df.empty:
        df = pd.merge(df, last_day_df, on='slot_number', how='left')
    else:
        df['last_diff'] = 0
        df['last_games'] = -1
        
    if not sum_diff_3d_df.empty:
        df = pd.merge(df, sum_diff_3d_df, on='slot_number', how='left')
    else:
        df['diff_3d'] = 0
        
    # 欠損値補完
    df['avg_diff'] = df['avg_diff'].fillna(0)
    df['win_rate'] = df['win_rate'].fillna(0)
    df['machine_avg_diff'] = df['machine_avg_diff'].fillna(0)
    df['last_diff'] = df['last_diff'].fillna(0)
    df['last_games'] = df['last_games'].fillna(-1)
    df['diff_3d'] = df['diff_3d'].fillna(0)
    
    # 末尾判定
    df['last_digit'] = df['slot_number'] % 10
    
    # スコアリングロジック
    # 台・機種のベーススコア
    df['score'] = (df['avg_diff'] * params['weight_slot_avg']) + (df['machine_avg_diff'] * params['weight_machine_avg'])
    
    # 末尾ボーナス
    if matching_digit is not None:
        df.loc[df['last_digit'] == matching_digit, 'score'] += params['bonus_matching_digit']
        
    # ゾロ目台番号ボーナス (例: 1777, 1888, 2022 などのゾロ目やゾロ目末尾)
    df['last_two'] = df['slot_number'] % 100
    df.loc[(df['last_two'] % 11 == 0) & (df['last_two'] != 0), 'score'] += params['bonus_zoro_digit']
    
    # 上げ狙いボーナス（前日凹んでいて、過去平均が良い台）
    # 条件A: 前日 -1500枚以下で、過去平均がプラスの台にボーナス
    df.loc[(df['last_diff'] < -1500) & (df['avg_diff'] > 100), 'score'] += params['bonus_raise_target']
    # 条件B: 3日間の累計差枚が -2500枚以下で、過去平均がプラス（>50）の台に追加ボーナス
    df.loc[(df['diff_3d'] < -2500) & (df['avg_diff'] > 50), 'score'] += params['bonus_raise_target']
    
    # スコア順にソートしてトップ20を返す
    df['score'] = df['score'].round(1)
    df['win_rate'] = (df['win_rate'] * 100).round(1)
    df['avg_diff'] = df['avg_diff'].round(0).astype(int)
    df['machine_avg_diff'] = df['machine_avg_diff'].round(0).astype(int)
    df['last_diff'] = df['last_diff'].round(0).astype(int)
    df['last_games'] = df['last_games'].astype(int)
    
    hot_slots = df.sort_values(by='score', ascending=False).head(20)
    
    return hot_slots[[
        'slot_number', 'machine_name', 'recorded_days', 
        'avg_diff', 'win_rate', 'machine_avg_diff', 
        'last_diff', 'last_games', 'score'
    ]]

def get_recent_trends():
    """
    直近7営業日のデータに基づき、店舗の最近の出玉傾向および高設定投入状況を分析する
    """
    conn = get_connection()
    
    # 1. 直近の7営業日の日付を取得
    date_query = "SELECT date FROM daily_summary ORDER BY date DESC LIMIT 7"
    cursor = conn.cursor()
    cursor.execute(date_query)
    recent_dates = [row[0] for row in cursor.fetchall()]
    
    if not recent_dates:
        conn.close()
        return {
            "recent_dates": [],
            "recent_machines": [],
            "total_high_settings": 0,
            "top_machines": [],
            "top_digits": [],
            "summary_text": "データが蓄積されていません。データを取得してください。"
        }
        
    recent_dates_placeholder = ','.join('?' for _ in recent_dates)
    
    # 2. 直近7日間の機種別ランキング（平均差枚上位）
    recent_machine_query = f"""
    SELECT 
        machine_name,
        COUNT(date) as recorded_days,
        MAX(count) as total_installed,
        SUM(total_diff) as sum_diff,
        AVG(average_diff) as avg_diff,
        AVG(winning_rate) * 100 as win_rate
    FROM machine_stats
    WHERE date IN ({recent_dates_placeholder})
    GROUP BY machine_name
    HAVING total_installed >= 5  -- 最低設置台数の閾値
    ORDER BY avg_diff DESC
    LIMIT 5
    """
    recent_machines_df = pd.read_sql_query(recent_machine_query, conn, params=recent_dates)
    
    # 3. 高設定濃厚（高設定挙動）台の抽出
    # 条件: games >= 5000G かつ diff >= 2000枚
    recent_slots_query = f"""
    SELECT 
        date,
        slot_number,
        machine_name,
        diff,
        games,
        last_digit
    FROM slot_details
    WHERE date IN ({recent_dates_placeholder})
      AND games >= 5000
      AND diff >= 2000
    """
    high_settings_df = pd.read_sql_query(recent_slots_query, conn, params=recent_dates)
    
    conn.close()
    
    # 分析サマリーの構築
    total_high_settings = len(high_settings_df)
    
    # 機種別の高設定投入頻度（どの機種に高設定濃厚台が多いか）
    top_high_setting_machines = []
    if not high_settings_df.empty:
        machine_counts = high_settings_df['machine_name'].value_counts()
        for m_name, count in machine_counts.head(3).items():
            top_high_setting_machines.append({"machine_name": m_name, "count": int(count)})
            
    # 末尾別の高設定投入頻度（どの末尾に高設定濃厚台が多いか）
    top_high_setting_digits = []
    if not high_settings_df.empty:
        digit_counts = high_settings_df['last_digit'].value_counts()
        for digit, count in digit_counts.head(3).items():
            top_high_setting_digits.append({"last_digit": int(digit), "count": int(count)})
            
    # 傾向要約テキストの自動生成
    summary_text = ""
    if total_high_settings > 0:
        most_common_machine = top_high_setting_machines[0]['machine_name'] if top_high_setting_machines else "なし"
        most_common_digit = top_high_setting_digits[0]['last_digit'] if top_high_setting_digits else "なし"
        
        summary_text = (
            f"直近7営業日の全台データから、しっかりと粘られて出玉が出ている「高設定挙動台（5000G以上稼働かつ+2000枚以上）」は累計 {total_high_settings} 台検出されました。 "
            f"機種別では「{most_common_machine}」に最も多く投入されている傾向が見られます。 "
            f"また、台番号末尾では「末尾 {most_common_digit}」の台が特に優秀な挙動を示しており、狙い目の候補となります。"
        )
    else:
        summary_text = "直近7営業日において、ゲーム数が5000G以上回され、かつ+2000枚以上の高設定挙動を示した台は検出されませんでした。通常日メインの集計期間である可能性があります。"
        
    return {
        "recent_dates": recent_dates,
        "recent_machines": recent_machines_df.to_dict(orient='records') if not recent_machines_df.empty else [],
        "total_high_settings": total_high_settings,
        "top_machines": top_high_setting_machines,
        "top_digits": top_high_setting_digits,
        "summary_text": summary_text
    }

def detect_high_confidence_blocks(min_games=3000, min_diff=100, sum_diff_threshold=4500):
    """
    3台並びの「高信頼度設定ブロック（塊）」を自動検出する
    しきい値:
      - 3台すべてが min_games 以上 (デフォルト 3000G)
      - 3台すべてが min_diff 以上 (デフォルト +100枚)
      - 3台の合計差枚数が sum_diff_threshold 以上 (デフォルト +4500枚)
    """
    conn = get_connection()
    # 直近15営業日を対象
    date_query = "SELECT date FROM daily_summary ORDER BY date DESC LIMIT 15"
    cursor = conn.cursor()
    cursor.execute(date_query)
    target_dates = [row[0] for row in cursor.fetchall()]
    
    if not target_dates:
        conn.close()
        return []
        
    placeholders = ','.join('?' for _ in target_dates)
    query = f"""
    SELECT date, slot_number, machine_name, diff, games 
    FROM slot_details 
    WHERE date IN ({placeholders}) 
    ORDER BY date DESC, slot_number ASC
    """
    df = pd.read_sql_query(query, conn, params=target_dates)
    conn.close()
    
    detected_blocks = []
    
    # 日付ごとにグルーピングして処理
    for date_str, group in df.groupby('date'):
        # 台番号が連続しているかチェックするため、リスト化
        slots = group.sort_values(by='slot_number').to_dict(orient='records')
        
        # 3台ずつのスライディングウィンドウでスキャン
        for i in range(len(slots) - 2):
            s1 = slots[i]
            s2 = slots[i+1]
            s3 = slots[i+2]
            
            # 台番号が連続しているか (1ずつ増えているか、または一定範囲内)
            if (s2['slot_number'] == s1['slot_number'] + 1) and (s3['slot_number'] == s2['slot_number'] + 1):
                # 条件判定
                cond_games = (s1['games'] >= min_games) and (s2['games'] >= min_games) and (s3['games'] >= min_games)
                cond_diff = (s1['diff'] >= min_diff) and (s2['diff'] >= min_diff) and (s3['diff'] >= min_diff)
                total_diff = s1['diff'] + s2['diff'] + s3['diff']
                cond_total = total_diff >= sum_diff_threshold
                
                if cond_games and cond_diff and cond_total:
                    # 同一機種かどうか、または複数機種にまたがっているか
                    machines = list(set([s1['machine_name'], s2['machine_name'], s3['machine_name']]))
                    machines_str = " / ".join(machines)
                    
                    detected_blocks.append({
                        "date": date_str,
                        "slots": f"{s1['slot_number']} - {s3['slot_number']}",
                        "machines": machines_str,
                        "total_diff": total_diff,
                        "details": f"{s1['slot_number']}(+{s1['diff']:,}枚) | {s2['slot_number']}(+{s2['diff']:,}枚) | {s3['slot_number']}(+{s3['diff']:,}枚)"
                    })
                    
    # 最新日付順、合計差枚の大きい順にソートして最大10件を返す
    detected_blocks.sort(key=lambda x: (x['date'], x['total_diff']), reverse=True)
    return detected_blocks[:10]

def analyze_weekday_machine_trends():
    """
    曜日別の機種別平均差枚数を計算する (直近90日間の最新トレンドを反映)
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM machine_stats")
    max_date_row = cursor.fetchone()
    
    if not max_date_row or not max_date_row[0]:
        conn.close()
        return {}
        
    latest_date = datetime.strptime(max_date_row[0], "%Y-%m-%d")
    start_date = (latest_date - timedelta(days=90)).strftime("%Y-%m-%d")
    
    query = """
    SELECT date, machine_name, average_diff, winning_rate, count
    FROM machine_stats
    WHERE date >= ?
    """
    df = pd.read_sql_query(query, conn, params=(start_date,))
    conn.close()
    
    if df.empty:
        return {}
        
    df['date_dt'] = pd.to_datetime(df['date'])
    df['weekday'] = df['date_dt'].dt.strftime('%w') # '0': 日曜日, '1': 月曜日...
    
    # 曜日別の日本語マッピング
    weekday_map = {'0': '日', '1': '月', '2': '火', '3': '水', '4': '木', '5': '金', '6': '土'}
    df['weekday_ja'] = df['weekday'].map(weekday_map)
    
    # 機種×曜日でグルーピング
    grouped = df.groupby(['weekday_ja', 'machine_name']).agg(
        avg_diff=('average_diff', 'mean'),
        win_rate=('winning_rate', 'mean'),
        total_count=('count', 'mean') # 平均設置台数に変更
     ).reset_index()
     
    # 曜日ごとに整理
    weekday_trends = {}
    for day in ['月', '火', '水', '木', '金', '土', '日']:
        day_df = grouped[grouped['weekday_ja'] == day]
        # 平均設置台数が2台以上のデータのみに限定してバラエティ等のノイズを減らす
        day_df = day_df[day_df['total_count'] >= 2.0]
        day_df = day_df.sort_values(by='avg_diff', ascending=False).head(3)
        
        weekday_trends[day] = []
        for _, row in day_df.iterrows():
            weekday_trends[day].append({
                "machine_name": row['machine_name'],
                "avg_diff": int(round(row['avg_diff'])),
                "win_rate": round(row['win_rate'] * 100, 1)
            })
            
    return weekday_trends

def analyze_setting_change_habits():
    """
    ホールの設定変更の癖（前日差枚からの設定上げ狙い vs 据え置き狙い）を分析する
    """
    conn = get_connection()
    
    # 稼働日順に全台データを日付と台番号で並べ、前日のデータを自己結合
    # SQLiteで直近の過去の営業日とのマッチングを行う
    query = """
    WITH ordered_details AS (
        SELECT 
            date,
            slot_number,
            diff,
            winning,
            LEAD(date) OVER(PARTITION BY slot_number ORDER BY date) as next_date,
            LEAD(diff) OVER(PARTITION BY slot_number ORDER BY date) as next_diff,
            LEAD(winning) OVER(PARTITION BY slot_number ORDER BY date) as next_winning
        FROM slot_details
    )
    SELECT 
        diff as last_diff,
        next_diff,
        next_winning
    FROM ordered_details
    WHERE next_date IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return {
            "raise_avg_diff": 0, "raise_win_rate": 50.0,
            "keep_avg_diff": 0, "keep_win_rate": 50.0,
            "raise_ratio": 50, "keep_ratio": 50,
            "verdict": "データ不足により判定不可"
        }
        
    # 1. 上げ狙い (前日大幅マイナス -1500枚以下 の翌日成績)
    raise_df = df[df['last_diff'] <= -1500]
    raise_avg_diff = raise_df['next_diff'].mean() if not raise_df.empty else 0.0
    raise_win_rate = (raise_df['next_winning'].mean() * 100) if not raise_df.empty else 50.0
    
    # 2. 据え置き狙い (前日大幅プラス +1500枚以上 の翌日成績)
    keep_df = df[df['last_diff'] >= 1500]
    keep_avg_diff = keep_df['next_diff'].mean() if not keep_df.empty else 0.0
    keep_win_rate = (keep_df['next_winning'].mean() * 100) if not keep_df.empty else 50.0
    
    # スコア化 (0-100)
    # それぞれの勝率や平均差枚数からスコアを算出
    raise_score = int(max(0, min(100, 50 + (raise_avg_diff / 10))))
    keep_score = int(max(0, min(100, 50 + (keep_avg_diff / 10))))
    
    total = raise_score + keep_score
    if total > 0:
        raise_ratio = int((raise_score / total) * 100)
        keep_ratio = 100 - raise_ratio
    else:
        raise_ratio = 50
        keep_ratio = 50
        
    if raise_ratio > 60:
        verdict = f"「設定上げ狙い」が非常に有効です（推奨度 {raise_ratio}%）。凹み台の翌日平均差枚数がプラス傾向にあり、設定変更によるリセットが期待できます。"
    elif keep_ratio > 60:
        verdict = f"「好調台の据え置き狙い」が有効です（推奨度 {keep_ratio}%）。前日良く出ていた台が翌日も高パフォーマンスを維持しやすく、据え置き多用の癖が見られます。"
    else:
        verdict = "上げ狙い・据え置き狙いともに五分五分です。前日のデータに関わらず、特定日や末尾番号、優秀機種の優先配分を主軸に立ち回ることを推奨します。"
        
    return {
        "raise_avg_diff": int(round(raise_avg_diff)),
        "raise_win_rate": round(raise_win_rate, 1),
        "keep_avg_diff": int(round(keep_avg_diff)),
        "keep_win_rate": round(keep_win_rate, 1),
        "raise_ratio": raise_ratio,
        "keep_ratio": keep_ratio,
        "verdict": verdict
    }

def analyze_recommended_machines():
    """
    登録されたおすすめ機種の実績を、指定期間内の差枚・勝率・高設定挙動数から集計して返す
    """
    conn = get_connection()
    # 登録一覧の取得
    rec_query = "SELECT id, machine_name, start_date, end_date, label FROM recommended_machines ORDER BY created_at DESC"
    try:
        recs_df = pd.read_sql_query(rec_query, conn)
    except Exception:
        # テーブルがない場合等のフォールバック
        conn.close()
        return []
    
    if recs_df.empty:
        conn.close()
        return []
        
    results = []
    for _, row in recs_df.iterrows():
        rec_id = int(row['id'])
        m_name = row['machine_name']
        start_d = row['start_date']
        end_d = row['end_date']
        label = row['label']
        
        # 期間内の出玉データの集計
        # 1. 設置台数（期間内における1日あたりの最大台数）の取得
        slots_count_query = """
        SELECT MAX(daily_count) FROM (
            SELECT COUNT(*) as daily_count 
            FROM slot_details 
            WHERE machine_name = ? 
              AND date >= ? 
              AND date <= ? 
            GROUP BY date
        )
        """
        cursor = conn.cursor()
        cursor.execute(slots_count_query, (m_name, start_d, end_d))
        slots_count_row = cursor.fetchone()
        total_slots = slots_count_row[0] if slots_count_row and slots_count_row[0] is not None else 0
        
        # 2. 差枚・勝率の平均値
        stats_query = """
        SELECT 
            AVG(diff) as avg_diff,
            AVG(winning) as win_rate
        FROM slot_details
        WHERE machine_name = ?
          AND date >= ?
          AND date <= ?
        """
        cursor.execute(stats_query, (m_name, start_d, end_d))
        stats = cursor.fetchone()
        
        avg_diff = int(round(stats[0])) if stats and stats[0] is not None else 0
        win_rate = round(stats[1] * 100, 1) if stats and stats[1] is not None else 0.0
        
        # 2. 高設定濃厚（5000Gかつ+2000枚以上）の発生台数
        high_setting_query = """
        SELECT COUNT(*)
        FROM slot_details
        WHERE machine_name = ?
          AND date >= ?
          AND date <= ?
          AND games >= 5000
          AND diff >= 2000
        """
        cursor.execute(high_setting_query, (m_name, start_d, end_d))
        high_settings_count = cursor.fetchone()[0]
        
        results.append({
            "id": rec_id,
            "machine_name": m_name,
            "start_date": start_d,
            "end_date": end_d,
            "label": label,
            "total_slots": total_slots,
            "avg_diff": avg_diff,
            "win_rate": win_rate,
            "high_settings_count": high_settings_count
        })
        
    conn.close()
    return results

def eval_parameters(target_dates, params, model_type="default"):
    """
    指定されたパラメータとモデルタイプで過去の予測シミュレーションを行い、のべ予測上位20台の「実際の平均差枚数」の平均値を返す
    """
    total_diff_sum = 0
    total_slots_count = 0
    
    conn = get_connection()
    for date_str in target_dates:
        pred_df = predict_next_hot_slots(date_str, params, model_type)
        if pred_df is None or pred_df.empty:
            continue
            
        slot_list = pred_df['slot_number'].tolist()
        placeholders = ','.join('?' for _ in slot_list)
        
        query = f"SELECT diff FROM slot_details WHERE date = ? AND slot_number IN ({placeholders})"
        cursor = conn.cursor()
        cursor.execute(query, [date_str] + slot_list)
        diffs = [row[0] for row in cursor.fetchall() if row[0] is not None]
        
        if diffs:
            total_diff_sum += sum(diffs)
            total_slots_count += len(diffs)
            
    conn.close()
    
    if total_slots_count > 0:
        return total_diff_sum / total_slots_count
    return 0.0

def tune_prediction_parameters():
    """
    過去の特定日データを使って、3つの予測モデル（default / raise / trend）それぞれ個別に
    最も的中精度が高くなる予測重みパラメータを自動探索（グリッドサーチ）して保存する
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date FROM daily_summary 
        WHERE strftime('%d', date) LIKE '%0' OR strftime('%d', date) LIKE '%5'
        ORDER BY date DESC LIMIT 5
    """)
    target_dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    if len(target_dates) < 2:
        return {"status": "error", "message": "学習に必要な過去の特定日データが不足しています（最低2回分必要）。"}
        
    # 各モデルのパラメータ探索候補（グリッド）定義
    model_grids = {
        'default': {
            'slot_weights': [0.2, 0.4],
            'machine_weights': [0.2, 0.4],
            'matching_bonuses': [150.0, 300.0],
            'zoro_bonuses': [50.0, 100.0],
            'raise_bonuses': [50.0, 120.0]
        },
        'raise': {
            'slot_weights': [0.1, 0.3],
            'machine_weights': [0.1, 0.3],
            'matching_bonuses': [50.0, 100.0],
            'zoro_bonuses': [30.0, 60.0],
            'raise_bonuses': [250.0, 400.0]
        },
        'trend': {
            'slot_weights': [0.1, 0.3],
            'machine_weights': [0.1, 0.3],
            'matching_bonuses': [400.0, 600.0],
            'zoro_bonuses': [100.0, 200.0],
            'raise_bonuses': [30.0, 80.0]
        }
    }
    
    results = {}
    
    for m_type, grid in model_grids.items():
        best_score = -999999
        best_params = None
        
        current_params = load_prediction_parameters(m_type)
        before_avg_diff = eval_parameters(target_dates, current_params, m_type)
        
        for w_slot in grid['slot_weights']:
            for w_mach in grid['machine_weights']:
                for b_match in grid['matching_bonuses']:
                    for b_zoro in grid['zoro_bonuses']:
                        for b_raise in grid['raise_bonuses']:
                            candidate = {
                                'weight_slot_avg': w_slot,
                                'weight_machine_avg': w_mach,
                                'bonus_matching_digit': b_match,
                                'bonus_zoro_digit': b_zoro,
                                'bonus_raise_target': b_raise
                            }
                            score = eval_parameters(target_dates, candidate, m_type)
                            if score > best_score:
                                best_score = score
                                best_params = candidate
                                
        if best_params:
            conn = get_connection()
            cursor = conn.cursor()
            for k, v in best_params.items():
                db_key = f"{m_type}_{k}"
                cursor.execute("INSERT OR REPLACE INTO model_parameters (key, value) VALUES (?, ?)", (db_key, v))
            conn.commit()
            conn.close()
            
            after_avg_diff = best_score
            improvement = after_avg_diff - before_avg_diff
            
            results[m_type] = {
                "before_avg_diff": int(round(before_avg_diff)),
                "after_avg_diff": int(round(after_avg_diff)),
                "improvement": int(round(improvement)),
                "updated_params": best_params
            }
            
    return {
        "status": "success",
        "results": results
    }

def get_prediction_accuracy_report(limit=5):
    """
    過去の特定日における3つの予測モデル（default / raise / trend）それぞれの答え合わせ成績レポートを生成する
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date FROM daily_summary 
        WHERE strftime('%d', date) LIKE '%0' OR strftime('%d', date) LIKE '%5'
        ORDER BY date DESC LIMIT ?
    """, (limit,))
    target_dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    if not target_dates:
        return []
        
    report = []
    model_types = ['default', 'raise', 'trend']
    
    # あらかじめ全モデルの現在のパラメータをロードしておく
    model_params = {m: load_prediction_parameters(m) for m in model_types}
    
    conn = get_connection()
    for date_str in target_dates:
        day_results = {"date": date_str}
        
        for m_type in model_types:
            pred_df = predict_next_hot_slots(date_str, model_params[m_type], m_type)
            if pred_df is None or pred_df.empty:
                day_results[m_type] = {"avg_diff": 0, "win_rate": 0.0}
                continue
                
            slot_list = pred_df['slot_number'].tolist()
            placeholders = ','.join('?' for _ in slot_list)
            
            query = f"SELECT diff, winning FROM slot_details WHERE date = ? AND slot_number IN ({placeholders})"
            cursor = conn.cursor()
            cursor.execute(query, [date_str] + slot_list)
            rows = cursor.fetchall()
            
            diffs = [r[0] for r in rows if r[0] is not None]
            wins = [r[1] for r in rows if r[1] is not None]
            
            if diffs:
                avg_diff = sum(diffs) / len(diffs)
                win_rate = (sum(wins) / len(wins) * 100) if wins else 0.0
                day_results[m_type] = {
                    "avg_diff": int(round(avg_diff)),
                    "win_rate": round(win_rate, 1)
                }
            else:
                day_results[m_type] = {"avg_diff": 0, "win_rate": 0.0}
                
        report.append(day_results)
        
    conn.close()
    return report

if __name__ == "__main__":
    # 簡易テスト
    print("--- Special Days Summary ---")
    print(analyze_special_days())
    
    print("\n--- Strong Machines (Top 5) ---")
    machines = analyze_machines(min_records=1)
    if machines is not None:
        print(machines.head(5))
        
    print("\n--- Last Digit stats (Overall) ---")
    digits = analyze_last_digits()
    if digits is not None:
        print(digits.head(5))
        
    print("\n--- Predictions for next 0-ending day (e.g. 2026-07-10) ---")
    predictions = predict_next_hot_slots("2026-07-10")
    if predictions is not None:
        print(predictions.head(10))
