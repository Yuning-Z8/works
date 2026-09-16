import sqlite3
import time

DB_PATH = "/storage/emulated/0/1/program/works/metadata.db"
ONE_DAY_MS = 24 * 60 * 60 * 1000

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT scan_time FROM last_scan_time WHERE id = 1")
row = cur.fetchone()
if not row:
    print("未找到 last_scan_time 记录")
    conn.close()
    exit(1)

old_time = row[0]
new_time = old_time - ONE_DAY_MS

cur.execute("UPDATE last_scan_time SET scan_time = ? WHERE id = 1", (new_time,))
conn.commit()

old_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(old_time / 1000))
new_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(new_time / 1000))
print(f"修改前: {old_str} ({old_time})")
print(f"修改后: {new_str} ({new_time})")

conn.close()
