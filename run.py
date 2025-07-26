import subprocess
import sys
import time
import re

ERROR_PATTERNS = [
    r"⚠️ Internal loop error:",
    r"❗ Outer error:",
]

def monitor_bot():
    while True:
        process = subprocess.Popen(
            ["python", "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )

        should_restart = False
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            print(line.strip(), flush=True)
            
            # Check for error patterns
            for pattern in ERROR_PATTERNS:
                if re.search(pattern, line):
                    should_restart = True
                    break
            
            if should_restart:
                print("🔄 Error detected, restarting bot...", flush=True)
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
                
        if not should_restart:
            break
            
        time.sleep(5)  # Wait before restart

if __name__ == "__main__":
    monitor_bot()