#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件迁移脚本（旧版适配）
将旧文件系统（月份目录下的 works_info.json 和详情 JSON）迁移到 SQLite 数据库
假设数据库表已存在且结构正确（works_info 使用偏移量生成列）
支持旧版作业详情（含 scan_time、无 is_exam、answers 为字典列表）
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, Any

# ==================== 配置 ====================
OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"
DB_PATH = os.path.join(OUTPUT_BASE_DIR, "metadata.db")
LOG_FILE = os.path.join(OUTPUT_BASE_DIR, "migration_old.log")

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {msg}\n")

def rename_to_bak(file_path):
    """将文件重命名为 .bak（如果存在）"""
    bak_path = file_path + ".bak"
    os.rename(file_path, bak_path)

def validate_work_info(work: Dict[str, Any]) -> bool:
    """验证作业元数据是否包含必需字段"""
    required = ['work_name', 'subject_id', 'start_time', 'upto_time', 'is_exam', 'has_content']
    for field in required:
        if field not in work:
            log(f"  缺少字段 {field}")
            return False
    return True

def validate_work_detail(detail: Dict[str, Any]) -> bool:
    """
    验证旧版作业详情是否包含必要字段（兼容 scan_time）
    """
    if not detail:
        log(f"  空")
        return False
    required_meta = ['work_name', 'subject_id', 'upto_time', 'questions']
    for field in required_meta:
        if field not in detail:
            log(f"  缺少字段 {field}")
            return False
    if not isinstance(detail['questions'], list):
        log("  questions 不是列表")
        return False
    # 必须有 start_time 或 scan_time 来获取时间
    if 'start_time' not in detail and 'scan_time' not in detail:
        log("  缺少 start_time 或 scan_time")
        return False
    return True

def convert_work_details_to_new(detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    将旧版作业详情转换为新版格式（answers 字符串列表，子题号整数）
    根据 scan_time 计算 start_time，is_exam 固定为 False
    """
    # 获取 start_time
    if 'start_time' in detail:
        start_time = detail['start_time']
    else:
        try:
            dt = datetime.strptime(detail['scan_time'], '%Y-%m-%d %H:%M:%S')
            start_time = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            raise ValueError(f"无法解析 scan_time: {detail.get('scan_time')}")

    new_detail = {
        'work_name': detail['work_name'],
        'subject_id': detail['subject_id'],
        'upto_time': detail['upto_time'],
        'is_exam': False,            # 此类作业不是考试
        'start_time': start_time,
        'questions': []
    }

    old_questions = detail.get('questions', [])
    qn = 0
    for q in old_questions:
        if q.get('question_type') == '分割线':
            divider = {
                'question_id': q.get('question_id', ''),
                'question_type': '分割线',
                'stem_content': q.get('stem_content', ''),
                'explain_content': q.get('explain_content', ''),
                'has_children': q.get('has_children', False),
                'answers': [],
                'sub_questions': []
            }
            new_detail['questions'].append(divider)
            continue

        qn += 1
        # 转换 answers（旧版为字典列表，新版为字符串列表）
        answers = []
        for ans in q.get('answers', []):
            if isinstance(ans, dict):
                answers.append(ans.get('answer_content', ''))
            else:
                answers.append(ans)

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

        # 迁移 works_info.json
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
                valid_works.append((
                    work_id,
                    work['work_name'],
                    work['subject_id'],
                    work['start_time'],
                    work['upto_time'],
                    1 if work['is_exam'] else 0,
                    1 if work['has_content'] else 0
                ))

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

        # 迁移作业详情文件
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
                    log(f"跳过 {file_path}: 数据验证失败（缺少必要字段或格式错误）")
                    skipped_details += 1
                    continue

                try:
                    new_detail = convert_work_details_to_new(detail_data)
                except ValueError as e:
                    log(f"跳过 {file_path}: 时间解析失败 - {e}")
                    skipped_details += 1
                    continue

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
    log("开始迁移旧版文件...")
    if not os.path.exists(OUTPUT_BASE_DIR):
        log(f"错误：根目录不存在 {OUTPUT_BASE_DIR}")
        return
    migrate_works_info_and_details()
    log("所有数据迁移完成！")

if __name__ == "__main__":
    main()