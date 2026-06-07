@echo off
echo Starting Pinui-Binui Scout...
start "" "http://127.0.0.1:8765"
echo Opening http://127.0.0.1:8765 in your browser...
echo Keep this window open while the scout is running.
wsl -d Ubuntu-24.04 -- bash -lc "cd '/mnt/c/Users/cassu/OneDrive - oren/Desktop/ramat yosef' && python3 -u server.py"
pause
