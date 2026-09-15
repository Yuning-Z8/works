#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动作业提取系统 v8
使用 SQLite 存储元数据和作业详情
"""

import json
import os
import re
import time
import queue
import threading
import html
import sqlite3
import atexit
import uuid
import secrets
import urllib.request
from functools import wraps
from datetime import datetime
from typing import Any, Dict, Set, List, Tuple, Optional
from flask import Flask, render_template, jsonify, request


# ============================================================================
# 基础组件模块
# ============================================================================


class Logger:
    """日志管理"""

    class Colors:
        RESET = "\033[0m"
        INFO = "\033[34m"
        SUCCESS = "\033[32m"
        WARNING = "\033[33m"
        ERROR = "\033[31m"
        BOLD = "\033[1m"

    def __init__(self, debug: bool = False):
        self.current_action: str = ""
        if debug:
            self.debug = self._debug
        else:
            self.debug = lambda _: None

    def set_action(self, action: str):
        self.current_action = action

    def clear_action(self):
        self.current_action = ""

    def _format_message(self, level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        level_color = getattr(self.Colors, level.upper(), self.Colors.INFO)
        if self.current_action:
            return f"{level_color}[{timestamp}] [{self.current_action}] {message}{self.Colors.RESET}"
        return f"{level_color}[{timestamp}] {message}{self.Colors.RESET}"

    def info(self, message: str):
        print(self._format_message("INFO", message))

    def success(self, message: str):
        print(self._format_message("SUCCESS", message))

    def warning(self, message: str):
        print(self._format_message("WARNING", message))

    def error(self, message: str):
        print(self._format_message("ERROR", message))

    def _debug(self, message: str):
        print(message)


class ConfigManager:
    """配置管理"""

    DEFAULT_CONFIG = {
        "subject_config": {
            "1": {"name": "语文", "color": "#E67E22", "short": "语"},
            "2": {"name": "数学", "color": "#4D7CFF", "short": "数"},
            "3": {"name": "英语", "color": "#F1C40F", "short": "英"},
            "7": {"name": "物理", "color": "#54B4FF", "short": "物"},
            "8": {"name": "化学", "color": "#B74093", "short": "化"},
            "13": {"name": "通用技术", "color": "#2ECC71", "short": "通"},
            "15": {"name": "信息技术", "color": "#00BCD4", "short": "信"},
            "default": {"name": "未知", "color": "#A0A0A0", "short": "未"},
        },
        "check_interval": 3600,
    }

    def __init__(self, config_path: str, logger: Logger):
        self.config_path = config_path
        self.config = self.DEFAULT_CONFIG.copy()
        self.logger = logger
        self.load()

    def load(self):
        self.logger.set_action("配置")
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self._deep_update(self.config, user_config)
                self.logger.success("已加载配置文件")
            else:
                self.save()
                self.logger.info("创建默认配置文件")
        except Exception as e:
            self.logger.error(f"加载失败：{str(e)}")
        finally:
            self.logger.clear_action()

    def save(self):
        self.logger.set_action("配置")
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.logger.info("配置已保存")
        except Exception as e:
            self.logger.error(f"保存失败：{str(e)}")
        finally:
            self.logger.clear_action()

    def _deep_update(self, target, source):
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and key in target
                and isinstance(target[key], dict)
            ):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def get_subject_info(self, subject_id):
        return self.config["subject_config"].get(
            str(subject_id), self.config["subject_config"]["default"]
        )

    def get_check_interval(self):
        return self.config.get("check_interval", 3600)


# ============================================================================
# 数据库连接池
# ============================================================================


class SQLiteConnectionPool:
    """
    线程安全的 SQLite 连接池，支持最小/最大连接数，空闲超时自动清理多余连接
    """

    def __init__(
        self,
        db_path: str,
        min_connections: int = 1,
        max_connections: int = 10,
        timeout: float = 30.0,
        idle_timeout: float = 600.0,
        check_interval: float = 60.0,
    ):
        self.db_path = db_path
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.timeout = timeout
        self.idle_timeout = idle_timeout

        self._idle_connections: queue.Queue = queue.Queue()
        self._active_count = 0
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        # 初始化最小连接数
        for _ in range(min_connections):
            conn = self._create_connection()
            self._idle_connections.put((conn, time.time()))
            self._active_count += 1

        self._cleaner_thread = None
        self._stop_cleaner = threading.Event()
        self._check_interval = check_interval
        self._start_cleaner()

    def _start_cleaner(self):
        def cleaner():
            while not self._stop_cleaner.wait(self._check_interval):
                self._clean_idle_connections()

        self._cleaner_thread = threading.Thread(target=cleaner, daemon=True)
        self._cleaner_thread.start()

    def _clean_idle_connections(self):
        now = time.time()
        to_keep = []
        while True:
            try:
                conn, last_used = self._idle_connections.get_nowait()
            except queue.Empty:
                break
            if (
                len(to_keep) + self._idle_connections.qsize() + 1
                <= self.min_connections
            ):
                to_keep.append((conn, last_used))
            else:
                if now - last_used < self.idle_timeout:
                    to_keep.append((conn, last_used))
                else:
                    self._close_connection(conn)
                    with self._lock:
                        self._active_count -= 1
        for item in to_keep:
            self._idle_connections.put(item)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_connection(self, conn: sqlite3.Connection):
        try:
            conn.close()
        except Exception:
            pass

    def _is_connection_valid(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def get_connection(self) -> sqlite3.Connection:
        deadline = time.time() + self.timeout
        with self._condition:
            while True:
                try:
                    conn, last_used = self._idle_connections.get_nowait()
                except queue.Empty:
                    if self._active_count < self.max_connections:
                        self._active_count += 1
                        return self._create_connection()
                else:
                    if self._is_connection_valid(conn):
                        return conn
                    else:
                        self._close_connection(conn)
                        with self._lock:
                            self._active_count -= 1
                        continue

                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"无法获取数据库连接，超时 {self.timeout} 秒")
                self._condition.wait(remaining)

    def return_connection(self, conn: sqlite3.Connection):
        if conn is None:
            return
        if self._is_connection_valid(conn):
            self._idle_connections.put((conn, time.time()))
        else:
            self._close_connection(conn)
            with self._lock:
                self._active_count -= 1
        with self._condition:
            self._condition.notify()

    def connection(self):
        return PooledConnection(self)

    def close_all(self):
        self._stop_cleaner.set()
        if self._cleaner_thread and self._cleaner_thread.is_alive():
            self._cleaner_thread.join(timeout=2)

        while True:
            try:
                conn, _ = self._idle_connections.get_nowait()
                self._close_connection(conn)
            except queue.Empty:
                break

        with self._lock:
            self._active_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


class PooledConnection:
    def __init__(self, pool: SQLiteConnectionPool):
        self.pool = pool
        self.conn = None

    def __enter__(self):
        self.conn = self.pool.get_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.pool.return_connection(self.conn)
            self.conn = None


# ============================================================================
# 数据管理
# ============================================================================


class DataManager:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.db_path = os.path.join(base_dir, "metadata.db")
        self.pool = SQLiteConnectionPool(
            db_path=self.db_path,
            min_connections=1,
            max_connections=10,
            idle_timeout=600,
            check_interval=3600,
        )

    # -------------------- 元数据批量操作 --------------------
    def batch_upsert_works_info(self, works_list: List[Dict[str, Any]]) -> None:
        if not works_list:
            return
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO works_info 
                    (uuid, work_name, subject_id, has_content, is_exam, start_at, end_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        (
                            w["uuid"],
                            w["work_name"],
                            w["subject_id"],
                            1 if w["has_content"] else 0,
                            1 if w["is_exam"] else 0,
                            w["start_at"],
                            w["end_at"],
                        )
                        for w in works_list
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def load_started_exams(self, timestamp) -> Set[str]:
        """返回 start_at 已到达（start_at <= timestamp）的待补充 URL 作业 uuid"""
        with self.pool.connection() as conn:
            cursor = conn.execute(
                "SELECT uuid FROM wait_url WHERE start_at <= ?", (timestamp,)
            )
            return {row["uuid"] for row in cursor.fetchall()}

    def add_wait_url_works(self, wait_list: List[Tuple[str, int]]) -> None:
        """登记等待补充 URL 的作业（uuid, start_at）"""
        if not wait_list:
            return
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO wait_url (uuid, start_at) VALUES (?, ?)",
                    wait_list,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def remove_wait_url_work(self, work_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM wait_url WHERE uuid = ?", (work_id,))
            conn.commit()

    def batch_save_work_details_meta(
        self, details_list: List[Tuple[str, str]]
    ) -> None:
        """仅登记作业详情的 URL（延迟到访问时再抓取正文）"""
        if not details_list:
            return
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO work_details (uuid, url, version)
                    VALUES (?, ?, ?)
                """,
                    [
                        (work_id, content_url, DETAIL_VERSION)
                        for work_id, content_url in details_list
                    ],
                )
                # URL 变更时作废旧详情，URL 未变则保留已抓取的详情
                conn.executemany(
                    """
                    UPDATE work_details
                    SET detail = CASE WHEN url = ? THEN detail ELSE NULL END,
                        url = ?,
                        version = ?
                    WHERE uuid = ?
                """,
                    [
                        (content_url, content_url, DETAIL_VERSION, work_id)
                        for work_id, content_url in details_list
                    ],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def save_work_detail(self, work_id: str, details: Any) -> bool:
        """保存抓取到的作业详情正文"""
        if isinstance(details, (dict, list)):
            detail = json.dumps(details, ensure_ascii=False)
        else:
            detail = details
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO work_details (uuid, version, detail)
                    VALUES (?, ?, ?)
                    ON CONFLICT(uuid) DO UPDATE SET
                        version = excluded.version,
                        detail = excluded.detail
                """,
                    (work_id, DETAIL_VERSION, detail),
                )
                conn.commit()
            return True
        except Exception as e:
            print(f"保存作业详情失败 {work_id}: {e}")
            return False

    def load_last_scan_time(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT scan_time FROM last_scan_time WHERE id = 1"
            ).fetchone()
            if row:
                return row["scan_time"]
            return 0

    def save_last_scan_time(self, scan_time: int) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO last_scan_time (id, scan_time) VALUES (1, ?)",
                (scan_time,),
            )
            conn.commit()

    # -------------------- 查询操作 --------------------
    def get_works_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        """date_str 为 YYYYMMDD，返回前端接口字段（work_id/start_time/upto_time）"""
        if len(date_str) != 8 or not date_str.isdigit():
            return []
        month_str = f"{date_str[:4]}-{date_str[4:6]}"
        day_str = date_str[6:8]
        with self.pool.connection() as conn:
            cursor = conn.execute(
                """
                SELECT uuid AS work_id, work_name, subject_id,
                       start_at AS start_time, end_at AS upto_time,
                       is_exam, has_content
                FROM works_info
                WHERE month_str = ? AND date_str = ?
                ORDER BY start_at DESC
            """,
                (month_str, day_str),
            )
            rows = cursor.fetchall()
            return [
                {
                    "work_id": row["work_id"],
                    "work_name": row["work_name"],
                    "subject_id": row["subject_id"],
                    "start_time": row["start_time"],
                    "upto_time": row["upto_time"],
                    "is_exam": bool(row["is_exam"]),
                    "has_content": bool(row["has_content"]),
                }
                for row in rows
            ]

    def get_works_counts_by_months(
        self, months: List[str]
    ) -> Dict[str, Dict[str, int]]:
        """months 为 YYYYMM 列表，返回 {YYYYMM: {YYYY-MM-DD: count}}"""
        if not months:
            return {}
        query_months = []
        month_map = {}
        for month in months:
            if len(month) != 6 or not month.isdigit():
                continue
            query_month = f"{month[:4]}-{month[4:6]}"
            query_months.append(query_month)
            month_map[query_month] = month
        result = {month: {} for month in months}
        if not query_months:
            return result
        placeholders = ",".join(["?"] * len(query_months))
        sql = f"""
            SELECT month_str, date_str, COUNT(*) as cnt
            FROM works_info
            WHERE month_str IN ({placeholders})
            GROUP BY month_str, date_str
        """
        with self.pool.connection() as conn:
            cursor = conn.execute(sql, query_months)
            rows = cursor.fetchall()
        for row in rows:
            month = month_map.get(row["month_str"])
            if not month:
                continue
            formatted = f'{row["month_str"]}-{row["date_str"]}'
            result[month][formatted] = row["cnt"]
        return result

    def get_total_works_count(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM works_info").fetchone()
            return row["cnt"] if row else 0

    def get_work_meta(self, work_id: str) -> Optional[Dict[str, Any]]:
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                SELECT uuid AS work_id, work_name, subject_id,
                       start_at AS start_time, end_at AS upto_time,
                       is_exam, has_content
                FROM works_info
                WHERE uuid = ?
            """,
                (work_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "work_id": row["work_id"],
                "work_name": row["work_name"],
                "subject_id": row["subject_id"],
                "start_time": row["start_time"],
                "upto_time": row["upto_time"],
                "is_exam": bool(row["is_exam"]),
                "has_content": bool(row["has_content"]),
            }

    def get_work_detail(self, work_id: str) -> Optional[Dict[str, Any]]:
        """返回 {url, version, questions}，questions 为 None 表示尚未抓取"""
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT url, version, detail FROM work_details WHERE uuid = ?",
                (work_id,),
            ).fetchone()
            if not row:
                return None
            detail = row["detail"]
            return {
                "url": row["url"],
                "version": row["version"],
                "questions": json.loads(detail) if detail else None,
            }

    # -------------------- 鉴权令牌管理 --------------------
    def load_permanent_tokens(self) -> Dict[str, Dict]:
        """加载所有永久令牌"""
        with self.pool.connection() as conn:
            cursor = conn.execute("SELECT token, created_at FROM permanent_tokens")
            tokens = {}
            for row in cursor.fetchall():
                tokens[row["token"]] = None
            return tokens

    def save_permanent_token(self, token: str) -> None:
        """保存永久令牌"""
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO permanent_tokens (token, created_at) VALUES (?, ?)",
                (token, time.time()),
            )
            conn.commit()

    def delete_permanent_token(self, token: str) -> None:
        """删除永久令牌（可选，用于撤销）"""
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM permanent_tokens WHERE token = ?", (token,))
            conn.commit()

    def close(self):
        self.pool.close_all()


