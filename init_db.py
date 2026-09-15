# uuid, work_name, subject_id, has_content, is_exam, start_at, end_at, month_str(yyyy-mm自动生成), date_str(dd自动生成)
# uuid, url, version, detail
# uuid索引，month_str索引，month_str date_str联合索引

import os
import sqlite3

OUTPUT_BASE_DIR = "/storage/emulated/0/1/works/"
DB_PATH = os.path.join(OUTPUT_BASE_DIR, "metadata.db")


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # 作业元数据
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS works_info (
                uuid TEXT PRIMARY KEY,
                work_name TEXT NOT NULL,
                subject_id INTEGER NOT NULL,
                has_content INTEGER NOT NULL,
                is_exam INTEGER NOT NULL,
                start_at INTEGER NOT NULL,
                end_at INTEGER NOT NULL,
                month_str TEXT
                    GENERATED ALWAYS AS (strftime('%Y-%m', start_at / 1000 + 28800, 'unixepoch'))
                    STORED,
                date_str TEXT
                    GENERATED ALWAYS AS (strftime('%d', start_at / 1000 + 28800, 'unixepoch'))
                    STORED
            )
            """
        )

        # 作业详情
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS work_details (
                uuid TEXT PRIMARY KEY,
                url TEXT,
                version INTEGER DEFAULT 1,
                detail TEXT
            )
            """
        )

        # 等待补充 URL 的作业
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wait_url (
                uuid TEXT PRIMARY KEY,
                start_at INTEGER NOT NULL
            )
            """
        )

        # 上次扫描时间戳
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS last_scan_time (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                scan_time INTEGER NOT NULL
            )
            """
        )

        # 永久令牌
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS permanent_tokens (
                token TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            )
            """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_month_str ON works_info(month_str)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_month_date ON works_info(month_str, date_str)"
        )

        conn.commit()
    finally:
        conn.close()

    print(f"数据库表结构已初始化：{db_path}")


if __name__ == "__main__":
    init_db()
