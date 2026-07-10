import requests
from bs4 import BeautifulSoup
import sqlite3
import os
import time
import re
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "slot_data.db")
PROGRESS_PATH = os.path.join(os.path.dirname(__file__), "progress.json")
TAG_URL = "https://min-repo.com/tag/damz%e7%9c%8c%e5%a4%ae%e5%ba%97/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def update_progress(status, current, total, message):
    """
    進捗状況を progress.json に保存する
    """
    progress_data = {
        "status": status,      # "idle", "running", "done", "error"
        "current": current,
        "total": total,
        "message": message,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to write progress file: {e}")

def estimate_date(display_date_str):
    """
    "7/7(火)" などの文字列から "2026-07-07" のような日付を推測する
    """
    match = re.search(r"(\d+)/(\d+)", display_date_str)
    if not match:
        return None
    
    month = int(match.group(1))
    day = int(match.group(2))
    
    now = datetime.now()
    year = now.year
    
    # 年越しの考慮
    if now.month == 1 and month == 12:
        year -= 1
    elif now.month == 12 and month == 1:
        year += 1
        
    return f"{year:04d}-{month:02d}-{day:02d}"

def parse_report_date(post_time_str, display_date_str):
    """
    正確な日付特定用
    """
    post_dt = datetime.fromisoformat(post_time_str.replace("Z", "+00:00"))
    match = re.search(r"(\d+)/(\d+)", display_date_str)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    
    year = post_dt.year
    if post_dt.month == 1 and month == 12:
        year -= 1
    elif post_dt.month == 12 and month == 1:
        year += 1
        
    target_date = datetime(year, month, day)
    return target_date.strftime("%Y-%m-%d")

def fetch_report_list():
    """
    店舗のタグページからレポートのURLと日付のリストを取得する
    """
    print(f"Fetching report list from: {TAG_URL}")
    response = requests.get(TAG_URL, headers=HEADERS, timeout=10)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    report_links = []
    
    table_wrap = soup.find('div', class_='table_wrap')
    if not table_wrap:
        print("table_wrap div not found.")
        return []
    table = table_wrap.find('table')
    if not table:
        print("Report table not found.")
        return []
        
    rows = table.find_all('tr')
    for row in rows:
        tds = row.find_all('td')
        if not tds:
            continue
            
        date_td = tds[0]
        a_tag = date_td.find('a')
        if not a_tag:
            continue
            
        href = a_tag.get('href')
        date_text = a_tag.get_text().strip()
        diff_text = tds[1].get_text().strip() if len(tds) > 1 else "-"
        
        report_links.append({
            "url": href,
            "display_date": date_text,
            "total_diff_str": diff_text
        })
        
    print(f"Found {len(report_links)} reports in list.")
    return report_links

def scrape_detail_page(url, display_date):
    """
    特定日の詳細レポートページ (?kishu=all) から全台データを取得し、データベースに保存する
    """
    all_data_url = f"{url}?kishu=all"
    print(f"Scraping detail page: {all_data_url}")
    
    response = requests.get(all_data_url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 1. 日付の特定
    time_tag = soup.find('time', class_='date')
    if not time_tag:
        print("Time tag not found. Skipping.")
        return False
        
    post_time = time_tag.get('datetime')
    date_str = parse_report_date(post_time, display_date)
    if not date_str:
        print(f"Could not parse date from {display_date}. Skipping.")
        return False
        
    print(f"Target date determined: {date_str}")
    
    # 2. 全台データテーブルのパース
    content_div = soup.find('div', class_='tab_content')
    if not content_div:
        print("Content div for all data not found.")
        return False
        
    all_table = content_div.find('table')
    if not all_table:
        print("All machine table not found.")
        return False
        
    machine_rows = all_table.find_all('tr')
    
    # 機種別集計用の辞書
    machine_summary = {}
    
    # 詳細データのリスト
    slot_details_list = []
    
    for row in machine_rows:
        tds = row.find_all('td')
        if not tds or len(tds) < 4:
            continue
            
        machine_name = tds[0].get_text().strip()
        slot_number_str = tds[1].get_text().strip()
        diff_str = tds[2].get_text().strip().replace(",", "").replace("+", "")
        games_str = tds[3].get_text().strip().replace(",", "")
        
        try:
            slot_number = int(slot_number_str)
            diff = int(diff_str) if diff_str != "-" else 0
            games = int(games_str) if games_str != "-" else 0
        except ValueError:
            continue
            
        winning = 1 if diff > 0 else 0
        last_digit = slot_number % 10
        
        slot_details_list.append((
            date_str,
            slot_number,
            machine_name,
            diff,
            games,
            winning,
            last_digit
        ))
        
        if machine_name not in machine_summary:
            machine_summary[machine_name] = {
                "count": 0,
                "total_diff": 0,
                "winning_count": 0
            }
        machine_summary[machine_name]["count"] += 1
        machine_summary[machine_name]["total_diff"] += diff
        machine_summary[machine_name]["winning_count"] += winning

    # 3. 全台データからサマリーを計算
    total_machines = len(slot_details_list)
    if total_machines == 0:
        print("No machine data parsed.")
        return False
        
    total_diff = sum(item[3] for item in slot_details_list)
    average_diff = int(total_diff / total_machines) if total_machines > 0 else 0
    winning_machines = sum(item[5] for item in slot_details_list)
    winning_rate = winning_machines / total_machines if total_machines > 0 else 0.0

    # 4. データベースへの書き込み
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 日次サマリー
        cursor.execute("""
        INSERT OR REPLACE INTO daily_summary (date, total_machines, total_diff, average_diff, winning_machines, winning_rate)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (date_str, total_machines, total_diff, average_diff, winning_machines, winning_rate))
        
        # 台番号詳細
        cursor.executemany("""
        INSERT OR REPLACE INTO slot_details (date, slot_number, machine_name, diff, games, winning, last_digit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, slot_details_list)
        
        # 機種別サマリー
        for m_name, stats in machine_summary.items():
            count = stats["count"]
            t_diff = stats["total_diff"]
            avg_diff = int(t_diff / count) if count > 0 else 0
            w_count = stats["winning_count"]
            w_rate = w_count / count if count > 0 else 0.0
            
            cursor.execute("""
            INSERT OR REPLACE INTO machine_stats (date, machine_name, count, total_diff, average_diff, winning_machines, winning_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (date_str, m_name, count, t_diff, avg_diff, w_count, w_rate))
            
        conn.commit()
        print(f"Successfully saved data for {date_str} ({len(slot_details_list)} machines).")
        success = True
    except Exception as e:
        conn.rollback()
        print(f"Database error while saving {date_str}: {e}")
        success = False
    finally:
        conn.close()
        
    return success

def run_scraper(limit=15):
    """
    スクレイパーのメイン処理（バックフィル対応）
    limit: 1回の実行で新しく取得する最大件数
    """
    update_progress("running", 0, limit, "レポート一覧を取得中...")
    
    try:
        reports = fetch_report_list()
    except Exception as e:
        error_msg = f"レポート一覧の取得に失敗しました: {e}"
        print(error_msg)
        update_progress("error", 0, limit, error_msg)
        return
        
    # すでに取得済みの日付をDBから確認
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT date FROM daily_summary")
    existing_dates = set(row[0] for row in cursor.fetchall())
    conn.close()
    
    # 未取得のレポートのみをフィルタリング
    target_reports = []
    for r in reports:
        if r["total_diff_str"] == "-":
            continue
            
        est_date = estimate_date(r["display_date"])
        if est_date and est_date in existing_dates:
            # すでに取得済みなら完全にスキップ
            continue
            
        target_reports.append(r)
        
    total_to_process = min(len(target_reports), limit)
    
    if total_to_process == 0:
        print("All reports are already up-to-date. No new data to fetch.")
        update_progress("done", 0, 0, "データはすべて最新です。")
        return
        
    print(f"Starting crawl for {total_to_process} new reports...")
    
    processed_count = 0
    for i in range(total_to_process):
        report = target_reports[i]
        url = report["url"]
        display_date = report["display_date"]
        
        update_progress(
            "running", 
            processed_count, 
            total_to_process, 
            f"データを取得中 ({processed_count + 1}/{total_to_process}日目): {display_date}"
        )
        
        try:
            success = scrape_detail_page(url, display_date)
            if success:
                processed_count += 1
                
            # ディレイ（IPブロック回避）
            if i < total_to_process - 1:
                time.sleep(4)
                
        except Exception as e:
            print(f"Error scraping {display_date} ({url}): {e}")
            time.sleep(5)
            
    update_progress("done", processed_count, total_to_process, f"データ更新完了！ 新しく {processed_count} 日分のデータを取得しました。")

import subprocess

def run_curl(args):
    """
    WAFブロックを回避するため、システムの curl.exe または curl を使ってリクエストを送信する
    """
    # Windows SchannelのSSL証明書失効リスト取得エラーやSSL警告を回避するためのオプションを追加
    # --ssl-no-revoke: 証明書失効チェックを回避 (Windows特有)
    # -k: 証明書エラーを無視
    additional_opts = ["--ssl-no-revoke", "-k"]
    
    cleaned_args = []
    for opt in additional_opts:
        if opt not in args:
            cleaned_args.append(opt)
    cleaned_args.extend(args)
    
    for executable in ["curl.exe", "curl"]:
        cmd = [executable] + cleaned_args
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if result.returncode != 0:
                stderr_msg = result.stderr.decode('utf-8', errors='replace').strip()
                print(f"[{executable} failed] returncode={result.returncode}, stderr={stderr_msg}")
                continue
            return result.stdout.decode('utf-8', errors='replace')
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"Error executing {executable}: {e}")
            return ""
            
    print("Error: Both curl.exe and curl executions failed or could not be found.")
    return ""

def init_goraggio_session(store_id):
    """
    ゴラッジョの規約同意セッション（Cookie）を確立する
    """
    base_url = f"https://daidata.goraggio.com/{store_id}"
    cookie_file = os.path.join(os.path.dirname(__file__), "goraggio_cookies.txt")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    
    if os.path.exists(cookie_file):
        try:
            os.remove(cookie_file)
        except Exception:
            pass
            
    # 1. 同意画面にアクセスしてCSRFトークンを取得
    print("Goraggio: Fetching CSRF token...")
    accept_get_url = f"{base_url}/accept"
    html = run_curl([
        "-s", "-L",
        "-A", ua,
        "-c", cookie_file,
        accept_get_url
    ])
    
    soup = BeautifulSoup(html, 'html.parser')
    token_input = soup.find('input', {'name': '_token'})
    if not token_input:
        print("Goraggio: Failed to find CSRF token on accept page.")
        return False
        
    token = token_input.get('value')
    print(f"Goraggio: CSRF Token obtained: {token}")
    
    # 2. 規約に同意するPOSTリクエストを送信してCookieを保存
    print("Goraggio: Accepting terms and conditions...")
    accept_url = f"{base_url}/accept"
    run_curl([
        "-s", "-L",
        "-A", ua,
        "-b", cookie_file,
        "-c", cookie_file,
        "-d", f"_token={token}",
        accept_url
    ])
    
    if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 50:
        print("Goraggio: Session Cookie successfully established.")
        return True
    else:
        print("Goraggio: Failed to save cookie file or cookie is empty.")
        return False

def fetch_goraggio_machines(store_id):
    """
    台番号一覧ページから全スロット台の「台番号」と「機種名」のマッピング辞書を取得する
    """
    list_url = f"https://daidata.goraggio.com/{store_id}/all_list?ps=S"
    cookie_file = os.path.join(os.path.dirname(__file__), "goraggio_cookies.txt")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    
    print("Goraggio: Fetching slot list page...")
    html = run_curl([
        "-s", "-L",
        "-A", ua,
        "-b", cookie_file,
        list_url
    ])
    
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables:
        print("Goraggio: Slot list table not found. Terms might not be accepted.")
        return {}
        
    machines = {}
    rows = tables[0].find_all('tr')
    for row in rows:
        tds = row.find_all('td')
        if len(tds) < 4:
            continue
            
        # 台番号のaタグから unit番号(実質台番号)とテキストの台番号を取得
        a_tag = tds[1].find('a') if len(tds) > 1 else None
        if not a_tag:
            continue
            
        href = a_tag.get('href', '')
        unit_match = re.search(r'unit=(\d+)', href)
        if not unit_match:
            continue
            
        unit_id = int(unit_match.group(1))
        machine_name = tds[3].get_text().strip()
        
        machines[unit_id] = machine_name
        
    print(f"Goraggio: Found {len(machines)} active slot machines.")
    return machines

def parse_goraggio_detail(html):
    """
    台ごとの詳細HTMLを解析し、過去8日分の日付ごとの「差枚数」「BB」「RB」「ART」「総ゲーム数」を取得する
    """
    soup = BeautifulSoup(html, 'html.parser')
    daily_data = {}
    
    # 1. 各日のスランプグラフ(差枚数)を JS から抽出
    scripts = soup.find_all('script')
    for script in scripts:
        content = script.string or ''
        if 'DailyCanvas' in content and 'min' in content:
            # 日付の抽出 (min: "YYYY-MM-DD 09:00:00")
            date_match = re.search(r'min:\s*"(\d{4}-\d{2}-\d{2})', content)
            if not date_match:
                continue
            date_str = date_match.group(1)
            
            # 最終差枚数の抽出 (jqplot の最後の座標のY値)
            array_match = re.search(r'jqplot\(\[\s*\[(.*?)\]\s*\]', content, re.DOTALL)
            if array_match:
                # ["2026-07-01 20:48:49",-3566] 形式にマッチ
                pairs = re.findall(r'\["[^"]+",\s*(-?\d+)\]', array_match.group(1))
                if pairs:
                    final_diff = int(pairs[-1])
                    if date_str not in daily_data:
                        daily_data[date_str] = {}
                    daily_data[date_str]['diff'] = final_diff
                    
    # 取得できた日付を古い順から新しい順にソート
    date_list = sorted(list(daily_data.keys()))
    if not date_list:
        return {}
        
    # 2. 過去履歴テーブルから BB/RB/ART/ゲーム数 を抽出
    tables = soup.find_all('table')
    
    # 最新日 (date_list[-1]) -> Table 0 (BB/RB/ART), Table 1 (累計スタート)
    # i日前 (i = 0..7) に対応するテーブルインデックス:
    # i == 0 のときは Table 0 / Table 1
    # i > 0 のときは Table 2i+1 / Table 2i+2
    for i in range(len(date_list)):
        # 配列の末尾から順に処理 (最新日から過去に向かって)
        date_idx = -(i + 1)
        if abs(date_idx) > len(date_list):
            break
            
        date_str = date_list[date_idx]
        
        # テーブルインデックスの算出
        bb_idx = 0 if i == 0 else (2 * i + 1)
        games_idx = 1 if i == 0 else (2 * i + 2)
        
        if bb_idx >= len(tables) or games_idx >= len(tables):
            break
            
        bb_table = tables[bb_idx]
        games_table = tables[games_idx]
        
        # 大当り回数の抽出 (BB, RB, ART)
        tds = bb_table.find_all('td')
        bb, rb, art = 0, 0, 0
        if len(tds) >= 3:
            try:
                bb = int(tds[0].get_text().strip())
                rb = int(tds[1].get_text().strip())
                art = int(tds[2].get_text().strip())
            except ValueError:
                pass
                
        # 総回転数(ゲーム数)の抽出
        games = 0
        cells = games_table.find_all(['th', 'td'])
        for idx, cell in enumerate(cells):
            if '累計スタート' in cell.get_text():
                if idx + 1 < len(cells):
                    try:
                        games_val = cells[idx + 1].get_text().strip().replace(',', '')
                        games = int(games_val)
                    except ValueError:
                        pass
                    break
                    
        if date_str not in daily_data:
            daily_data[date_str] = {}
        daily_data[date_str]['bb'] = bb
        daily_data[date_str]['rb'] = rb
        daily_data[date_str]['art'] = art
        daily_data[date_str]['games'] = games
        
    return daily_data

def run_goraggio_scraper(limit=450):
    """
    ゴラッジョ（台データオンライン）からグランドDAMZ県央店の直近8日分のスロット全台データを取得する
    """
    store_id = 101294
    cookie_file = os.path.join(os.path.dirname(__file__), "goraggio_cookies.txt")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    
    update_progress("running", 0, 100, "台データオンラインのセッションを確立中...")
    
    if not init_goraggio_session(store_id):
        error_msg = "セッションの確立に失敗しました。規約同意画面の取得エラーです。"
        print(error_msg)
        update_progress("error", 0, 100, error_msg)
        return
        
    try:
        machines = fetch_goraggio_machines(store_id)
    except Exception as e:
        error_msg = f"台番号一覧の取得に失敗しました: {e}"
        print(error_msg)
        update_progress("error", 0, 100, error_msg)
        return
        
    unit_ids = list(machines.keys())
    total_units = min(len(unit_ids), limit)
    
    if total_units == 0:
        update_progress("done", 0, 0, "稼働中のスロット台が見つかりませんでした。")
        return
        
    print(f"Starting slot data retrieval for {total_units} machines...")
    
    processed_count = 0
    slot_details_to_insert = []
    
    # データベース書き込み用
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for i in range(total_units):
        unit_id = unit_ids[i]
        machine_name = machines[unit_id]
        
        percent = int(((i + 1) / total_units) * 100)
        update_progress(
            "running",
            i + 1,
            total_units,
            f"詳細データを取得中 ({i + 1}/{total_units}台目): 台番号 {unit_id} ({machine_name})"
        )
        
        detail_url = f"https://daidata.goraggio.com/{store_id}/detail?unit={unit_id}"
        
        try:
            html = run_curl([
                "-s", "-L",
                "-A", ua,
                "-b", cookie_file,
                detail_url
            ])
            
            daily_data = parse_goraggio_detail(html)
            
            for date_str, data in daily_data.items():
                diff = data.get('diff', 0)
                games = data.get('games', 0)
                bb = data.get('bb', 0)
                rb = data.get('rb', 0)
                art = data.get('art', 0)
                winning = 1 if diff > 0 else 0
                last_digit = unit_id % 10
                
                # slot_details テーブルに保存
                cursor.execute("""
                INSERT OR REPLACE INTO slot_details (date, slot_number, machine_name, diff, games, winning, last_digit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (date_str, unit_id, machine_name, diff, games, winning, last_digit))
                
            processed_count += 1
            
            # 定期的にコミットして進捗を保存
            if processed_count % 10 == 0:
                conn.commit()
                
            # サーバー負荷対策のためディレイを入れる (0.5秒〜1秒程度)
            time.sleep(0.6)
            
        except Exception as e:
            print(f"Error processing unit {unit_id}: {e}")
            time.sleep(2)
            
    try:
        # i. 日次サマリーと機種別統計の再計算とUPSERT
        # goraggioから取得した日付のリストを取得
        cursor.execute("SELECT DISTINCT date FROM slot_details WHERE date >= date('now', '-10 day')")
        recent_dates = [row[0] for row in cursor.fetchall()]
        
        print("Re-calculating daily summaries and machine stats for updated dates...")
        for date_str in recent_dates:
            # 1. 日次サマリーの集計
            cursor.execute("""
            SELECT COUNT(*), SUM(diff), SUM(winning)
            FROM slot_details WHERE date = ?
            """, (date_str,))
            count, t_diff, w_count = cursor.fetchone()
            if count and count > 0:
                avg_diff = int(t_diff / count)
                w_rate = w_count / count
                cursor.execute("""
                INSERT OR REPLACE INTO daily_summary (date, total_machines, total_diff, average_diff, winning_machines, winning_rate)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (date_str, count, t_diff, avg_diff, w_count, w_rate))
                
            # 2. 機種別サマリーの集計
            cursor.execute("""
            SELECT machine_name, COUNT(*), SUM(diff), SUM(winning)
            FROM slot_details WHERE date = ?
            GROUP BY machine_name
            """, (date_str,))
            m_rows = cursor.fetchall()
            for row in m_rows:
                m_name, m_count, m_tdiff, m_wcount = row
                m_avgdiff = int(m_tdiff / m_count) if m_count > 0 else 0
                m_wrate = m_wcount / m_count if m_count > 0 else 0.0
                cursor.execute("""
                INSERT OR REPLACE INTO machine_stats (date, machine_name, count, total_diff, average_diff, winning_machines, winning_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (date_str, m_name, m_count, m_tdiff, m_avgdiff, m_wcount, m_wrate))
                
        conn.commit()
        print("Re-calculation completed.")
    except Exception as e:
        print(f"Error re-calculating stats: {e}")
        
    conn.close()
    
    # 一時ファイルの削除
    if os.path.exists(cookie_file):
        try:
            os.remove(cookie_file)
        except Exception:
            pass
            
    update_progress("done", processed_count, total_units, f"通常営業日データの回収完了！ {processed_count}台のスロット詳細データを過去8日分回収しました。")

if __name__ == "__main__":
    run_scraper(limit=15)

