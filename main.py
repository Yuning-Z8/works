import json
import os
import re
import time
import threading
import html
import http.server
import socketserver
import urllib.parse
from datetime import datetime


# ---------------------- 常量与配置 ----------------------
class LogColor:
    """ANSI终端颜色常量"""
    RESET = "\033[0m"
    INFO = "\033[34m"
    SUCCESS = "\033[32m"
    WARNING = "\033[33m"
    ERROR = "\033[31m"
    BOLD = "\033[1m"


SUBJECT_CONFIG = {
    "1": {"name": "语文", "color": "#E67E22", "short": "语"},    # 降低亮度的橙色，适配基准
    "2": {"name": "数学", "color": "#4D7CFF", "short": "数"},    # 基准色，保持不变
    "3": {"name": "英语", "color": "#F1C40F", "short": "英"},    # 降低亮度的黄色，匹配基准
    "7": {"name": "物理", "color": "#54B4FF", "short": "物"},    # 基准色，保持不变
    "8": {"name": "化学", "color": "#B74093", "short": "化"},    # 基准色，保持不变
    "13": {"name": "通用技术", "color": "#2ECC71", "short": "通"},  # 降低亮度的绿色，适配基准
    "15": {"name": "信息技术", "color": "#00BCD4", "short": "信"},  # 降低亮度的青色，适配基准
    "default": {"name": "未知", "color": "#A0A0A0", "short": "未"}  # 微调灰色亮度，贴合整体
}

# 路径常量
LOG_BASE_DIR = "/storage/emulated/0/XHLocalLog/5210/1364978/"
FILE_BASE_DIR = "/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/"
OUTPUT_BASE_DIR = "/storage/emulated/0/1/answers"
STATE_FILE_PATH = f"{OUTPUT_BASE_DIR}/state.json"
JSON_COUNT_LOG_PATH = f"{OUTPUT_BASE_DIR}/json_processed_count.json"


