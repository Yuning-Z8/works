#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动答案提取系统 v8
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
from datetime import datetime, timedelta
from typing import Any, Dict, Set, List, Tuple, Optional
from flask import Flask, render_template, jsonify, request, send_from_directory


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
        self.current_action = ""
        if debug:
            self.debug = self._debug
        else:
            self.debug = lambda message: None

    def set_action(self, action):
        self.current_action = action

    def clear_action(self):
        self.current_action = ""

    def _format_message(self, level, message):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        level_color = getattr(self.Colors, level.upper(), self.Colors.INFO)
        if self.current_action:
            return f"{level_color}[{timestamp}] [{self.current_action}] {message}{self.Colors.RESET}"
        return f"{level_color}[{timestamp}] {message}{self.Colors.RESET}"

    def info(self, message):
        print(self._format_message("INFO", message))

    def success(self, message):
        print(self._format_message("SUCCESS", message))

    def warning(self, message):
        print(self._format_message("WARNING", message))

    def error(self, message):
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
            "default": {"name": "未知", "color": "#A0A0A0", "short": "未"}
        },
        "check_interval": 3600
    }

    def __init__(self, config_path, logger: Logger):
        self.config_path = config_path
        self.config = self.DEFAULT_CONFIG.copy()
        self.logger = logger
        self.load()

    def load(self):
        self.logger.set_action("配置")
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
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
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self.logger.info("配置已保存")
        except Exception as e:
            self.logger.error(f"保存失败：{str(e)}")
        finally:
            self.logger.clear_action()

    def _deep_update(self, target, source):
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def get_subject_info(self, subject_id):
        return self.config['subject_config'].get(str(subject_id),
                                                self.config['subject_config']["default"])

    def get_check_interval(self):
        return self.config.get('check_interval', 3600)


# ============================================================================
# 数据库连接池
# ============================================================================

