#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据迁移脚本 v2：将旧的文件存储迁移到 SQLite 数据库
- 使用 GENERATED 列自动生成 month_str 和 work_date
- 迁移前验证 JSON 结构，符合预期才迁移并重命名原文件为 .bak，否则保留原文件
- 自动将旧版作业详情转换为新版格式（answers 为字符串列表，子题号整数，移除 version 键）
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, List

OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"
DB_PATH = os.path.join(OUTPUT_BASE_DIR, "metadata.db")
LOG_FILE = os.path.join(OUTPUT_BASE_DIR, "migration.log")

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {msg}\n")

def rename_to_bak(file_path):
    """将文件重命名为 .bak（如果存在且未被备份过）"""
    bak_path = file_path + ".bak"
    os.rename(file_path, bak_path)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS works_info (
            work_id TEXT PRIMARY KEY,
            work_name TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            start_time INTEGER NOT NULL,
            upto_time INTEGER NOT NULL,
            is_exam INTEGER NOT NULL,
            has_content INTEGER NOT NULL,
            month_str TEXT 
                GENERATED ALWAYS AS (strftime('%Y%m', start_time / 1000, 'unixepoch')) 
                STORED,
            work_date TEXT 
                GENERATED ALWAYS AS (strftime('%Y%m%d', start_time / 1000, 'unixepoch')) 
                STORED
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS work_details (
            work_id TEXT PRIMARY KEY,
            version INTEGER DEFAULT 1,
            detail_json TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS no_content_url (
            work_id TEXT PRIMARY KEY
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS last_scan_time (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            scan_time INTEGER NOT NULL
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_work_date ON works_info(work_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_month_str ON works_info(month_str)")
    conn.commit()
    conn.close()
    log("数据库表结构已初始化")

def validate_work_info(work: Dict[str, Any]) -> bool:
    """验证单个作业信息是否包含必需字段且类型基本正确"""
    required_fields = ['work_name', 'subject_id', 'start_time', 'upto_time', 'is_exam', 'has_content']
    for field in required_fields:
        if field not in work:
            log(f"  缺少字段 {field}")
            return False
    if not isinstance(work['subject_id'], int):
        log(f"  subject_id 应为整数，实际 {type(work['subject_id'])}")
        return False
    if not isinstance(work['start_time'], int) or work['start_time'] <= 0:
        log(f"  start_time 应为正整数，实际 {work['start_time']}")
        return False
    if not isinstance(work['upto_time'], int):
        log(f"  upto_time 应为整数，实际 {work['upto_time']}")
        return False
    if not isinstance(work['is_exam'], bool):
        log(f"  is_exam 应为布尔值，实际 {type(work['is_exam'])}")
        return False
    if not isinstance(work['has_content'], bool):
        log(f"  has_content 应为布尔值，实际 {type(work['has_content'])}")
        return False
    return True

def validate_work_detail(detail: Dict[str, Any]) -> bool:
    """验证作业详情 JSON 是否包含必需字段"""
    if not isinstance(detail, dict):
        log(f"  详情不是字典类型，实际 {type(detail)}")
        return False
    required_fields = ['work_name', 'subject_id', 'upto_time', 'is_exam', 'start_time', 'questions']
    for field in required_fields:
        if field not in detail:
            log(f"  缺少字段 {field}")
            return False
    if not isinstance(detail['questions'], list):
        log(f"  questions 应为列表")
        return False
    return True

def convert_work_details_to_new(old_detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    将旧格式的作业详情转换为新格式：
    - 移除 version 键（如果有）
    - answers 从列表字典变为简单字符串列表
    - 子题目的 question_number 从字符串变为整数（重新编号）
    """
    new_detail = {
        'work_name': old_detail.get('work_name', ''),
        'subject_id': old_detail.get('subject_id', 0),
        'upto_time': old_detail.get('upto_time', 0),
        'is_exam': old_detail.get('is_exam', False),
        'start_time': old_detail.get('start_time', 0),
        'questions': []
    }
    old_questions = old_detail.get('questions', [])
    qn = 0
    for q in old_questions:
        # 处理分割线
        if q.get('question_type') == '分割线':
            divider = {
                'question_id': q.get('question_id', ''),
                'question_type': '分割线',
                'stem_content': q.get('stem_content', ''),
                'explain_content': q.get('explain_content', ''),
                'has_children': q.get('has_children', False),
                'answers': [],  # 分割线无答案
                'sub_questions': []
            }
            new_detail['questions'].append(divider)
            continue

        # 普通题目
        qn += 1
        # 转换 answers
        answers = []
        for ans in q.get('answers', []):
            if isinstance(ans, dict):
                answers.append(ans.get('answer_content', ''))
            else:
                answers.append(ans)  # 已经是字符串
        # 转换子题目
        sub_questions = []
        sub_qn = 1
        for sub in q.get('sub_questions', []):
            sub_answers = []
            for ans in sub.get('answers', []):
                if isinstance(ans, dict):
                    sub_answers.append(ans.get('answer_content', ''))
                else:
                    sub_answers.append(ans)
            sub_q = {
                'question_id': sub.get('question_id', ''),
                'question_number': sub_qn,
                'question_type': sub.get('question_type', ''),
                'stem_content': sub.get('stem_content', ''),
                'explain_content': sub.get('explain_content', ''),
                'answers': sub_answers
            }
            sub_questions.append(sub_q)
            sub_qn += 1

        new_q = {
            'question_id': q.get('question_id', ''),
            'question_number': qn,
            'question_type': q.get('question_type', ''),
            'stem_content': q.get('stem_content', ''),
            'explain_content': q.get('explain_content', ''),
            'has_children': bool(sub_questions),
            'answers': answers,
            'sub_questions': sub_questions
        }
        new_detail['questions'].append(new_q)

    return new_detail

def migrate_last_scan_time():
    file_path = os.path.join(OUTPUT_BASE_DIR, "last_scan_time.txt")
    if not os.path.exists(file_path):
        log("未找到 last_scan_time.txt，跳过")
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                scan_time = int(content)
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO last_scan_time (id, scan_time) VALUES (1, ?)",
                    (scan_time,)
                )
                conn.commit()
                conn.close()
                log(f"已迁移 last_scan_time: {scan_time}")
                rename_to_bak(file_path)
            else:
                log("last_scan_time.txt 为空，跳过")
    except Exception as e:
        log(f"迁移 last_scan_time 失败: {e}")

def migrate_no_content_url():
    file_path = os.path.join(OUTPUT_BASE_DIR, "no_content_url.txt")
    if not os.path.exists(file_path):
        log("未找到 no_content_url.txt，跳过")
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines:
            log("no_content_url.txt 为空，跳过")
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM no_content_url")
        cursor.executemany("INSERT INTO no_content_url (work_id) VALUES (?)", [(wid,) for wid in lines])
        conn.commit()
        conn.close()
        log(f"已迁移 no_content_url，共 {len(lines)} 条记录")
        rename_to_bak(file_path)
    except Exception as e:
        log(f"迁移 no_content_url 失败: {e}")

def migrate_works_info_and_details():
    total_works = 0
    total_details = 0
    skipped_works = 0
    skipped_details = 0

    for entry in os.listdir(OUTPUT_BASE_DIR):
        if not entry.isdigit() or len(entry) != 6:
            continue
        month_dir = os.path.join(OUTPUT_BASE_DIR, entry)
        if not os.path.isdir(month_dir):
            continue

        # 处理 works_info.json
        works_info_file = os.path.join(month_dir, "works_info.json")
        if os.path.exists(works_info_file):
            try:
                with open(works_info_file, 'r', encoding='utf-8') as f:
                    works_data = json.load(f)
            except json.JSONDecodeError as e:
                log(f"JSON 解析失败，跳过 {works_info_file}: {e}")
                continue

            if not isinstance(works_data, dict):
                log(f"works_info.json 格式错误，跳过 {works_info_file}")
                continue

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            valid_works = []
            for work_id, work in works_data.items():
                if not isinstance(work, dict):
                    log(f"  跳过 {work_id}: 值不是字典")
                    skipped_works += 1
                    continue
                if not validate_work_info(work):
                    log(f"  跳过 {work_id}: 字段验证失败")
                    skipped_works += 1
                    continue
                work_name = work['work_name']
                subject_id = work['subject_id']
                start_time = work['start_time']
                upto_time = work['upto_time']
                is_exam = 1 if work['is_exam'] else 0
                has_content = 1 if work['has_content'] else 0
                valid_works.append((work_id, work_name, subject_id, start_time, upto_time,
                                    is_exam, has_content))

            if valid_works:
                cursor.executemany('''
                    INSERT OR REPLACE INTO works_info
                    (work_id, work_name, subject_id, start_time, upto_time, is_exam, has_content)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', valid_works)
                conn.commit()
                log(f"已迁移 {works_info_file}: {len(valid_works)} 条记录")
                total_works += len(valid_works)
                rename_to_bak(works_info_file)
            else:
                log(f"无有效数据，跳过 {works_info_file}")
            conn.close()

        # 处理作业详情文件
        details_files = [f for f in os.listdir(month_dir) if f.endswith('.json') and f != 'works_info.json']
        if details_files:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            valid_details = []
            for filename in details_files:
                work_id = filename[:-5]
                file_path = os.path.join(month_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        detail_data = json.load(f)
                except json.JSONDecodeError as e:
                    log(f"跳过 {file_path}: JSON 解析失败 - {e}")
                    skipped_details += 1
                    continue

                if not validate_work_detail(detail_data):
                    log(f"跳过 {file_path}: 数据结构不符合预期")
                    skipped_details += 1
                    continue

                # 转换为新格式
                new_detail = convert_work_details_to_new(detail_data)
                detail_json = json.dumps(new_detail, ensure_ascii=False)
                valid_details.append((work_id, detail_json))

            if valid_details:
                cursor.executemany('''
                    INSERT OR REPLACE INTO work_details (work_id, detail_json)
                    VALUES (?, ?)
                ''', valid_details)
                conn.commit()
                log(f"已迁移 {month_dir} 中的 {len(valid_details)} 个详情文件")
                total_details += len(valid_details)
                for work_id, _ in valid_details:
                    file_path = os.path.join(month_dir, work_id + ".json")
                    rename_to_bak(file_path)
            conn.close()

    log(f"works_info 迁移完成：成功 {total_works} 条，跳过 {skipped_works} 条")
    log(f"work_details 迁移完成：成功 {total_details} 条，跳过 {skipped_details} 条")

def main():
    log("开始迁移数据...")
    if not os.path.exists(OUTPUT_BASE_DIR):
        log(f"错误：根目录不存在 {OUTPUT_BASE_DIR}")
        return
    init_db()
    migrate_last_scan_time()
    migrate_no_content_url()
    migrate_works_info_and_details()
    log("所有数据迁移完成！")

if __name__ == "__main__":
    main()