# ============================================================================
# 扫描提取作业
# ============================================================================


class DatabaseExtractor:
    def __init__(
        self, db_path, file_base_dir, data_manager: DataManager, logger: Logger
    ):
        self.db_path = db_path
        self.file_base_dir = file_base_dir
        self.data_manager = data_manager
        self.logger = logger
        self.question_type_mapping = {}
        self._load_question_types()

    def _load_question_types(self):
        self.logger.set_action("题目类型")
        try:
            if not os.path.exists(self.db_path):
                self.logger.warning(f"数据库文件不存在：{self.db_path}")
                return
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT _id, NAME FROM QuestionUserType")
                rows = cursor.fetchall()
                for row_id, name in rows:
                    self.question_type_mapping[row_id] = name
                self.logger.info(f"已加载 {len(self.question_type_mapping)} 种题目类型")
            finally:
                conn.close()
        except sqlite3.Error as e:
            self.logger.error(f"读取题目类型失败：{str(e)}")
        except Exception as e:
            self.logger.error(f"加载题目类型映射失败：{str(e)}")
        finally:
            self.logger.clear_action()

    def extract_work_info(self):
        """
        扫描源数据库，返回 (all_works, details_list, wait_list, resolved_wait)

        - all_works: 本次发现的作业元数据
        - details_list: [(uuid, content_url)] 需要延迟抓取详情的作业
        - wait_list: [(uuid, start_at)] 尚无 URL、等待考试开始后重试的作业
        - resolved_wait: 已获得 URL 或已过期、需要从等待表移除的 uuid
        """
        empty = ([], [], [], [])
        try:
            if not os.path.exists(self.db_path):
                self.logger.error(f"数据库文件不存在：{self.db_path}")
                return empty
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                cursor = conn.cursor()
                now_ms = int(time.time() * 1000)
                last_scan_ts = self.data_manager.load_last_scan_time()
                started_exams = self.data_manager.load_started_exams(now_ms)

                all_works = []
                details_list = []
                wait_list = []
                resolved_wait = []
                seen = set()

                columns = (
                    "WORK_ID, CONTENT_URL, NAME, SUBJECT, "
                    "CREATE_TIME, UPTO_TIME, START_TIME, END_TIME, UPDATE_TIME"
                )

                cursor.execute(
                    f"""
                    SELECT {columns}
                    FROM xh_yzy_student_work_list 
                    WHERE UPDATE_TIME > ?
                    """,
                    (last_scan_ts,),
                )
                rows = list(cursor.fetchall())
                for row in rows:
                    seen.add(row[0])

                if started_exams:
                    placeholders = ",".join(["?"] * len(started_exams))
                    cursor.execute(
                        f"""
                        SELECT {columns}
                        FROM xh_yzy_student_work_list 
                        WHERE WORK_ID IN ({placeholders})
                        """,
                        tuple(started_exams),
                    )
                    for row in cursor.fetchall():
                        if row[0] not in seen:
                            rows.append(row)
                            seen.add(row[0])

                self.logger.info(f"找到{len(rows)}条作业记录")

                for row in rows:
                    try:
                        (
                            work_id,
                            content_url,
                            work_name,
                            subject_id,
                            create_time,
                            upto_time,
                            start_time,
                            end_time,
                            update_time,
                        ) = row

                        has_url = bool(content_url)
                        is_exam = (
                            upto_time == 0 and start_time != 0 and end_time != 0
                        )
                        expired = bool(end_time) and now_ms > end_time

                        if work_id in started_exams:
                            if has_url:
                                resolved_wait.append(work_id)
                                self.logger.info(
                                    f"{work_name} (科目: {subject_id}) 新增URL"
                                )
                            elif expired:
                                resolved_wait.append(work_id)
                                self.logger.info(f"移除过期无内容作业: {work_name}")
                                continue

                        if has_url:
                            details_list.append((work_id, content_url))
                        elif is_exam and not expired:
                            wait_list.append(
                                (work_id, start_time if start_time else now_ms)
                            )

                        all_works.append(
                            {
                                "uuid": work_id,
                                "work_name": work_name,
                                "subject_id": subject_id,
                                "has_content": has_url,
                                "is_exam": is_exam,
                                "start_at": start_time if is_exam else create_time,
                                "end_at": end_time if is_exam else upto_time,
                            }
                        )
                        self.logger.info(
                            f"发现{'考试' if is_exam else '作业'} {work_name} (科目: {subject_id})"
                        )
                    except Exception as e:
                        self.logger.error(f"解析作业记录失败：{str(e)}")
                        continue

                self.logger.success(f"成功提取{len(all_works)}个作业信息")
                return all_works, details_list, wait_list, resolved_wait
            finally:
                conn.close()
        except sqlite3.Error as e:
            self.logger.error(f"SQLite错误：{str(e)}")
            return empty
        except Exception as e:
            self.logger.error(f"提取失败：{str(e)}")
            return empty

    def get_question_type_name(self, type_id):
        return self.question_type_mapping.get(type_id, f"未知类型({type_id})")