class SQLiteConnectionPool:
    """
    线程安全的 SQLite 连接池，支持最小/最大连接数，空闲超时自动清理多余连接
    """

    def __init__(self, db_path: str, min_connections: int = 1, max_connections: int = 10,
                 timeout: float = 30.0, idle_timeout: float = 600.0,
                 check_interval: float = 60.0):
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
            if len(to_keep) + self._idle_connections.qsize() + 1 <= self.min_connections:
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
# 数据管理（仅操作，不创建表）
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
            check_interval=60
        )

    # -------------------- 元数据批量操作 --------------------
    def batch_upsert_works_info(self, works_list: List[Dict[str, Any]]) -> None:
        if not works_list:
            return
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.executemany("""
                    INSERT OR REPLACE INTO works_info 
                    (work_id, work_name, subject_id, start_time, upto_time, is_exam, has_content)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [(
                    w['work_id'],
                    w['work_name'],
                    w['subject_id'],
                    w['start_time'],
                    w['upto_time'],
                    1 if w['is_exam'] else 0,
                    1 if w['has_content'] else 0
                ) for w in works_list])
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def batch_save_work_details(self, details_list: List[Tuple[str, Dict]]) -> None:
        if not details_list:
            return
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.executemany("""
                    INSERT OR REPLACE INTO work_details (work_id, version, detail_json)
                    VALUES (?, ?, ?)
                """, [(
                    work_id,
                    DETAIL_VERSION,
                    json.dumps(details, ensure_ascii=False)
                ) for work_id, details in details_list])
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def load_no_content_url_records(self) -> Set[str]:
        with self.pool.connection() as conn:
            cursor = conn.execute("SELECT work_id FROM no_content_url")
            return {row['work_id'] for row in cursor.fetchall()}

    def batch_update_no_content_url(self, current_set: Set[str]) -> None:
        """用当前集合完全替换 no_content_url 表"""
        with self.pool.connection() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM no_content_url")
                if current_set:
                    conn.executemany("INSERT INTO no_content_url (work_id) VALUES (?)",
                                     [(wid,) for wid in current_set])
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def load_last_scan_time(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT scan_time FROM last_scan_time WHERE id = 1").fetchone()
            if row:
                return row['scan_time']
            return 1765400000000  # 2025-12-10 00:00:00

    def save_last_scan_time(self, scan_time: int) -> None:
        with self.pool.connection() as conn:
            conn.execute("INSERT OR REPLACE INTO last_scan_time (id, scan_time) VALUES (1, ?)",
                         (scan_time,))
            conn.commit()

    # -------------------- 查询操作 --------------------
    def get_works_by_date(self, date_str: str) -> List[Dict[str, Any]]:
        with self.pool.connection() as conn:
            cursor = conn.execute("""
                SELECT work_id, work_name, subject_id, start_time, upto_time, is_exam, has_content
                FROM works_info
                WHERE work_date = ?
                ORDER BY start_time DESC
            """, (date_str,))
            rows = cursor.fetchall()
            return [{
                'work_id': row['work_id'],
                'work_name': row['work_name'],
                'subject_id': row['subject_id'],
                'start_time': row['start_time'],
                'upto_time': row['upto_time'],
                'is_exam': bool(row['is_exam']),
                'has_content': bool(row['has_content']),
            } for row in rows]

    def get_works_counts_by_months(self, months: List[str]) -> Dict[str, Dict[str, int]]:
        if not months:
            return {}
        placeholders = ','.join(['?'] * len(months))
        sql = f"""
            SELECT month_str, work_date, COUNT(*) as cnt
            FROM works_info
            WHERE month_str IN ({placeholders})
            GROUP BY month_str, work_date
        """
        with self.pool.connection() as conn:
            cursor = conn.execute(sql, months)
            rows = cursor.fetchall()
        result = {month: {} for month in months}
        for row in rows:
            month_str = row['month_str']
            work_date = row['work_date']
            formatted = f"{work_date[:4]}-{work_date[4:6]}-{work_date[6:8]}"
            result[month_str][formatted] = row['cnt']
        return result

    def get_total_works_count(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM works_info").fetchone()
            return row['cnt'] if row else 0

    def load_work_details(self, work_id: str) -> Optional[Dict]:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT version, detail_json FROM work_details WHERE work_id = ?",
                               (work_id,)).fetchone()
            if not row:
                return None
            version = row['version']
            details = json.loads(row['detail_json'])
            migrated = self._migrate_work_details(details, version)
            if migrated.get('version') != version:
                self.save_work_details(work_id, migrated)  # 回写迁移后的版本
                return migrated
            return details

    @staticmethod
    def _migrate_work_details(details: Dict, current_version: int) -> Dict:
        LATEST_VERSION = 2
        if current_version >= LATEST_VERSION:
            return details
        if current_version == 1:
            details['version'] = 2
            if 'detail' not in details:
                details['detail'] = {}
        return details

    def save_work_details(self, work_id: str, details: Dict) -> bool:
        if 'version' not in details:
            details['version'] = 1
        detail_json = json.dumps(details, ensure_ascii=False)
        try:
            with self.pool.connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO work_details (work_id, version, detail_json)
                    VALUES (?, ?, ?)
                """, (work_id, details['version'], detail_json))
                conn.commit()
            return True
        except Exception as e:
            print(f"保存作业详情失败 {work_id}: {e}")
            return False

    def close(self):
        self.pool.close_all()


# ============================================================================
# 作业处理模块
# ============================================================================

