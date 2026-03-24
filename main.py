import json
import os
import re
import time
import threading
import html
import sqlite3
from datetime import datetime, timedelta
from typing import Any, TypedDict
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
        """设置当前执行的动作"""
        self.current_action = action

    def clear_action(self):
        """清除当前动作"""
        self.current_action = ""

    def _format_message(self, level, message):
        """格式化日志消息"""
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
        """加载配置"""
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
        """保存配置"""
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
        """深度更新字典"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def get_subject_info(self, subject_id):
        """获取学科信息"""
        return self.config['subject_config'].get(str(subject_id), 
                                                self.config['subject_config']["default"])

    def get_check_interval(self):
        """获取检查间隔"""
        return self.config.get('check_interval', 3600)


class DataManager:
    """数据存储管理"""

    def __init__(self, base_dir, logger: Logger):
        self.base_dir = base_dir
        self.logger = logger
        self.last_scan_time_file = os.path.join(base_dir, "last_scan_time.txt")
        self.loaded_works_infos = {}
        self.cache_lock = threading.Lock()

    def load_last_scan_time(self):
        """加载上次扫描时间"""
        try:
            if os.path.exists(self.last_scan_time_file):
                # 以读模式打开文件读取
                with open(self.last_scan_time_file, 'r', encoding='utf-8') as f:
                    return int(f.read().strip())
        except Exception as e:
            self.logger.warning(f"加载上次扫描时间失败，使用默认值：{str(e)}")
        return 1765400000000

    def save_last_scan_time(self, last_scan_time):
        """保存上次扫描时间"""
        try:
            with open(self.last_scan_time_file, 'w', encoding='utf-8') as f:
                f.write(str(last_scan_time))
        except Exception as e:
            self.logger.error(f"保存上次扫描时间失败：{str(e)}")

    def load_works_info(self, date_str):
        """加载作业信息"""
        with self.cache_lock:
            if date_str in self.loaded_works_infos:
                return self.loaded_works_infos[date_str]
            
            works_file = self._get_works_info_file_path(date_str)
            try:
                if os.path.exists(works_file):
                    with open(works_file, 'r', encoding='utf-8') as f:
                        works_info = json.load(f)
                    self.loaded_works_infos[date_str] = works_info
                    return works_info
            except Exception as e:
                self.logger.error(f"加载作业信息失败：{str(e)}")
            self.loaded_works_infos[date_str] = {}
            return {}
    
    def save_works_infos(self) -> None:
        with self.cache_lock:
            for date_str in self.loaded_works_infos:
                self._save_works_info(date_str, self.loaded_works_infos[date_str])
            self.loaded_works_infos.clear()

    def _save_works_info(self, date_str, works_info):
        """保存作业信息"""
        works_file = self._get_works_info_file_path(date_str)

        try:
            with open(works_file, 'w', encoding='utf-8') as f:
                json.dump(works_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存作业信息失败：{str(e)}")

    def save_work_details(self, date_str, work_id, work_data):
        """保存作业详情"""
        details_file = self._get_work_details_file_path(date_str, work_id)

        try:
            with open(details_file, 'w', encoding='utf-8') as f:
                json.dump(work_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"保存作业详情失败：{str(e)}")
            return False

    def load_work_details(self, date_str, work_id):
        """加载作业详情"""
        details_file = self._get_work_details_file_path(date_str, work_id)

        try:
            if os.path.exists(details_file):
                with open(details_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"加载作业详情失败：{str(e)}")
        return None
    
    def load_no_content_url_records(self):
        """加载无内容URL的记录"""
        records_file = self._get_no_content_url_file_path()
        records = set()
        
        try:
            if os.path.exists(records_file):
                with open(records_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        work_id = line.strip()
                        if work_id:
                            records.add(work_id)
        except Exception as e:
            self.logger.error(f"加载无内容URL记录失败：{str(e)}")
        
        return records
    
    def save_no_content_url_records(self, records):
        """保存无内容URL的记录"""
        records_file = self._get_no_content_url_file_path()
        
        try:
            with open(records_file, 'w', encoding='utf-8') as f:
                for work_id in records:
                    f.write(f"{work_id}\n")
        except Exception as e:
            self.logger.error(f"保存无内容URL记录失败：{str(e)}")

    def _get_month_dir(self, date_str=None):
        """获取月份目录"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m")
        month_dir = os.path.join(self.base_dir, date_str)
        os.makedirs(month_dir, exist_ok=True)
        return month_dir

    def _get_work_details_file_path(self, date_str, work_id):
        """获取作业详情文件路径"""
        month_dir = self._get_month_dir(date_str[:6])
        return os.path.join(month_dir, f"{work_id}.json")

    def _get_works_info_file_path(self, date_str):
        """获取作业信息文件路径"""
        month_dir = self._get_month_dir(date_str[:6])
        return os.path.join(month_dir, "works_info.json")

    def _get_no_content_url_file_path(self):
        """获取无内容URL的记录文件路径"""
        return os.path.join(self.base_dir, "no_content_url.txt")