class WorkFileProcessor:
    def __init__(self, logger: Logger, db_extractor: DatabaseExtractor):
        self.logger = logger
        self.db_extractor = db_extractor

    def process(self, content_url: str):
        """按需抓取并解析作业详情，返回题目列表"""
        if not content_url:
            return None

        self.logger.info(f"开始抓取作业详情：{content_url}")
        try:
            req = urllib.request.Request(content_url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.logger.error(f"无效JSON：{content_url}")
            return None
        except Exception as e:
            self.logger.error(f"请求失败：{str(e)}")
            return None

        questions = self._extract_work_details(data)
        self.logger.success("已提取作业详情")
        return questions

    def _extract_work_details(self, data):
        questions = []

        answers_by_question = {}
        for answer in data.get("questionAnswers", []):
            qid = answer["questionId"]
            answers_by_question.setdefault(qid, []).append(answer)

        question_map = {
            q["questionId"]: q for q in data.get("questionPoolContentInfos", [])
        }
        parent_to_children = {}
        for question in data.get("questionPoolContentInfos", []):
            parent_id = question.get("parentQuestionId", "0")
            if parent_id != "0" and parent_id in question_map:
                parent_to_children.setdefault(parent_id, []).append(question)

        top_level_questions = [
            q
            for q in data.get("questionPoolContentInfos", [])
            if q.get("parentQuestionId", "0") == "0"
            or q.get("parentQuestionId") not in question_map
        ]

        qn = 0
        for question in top_level_questions:
            qid = question["questionId"]
            question_user_type = question.get("questionUserType", 0)
            question_type_name = self.db_extractor.get_question_type_name(
                question_user_type
            )

            if question_user_type == 0:
                divider_question = {
                    "question_id": qid,
                    "question_type": "分割线",
                    "stem_content": self._process_html_content(
                        question.get("stemContent", "")
                    ),
                    "explain_content": "",
                    "has_children": False,
                    "answers": [],
                    "sub_questions": [],
                }
                questions.append(divider_question)
                continue

            qn += 1
            answers = answers_by_question.get(qid, [])
            stem_content = self._process_html_content(question.get("stemContent", ""))
            explain_content = self._process_html_content(
                question.get("explainContent", "")
            )
            has_children = qid in parent_to_children

            question_data = {
                "question_id": qid,
                "question_number": qn,
                "question_type": question_type_name,
                "stem_content": stem_content,
                "explain_content": explain_content,
                "has_children": has_children,
                "answers": [],
                "sub_questions": [],
            }

            for answer in answers:
                question_data["answers"].append(
                    self._process_html_content(answer["answerContent"])
                )

            if has_children:
                sub_questions = parent_to_children[qid]
                sub_qn = 1
                for sub_question in sub_questions:
                    sub_qid = sub_question["questionId"]
                    sub_question_user_type = sub_question.get("questionUserType", 0)
                    sub_question_type_name = self.db_extractor.get_question_type_name(
                        sub_question_user_type
                    )
                    sub_answers = answers_by_question.get(sub_qid, [])
                    sub_stem_content = self._process_html_content(
                        sub_question.get("stemContent", "")
                    )
                    sub_explain_content = self._process_html_content(
                        sub_question.get("explainContent", "")
                    )

                    sub_question_data = {
                        "question_id": sub_qid,
                        "question_number": sub_qn,
                        "question_type": sub_question_type_name,
                        "stem_content": sub_stem_content,
                        "explain_content": sub_explain_content,
                        "answers": [],
                    }
                    for answer in sub_answers:
                        sub_question_data["answers"].append(
                            self._process_html_content(answer["answerContent"])
                        )
                    question_data["sub_questions"].append(sub_question_data)
                    sub_qn += 1

            questions.append(question_data)

        return questions

    def _process_html_content(self, text):
        if not text:
            return ""
        text = html.unescape(text)
        text = re.sub(
            r'<span\s+class="mathquill-embedded-latex"\s*>(.*?)</span>',
            r"\(\1\)",
            text,
            flags=re.DOTALL,
        )
        return text


class Scanner:
    def __init__(
        self,
        config_manager: ConfigManager,
        data_manager: DataManager,
        db_extractor: DatabaseExtractor,
        work_processor: WorkFileProcessor,
        logger: Logger,
    ):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.db_extractor = db_extractor
        self.work_processor = work_processor
        self.logger = logger
        self.scan_lock = threading.Lock()
        self.last_scan_time = 0

    def perform_scan(self):
        if not self.scan_lock.acquire(blocking=False):
            self.logger.warning("扫描任务正在进行中，跳过")
            return
        self.logger.info("开始扫描作业...")

        try:
            self.logger.set_action("提取数据")
            works, details_list, wait_list, resolved_wait = (
                self.db_extractor.extract_work_info()
            )

            # 批量写入数据库（详情延迟到访问时抓取）
            self.logger.set_action("保存数据")
            if works:
                self.data_manager.batch_upsert_works_info(works)
                self.logger.info(f"已更新 {len(works)} 条作业元数据")
            if details_list:
                self.data_manager.batch_save_work_details_meta(details_list)
                self.logger.info(f"已登记 {len(details_list)} 个待抓取详情")
            for work_id in resolved_wait:
                self.data_manager.remove_wait_url_work(work_id)
            if wait_list:
                self.data_manager.add_wait_url_works(wait_list)
                self.logger.info(f"已登记 {len(wait_list)} 个待补充URL作业")

            self.data_manager.save_last_scan_time(int(time.time() * 1000) - 10)
            self.logger.success("扫描完成")
            self.last_scan_time = int(time.time() - 10)
        except Exception as e:
            self.logger.error(f"执行失败：{str(e)}")
        finally:
            self.scan_lock.release()
            self.logger.clear_action()

    def start_scan_loop(self):
        self.logger.set_action("扫描循环")
        while True:
            try:
                if not self.scan_lock.locked():
                    self.perform_scan()
                time.sleep(self.config_manager.get_check_interval())
            except Exception as e:
                self.logger.error(f"错误：{str(e)}")
                time.sleep(60)


# ============================================================================
# 网络服务模块
# ============================================================================


class Author:
    def __init__(self, logger: Logger, data_manager: DataManager) -> None:
        self.logger = logger
        self.data_manager = data_manager

        self.auth_lock = threading.RLock()
        self.verification_codes = {}
        self.tokens = {}

        self.tokens.update(self.data_manager.load_permanent_tokens())

    def auth(self, token):
        with self.auth_lock:
            if token not in self.tokens:
                return False
            if self.tokens[token] is None:
                return True
            time_now = time.time()
            if self.tokens[token] > time_now:
                self.tokens[token] = time_now + EXPIRE_TEMP_TOKEN
                return True
            else:
                del self.tokens[token]
                return False

    def create_code(self, permanent: bool, info: str):
        code = self._generate_verification_code()
        code_id = str(uuid.uuid4())
        expire = time.time() + EXPIRE_VERIFY
        with self.auth_lock:
            self.verification_codes[code_id] = (code, permanent, expire)
        self.logger.info(
            f"\t令牌申请：{info}\n\t类型：{'永久' if permanent else '临时'}  验证码：{code}"
        )
        return code_id

    def verify(self, code_id, verify_code):
        with self.auth_lock:
            if code_id not in self.verification_codes:
                return False
            if self.verification_codes[code_id][2] < time.time():
                del self.verification_codes[code_id]
                return False
            if verify_code != self.verification_codes[code_id][0]:
                return False
            token = secrets.token_urlsafe()
            if self.verification_codes[code_id][1]:
                self.tokens[token] = None
                self.data_manager.save_permanent_token(token)
                self.logger.info(f"创建了一个永久令牌 {token}")
            else:
                self.tokens[token] = time.time() + EXPIRE_TEMP_TOKEN
                self.logger.info(f"创建了一个临时令牌 {token}")
            del self.verification_codes[code_id]
            return token

    def _clean(self):
        now = time.time()
        with self.auth_lock:
            pass

    def _generate_verification_code(self) -> str:
        """生成验证码"""
        return secrets.token_hex(3).upper()


class WebService:
    def __init__(
        self,
        scanner: Scanner,
        config_manager: ConfigManager,
        data_manager: DataManager,
        author: Author,
    ):
        self.scanner = scanner
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.author = author
        self.app = Flask(__name__)
        self.app.config["TEMPLATES_AUTO_RELOAD"] = True

        self._setup_routes()

    def _require_auth(self, f):
        """鉴权装饰器"""

        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_header = request.headers.get("Authorization")
            if not auth_header:
                return jsonify({"error": "缺少认证头"}), 401

            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                return jsonify({"error": "认证头格式错误，应使用 Bearer <token>"}), 401

            token = parts[1]
            if not self.author.auth(token):
                return jsonify({"error": "无效的令牌"}), 401

            return f(*args, **kwargs)

        return decorated_function

    def _setup_routes(self):
        # -------------------- 鉴权API --------------------
        @self.app.route("/api/auth/code", methods=["GET"])
        def get_auth_code():
            """获取验证码（2分钟有效）"""
            code_type = request.args.get("type", "temp")
            if code_type == "temp":
                permanent = False
            elif code_type == "permanent":
                permanent = True
            else:
                return jsonify({"error": "类型必须是 temp 或 permanent"}), 400

            code_id = self.author.create_code(
                permanent, f"请求IP {request.remote_addr}"
            )
            return jsonify({"code_id": code_id, "expires_in": EXPIRE_VERIFY})

        @self.app.route("/api/auth/verify", methods=["POST"])
        def verify_code():
            """验证验证码并返回令牌"""
            data = request.get_json()
            if not data:
                return jsonify({"error": "需要JSON数据"}), 400

            code_id = data.get("code_id")
            code_str = data.get("code")
            if not code_id or not code_str:
                return jsonify({"error": "缺少 code_id 或 code"}), 400

            token = self.author.verify(code_id, code_str)
            if not token:
                return jsonify({"error": "验证码错误"}), 400
            return jsonify({"token": token})

        # -------------------- 原有页面路由 --------------------
        @self.app.route("/")
        def main_page():
            return render_template("main_page.html")

        @self.app.route("/work/<work_id>")
        def work_page(work_id):
            return render_template("work_page.html", work_id=work_id)

        # -------------------- 数据API（部分需要鉴权）--------------------
        @self.app.route("/api/work/<work_id>")
        def get_work_details(work_id):
            work_meta = self.data_manager.get_work_meta(work_id)
            if not work_meta:
                return jsonify({"error": "作业不存在"}), 404

            detail = self.data_manager.get_work_detail(work_id)
            questions = detail.get("questions") if detail else None

            # 延迟处理：首次访问时才抓取正文
            if questions is None:
                if not detail or not detail.get("url"):
                    return jsonify({"error": "该作业暂无内容"}), 404
                questions = self.scanner.work_processor.process(detail["url"])
                if questions is None:
                    return jsonify({"error": "获取作业详情失败"}), 502
                self.data_manager.save_work_detail(work_id, questions)

            result = dict(work_meta)
            result["questions"] = questions
            result["subject_info"] = self.config_manager.get_subject_info(
                work_meta["subject_id"]
            )
            return jsonify(result)

        @self.app.route("/api/works")
        def get_works():
            date_param = request.args.get("date", "")
            if not date_param:
                return jsonify([])
            search_date = date_param.replace("-", "")
            works = self.data_manager.get_works_by_date(search_date)
            return jsonify(works)

        @self.app.route("/api/download/html")
        def download_work():
            return jsonify({}), 501

        @self.app.route("/api/calendar")
        def get_calendar_data():
            months_param = request.args.get("months", "")
            months = months_param.split(",") if months_param else []
            data = self.data_manager.get_works_counts_by_months(months)
            return jsonify(data)

        @self.app.route("/api/scan", methods=["POST"])
        # @self._require_auth
        def trigger_scan():
            if self.scanner.scan_lock.locked():
                return jsonify({"status": "error", "message": "扫描正在进行中"})
            threading.Thread(target=self.scanner.perform_scan, daemon=True).start()
            return jsonify({"status": "success", "message": "扫描已开始"})

        @self.app.route("/api/config")
        def get_config():
            return jsonify(self.config_manager.config)

        @self.app.route("/api/config/reload", methods=["POST"])
        # @self._require_auth
        def reload_config():
            self.config_manager.load()
            return jsonify({"status": "success", "message": "配置已重新加载"})

        @self.app.route("/api/status")
        def get_status():
            status = {
                "last_scan_time": self.scanner.last_scan_time,
                "total_works": self.data_manager.get_total_works_count(),
                "scan_in_progress": self.scanner.scan_lock.locked(),
            }
            return jsonify(status)

    def run(self, host="0.0.0.0", port=8001):
        self.app.run(host=host, port=port, debug=False)


# ============================================================================
# 主程序
# ============================================================================
CONFIG_FILE = "/storage/emulated/0/1/program/works/config.json"
DATABASE_PATH = (
    "/storage/emulated/0/xuehai/5210/databases/com.xh.acldstu/1364978/xh_yunzuoye.db"
)
FILE_BASE_DIR = "/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/"
OUTPUT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DETAIL_VERSION = 2
EXPIRE_TEMP_TOKEN = 900
EXPIRE_VERIFY = 120


def main():
    logger = Logger()
    logger.set_action("系统初始化")

    config_manager = ConfigManager(CONFIG_FILE, logger)
    data_manager = DataManager(OUTPUT_BASE_DIR)
    db_extractor = DatabaseExtractor(DATABASE_PATH, FILE_BASE_DIR, data_manager, logger)
    work_processor = WorkFileProcessor(logger, db_extractor)
    scanner = Scanner(
        config_manager, data_manager, db_extractor, work_processor, logger
    )
    author = Author(logger, data_manager)
    web_service = WebService(scanner, config_manager, data_manager, author)

    logger.success("系统初始化完成")
    logger.clear_action()

    atexit.register(data_manager.close)

    scan_thread = threading.Thread(target=scanner.start_scan_loop, daemon=True)
    scan_thread.start()

    print(
        f"{Logger.Colors.BOLD}{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ===== 自动答案提取系统 ====={Logger.Colors.RESET}"
    )
    print(
        f"{Logger.Colors.SUCCESS}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 服务器启动，地址：http://localhost:8001{Logger.Colors.RESET}"
    )
    print(
        f"{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 检查间隔：{config_manager.get_check_interval()}秒{Logger.Colors.RESET}"
    )

    web_service.run()


if __name__ == "__main__":
    main()