class DatabaseExtractor:
    def __init__(self, db_path, file_base_dir, data_manager: DataManager, logger: Logger):
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
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
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

    def extract_work_info(self) -> List[dict]:
        self.logger.set_action("数据库")
        try:
            if not os.path.exists(self.db_path):
                self.logger.error(f"数据库文件不存在：{self.db_path}")
                return []
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            no_url_set = self.data_manager.load_no_content_url_records()
            last_scan_ts = self.data_manager.load_last_scan_time()
            latest_scan_ts = last_scan_ts
            try:
                cursor = conn.cursor()
                all_works = []
                now_ms = int(time.time() * 1000)

                if no_url_set:
                    placeholders = ','.join(['?'] * len(no_url_set))
                    query = f"""
                    SELECT WORK_ID, CONTENT_URL, NAME, SUBJECT,
                           CREATE_TIME, UPTO_TIME, START_TIME, END_TIME, UPDATE_TIME
                    FROM xh_yzy_student_work_list 
                    WHERE UPDATE_TIME > ? OR WORK_ID IN ({placeholders})
                    """
                    params = (last_scan_ts,) + tuple(no_url_set)
                else:
                    query = """
                    SELECT WORK_ID, CONTENT_URL, NAME, SUBJECT,
                           CREATE_TIME, UPTO_TIME, START_TIME, END_TIME, UPDATE_TIME
                    FROM xh_yzy_student_work_list 
                    WHERE UPDATE_TIME > ?
                    """
                    params = (last_scan_ts,)

                cursor.execute(query, params)
                rows = cursor.fetchall()
                self.logger.info(f"找到{len(rows)}条作业记录")

                for row in rows:
                    try:
                        work_id, content_url, work_name, subject_id, \
                            create_time, upto_time, start_time, end_time, update_time = row

                        if work_id in no_url_set:
                            if content_url:
                                no_url_set.remove(work_id)
                                self.logger.info(f"{work_name} (科目: {subject_id}) 新增URL")
                            elif now_ms > max(upto_time, end_time):
                                no_url_set.remove(work_id)
                                self.logger.info(f"移除过期无内容作业: {work_name}")
                                continue
                            else:
                                continue

                        if not content_url:
                            if now_ms > max(upto_time, end_time):
                                continue
                            no_url_set.add(work_id)
                            file_name = 'no_file'
                            no_url = True
                        else:
                            file_name = content_url[-36:-4]
                            no_url = False

                        is_exam = upto_time == 0 and start_time != 0 and end_time != 0
                        work_info = {
                            'work_id': work_id,
                            'no_url': no_url,
                            'file_name': file_name,
                            'month_str': datetime.fromtimestamp(create_time // 1000).strftime("%Y%m"),
                            'work_name': work_name,
                            'subject_id': subject_id,
                            'is_exam': is_exam,
                            'start_time': start_time if is_exam else create_time,
                            'upto_time': end_time if is_exam else upto_time
                        }
                        all_works.append(work_info)
                        self.logger.info(f"发现{'无URL' if no_url else ''}{'考试' if is_exam else '作业'} {work_name} (科目: {subject_id})")

                        if update_time > latest_scan_ts:
                            latest_scan_ts = update_time
                    except Exception as e:
                        self.logger.error(f"解析作业记录失败：{str(e)}")
                        continue

                self.logger.success(f"成功提取{len(all_works)}个作业信息")
                return all_works
            finally:
                conn.close()
                self.data_manager.batch_update_no_content_url(no_url_set)
                self.data_manager.save_last_scan_time(latest_scan_ts)
        except sqlite3.Error as e:
            self.logger.error(f"SQLite错误：{str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"提取失败：{str(e)}")
            return []
        finally:
            self.logger.clear_action()

    def get_question_type_name(self, type_id):
        return self.question_type_mapping.get(type_id, f"未知类型({type_id})")


class WorkFileProcessor:
    def __init__(self, file_base_dir, logger: Logger, db_extractor: DatabaseExtractor):
        self.file_base_dir = file_base_dir
        self.logger = logger
        self.db_extractor = db_extractor

    def process(self, work_info: dict):
        self.logger.set_action("文件处理")
        file_path = os.path.join(self.file_base_dir, work_info['month_str'], work_info['file_name']+'.txt')
        if not os.path.exists(file_path):
            self.logger.warning(f"文件不存在：{file_path}")
            self.logger.clear_action()
            return None

        self.logger.info(f"开始处理 {work_info['work_name']}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            self.logger.error(f"无效JSON：{file_path}")
            self.logger.clear_action()
            return None
        except Exception as e:
            self.logger.error(f"读取失败：{str(e)}")
            self.logger.clear_action()
            return None

        work_details = self._extract_work_details(data, work_info)
        self.logger.success(f"提取作业详情：{work_info['work_name']}")
        self.logger.clear_action()
        return work_details

    def _extract_work_details(self, data, work_info):
        work_details = {
            'work_name': work_info['work_name'],
            'subject_id': work_info['subject_id'],
            'upto_time': work_info['upto_time'],
            'is_exam': work_info['is_exam'],
            'start_time': work_info['start_time'],
            'questions': []
        }

        answers_by_question = {}
        for answer in data.get('questionAnswers', []):
            qid = answer['questionId']
            answers_by_question.setdefault(qid, []).append(answer)

        question_map = {q['questionId']: q for q in data.get('questionPoolContentInfos', [])}
        parent_to_children = {}
        for question in data.get('questionPoolContentInfos', []):
            parent_id = question.get('parentQuestionId', '0')
            if parent_id != "0" and parent_id in question_map:
                parent_to_children.setdefault(parent_id, []).append(question)

        top_level_questions = [
            q for q in data.get('questionPoolContentInfos', [])
            if q.get('parentQuestionId', '0') == "0" or q.get('parentQuestionId') not in question_map
        ]

        qn = 0
        for question in top_level_questions:
            qid = question['questionId']
            question_user_type = question.get('questionUserType', 0)
            question_type_name = self.db_extractor.get_question_type_name(question_user_type)

            if question_user_type == 0:
                divider_question = {
                    'question_id': qid,
                    'question_type': '分割线',
                    'stem_content': self._process_html_content(question.get('stemContent', '')),
                    'explain_content': '',
                    'has_children': False,
                    'answers': [],
                    'sub_questions': []
                }
                work_details['questions'].append(divider_question)
                continue

            qn += 1
            answers = answers_by_question.get(qid, [])
            stem_content = self._process_html_content(question.get('stemContent', ''))
            explain_content = self._process_html_content(question.get('explainContent', ''))
            has_children = qid in parent_to_children

            question_data = {
                'question_id': qid,
                'question_number': qn,
                'question_type': question_type_name,
                'stem_content': stem_content,
                'explain_content': explain_content,
                'has_children': has_children,
                'answers': [],
                'sub_questions': []
            }

            for answer in answers:
                question_data['answers'].append(self._process_html_content(answer['answerContent']))

            if has_children:
                sub_questions = parent_to_children[qid]
                sub_qn = 1
                for sub_question in sub_questions:
                    sub_qid = sub_question['questionId']
                    sub_question_user_type = sub_question.get('questionUserType', 0)
                    sub_question_type_name = self.db_extractor.get_question_type_name(sub_question_user_type)
                    sub_answers = answers_by_question.get(sub_qid, [])
                    sub_stem_content = self._process_html_content(sub_question.get('stemContent', ''))
                    sub_explain_content = self._process_html_content(sub_question.get('explainContent', ''))

                    sub_question_data = {
                        'question_id': sub_qid,
                        'question_number': sub_qn,
                        'question_type': sub_question_type_name,
                        'stem_content': sub_stem_content,
                        'explain_content': sub_explain_content,
                        'answers': []
                    }
                    for answer in sub_answers:
                        sub_question_data['answers'].append(self._process_html_content(answer['answerContent']))
                    question_data['sub_questions'].append(sub_question_data)
                    sub_qn += 1

            work_details['questions'].append(question_data)

        return work_details

    def _process_html_content(self, text):
        if not text:
            return ""
        text = html.unescape(text)
        text = re.sub(
            r'<span\s+class="mathquill-embedded-latex"\s*>(.*?)</span>',
            r'\(\1\)',
            text,
            flags=re.DOTALL
        )
        return text


# ============================================================================
# 扫描服务模块
# ============================================================================

class Scanner:
    def __init__(self, config_manager: ConfigManager, data_manager: DataManager,
                 db_extractor: DatabaseExtractor, work_processor: WorkFileProcessor, logger: Logger):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.db_extractor = db_extractor
        self.work_processor = work_processor
        self.logger = logger
        self.scan_in_progress = False
        self.last_scan_time = 0

    def perform_scan(self):
        if self.scan_in_progress:
            self.logger.warning("扫描任务正在进行中，跳过")
            return

        self.scan_in_progress = True
        self.logger.set_action("扫描任务")
        self.logger.info("开始扫描作业...")

        try:
            works = self.db_extractor.extract_work_info()
            works_info_batch = []
            details_batch = []

            for work in works:
                # 准备元数据（用于 works_info）
                works_info_batch.append({
                    'work_id': work['work_id'],
                    'work_name': work['work_name'],
                    'subject_id': work['subject_id'],
                    'start_time': work['start_time'],
                    'upto_time': work['upto_time'],
                    'is_exam': work['is_exam'],
                    'has_content': not work['no_url']
                })

                # 如果作业有内容，处理详情
                if not work['no_url']:
                    work_details = self.work_processor.process(work)
                    if work_details:
                        details_batch.append((work['work_id'], work_details))

            # 批量写入数据库
            if works_info_batch:
                self.data_manager.batch_upsert_works_info(works_info_batch)
                self.logger.info(f"已更新 {len(works_info_batch)} 条作业元数据")
            if details_batch:
                self.data_manager.batch_save_work_details(details_batch)
                self.logger.info(f"已保存 {len(details_batch)} 个作业详情")

            self.logger.success("扫描完成")
            self.last_scan_time = int(time.time())
        except Exception as e:
            self.logger.error(f"执行失败：{str(e)}")
        finally:
            self.scan_in_progress = False
            self.logger.clear_action()

    def start_scan_loop(self):
        self.logger.set_action("扫描循环")
        while True:
            try:
                if not self.scan_in_progress:
                    self.perform_scan()
                time.sleep(self.config_manager.get_check_interval())
            except Exception as e:
                self.logger.error(f"错误：{str(e)}")
                time.sleep(60)


# ============================================================================
# 网络服务模块
# ============================================================================

class WebService:
    def __init__(self, scanner: Scanner, config_manager: ConfigManager, data_manager: DataManager):
        self.scanner = scanner
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.app = Flask(__name__)
        self.app.config['TEMPLATES_AUTO_RELOAD'] = True
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/')
        def main_page():
            return render_template('main_page.html')

        @self.app.route('/work/<work_id>')
        def work_page(work_id):
            return render_template('work_page.html', work_id=work_id)

        @self.app.route('/api/work/<work_id>')
        def get_work_details(work_id):
            work_details = self.data_manager.load_work_details(work_id)
            if not work_details:
                return jsonify({'error': '作业不存在'}), 404
            subject_info = self.config_manager.get_subject_info(work_details.get('subject_id', 0))
            work_details['subject_info'] = subject_info
            return jsonify(work_details)

        @self.app.route('/api/works')
        def get_works():
            date_param = request.args.get('date', '')
            if not date_param:
                return jsonify([])
            search_date = date_param.replace('-', '')
            works = self.data_manager.get_works_by_date(search_date)
            return jsonify(works)

        @self.app.route('/api/calendar')
        def get_calendar_data():
            months_param = request.args.get('months', '')
            months = months_param.split(',') if months_param else []
            data = self.data_manager.get_works_counts_by_months(months)
            return jsonify(data)

        @self.app.route('/api/scan', methods=['POST'])
        def trigger_scan():
            if self.scanner.scan_in_progress:
                return jsonify({'status': 'error', 'message': '扫描正在进行中'})
            threading.Thread(target=self.scanner.perform_scan, daemon=True).start()
            return jsonify({'status': 'success', 'message': '扫描已开始'})

        @self.app.route('/api/config')
        def get_config():
            return jsonify(self.config_manager.config)

        @self.app.route('/api/config/reload', methods=['POST'])
        def reload_config():
            self.config_manager.load()
            return jsonify({'status': 'success', 'message': '配置已重新加载'})

        @self.app.route('/api/status')
        def get_status():
            status = {
                'last_scan_time': self.scanner.last_scan_time,
                'total_works': self.data_manager.get_total_works_count(),
                'scan_in_progress': self.scanner.scan_in_progress,
            }
            return jsonify(status)

        @self.app.route('/es5/<path:filename>')
        def serve_es5_files(filename):
            es5_dir = "/storage/emulated/0/1/answers/es5"
            try:
                return send_from_directory(es5_dir, filename)
            except FileNotFoundError:
                return "File not found", 404

    def run(self, host='0.0.0.0', port=8001):
        self.app.run(host=host, port=port, debug=False)


# ============================================================================
# 主程序
# ============================================================================
CONFIG_FILE = "/storage/emulated/0/1/program/获取答案/config.json"
DATABASE_PATH = "/storage/emulated/0/xuehai/5210/databases/com.xh.acldstu/1364978/xh_yunzuoye.db"
FILE_BASE_DIR = "/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/"
OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"
DETAIL_VERSION = 1

def main():

    logger = Logger()
    logger.set_action("系统初始化")

    config_manager = ConfigManager(CONFIG_FILE, logger)
    data_manager = DataManager(OUTPUT_BASE_DIR)
    db_extractor = DatabaseExtractor(DATABASE_PATH, FILE_BASE_DIR, data_manager, logger)
    work_processor = WorkFileProcessor(FILE_BASE_DIR, logger, db_extractor)
    scanner = Scanner(config_manager, data_manager, db_extractor, work_processor, logger)
    web_service = WebService(scanner, config_manager, data_manager)

    logger.success("系统初始化完成")
    logger.clear_action()

    atexit.register(data_manager.close)

    scan_thread = threading.Thread(target=scanner.start_scan_loop, daemon=True)
    scan_thread.start()

    print(f"{Logger.Colors.BOLD}{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ===== 自动答案提取系统 ====={Logger.Colors.RESET}")
    print(f"{Logger.Colors.SUCCESS}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 服务器启动，地址：http://localhost:8001{Logger.Colors.RESET}")
    print(f"{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 检查间隔：{config_manager.get_check_interval()}秒{Logger.Colors.RESET}")

    web_service.run()


if __name__ == "__main__":
    main()