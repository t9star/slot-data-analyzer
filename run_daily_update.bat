@echo off
chcp 65001 > nul
cd /d "C:\Users\frog9\.gemini\antigravity\scratch\slot-data-analyzer"
set UV="C:\Users\frog9\.local\bin\uv.exe"
set GIT="C:\Program Files\Git\cmd\git.exe"
set LOG_FILE="daily_update.log"

echo ======================================================== >> %LOG_FILE%
echo [%DATE% %TIME%] 日次データ自動回収バッチを開始します >> %LOG_FILE%

echo [1/4] リモートリポジトリの最新状態を確認中... >> %LOG_FILE%
%GIT% fetch origin master >> %LOG_FILE% 2>&1
%GIT% merge -X ours origin/master --no-edit >> %LOG_FILE% 2>&1

echo [2/4] みんレポ＆ゴラッジョ（通常日データ全409台）のデータ回収中... >> %LOG_FILE%
%UV% run python -c "import scraper; scraper.run_scraper(limit=5); scraper.run_goraggio_scraper(limit=450)" >> %LOG_FILE% 2>&1

echo [3/4] ダッシュボード（index.html）の再生成中... >> %LOG_FILE%
%UV% run python dashboard_generator.py >> %LOG_FILE% 2>&1

echo [4/4] GitHub Pages へアップロード中... >> %LOG_FILE%
%UV% run python -c "import app; app.push_to_github()" >> %LOG_FILE% 2>&1

echo [%DATE% %TIME%] 日次データ自動回収バッチが完了しました >> %LOG_FILE%
echo ======================================================== >> %LOG_FILE%
