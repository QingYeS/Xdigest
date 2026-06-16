@echo off
cd /d "C:\Users\Jinge\Desktop\Projects_Me\Agents\Xdigest"
set PYTHONIOENCODING=utf-8
if not exist "logs" mkdir "logs"
for /f "tokens=*" %%d in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd'"') do set LOGDATE=%%d
"C:\Users\Jinge\anaconda3\envs\xdigest\python.exe" -u main.py --no-email >> "logs\run_%LOGDATE%.log" 2>&1
