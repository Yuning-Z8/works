import json
import os
import re
import time
import threading
import html
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ---------------------- 常量与配置 ----------------------
class LogColor:
    """ANSI终端颜色常量"""
    RESET = "\033[0m"
    INFO = "\033[34m"
    SUCCESS = "\033[32m"
    WARNING = "\033[33m"
    ERROR = "\033[31m"
    BOLD = "\033[1m"


# 默认配置
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
    "check_interval": 1200
}

# 路径常量
CONFIG_FILE = "/storage/emulated/0/1/program/获取答案/config.json"
LOG_BASE_DIR = "/storage/emulated/0/XHLocalLog/5210/1364978/"
FILE_BASE_DIR = "/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/"
OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"

# ---------------------- 工具函数 ----------------------
def get_today_date_str():
    """获取当前日期字符串(YYYYMMDD)"""
    return datetime.now().strftime("%Y%m%d")

def get_time_stamp():
    """获取当前时间戳(HH:MM:SS.fff)，精确到微秒"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def sanitize_filename(filename):
    """清理文件名并添加时间戳避免冲突"""
    invalid_chars = '/\\:*?"<>|'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    time_suffix = datetime.now().strftime("%d%H%M%S")
    return f"{time_suffix}_{filename.strip()}"

def process_html_content(text, answers=None):
    """处理HTML内容（修复格式、转换数学公式等，并填入答案）"""
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

    # # 处理图片
    # text = re.sub(
    #     r'<img[^>]*src="([^"]*)"[^>]*>',
    #     r'<img src="\1" style="max-width: 100%; height: auto; margin: 10px 0;">',
    #     text
    # )

    return text

# ---------------------- 配置管理 ----------------------
class ConfigManager:
    def __init__(self):
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()

    def load_config(self):
        """加载配置文件"""
        global LOG_BASE_DIR, FILE_BASE_DIR, OUTPUT_BASE_DIR

        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    # 深度合并配置
                    self.deep_update(self.config, user_config)

                print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [配置] 已加载配置文件{LogColor.RESET}")
            else:
                # 创建默认配置文件
                self.save_config()
                print(f"{LogColor.INFO}[{get_time_stamp()}] [配置] 创建默认配置文件{LogColor.RESET}")

        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [配置] 加载失败：{str(e)}{LogColor.RESET}")

    def save_config(self):
        """保存配置文件"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            print(f"{LogColor.INFO}[{get_time_stamp()}] [配置] 配置已保存{LogColor.RESET}")
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [配置] 保存失败：{str(e)}{LogColor.RESET}")

    def deep_update(self, target, source):
        """深度更新字典"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self.deep_update(target[key], value)
            else:
                target[key] = value

    def get_subject_info(self, subject_id):
        """根据学科ID获取学科信息"""
        return self.config['subject_config'].get(str(subject_id), self.config['subject_config']["default"])

    def get_check_interval(self):
        """获取检查间隔"""
        return self.config.get('check_interval', 1200)

# ---------------------- 数据存储管理 ----------------------
class DataManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def get_month_dir(self, date_str=None):
        """获取月份目录路径"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y%m")
        month_dir = os.path.join(self.base_dir, date_str)
        os.makedirs(month_dir, exist_ok=True)
        return month_dir

    def get_processed_works_file(self, date_str):
        """获取已处理作业记录文件路径"""
        month_dir = self.get_month_dir(date_str)
        return os.path.join(month_dir, "processed_works.txt")

    def get_works_info_file(self, date_str):
        """获取作业信息文件路径"""
        month_dir = self.get_month_dir(date_str)
        return os.path.join(month_dir, "works_info.json")

    def load_processed_works(self, date_str):
        """加载已处理的作业记录"""
        processed_file = self.get_processed_works_file(date_str)
        processed_works = set()

        try:
            if os.path.exists(processed_file):
                with open(processed_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        processed_works.add(line.strip())
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 加载已处理记录失败：{str(e)}{LogColor.RESET}")

        return processed_works

    def save_processed_works(self, date_str, processed_works):
        """保存已处理的作业记录"""
        processed_file = self.get_processed_works_file(date_str)

        try:
            with open(processed_file, 'w', encoding='utf-8') as f:
                for work in processed_works:
                    f.write(work + '\n')
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 保存已处理记录失败：{str(e)}{LogColor.RESET}")

    def load_works_info(self, date_str):
        """加载作业信息"""
        works_file = self.get_works_info_file(date_str)

        try:
            if os.path.exists(works_file):
                with open(works_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 加载作业信息失败：{str(e)}{LogColor.RESET}")

        return {"works": []}

    def save_works_info(self, date_str, works_info):
        """保存作业信息"""
        works_file = self.get_works_info_file(date_str)

        try:
            with open(works_file, 'w', encoding='utf-8') as f:
                json.dump(works_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 保存作业信息失败：{str(e)}{LogColor.RESET}")

    def get_work_details_file(self, date_str, work_id):
        """获取作业详情文件路径"""
        month_dir = self.get_month_dir(date_str)
        return os.path.join(month_dir, f"{work_id}.json")

    def save_work_details(self, date_str, work_id, work_data):
        """保存作业详情"""
        details_file = self.get_work_details_file(date_str, work_id)

        try:
            with open(details_file, 'w', encoding='utf-8') as f:
                json.dump(work_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 保存作业详情失败：{str(e)}{LogColor.RESET}")
            return False

    def load_work_details(self, date_str, work_id):
        """加载作业详情"""
        details_file = self.get_work_details_file(date_str, work_id)

        try:
            if os.path.exists(details_file):
                with open(details_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [数据] 加载作业详情失败：{str(e)}{LogColor.RESET}")

        return None

# ---------------------- 全局状态 ----------------------
config_manager = ConfigManager()
data_manager = DataManager(OUTPUT_BASE_DIR)

# 扫描状态
scan_in_progress = False
last_scan_time = 0
current_date_str = datetime.now().strftime("%Y%m")

# ---------------------- 作业信息处理 ----------------------
def extract_work_info():
    """从日志文件提取作业信息"""
    try:
        # 构建日志文件路径
        today_date = get_today_date_str()
        log_filename = f"作业列表日志{today_date}().txt"
        log_file_path = f"{LOG_BASE_DIR.rstrip('/')}/{log_filename}"
        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 读取作业日志：{log_file_path}{LogColor.RESET}")

        # 读取日志内容（兼容多种编码）
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                log_content = f.read()
        except UnicodeDecodeError:
            with open(log_file_path, 'r', encoding='gbk', errors='ignore') as f:
                log_content = f.read()

        # 提取JSON数据
        json_pattern = r'获取首页作业列表：(\{[\s\S]*?\})(?=\n|$)'
        matched_jsons = re.findall(json_pattern, log_content)
        if not matched_jsons:
            print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 未找到作业列表JSON数据{LogColor.RESET}")
            return []

        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 找到{len(matched_jsons)}条作业JSON数据{LogColor.RESET}")

        # 解析作业信息
        all_works = []
        seen_file_paths = set()
        url_pattern = r'https://[\d\w]*.ztytech.com/CA103001/SingleUpload/(.*)'

        for json_str in matched_jsons:
            try:
                work_data = json.loads(json_str)
                # 合并各类作业列表
                all_work_entries = (
                    work_data.get("latestWorkList", []) +
                    work_data.get("topWorkList", []) +
                    work_data.get("topExamList", [])
                )

                for work in all_work_entries:
                    work_name = work.get("name", f"未知作业_{int(time.time())}")
                    content_url = work.get("preDownloadUrls", "")
                    subject_id = work.get("subject", "default")
                    upto_time = work.get("uptoTime", "")  # 获取截止时间

                    if not content_url:
                        continue

                    # 提取文件路径
                    match = re.search(url_pattern, content_url)
                    if match:
                        file_path = match.group(1).split('?')[0]
                        if file_path in seen_file_paths:
                            continue
                        seen_file_paths.add(file_path)

                        # 构建作业信息
                        all_works.append({
                            'file_path': file_path,
                            'work_name': work_name,
                            'subject_id': subject_id,
                            'upto_time': upto_time,
                            'scan_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 发现作业 {work_name} (科目: {subject_id}){LogColor.RESET}")

            except json.JSONDecodeError:
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] JSON解析失败{LogColor.RESET}")
                continue

        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [日志提取] 成功提取{len(all_works)}个作业信息{LogColor.RESET}")
        return all_works

    except FileNotFoundError:
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 日志文件不存在 {log_file_path}{LogColor.RESET}") # pyright: ignore[reportPossiblyUnboundVariable]
        return []
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] 失败：{str(e)}{LogColor.RESET}")
        return []

def process_work_file(file_path, work_name, subject_id, upto_time, date_str):
    """处理单个作业文件并提取详细信息"""
    # 检查文件是否存在
    input_path = f"{FILE_BASE_DIR}/{date_str}/{file_path}"
    if not os.path.exists(input_path):
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [文件处理] 文件不存在：{input_path}{LogColor.RESET}")
        return None

    print(f"{LogColor.INFO}[{get_time_stamp()}] [文件处理] 开始处理：{file_path}（{work_name}）{LogColor.RESET}")

    # 读取并解析JSON
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件处理] 无效JSON：{file_path}{LogColor.RESET}")
        return None
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件处理] 读取失败：{str(e)}{LogColor.RESET}")
        return None

    # 提取作业详情
    work_details = {
        'work_name': work_name,
        'subject_id': subject_id,
        'upto_time': upto_time,
        'scan_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'file_path': file_path,
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
        qn += 1
        answers = answers_by_question.get(qid, [])

        # 处理题目内容
        stem_content = process_html_content(question.get('stemContent', ''), answers)
        explain_content = process_html_content(question.get('explainContent', ''))
        has_children = qid in parent_to_children

        question_data = {
            'question_id': qid,
            'question_number': qn,
            'stem_content': stem_content,
            'explain_content': explain_content,
            'has_children': has_children,
            'answers': [],
            'sub_questions': []
        }

        # 添加答案
        for answer in answers:
            question_data['answers'].append({
                'answer_content': process_html_content(answer['answerContent']),
                'index': answer.get('index', 0)
            })

        # 处理子题目
        if has_children:
            sub_questions = parent_to_children[qid]
            sub_qn = 1
            for sub_question in sub_questions:
                sub_qid = sub_question['questionId']
                sub_answers = answers_by_question.get(sub_qid, [])
                sub_stem_content = process_html_content(sub_question.get('stemContent', ''), sub_answers)
                sub_explain_content = process_html_content(sub_question.get('explainContent', ''))

                sub_question_data = {
                    'question_id': sub_qid,
                    'question_number': f"{qn}.{sub_qn}",
                    'stem_content': sub_stem_content,
                    'explain_content': sub_explain_content,
                    'answers': []
                }

                # 添加子题目答案
                for answer in sub_answers:
                    sub_question_data['answers'].append({
                        'answer_content': process_html_content(answer['answerContent']),
                        'index': answer.get('index', 0)
                    })

                question_data['sub_questions'].append(sub_question_data)
                sub_qn += 1

        work_details['questions'].append(question_data)

    print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [处理成功] 提取作业详情：{work_name}{LogColor.RESET}")
    return work_details

# ---------------------- 扫描任务 ----------------------
def perform_scan():
    """执行作业扫描与处理"""
    global scan_in_progress, last_scan_time, current_date_str

    if scan_in_progress:
        return

    scan_in_progress = True
    print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 开始扫描作业...{LogColor.RESET}")

    try:
        # 检查是否需要跨月切换目录
        new_date_str = datetime.now().strftime("%Y%m")
        if new_date_str != current_date_str:
            current_date_str = new_date_str
            print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [跨月更新] 切换年月目录至：{current_date_str}{LogColor.RESET}")

        # 加载已处理记录和作业信息
        processed_works = data_manager.load_processed_works(current_date_str)
        works_info = data_manager.load_works_info(current_date_str)

        # 提取作业信息
        works = extract_work_info()
        processed_count = 0

        # 处理每个作业
        for work in works:
            if work['file_path'] in processed_works:
                print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 跳过已处理：{work['file_path']}{LogColor.RESET}")
                continue

            # 处理作业文件
            work_details = process_work_file(
                work['file_path'], 
                work['work_name'],
                work['subject_id'],
                work['upto_time'],
                current_date_str
            )

            if work_details:
                # 生成唯一作业ID
                work_id = sanitize_filename(work['work_name'])

                # 保存作业详情
                if data_manager.save_work_details(current_date_str, work_id, work_details):
                    # 更新作业信息
                    works_info['works'].append({
                        'work_id': work_id,
                        'work_name': work['work_name'],
                        'subject_id': work['subject_id'],
                        'upto_time': work['upto_time'],
                        'scan_time': work['scan_time'],
                        'work_date': datetime.now().strftime("%Y%m%d")  # 使用扫描日期作为作业日期
                    })

                    # 更新已处理记录
                    processed_works.add(work['file_path'])
                    processed_count += 1

        # 保存更新后的数据
        if processed_count > 0:
            data_manager.save_works_info(current_date_str, works_info)
            data_manager.save_processed_works(current_date_str, processed_works)
            last_scan_time = int(time.time())
            print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [扫描任务] 成功处理{processed_count}个作业{LogColor.RESET}")
        else:
            print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 未发现新作业{LogColor.RESET}")

    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [扫描任务] 执行失败：{str(e)}{LogColor.RESET}")
    finally:
        scan_in_progress = False

# ---------------------- 扫描循环任务 ----------------------
def scan_loop():
    """扫描循环，支持定时扫描"""
    global scan_in_progress
    while True:
        try:
            if not scan_in_progress:
                perform_scan()

            # 等待检查间隔
            time.sleep(config_manager.get_check_interval())
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [扫描循环] 错误：{str(e)}{LogColor.RESET}")
            time.sleep(60)  # 出错时等待1分钟再重试

# ---------------------- Flask路由 ----------------------
@app.route('/')
def main_page():
    """主页面"""
    return render_template('main_page.html')

@app.route('/work/<date_str>/<work_id>')
def work_page(date_str, work_id):
    """作业详情页面"""
    return render_template('work_page.html', date_str=date_str[:6], work_id=work_id)

@app.route('/api/config')
def get_config():
    """获取配置信息"""
    return jsonify(config_manager.config)

@app.route('/api/config/reload', methods=['POST'])
def reload_config():
    """重新加载配置"""
    config_manager.load_config()
    return jsonify({'status': 'success', 'message': '配置已重新加载'})

@app.route('/es5/<path:filename>')
def serve_es5_files(filename):
    """提供es5目录下的静态文件（包括MathJax）"""
    es5_dir = "/storage/emulated/0/1/answers/es5"
    try:
        return send_from_directory(es5_dir, filename)
    except FileNotFoundError:
        return "File not found", 404

@app.route('/api/status')
def get_status():
    """获取服务器状态"""
    last_scan_time_str = "从未扫描"
    if last_scan_time > 0:
        last_scan_dt = datetime.fromtimestamp(last_scan_time)
        last_scan_time_str = last_scan_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 计算总作业数
    total_works = 0
    try:
        # 获取所有月份的作业信息
        if os.path.exists(OUTPUT_BASE_DIR):
            for month_dir in os.listdir(OUTPUT_BASE_DIR):
                if len(month_dir) == 6 and month_dir.isdigit():  # 年月目录
                    works_info = data_manager.load_works_info(month_dir)
                    total_works += len(works_info.get('works', []))
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [状态] 计算总作业数失败：{str(e)}{LogColor.RESET}")

    status = {
        'last_scan_time': last_scan_time,
        'last_scan_time_str': last_scan_time_str,
        'check_interval': config_manager.get_check_interval(),
        'scan_in_progress': scan_in_progress,
        'total_works': total_works,
        'current_date_str': current_date_str
    }

    return jsonify(status)

@app.route('/api/scan', methods=['POST'])
def trigger_scan():
    """触发扫描"""
    global scan_in_progress

    if scan_in_progress:
        return jsonify({'status': 'error', 'message': '扫描正在进行中'})

    # 在后台线程中执行扫描
    threading.Thread(target=perform_scan, daemon=True).start()

    return jsonify({'status': 'success', 'message': '扫描已开始'})

@app.route('/api/works')
def get_works():
    """获取指定日期的作业列表"""
    date_param = request.args.get('date', '')
    if not date_param:
        return jsonify([])

    # 将YYYY-MM-DD转换为YYYYMMDD
    search_date = date_param.replace('-', '')
    works_data = []

    # 查找对应月份的作业
    month_str = search_date[:6]  # 年月部分
    works_info = data_manager.load_works_info(month_str)

    for work in works_info.get('works', []):
        # 检查作业日期是否匹配
        if work.get('work_date', '').startswith(search_date):
            subject_info = config_manager.get_subject_info(work['subject_id'])
            works_data.append({
                'work_id': work['work_id'],
                'work_name': work['work_name'],
                'subject_id': work['subject_id'],
                'subject_name': subject_info['name'],
                'subject_color': subject_info['color'],
                'subject_short': subject_info['short'],
                'upto_time': work.get('upto_time', ''),
                'scan_time': work['scan_time']
            })

    return jsonify(works_data)

@app.route('/api/work/<date_str>/<work_id>')
def get_work_details(date_str, work_id):
    """获取作业详情"""
    work_details = data_manager.load_work_details(date_str[:6], work_id)
    if not work_details:
        return jsonify({'error': '作业不存在'}), 404

    # 添加科目信息
    subject_info = config_manager.get_subject_info(work_details['subject_id'])
    work_details['subject_info'] = subject_info

    return jsonify(work_details)

@app.route('/api/calendar')
def get_calendar_data():
    """获取日历数据（有作业的日期）"""
    # 获取最近3个月的数据
    calendar_data = {}
    today = datetime.now()

    for i in range(3):
        date = today - timedelta(days=30 * i)
        month_str = date.strftime("%Y%m")

        works_info = data_manager.load_works_info(month_str)
        month_data = {}

        for work in works_info.get('works', []):
            work_date = work.get('work_date', '')
            if work_date:
                # 转换为YYYY-MM-DD格式
                formatted_date = f"{work_date[:4]}-{work_date[4:6]}-{work_date[6:8]}"
                if formatted_date not in month_data:
                    month_data[formatted_date] = 0
                month_data[formatted_date] += 1

        calendar_data[month_str] = month_data

    return jsonify(calendar_data)

# ---------------------- 程序入口 ----------------------
if __name__ == "__main__":
    # 启动扫描循环线程
    scan_thread = threading.Thread(target=scan_loop, daemon=True)
    scan_thread.start()

    print(f"{LogColor.BOLD}{LogColor.INFO}[{get_time_stamp()}] ===== 自动答案提取系统 (Flask版) ====={LogColor.RESET}")
    print(f"{LogColor.SUCCESS}[{get_time_stamp()}] 服务器启动，地址：http://localhost:5000{LogColor.RESET}")
    print(f"{LogColor.INFO}[{get_time_stamp()}] 检查间隔：{config_manager.get_check_interval()}秒{LogColor.RESET}")

    # 启动Flask应用
    app.run(host='0.0.0.0', port=8001, debug=False)