# ============================================================================
# 作业处理模块
# ============================================================================

class DatabaseExtractor:
    """数据库提取器"""

    def __init__(self, db_path, file_base_dir, data_manager: DataManager, logger: Logger):
        self.db_path = db_path
        self.file_base_dir = file_base_dir
        self.data_manager = data_manager
        self.logger = logger
        self.question_type_mapping = {}
        self._load_question_types()

    def _load_question_types(self):
        """从数据库加载题目类型映射"""
        self.logger.set_action("题目类型")
        
        try:
            if not os.path.exists(self.db_path):
                self.logger.warning(f"数据库文件不存在：{self.db_path}")
                return

            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            try:
                cursor = conn.cursor()
                
                # 查询QuestionUserType表
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

    def extract_work_info(self) -> list[dict]:
        """从数据库提取作业信息"""
        self.logger.set_action("数据库")

        try:
            if not os.path.exists(self.db_path):
                self.logger.error(f"数据库文件不存在：{self.db_path}")
                return []

            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            no_url_works = self.data_manager.load_no_content_url_records()
            # 获取上次扫描时间
            last_scan_timestamp = self.data_manager.load_last_scan_time()
            latest_scan_timestamp = last_scan_timestamp
            try:
                cursor = conn.cursor()
                all_works = []
                time_now = int(time.time() * 1000)


                # 合并查询：查找更新的记录 + 无内容URL的记录
                if no_url_works:
                    placeholders = ','.join(['?'] * len(no_url_works))
                    query = f"""
                    SELECT WORK_ID, CONTENT_URL, NAME, SUBJECT,
                        CREATE_TIME, UPTO_TIME, START_TIME, END_TIME, UPDATE_TIME
                    FROM xh_yzy_student_work_list 
                    WHERE UPDATE_TIME > ? OR WORK_ID IN ({placeholders})
                    """
                    params = (last_scan_timestamp,) + tuple(no_url_works)
                else:
                    query = """
                    SELECT WORK_ID, CONTENT_URL, NAME, SUBJECT,
                        CREATE_TIME, UPTO_TIME, START_TIME, END_TIME, UPDATE_TIME
                    FROM xh_yzy_student_work_list 
                    WHERE UPDATE_TIME > ?
                    """
                    params = (last_scan_timestamp,)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                self.logger.info(f"找到{len(rows)}条作业记录")

                for row in rows:
                    try:
                        work_id, content_url, work_name, subject_id, \
                            create_time, upto_time, start_time, end_time, update_time = row
                        
                        if work_id in no_url_works:
                            if content_url:
                                no_url_works.remove(work_id)
                                self.logger.info(f"{work_name} (科目: {subject_id}) 新增URL")
                            elif time_now > max(upto_time, end_time):
                                no_url_works.remove(work_id)
                                self.logger.info(f"移除过期无内容作业: {work_name}")
                                continue
                            else:
                                continue

                        if not content_url:
                            if time_now > max(upto_time, end_time):
                                continue
                            no_url_works.add(work_id)
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
                        self.logger.debug(f'{create_time, upto_time, start_time, end_time, update_time, last_scan_timestamp, latest_scan_timestamp}')

                        if update_time > latest_scan_timestamp:
                            latest_scan_timestamp = update_time

                    except Exception as e:
                        self.logger.error(f"解析作业记录失败：{str(e)}")
                        continue

                self.logger.success(f"成功提取{len(all_works)}个作业信息")
                return all_works
            finally:
                conn.close()
                self.data_manager.save_no_content_url_records(no_url_works)
                self.data_manager.save_last_scan_time(latest_scan_timestamp)
        except sqlite3.Error as e:
            self.logger.error(f"SQLite错误：{str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"提取失败：{str(e)}")
            return []
        finally:
            self.logger.clear_action()

    def get_question_type_name(self, type_id):
        """根据类型ID获取题目类型名称"""
        return self.question_type_mapping.get(type_id, f"未知类型({type_id})")


class WorkFileProcessor:
    """作业文件处理器"""

    def __init__(self, file_base_dir, logger: Logger, db_extractor: DatabaseExtractor):
        self.file_base_dir = file_base_dir
        self.logger = logger
        self.db_extractor = db_extractor

    def process(self, work_info: dict[str, Any]):
        """处理单个作业文件"""
        self.logger.set_action("文件处理")

        # 构建完整文件路径
        file_path = os.path.join(self.file_base_dir, work_info['month_str'], work_info['file_name']+'.txt')

        if not os.path.exists(file_path):
            self.logger.warning(f"文件不存在：{file_path}")
            self.logger.clear_action()
            return None

        self.logger.info(f"开始处理 {work_info['work_name']}")

        # 读取并解析JSON
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

        # 提取作业详情
        work_details = self._extract_work_details(data, work_info)

        self.logger.success(f"提取作业详情：{work_info['work_name']}")
        self.logger.clear_action()
        return work_details

    def _extract_work_details(self, data, work_info):
        """从数据中提取作业详情"""
        work_details = {
            'work_name': work_info['work_name'],
            'subject_id': work_info['subject_id'],
            'upto_time': work_info['upto_time'],
            'is_exam': work_info['is_exam'],
            'start_time': work_info['start_time'],
            'questions': []
        }

        # 组织答案和题目
        answers_by_question = {}
        for answer in data.get('questionAnswers', []):
            qid = answer['questionId']
            if qid not in answers_by_question:
                answers_by_question[qid] = []
            answers_by_question[qid].append(answer)

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

        # 构建题目结构
        qn = 0
        for question in top_level_questions:
            qid = question['questionId']
            # 获取题目类型
            question_user_type = question.get('questionUserType', 0)
            question_type_name = self.db_extractor.get_question_type_name(question_user_type)

            # 特殊处理：如果类型为"未知类型(0)"，作为分割线处理
            if question_user_type == 0:
                # 创建分割线题目
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
                continue  # 跳过正常的题目处理

            qn += 1
            
            answers = answers_by_question.get(qid, [])

            # 处理题目内容
            stem_content = self._process_html_content(
                question.get('stemContent', ''))
            explain_content = self._process_html_content(
                question.get('explainContent', ''))
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

            # 添加答案
            for answer in answers:
                question_data['answers'].append({
                    'answer_content': self._process_html_content(answer['answerContent']),
                    'index': answer.get('index', 0)
                })

            # 处理子题目
            if has_children:
                sub_questions = parent_to_children[qid]
                sub_qn = 1
                for sub_question in sub_questions:
                    sub_qid = sub_question['questionId']
                    
                    # 获取子题目类型
                    sub_question_user_type = sub_question.get('questionUserType', 0)
                    sub_question_type_name = self.db_extractor.get_question_type_name(sub_question_user_type)
                    
                    sub_answers = answers_by_question.get(sub_qid, [])
                    sub_stem_content = self._process_html_content(
                        sub_question.get('stemContent', ''))
                    sub_explain_content = self._process_html_content(
                        sub_question.get('explainContent', ''))

                    sub_question_data = {
                        'question_id': sub_qid,
                        'question_number': f"{qn}.{sub_qn}",
                        'question_type': sub_question_type_name,
                        'stem_content': sub_stem_content,
                        'explain_content': sub_explain_content,
                        'answers': []
                    }

                    # 添加子题目答案
                    for answer in sub_answers:
                        sub_question_data['answers'].append({
                            'answer_content': self._process_html_content(answer['answerContent']),
                            'index': answer.get('index', 0)
                        })

                    question_data['sub_questions'].append(sub_question_data)
                    sub_qn += 1

            work_details['questions'].append(question_data)

        return work_details

    def _process_html_content(self, text):
        """处理HTML内容"""
        if not text:
            return ""

        text = html.unescape(text)

        # 处理数学公式
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
    """扫描服务"""

    def __init__(self, config_manager: ConfigManager, data_manager: DataManager, db_extractor: DatabaseExtractor, work_processor: WorkFileProcessor, logger: Logger):
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.db_extractor = db_extractor
        self.work_processor = work_processor
        self.logger = logger

        self.scan_in_progress = False
        self.last_scan_time = 0

    def perform_scan(self):
        """执行扫描"""
        if self.scan_in_progress:
            self.logger.warning("扫描任务正在进行中，跳过")
            return

        self.scan_in_progress = True
        self.logger.set_action("扫描任务")
        self.logger.info("开始扫描作业...")

        try:

            # 提取作业信息
            works = self.db_extractor.extract_work_info()
            processed_count = 0

            # 处理每个作业
            for work in works:
                if not work['no_url']:
                    work_id = work['work_id']
                    month_str = work['month_str']
                    # 处理作业文件
                    work_details = self.work_processor.process(work)
                    # 保存作业详情
                    if not self.data_manager.save_work_details(month_str, work_id, work_details):
                        continue
                    processed_count += 1
                # 更新作业信息列表
                self._update_works_info(work)
            self.data_manager.save_works_infos()

            if processed_count > 0:
                self.logger.success(f"成功处理{processed_count}个作业")
            else:
                self.logger.info("未发现新作业")

            # 更新最后扫描时间
            self.last_scan_time = int(time.time())

        except Exception as e:
            self.logger.error(f"执行失败：{str(e)}")
        finally:
            self.scan_in_progress = False
            self.logger.clear_action()

    def _update_works_info(self, work_info: dict):
        """更新作业信息列表"""
        works_infos = self.data_manager.load_works_info(work_info['month_str'])

        # 构建作业信息
        work_data = {
            'work_id': work_info['work_id'],
            'has_content': not work_info['no_url'],
            'file_name': work_info['file_name'],
            'work_name': work_info['work_name'],
            'subject_id': work_info['subject_id'],
            'upto_time': work_info['upto_time'],
            'is_exam': work_info['is_exam'],
            'start_time': work_info['start_time'],
            'work_date': datetime.fromtimestamp(work_info['start_time'] // 1000).strftime("%Y%m%d")
        }

        works_infos[work_info['work_id']] = work_data

    def start_scan_loop(self):
        """启动扫描循环"""
        self.logger.set_action("扫描循环")

        while True:
            try:
                if not self.scan_in_progress:
                    self.perform_scan()

                # 等待检查间隔
                time.sleep(self.config_manager.get_check_interval())
            except Exception as e:
                self.logger.error(f"错误：{str(e)}")
                time.sleep(60)


# ============================================================================
# 网络服务模块
# ============================================================================

class WebService:
    """网络服务"""

    def __init__(self, scanner: Scanner, config_manager: ConfigManager, data_manager: DataManager):
        self.scanner = scanner
        self.config_manager = config_manager
        self.data_manager = data_manager
        self.app = Flask(__name__)
        self.app.config['TEMPLATES_AUTO_RELOAD'] = True
        self._setup_routes()

    def _setup_routes(self):
        """设置Flask路由"""

        @self.app.route('/')
        def main_page():
            return render_template('main_page.html')

        @self.app.route('/work/<date_str>/<work_id>')
        def work_page(date_str, work_id):
            return render_template('work_page.html', date_str=date_str[:6], work_id=work_id)

        @self.app.route('/api/config')
        def get_config():
            return jsonify(self.config_manager.config)

        @self.app.route('/api/config/reload', methods=['POST'])
        def reload_config():
            self.config_manager.load()
            return jsonify({'status': 'success', 'message': '配置已重新加载'})

        @self.app.route('/es5/<path:filename>')
        def serve_es5_files(filename):
            es5_dir = "/storage/emulated/0/1/answers/es5"
            try:
                return send_from_directory(es5_dir, filename)
            except FileNotFoundError:
                return "File not found", 404

        @self.app.route('/api/status')
        def get_status():
            last_scan_time_str = "从未扫描"
            if self.scanner.last_scan_time > 0:
                last_scan_dt = datetime.fromtimestamp(self.scanner.last_scan_time)
                last_scan_time_str = last_scan_dt.strftime("%Y-%m-%d %H:%M:%S")

            # 计算总作业数
            total_works = 0
            output_base_dir = self.data_manager.base_dir

            try:
                if os.path.exists(output_base_dir):
                    for month_dir in os.listdir(output_base_dir):
                        if len(month_dir) == 6 and month_dir.isdigit():
                            works_info = self.data_manager.load_works_info(month_dir)
                            total_works += len(works_info)
            except Exception:
                pass

            status = {
                'last_scan_time': self.scanner.last_scan_time,
                'last_scan_time_str': last_scan_time_str,
                'check_interval': self.config_manager.get_check_interval(),
                'scan_in_progress': self.scanner.scan_in_progress,
                'total_works': total_works,
                'current_date_str': datetime.now().strftime("%Y%m")
            }

            return jsonify(status)

        @self.app.route('/api/scan', methods=['POST'])
        def trigger_scan():
            if self.scanner.scan_in_progress:
                return jsonify({'status': 'error', 'message': '扫描正在进行中'})

            threading.Thread(target=self.scanner.perform_scan, daemon=True).start()
            return jsonify({'status': 'success', 'message': '扫描已开始'})

        @self.app.route('/api/works')
        def get_works():
            date_param = request.args.get('date', '')
            if not date_param:
                return jsonify([])

            search_date = date_param.replace('-', '')
            works_data = []

            month_str = search_date[:6]
            works_info = self.data_manager.load_works_info(month_str)

            for work in works_info.values():
                if work.get('work_date', '').startswith(search_date):
                    subject_info = self.config_manager.get_subject_info(work['subject_id'])

                    # 兼容旧数据
                    is_exam = work.get('is_exam', False)
                    if 'has_content' in work:
                        has_content = work['has_content']
                    elif 'is_no_url' in work:
                        has_content = not work['is_no_url']
                    else:
                        has_content = not work.get('work_id', '').startswith('no_url_')
                    if 'start_time' in work:
                        start_time = work['start_time']
                    elif 'scan_time' in work:
                        # 尝试从scan_time字符串解析时间
                        scan_time_str = work['scan_time']
                        scan_dt = datetime.strptime(scan_time_str, "%Y-%m-%d %H:%M:%S")
                        start_time = int(scan_dt.timestamp() * 1000)
                    else:
                        start_time = 0
                    
                    # 构建作业数据
                    work_data = {
                        'work_id': work['work_id'],
                        'work_name': work['work_name'],
                        'subject_id': work['subject_id'],
                        'subject_name': subject_info['name'],
                        'subject_color': subject_info['color'],
                        'subject_short': subject_info['short'],
                        'upto_time': work.get('upto_time', 0),
                        'is_exam': is_exam,
                        'start_time': start_time,
                        'has_content': has_content
                    }
                    
                    works_data.append(work_data)

            return jsonify(works_data)

        @self.app.route('/api/work/<date_str>/<work_id>')
        def get_work_details(date_str, work_id):
            work_details = self.data_manager.load_work_details(date_str, work_id)

            if not work_details:
                return jsonify({'error': '作业不存在'}), 404
            
            # 添加学科信息
            subject_info = self.config_manager.get_subject_info(work_details.get('subject_id', 0))
            work_details['subject_info'] = subject_info

            # 兼容旧数据
            if 'is_exam' not in work_details:
                work_details['is_exam'] = False
            if 'start_time' not in work_details:
                if 'scan_time' in work_details:
                    scan_time_str = work_details['scan_time']
                    scan_dt = datetime.strptime(scan_time_str, "%Y-%m-%d %H:%M:%S")
                    work_details['start_time'] = int(scan_dt.timestamp() * 1000)
                else:
                    work_details['start_time'] = 0

            return jsonify(work_details)

        @self.app.route('/api/calendar')
        def get_calendar_data():
            calendar_data = {}
            today = datetime.now()

            for i in range(3):
                date = today - timedelta(days=30 * i)
                month_str = date.strftime("%Y%m")

                works_info = self.data_manager.load_works_info(month_str)
                month_data = {}

                for work in works_info.values():
                    work_date = work.get('work_date', '')
                    if work_date:
                        formatted_date = f"{work_date[:4]}-{work_date[4:6]}-{work_date[6:8]}"
                        if formatted_date not in month_data:
                            month_data[formatted_date] = 0
                        month_data[formatted_date] += 1

                calendar_data[month_str] = month_data

            return jsonify(calendar_data)

    def run(self, host='0.0.0.0', port=8001):
        """运行Web服务"""
        self.app.run(host=host, port=port, debug=False)


# ============================================================================
# 主程序
# ============================================================================

def main():
    """程序主入口"""

    # 路径常量
    CONFIG_FILE = "/storage/emulated/0/1/program/获取答案/config.json"
    DATABASE_PATH = "/storage/emulated/0/xuehai/5210/databases/com.xh.acldstu/1364978/xh_yunzuoye.db"
    FILE_BASE_DIR = "/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/"
    OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"

    # 初始化日志
    logger = Logger()

    # 初始化各组件
    logger.set_action("系统初始化")
    
    config_manager = ConfigManager(CONFIG_FILE, logger)
    data_manager = DataManager(OUTPUT_BASE_DIR, logger)
    db_extractor = DatabaseExtractor(DATABASE_PATH, FILE_BASE_DIR, data_manager, logger)
    work_processor = WorkFileProcessor(FILE_BASE_DIR, logger, db_extractor)
    scanner = Scanner(config_manager, data_manager, db_extractor, work_processor, logger)
    web_service = WebService(scanner, config_manager, data_manager)

    logger.success("系统初始化完成")
    logger.clear_action()

    # 启动扫描循环线程
    scan_thread = threading.Thread(target=scanner.start_scan_loop, daemon=True)
    scan_thread.start()

    # 打印启动信息
    print(f"{Logger.Colors.BOLD}{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ===== 自动答案提取系统 ====={Logger.Colors.RESET}")
    print(f"{Logger.Colors.SUCCESS}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 服务器启动，地址：http://localhost:8001{Logger.Colors.RESET}")
    print(f"{Logger.Colors.INFO}[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 检查间隔：{config_manager.get_check_interval()}秒{Logger.Colors.RESET}")

    # 启动Web服务
    web_service.run()


if __name__ == "__main__":
    main()