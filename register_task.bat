@echo off
chcp 65001 > nul
echo ======================================================
echo スロットデータ自動回収バッチのタスクスケジューラ登録
echo ======================================================
echo 毎日 23:25 に自動実行するタスク「SlotDataAnalyzerDailyUpdate」を登録します。
echo （PC起動時に未実行だった場合も自動実行されるように設定します）
echo.

schtasks /create /tn "SlotDataAnalyzerDailyUpdate" /tr "\"C:\Users\frog9\.gemini\antigravity\scratch\slot-data-analyzer\run_daily_update.bat\"" /sc daily /st 23:25 /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo [成功] タスクスケジューラへの登録が完了しました！
    echo これで毎日 23:25 に自動で最新データが回収され、GitHub Pages が更新されます。
) else (
    echo.
    echo [警告] 登録に失敗しました。管理者権限が必要な場合があります。
)
pause