# ---------------------- 全局状态管理 ----------------------
class GlobalState:
    """管理应用程序持久化状态"""

    def __init__(self):
        self.last_scan_time = 0
        self.check_interval = 1200  # 默认1200秒
        self.scan_in_progress = False
        self.works_data = []
        self.processed_files = set()  # 已处理文件记录
        self.processed_json_count = 0  # 新增：已处理JSON计数
        self.current_date_str = datetime.now().strftime("%Y%m")  # 新增：当前年月
        self.load_state()

    def load_state(self):
        """从文件加载状态"""
        try:
            if os.path.exists(STATE_FILE_PATH):
                with open(STATE_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.last_scan_time = data.get('last_scan_time', 0)
                    self.check_interval = data.get('check_interval', 60)
                    self.works_data = data.get('works_data', [])
                    self.processed_files = set(data.get('processed_files', []))

                # 加载JSON处理计数
                self.processed_json_count = self.load_json_processed_count()
                print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [状态] 已加载持久化状态{LogColor.RESET}")
            else:
                print(f"{LogColor.INFO}[{get_time_stamp()}] [状态] 无持久化状态，使用默认值{LogColor.RESET}")
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [状态] 加载失败：{str(e)}{LogColor.RESET}")

    def save_state(self):
        """保存状态到文件"""
        try:
            os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)
            data = {
                'last_scan_time': self.last_scan_time,
                'check_interval': self.check_interval,
                'works_data': self.works_data,
                'processed_files': list(self.processed_files),
                'last_save_time': time.time(),
                'current_date_str': self.current_date_str
            }
            with open(STATE_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # 保存JSON处理计数
            self.save_json_processed_count()
            print(f"{LogColor.INFO}[{get_time_stamp()}] [状态] 状态已保存{LogColor.RESET}")
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [状态] 保存失败：{str(e)}{LogColor.RESET}")

    def load_json_processed_count(self):
        """加载已处理的JSON条数记录（跨日自动清零）"""
        today = get_today_date_str()
        if os.path.exists(JSON_COUNT_LOG_PATH):
            try:
                with open(JSON_COUNT_LOG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("last_processed_date") == today:
                        return data.get("processed_json_count", 0)
                    else:
                        print(f"{LogColor.INFO}[{get_time_stamp()}] [跨日清零] 日期变更，已处理JSON条数重置为0{LogColor.RESET}")
                        self.save_json_processed_count(0)
                        return 0
            except:
                return 0
        return 0

    def save_json_processed_count(self, count=None):
        """保存已处理的JSON条数记录（包含日期标记）"""
        if count is not None:
            self.processed_json_count = count

        data = {
            "processed_json_count": self.processed_json_count,
            "last_processed_date": get_today_date_str()
        }

        with open(JSON_COUNT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"{LogColor.INFO}[{get_time_stamp()}] [JSON记录] 已记录处理JSON条数：{self.processed_json_count}{LogColor.RESET}")


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
    time_suffix = datetime.now().strftime("%d%H")
    return f"{time_suffix}_{filename.strip()}"


def get_subject_info(subject_id):
    """根据学科ID获取学科信息"""
    return SUBJECT_CONFIG.get(str(subject_id), SUBJECT_CONFIG["default"])


# ---------------------- 作业信息处理 ----------------------
def extract_work_info():
    """从日志文件提取作业信息，只处理新增的JSON数据"""
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
            return [], len(matched_jsons)

        total_jsons = len(matched_jsons)
        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 找到{total_jsons}条作业JSON数据，已处理{global_state.processed_json_count}条{LogColor.RESET}")

        # 只处理新增的JSON数据
        if global_state.processed_json_count >= total_jsons:
            print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 没有新的JSON数据需要处理{LogColor.RESET}")
            return [], total_jsons

        # 解析作业信息
        all_works = []
        seen_file_paths = set()
        url_pattern = r'https://[\d\w]*.ztytech.com/CA103001/SingleUpload/(.*)'

        # 从已处理位置开始遍历新增的JSON
        for idx, json_str in enumerate(matched_jsons[global_state.processed_json_count:], 
                                      global_state.processed_json_count + 1):
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
                        subject_info = get_subject_info(subject_id)
                        all_works.append({
                            'file_path': file_path,
                            'work_name': work_name,
                            'subject_id': subject_id,
                            'subject_name': subject_info['name'],
                            'subject_color': subject_info['color'],
                            'subject_short': subject_info['short'],
                            'scan_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 发现作业 {work_name} ({subject_info['name']}){LogColor.RESET}")

            except json.JSONDecodeError:
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] 第{idx}条JSON解析失败{LogColor.RESET}")
                continue

        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [日志提取] 成功提取{len(all_works)}个作业信息{LogColor.RESET}")
        return all_works, total_jsons

    except FileNotFoundError:
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 日志文件不存在 {log_file_path}{LogColor.RESET}") # type: ignore
        return [], 0
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] 失败：{str(e)}{LogColor.RESET}")
        return [], 0


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

    # 处理图片
    text = re.sub(
        r'<img[^>]*src="([^"]*)"[^>]*>',
        r'<img src="\1" style="max-width: 100%; height: auto; margin: 10px 0;">',
        text
    )

    # 处理<answer>标签 - 填入答案
    if answers:
        # 对答案按索引排序
        sorted_answers = sorted(answers, key=lambda x: x.get('index', 0))

        def replace_answer(match):
            answer_index = int(match.group(1))
            if answer_index < len(sorted_answers):
                answer_content = sorted_answers[answer_index]['answerContent']
                # 清理答案内容
                clean_answer = re.sub(r'<[^>]+>', '', answer_content)  # 移除HTML标签
                clean_answer = html.unescape(clean_answer).strip()
                return f'<span class="answer-text" id="inline-answer-{answer_index}">{clean_answer}</span><button class="copy-btn" onclick="copyAnswer(\"inline-answer-{answer_index}\")">复制</button>'
            return match.group(0)

        # 替换<answer>标签
        text = re.sub(r'<answer>(\d+)</answer>', replace_answer, text)

    return text


def process_work_file(file_path, work_name, date_str):
    """处理单个作业文件并生成HTML"""
    # 检查文件是否存在
    input_path = f"{FILE_BASE_DIR}/{date_str}/{file_path}"
    if not os.path.exists(input_path):
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [文件处理] 文件不存在：{input_path}{LogColor.RESET}")
        return None

    # 检查是否已处理
    if file_path in global_state.processed_files:
        print(f"{LogColor.INFO}[{get_time_stamp()}] [文件处理] 已处理文件：{file_path}{LogColor.RESET}")
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

    # 准备输出路径
    output_dir = f"{OUTPUT_BASE_DIR}/{date_str}"
    os.makedirs(output_dir, exist_ok=True)
    html_filename = f"{sanitize_filename(work_name)}.html"
    html_output_path = f"{output_dir}/{html_filename}"

    # 生成HTML内容
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

    # HTML内容生成
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{work_name}</title>
        <script src="/es5/tex-mml-chtml.js"></script>
        <script>
            MathJax = {{
                tex: {{
                    inlineMath: [['$', '$'], ['\\(', '\\)']],
                    packages: {{'[+]': ['ams', 'boldsymbol', 'amsmath']}}
                }},
                svg: {{
                    fontCache: 'global'
                }}
            }};
        </script>
        <style>
            body {{
                font-family: "Microsoft YaHei", Arial, sans-serif;
                line-height: 1.8;
                margin: 20px auto;
                padding: 0 15px;
                max-width: 850px;
            }}
            .question {{ margin-bottom: 25px; padding: 15px; border-left: 4px solid #4CAF50; background-color: #f9f9f9; border-radius: 0 4px 4px 0; }}
            .question-number {{ font-weight: bold; color: #2E7D32; font-size: 1.05em; margin-bottom: 8px; }}
            .stem {{ margin-bottom: 15px; }}
            .answer {{ padding: 10px; background-color: #e8f5e9; border-radius: 4px; margin-bottom: 10px; }}
            .answer-text {{ color: #d32f2f; font-weight: bold; }}  /* 答案文字改为红色 */
            .copy-btn {{
                background: #4CAF50;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 3px;
                cursor: pointer;
                font-size: 12px;
                margin-left: 8px;
            }}
            .copy-btn:hover {{ background: #45a049; }}
            .explanation {{ 
                margin-top: 10px;
                border-radius: 4px;
                overflow: hidden;
            }}
            .explanation summary {{
                padding: 10px;
                background-color: #e3f2fd;
                font-weight: bold;
                cursor: pointer;
            }}
            .explanation details {{
                padding: 10px;
                background-color: #f0f7ff;
            }}
            .blank-answer {{ margin: 5px 0; padding-left: 15px; }}
            .blank-number {{ font-weight: bold; color: #d32f2f; }}
            .sub-question {{ margin-left: 20px; border-left: 2px solid #FF9800; padding-left: 15px; }}
            .sub-question-number {{ font-weight: bold; color: #FF9800; }}
            img {{ border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            .MathJax {{ line-height: 1.5 !important; }}
        </style>
    </head>
    <body>
        <h1 style="text-align: center; color: #2E7D32;">{work_name}</h1>
    """

    qn = 0
    for question in top_level_questions:
        qid = question['questionId']
        qn += 1
        # 修改：传入答案列表到process_html_content
        answers = answers_by_question.get(qid, [])
        stem_content = process_html_content(question.get('stemContent', ''), answers)
        explain_content = process_html_content(question.get('explainContent', ''))
        has_children = qid in parent_to_children

        html_content += f"""
        <div class="question">
            <div class="question-number">{qn}:</div>
            <div class="stem">{stem_content}</div>"""

        if not has_children and answers:
            html_content += "<div class='answer'>"
            answers.sort(key=lambda x: x.get('index', 0))
            if len(answers) == 1:
                answer_content = process_html_content(answers[0]['answerContent'])
                # 修改答案显示，添加红色样式和复制按钮
                html_content += f"<div>答案: <span class='answer-text' id='answer-{qid}'>{answer_content}</span><button class='copy-btn' onclick='copyAnswer(\"answer-{qid}\")'>复制</button></div>"
            else:
                html_content += "<div>答案:</div>"
                for i, answer in enumerate(answers):
                    answer_content = process_html_content(answer['answerContent'])
                    blank_num = i + 1
                    html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> <span class='answer-text' id='answer-{qid}-{i}'>{answer_content}</span><button class='copy-btn' onclick='copyAnswer(\"answer-{qid}-{i}\")'>复制</button></div>"
            html_content += "</div>"

        if explain_content and explain_content.strip() not in ["", "<p>无</p>"]:
            html_content += f"""
            <details class="explanation" onToggle="toggleExplanation(this)">
                <summary>展开解析</summary>
                <div>{explain_content}</div>
            </details>"""

        if has_children:
            sub_questions = parent_to_children[qid]
            sub_qn = 1
            for sub_question in sub_questions:
                sub_qid = sub_question['questionId']
                sub_answers = answers_by_question.get(sub_qid, [])
                # 修改：传入答案列表到process_html_content
                sub_stem_content = process_html_content(sub_question.get('stemContent', ''), sub_answers)
                sub_explain_content = process_html_content(sub_question.get('explainContent', ''))

                html_content += f"""
                <div class="sub-question">
                    <div class="sub-question-number">{qn}.{sub_qn}:</div>
                    <div class="stem">{sub_stem_content}</div>"""

                if sub_answers:
                    html_content += "<div class='answer'>"
                    sub_answers.sort(key=lambda x: x.get('index', 0))
                    if len(sub_answers) == 1:
                        answer_content = process_html_content(sub_answers[0]['answerContent'])
                        html_content += f"<div>答案: <span class='answer-text' id='answer-{sub_qid}'>{answer_content}</span><button class='copy-btn' onclick='copyAnswer(\"answer-{sub_qid}\")'>复制</button></div>"
                    else:
                        html_content += "<div>答案:</div>"
                        for i, answer in enumerate(sub_answers):
                            answer_content = process_html_content(answer['answerContent'])
                            blank_num = i + 1
                            html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> <span class='answer-text' id='answer-{sub_qid}-{i}'>{answer_content}</span><button class='copy-btn' onclick='copyAnswer(\"answer-{sub_qid}-{i}\")'>复制</button></div>"
                    html_content += "</div>"

                if sub_explain_content and sub_explain_content.strip() not in ["", "<p>无</p>"]:
                    html_content += f"""
                    <details class="explanation" onToggle="toggleExplanation(this)">
                        <summary>展开解析</summary>
                        <div>{sub_explain_content}</div>
                    </details>"""

                html_content += "</div>"
                sub_qn += 1

        html_content += "</div>"

    # 添加复制功能和解析切换功能
    html_content += """
        <script>
            // 复制答案功能
            function copyAnswer(elementId) {
                const element = document.getElementById(elementId);
                const text = element.innerText || element.textContent;

                // 创建临时textarea元素
                const textarea = document.createElement('textarea');
                textarea.value = text;
                document.body.appendChild(textarea);

                // 选中并复制文本
                textarea.select();
                textarea.setSelectionRange(0, 99999); // 对于移动设备

                try {
                    const successful = document.execCommand('copy');
                    const btn = element.nextElementSibling;
                    const originalText = btn.textContent;
                    btn.textContent = '已复制!';
                    setTimeout(() => {
                        btn.textContent = originalText;
                    }, 2000);
                } catch (err) {
                    console.error('复制失败:', err);
                }

                // 清理
                document.body.removeChild(textarea);
            }

            // 切换解析显示文字
            function toggleExplanation(details) {
                const summary = details.querySelector('summary');
                if (details.open) {
                    summary.textContent = '收起解析';
                } else {
                    summary.textContent = '展开解析';
                }
            }

            window.addEventListener('load', function() {
                MathJax.typeset();
                // 初始化所有解析按钮状态
                document.querySelectorAll('.explanation').forEach(exp => {
                    const summary = exp.querySelector('summary');
                    if (!exp.open) {
                        summary.textContent = '展开解析';
                    }
                });
            });
        </script>
    </body>
    </html>
    """

    # 写入HTML文件
    try:
        with open(html_output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        global_state.processed_files.add(file_path)
        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [处理成功] 生成文件：{html_output_path}{LogColor.RESET}")
        return f"{date_str}/{html_filename}"
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [处理失败] 写入文件出错：{str(e)}{LogColor.RESET}")
        return None


# ---------------------- 扫描任务 ----------------------
def perform_scan():
    """执行作业扫描与处理"""
    global global_state
    if global_state.scan_in_progress:
        return

    global_state.scan_in_progress = True
    print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 开始扫描作业...{LogColor.RESET}")

    try:
        # 提取作业信息
        works, total_jsons = extract_work_info()
        processed_works = []

        # 更新已处理的JSON条数
        if global_state.processed_json_count != total_jsons:
            global_state.save_json_processed_count(total_jsons)

        # 处理每个作业
        for work in works:
            if work['file_path'] in global_state.processed_files:
                print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 跳过已处理：{work['file_path']}{LogColor.RESET}")
                continue

            html_path = process_work_file(
                work['file_path'], 
                work['work_name'], 
                global_state.current_date_str
            )

            if html_path:
                processed_work = work.copy()
                processed_work['html_path'] = html_path
                processed_work['file_url'] = f"/files/{html_path}"
                processed_works.append(processed_work)

        # 更新状态
        if processed_works:
            global_state.works_data.extend(processed_works)
            global_state.last_scan_time = int(time.time())
            global_state.save_state()
            print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [扫描任务] 成功处理{len(processed_works)}个作业{LogColor.RESET}")
        else:
            print(f"{LogColor.INFO}[{get_time_stamp()}] [扫描任务] 未发现新作业{LogColor.RESET}")

    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [扫描任务] 执行失败：{str(e)}{LogColor.RESET}")
    finally:
        global_state.scan_in_progress = False


# ---------------------- 本地HTTP服务器 ----------------------
class WorkServerHandler(http.server.SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器"""

    def do_GET(self):
        """处理GET请求路由"""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            self.send_main_page()
        elif path == '/api/works':
            self.send_works_data()
        elif path == '/api/scan':
            # 只允许本机进行扫描
            if not self.is_localhost():
                self.send_error(403, "只允许本机进行扫描操作")
                print(f"{LogColor.WARNING}[{get_time_stamp()}] [安全拦截] 非本机扫描请求来自: {self.client_address[0]}{LogColor.RESET}")
                return
            self.trigger_scan()
        elif path == '/api/status':
            self.send_status()
        elif path.startswith('/files/'):
            self.serve_static_file()
        elif path == '/es5/tex-mml-chtml.js':
            self.serve_mathjax()
        else:
            self.send_error(404, "File not found")

    def is_localhost(self):
        """检查请求是否来自本机"""
        client_ip = self.client_address[0]
        return client_ip == '127.0.0.1' or client_ip == 'localhost' or client_ip == '::1'

    def serve_static_file(self):
        """提供生成的HTML文件服务"""
        try:
            # 移除/files/前缀，构建实际文件路径
            file_path = self.path[7:]  # 移除 '/files/'

            # 添加调试信息
            print(f"{LogColor.INFO}[{get_time_stamp()}] [文件服务] 请求路径: {file_path}{LogColor.RESET}")

            file_path = urllib.parse.unquote(file_path)
            full_path = os.path.join(OUTPUT_BASE_DIR, file_path)

            # 添加调试信息
            print(f"{LogColor.INFO}[{get_time_stamp()}] [文件服务] 完整路径: {full_path}{LogColor.RESET}")
            print(f"{LogColor.INFO}[{get_time_stamp()}] [文件服务] 文件存在: {os.path.exists(full_path)}{LogColor.RESET}")

            # 安全检查：确保路径在输出目录内
            if not os.path.abspath(full_path).startswith(os.path.abspath(OUTPUT_BASE_DIR)):
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件服务] 路径安全检查失败{LogColor.RESET}")
                self.send_error(403, "Access denied")
                return

            if os.path.exists(full_path) and os.path.isfile(full_path):
                with open(full_path, 'rb') as f:
                    content = f.read()

                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [文件服务] 成功发送文件{LogColor.RESET}")
            else:
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件服务] 文件不存在{LogColor.RESET}")
                self.send_error(404, "File not found")

        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件服务] 错误: {str(e)}{LogColor.RESET}")
            self.send_error(500, f"Server error: {str(e)}")

    def serve_mathjax(self):
        """提供MathJax脚本服务"""
        mathjax_path = "/storage/emulated/0/1/answers/es5/tex-mml-chtml.js"
        try:
            print(f"{LogColor.INFO}[{get_time_stamp()}] [MathJax] 请求MathJax文件{LogColor.RESET}")
            print(f"{LogColor.INFO}[{get_time_stamp()}] [MathJax] 文件路径: {mathjax_path}{LogColor.RESET}")
            print(f"{LogColor.INFO}[{get_time_stamp()}] [MathJax] 文件存在: {os.path.exists(mathjax_path)}{LogColor.RESET}")

            if os.path.exists(mathjax_path):
                with open(mathjax_path, 'rb') as f:
                    content = f.read()

                self.send_response(200)
                self.send_header('Content-type', 'application/javascript')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [MathJax] 成功发送MathJax文件{LogColor.RESET}")
            else:
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [MathJax] MathJax文件不存在{LogColor.RESET}")
                self.send_error(404, "MathJax not found")
        except Exception as e:
            print(f"{LogColor.ERROR}[{get_time_stamp()}] [MathJax] 错误: {str(e)}{LogColor.RESET}")
            self.send_error(500, f"MathJax error: {str(e)}")

    def send_main_page(self):
        """发送主页面HTML，非本机隐藏扫描按钮"""
        try:
            with open('main_page.html', 'r', encoding='utf-8') as file:
                html_content = file.read()

                # 如果不是本机访问，隐藏扫描按钮
                if not self.is_localhost():
                    # 使用JavaScript隐藏扫描按钮
                    hide_script = """
                    <script>
                        document.addEventListener('DOMContentLoaded', function() {
                            const scanBtn = document.getElementById('scanBtn');
                            if (scanBtn) {
                                scanBtn.style.display = 'none';
                            }
                        });
                    </script>
                    """
                    # 在body结束前插入隐藏脚本
                    html_content = html_content.replace('</body>', hide_script + '</body>')

                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
        except Exception as e:
            error_html = f"<html><body><h1>主页面加载失败</h1><p>{str(e)}</p></body></html>"
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(error_html.encode('utf-8'))

    def send_works_data(self):
        """发送指定日期的作业数据"""
        query_params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        date_param = query_params.get('date', [None])[0]
        works_data = self.get_works_by_date(date_param)

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(works_data).encode('utf-8'))

    def trigger_scan(self):
        """触发后台扫描任务"""
        threading.Thread(target=perform_scan, daemon=True).start()

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'scan_started'}).encode('utf-8'))

    def send_status(self):
        """发送服务器状态信息"""
        last_scan_time_str = "从未扫描"
        if global_state.last_scan_time > 0:
            last_scan_dt = datetime.fromtimestamp(global_state.last_scan_time)
            last_scan_time_str = last_scan_dt.strftime("%Y-%m-%d %H:%M:%S")

        status = {
            'last_scan_time': global_state.last_scan_time,
            'last_scan_time_str': last_scan_time_str,
            'check_interval': global_state.check_interval,
            'scan_in_progress': global_state.scan_in_progress,
            'total_works': len(global_state.works_data),
            'processed_json_count': global_state.processed_json_count
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(status).encode('utf-8'))

    def get_works_by_date(self, date_str):
        """根据日期筛选作业数据"""
        if not date_str:
            return []

        search_date = date_str.replace('-', '')
        works_data = []

        for work in global_state.works_data:
            html_path = work.get('html_path', '')
            if not html_path:
                continue

            path_parts = html_path.split('/')
            if len(path_parts) < 2:
                continue

            path_date = path_parts[0]  # 年月部分(202510)
            file_name = path_parts[1]  # 文件名(0918_作业名.html)

            if '_' in file_name:
                date_part = file_name.split('_')[0]
                full_date = path_date + date_part  # 组合完整日期
                if full_date[:8] == search_date:
                    works_data.append({
                        'work_name': work['work_name'],
                        'subject_name': work['subject_name'],
                        'subject_color': work['subject_color'],
                        'subject_short': work['subject_short'],
                        'scan_time': work['scan_time'],
                        'file_url': work['file_url']
                    })

        return works_data

    def generate_main_html(self):
        """生成主页面HTML"""
        try:
            with open('main_page.html', 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            return f"<html><body><h1>主页面加载失败</h1><p>{str(e)}</p></body></html>"

    def log_message(self, format, *args):
        """重写日志方法，使用彩色日志"""
        print(f"{LogColor.INFO}[{get_time_stamp()}] [HTTP] {format % args}{LogColor.RESET}")


# ---------------------- 扫描循环任务 ----------------------
def scan_loop():
    """扫描循环，支持定时扫描和手动触发"""
    global global_state
    while True:
        # 检查是否需要跨月切换目录
        new_date_str = datetime.now().strftime("%Y%m")
        if new_date_str != global_state.current_date_str:
            global_state.current_date_str = new_date_str
            global_state.save_state()
            print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [跨月更新] 切换年月目录至：{global_state.current_date_str}{LogColor.RESET}")

        # 执行扫描
        print(f"{LogColor.INFO}[{get_time_stamp()}] [定时扫描] 执行扫描...{LogColor.RESET}")
        perform_scan()

        # 等待检查间隔，期间监听用户输入
        time.sleep(global_state.check_interval)


# ---------------------- 程序入口 ----------------------
if __name__ == "__main__":
    global_state = GlobalState()

    # 启动扫描循环线程
    scan_thread = threading.Thread(target=scan_loop, daemon=True)
    scan_thread.start()

    # 启动HTTP服务器
    PORT = 8000
    Handler = WorkServerHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"{LogColor.BOLD}{LogColor.INFO}[{get_time_stamp()}] ===== 自动答案提取系统 ====={LogColor.RESET}")
        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] 服务器启动，地址：http://localhost:{PORT}{LogColor.RESET}")
        print(f"{LogColor.INFO}[{get_time_stamp()}] 检查间隔：{global_state.check_interval}秒 | 输入任意内容可立即扫描 | 按Ctrl+C停止{LogColor.RESET}")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\n{LogColor.INFO}[{get_time_stamp()}] 服务器已停止{LogColor.RESET}")
            httpd.shutdown()