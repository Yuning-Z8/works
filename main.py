import json
import os
import re
import time
import select
import sys
from datetime import datetime
import html

# ---------------------- ANSI彩色日志常量 ----------------------
class LogColor:
    """ANSI转义序列颜色常量（兼容大多数终端/控制台）"""
    RESET = "\033[0m"       # 重置为默认颜色
    INFO = "\033[34m"       # 蓝色：普通信息
    SUCCESS = "\033[32m"    # 绿色：成功信息
    WARNING = "\033[33m"    # 黄色：警告/提示
    ERROR = "\033[31m"      # 红色：错误信息
    BOLD = "\033[1m"        # 加粗（可选，增强重点）

# ---------------------- 作业信息提取核心函数 ----------------------
def get_today_date_str():
    """获取当前日期字符串（格式：20250920）"""
    return datetime.now().strftime("%Y%m%d")

def get_time_stamp():
    """获取当前时分秒时间戳（格式：hh:mm:ss）"""
    return datetime.now().strftime("%H:%M:%S.%f")

def sanitize_filename(filename):
    """清理文件名中的非法字符+添加时间戳避免冲突"""
    invalid_chars = '/\\:*?"<>|'  # 系统非法字符
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    # 添加时分秒时间戳（避免同名冲突）
    time_suffix = datetime.now().strftime("%d%H")
    return f"{time_suffix}_{filename.strip()}"

def extract_work_with_auto_path(base_dir="/storage/emulated/0/XHLocalLog/5210/1364978/"):
    """从日志提取所有作业信息（彩色日志输出）"""
    try:
        # 1. 自动生成当日日志路径
        today_date = get_today_date_str()
        log_filename = f"作业列表日志{today_date}().txt"
        log_file_path = f"{base_dir.rstrip('/')}/{log_filename}"
        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 读取作业日志：{log_file_path}{LogColor.RESET}")

        # 2. 读取日志（兼容utf-8/gbk编码）
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                log_content = f.read()
        except UnicodeDecodeError:
            with open(log_file_path, 'r', encoding='gbk', errors='ignore') as f:
                log_content = f.read()

        # 3. 匹配日志中所有的作业列表JSON（非贪婪匹配，避免跨条目）
        json_pattern = r'获取首页作业列表：(\{[\s\S]*?\})(?=\n|$)'
        matched_jsons = re.findall(json_pattern, log_content)
        if not matched_jsons:
            print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 未找到任何作业列表JSON数据{LogColor.RESET}")
            return {}, 0
        
        total_jsons = len(matched_jsons)
        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 共找到{total_jsons}条作业列表JSON数据，已处理{processed_json_count}条{LogColor.RESET}")

        # 4. 只处理新增的JSON数据
        if load_json_processed_count(json_count_log_path) >= total_jsons:
            print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 没有新的JSON数据需要处理{LogColor.RESET}")
            return {}, total_jsons

        # 5. 遍历新增的JSON，合并作业信息（去重，保留最新）
        work_info_map = {}  # 键：file_path，值：work_name（最新状态）
        # 优化正则：兼容 xuehaifile 和 xhfs3 域名
        url_prefix = r'https://[\d\w]*.ztytech.com/CA103001/SingleUpload/(.*)'

        for idx, json_str in enumerate(matched_jsons[processed_json_count:], processed_json_count + 1):  # 从已处理位置开始遍历
            try:
                current_json = json.loads(json_str)
                work_list = current_json.get("latestWorkList", [])
                top_work = current_json.get("topWorkList", [])
                top_exam = current_json.get("topExamList", [])
                work_list = work_list + top_work + top_exam
                if not work_list:
                    print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 第{idx}条JSON无作业列表{LogColor.RESET}")
                    continue

                # 提取当前JSON中的作业信息
                for work in work_list:
                    work_name = work.get("name", f"未知作业_{int(time.time())}")
                    content_url = work.get("preDownloadUrls", None)
                    
                    if content_url is None:
                        print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] {work_name} URL为空{LogColor.RESET}")
                        continue
                    match = re.search(url_prefix, content_url)
                    if match:
                        file_path = match.group(1).split('?')[0]
                        print(f"{LogColor.INFO}[{get_time_stamp()}] [日志提取] 发现作业 {work_name}: {file_path}{LogColor.RESET}")
                        work_info_map[file_path] = work_name  # 覆盖旧值，保留最新
                    else:
                        print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] URL匹配失败：{content_url}{LogColor.RESET}")

            except json.JSONDecodeError:
                print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] 第{idx}条JSON解析失败：{json_str[:20]}...{LogColor.RESET}")
                continue

        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [日志提取] 成功合并 {len(work_info_map)} 个作业信息（去重后）{LogColor.RESET}")
        return work_info_map, total_jsons

    except FileNotFoundError:
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [日志提取] 当日日志文件不存在（{log_file_path}）{LogColor.RESET}") # type: ignore
        return {}, 0
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [日志提取] 失败：{str(e)}{LogColor.RESET}")
        return {}, 0

# ---------------------- HTML处理与文件生成 ----------------------
def process_html_content(text):
    """HTML内容修复函数（保持不变）"""
    if text is None:
        return ""
    
    text = html.unescape(text)
    mathquill_pattern = r'<span\s+class="mathquill-embedded-latex"\s*>(.*?)</span>'
    text = re.sub(mathquill_pattern, r'\(\1\)', text, flags=re.DOTALL)
    img_pattern = r'<img[^>]*src="([^"]*)"[^>]*>'
    text = re.sub(
        img_pattern, 
        r'<img src="\1" style="max-width: 100%; height: auto; margin: 10px 0;">', 
        text
    )
    text = re.sub(r'<br\s*/?>', '<br>', text)
    unnecessary_tags_pattern = r'<(?!img|br)\w+[^>]*>'
    text = re.sub(unnecessary_tags_pattern, '', text)
    
    return text

def process_single_file(file_path, work_name, date_str, processed_log):
    """处理单个txt文件（彩色日志输出）"""
    # 1. 构建txt文件完整输入路径
    input_path = f"/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/{date_str}/{file_path}"
    
    # 2. 基础校验
    if not os.path.exists(input_path):
        print(f"{LogColor.WARNING}[{get_time_stamp()}] [文件处理] 跳过：{file_path} 不存在（{input_path}）{LogColor.RESET}")
        return False
    if file_path in processed_log:
        print(f"{LogColor.INFO}[{get_time_stamp()}] [文件处理] 跳过：{file_path} 已处理{LogColor.RESET}")
        return False

    print(f"{LogColor.INFO}[{get_time_stamp()}] [文件处理] 开始处理：{file_path}（作业名：{work_name}）{LogColor.RESET}")

    # 3. 读取txt文件（JSON格式）
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件处理] 跳过：{file_path} 不是有效JSON{LogColor.RESET}")
        return False
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [文件处理] 读取失败：{file_path}（{str(e)}）{LogColor.RESET}")
        return False

    # 4. 构建HTML输出路径
    root_output_dir = "/storage/emulated/0/1/answers"
    date_output_dir = f"{root_output_dir}/{date_str}"
    os.makedirs(date_output_dir, exist_ok=True)
    
    sanitized_work_name = sanitize_filename(work_name)
    html_filename = f"{sanitized_work_name}.html"
    html_output_path = f"{date_output_dir}/{html_filename}"

    # 5. 生成HTML内容（原有逻辑不变）
    answers_by_question = {}
    for answer in data.get('questionAnswers', []):
        qid = answer['questionId']
        if qid not in answers_by_question:
            answers_by_question[qid] = []
        answers_by_question[qid].append(answer)

    question_map = {}
    for question in data.get('questionPoolContentInfos', []):
        qid = question['questionId']
        question_map[qid] = question

    parent_to_children = {}
    for question in data.get('questionPoolContentInfos', []):
        parent_id = question.get('parentQuestionId', '0')
        if parent_id != "0" and parent_id in question_map:
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(question)

    top_level_questions = []
    for question in data.get('questionPoolContentInfos', []):
        parent_id = question.get('parentQuestionId', '0')
        if parent_id == "0" or parent_id not in question_map:
            top_level_questions.append(question)

    html_content = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>题目答案</title>
        <script src="file:///storage/emulated/0/1/answers/es5/tex-mml-chtml.js"></script>
        <script>
            MathJax = {
                tex: {
                    inlineMath: [['$', '$'], ['\\(', '\\)']],
                    packages: {'[+]': ['ams', 'boldsymbol', 'amsmath']}
                },
                svg: {
                    fontCache: 'global'
                }
            };
        </script>
        <style>
            body {
                font-family: "Microsoft YaHei", Arial, sans-serif;
                line-height: 1.8;
                margin: 20px auto;
                padding: 0 15px;
                max-width: 850px;
            }
            .question { margin-bottom: 25px; padding: 15px; border-left: 4px solid #4CAF50; background-color: #f9f9f9; border-radius: 0 4px 4px 0; }
            .question-number { font-weight: bold; color: #2E7D32; font-size: 1.05em; margin-bottom: 8px; }
            .stem { margin-bottom: 15px; }
            .answer { padding: 10px; background-color: #e8f5e9; border-radius: 4px; margin-bottom: 10px; }
            /* 解析部分样式调整 */
            .explanation { 
                margin-top: 10px;
                border-radius: 4px;
                overflow: hidden;
            }
            .explanation summary {
                padding: 10px;
                background-color: #e3f2fd;
                font-weight: bold;
                cursor: pointer;
            }
            .explanation details {
                padding: 10px;
                background-color: #f0f7ff;
            }
            .blank-answer { margin: 5px 0; padding-left: 15px; }
            .blank-number { font-weight: bold; color: #d32f2f; }
            .sub-question { margin-left: 20px; border-left: 2px solid #FF9800; padding-left: 15px; }
            .sub-question-number { font-weight: bold; color: #FF9800; }
            img { border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .MathJax { line-height: 1.5 !important; }
        </style>
    </head>
    <body>
        <h1 style="text-align: center; color: #2E7D32;">题目答案</h1>
    """

    qn = 0
    for question in top_level_questions:
        qid = question['questionId']
        qn += 1
        stem_content = process_html_content(question.get('stemContent', ''))
        explain_content = process_html_content(question.get('explainContent', ''))
        answers = answers_by_question.get(qid, [])
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
                html_content += f"<div>答案: {answer_content}</div>"
            else:
                html_content += "<div>答案:</div>"
                for i, answer in enumerate(answers):
                    answer_content = process_html_content(answer['answerContent'])
                    blank_num = i + 1
                    html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> {answer_content}</div>"
            html_content += "</div>"

        # 修改解析部分为默认折叠
        if explain_content and explain_content.strip() not in ["", "<p>无</p>"]:
            html_content += f"""
            <details class="explanation">
                <summary>点击查看解析</summary>
                <div>{explain_content}</div>
            </details>"""

        if has_children:
            sub_questions = parent_to_children[qid]
            sub_qn = 1
            for sub_question in sub_questions:
                sub_qid = sub_question['questionId']
                sub_stem_content = process_html_content(sub_question.get('stemContent', ''))
                sub_explain_content = process_html_content(sub_question.get('explainContent', ''))
                sub_answers = answers_by_question.get(sub_qid, [])

                html_content += f"""
                <div class="sub-question">
                    <div class="sub-question-number">{qn}.{sub_qn}:</div>
                    <div class="stem">{sub_stem_content}</div>"""

                if sub_answers:
                    html_content += "<div class='answer'>"
                    sub_answers.sort(key=lambda x: x.get('index', 0))
                    if len(sub_answers) == 1:
                        answer_content = process_html_content(sub_answers[0]['answerContent'])
                        html_content += f"<div>答案: {answer_content}</div>"
                    else:
                        html_content += "<div>答案:</div>"
                        for i, answer in enumerate(sub_answers):
                            answer_content = process_html_content(answer['answerContent'])
                            blank_num = i + 1
                            html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> {answer_content}</div>"
                    html_content += "</div>"

                # 子问题解析同样默认折叠
                if sub_explain_content and sub_explain_content.strip() not in ["", "<p>无</p>"]:
                    html_content += f"""
                    <details class="explanation">
                        <summary>点击查看解析</summary>
                        <div>{sub_explain_content}</div>
                    </details>"""

                html_content += "</div>"
                sub_qn += 1

        html_content += "</div>"

    html_content += """
        <script>
            window.addEventListener('load', function() {
                MathJax.typeset();
                // 为所有解析部分添加展开/折叠的动画效果
                document.querySelectorAll('.explanation summary').forEach(summary => {
                    summary.addEventListener('click', function() {
                        const details = this.parentElement;
                        details.style.transition = 'all 0.3s ease';
                    });
                });
            });
        </script>
    </body>
    </html>
    """

    # 6. 写入HTML文件
    try:
        with open(html_output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [处理成功] HTML文件：{html_output_path}{LogColor.RESET}")
        return True
    except Exception as e:
        print(f"{LogColor.ERROR}[{get_time_stamp()}] [处理失败] 写入{html_filename}出错：{str(e)}{LogColor.RESET}")
        return False

# ---------------------- 已处理文件日志管理 ----------------------
def load_processed_log(log_path):
    """加载已处理文件记录"""
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_processed_log(log_path, file_path):
    """记录已处理的文件"""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{file_path}\n")
    print(f"{LogColor.INFO}[{get_time_stamp()}] [日志更新] 已记录处理完成：{file_path}{LogColor.RESET}")

# ---------------------- JSON处理记录管理 ----------------------
# 修改JSON处理记录管理函数（替换原有相关函数）
def load_json_processed_count(log_path):
    """加载已处理的JSON条数记录（跨日自动清零）"""
    today = get_today_date_str()  # 获取当前日期
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 检查记录的日期是否为今天，不是则返回0（清零）
                if data.get("last_processed_date", None) == today:
                    return data.get("processed_json_count", 0)
                else:
                    print(f"{LogColor.INFO}[{get_time_stamp()}] [跨日清零] 日期变更，已处理JSON条数重置为0{LogColor.RESET}")
                    save_json_processed_count(log_path, 0)
                    return 0
        except:
            return 0
    return 0

def save_json_processed_count(log_path, count):
    """保存已处理的JSON条数记录（包含日期标记）"""
    data = {
        "processed_json_count": count,
        "last_processed_date": get_today_date_str()  # 记录当前日期
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"{LogColor.INFO}[{get_time_stamp()}] [JSON记录] 已记录处理JSON条数：{count}（日期：{data['last_processed_date']}）{LogColor.RESET}")

# ---------------------- 输入监听函数 ----------------------
def wait_for_input_with_timeout(timeout):
    """等待用户输入，但最多等待指定的超时时间"""
    print(f"{LogColor.INFO}[{get_time_stamp()}] 输入任意内容可立即扫描...{LogColor.RESET}")
    
    # 使用select监听标准输入
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    
    if ready:
        # 读取输入内容以清空缓冲区
        input_data = sys.stdin.readline()
        return True  # 表示有输入
    else:
        return False  # 表示超时

# ---------------------- 主程序 ----------------------
if __name__ == "__main__":
    # 配置参数
    check_interval = 1000  # 作业检查间隔（秒）
    processed_log_path = "/storage/emulated/0/1/answers/processed_files.log"  # 已处理记录
    json_count_log_path = "/storage/emulated/0/1/answers/json_processed_count.json"  # JSON处理记录
    work_log_base_dir = "/storage/emulated/0/XHLocalLog/5210/1364978/"  # 作业日志目录
    current_date_str = datetime.now().strftime("%Y%m")  # 年月目录（如202509）

    # 启动提示（加粗+蓝色）
    print(f"{LogColor.BOLD}{LogColor.INFO}[{get_time_stamp()}] ===== 自动答案提取 ====={LogColor.RESET}")
    print(f"{LogColor.INFO}[{get_time_stamp()}] 检查间隔：{check_interval}秒 | 输入任意内容可立即扫描 | 按Ctrl+C停止{LogColor.RESET}")

    # 加载已处理的JSON条数
    processed_json_count = load_json_processed_count(json_count_log_path)
    print(f"{LogColor.INFO}[{get_time_stamp()}] [初始化] 已处理JSON条数：{processed_json_count}{LogColor.RESET}")

    try:
        while True:
            # 1. 提取所有作业信息（只处理新增的JSON）
            work_info_map, total_jsons = extract_work_with_auto_path(work_log_base_dir)
            
            # 2. 更新已处理的JSON条数
            if processed_json_count == total_jsons:
                processed_json_count = total_jsons
                save_json_processed_count(json_count_log_path, processed_json_count)
            
            if not work_info_map:
                print(f"{LogColor.INFO}[{get_time_stamp()}] [等待作业] 无可用作业信息，{check_interval}秒后重试...{LogColor.RESET}")
                
                # 等待期间监听用户输入
                wait_for_input_with_timeout(check_interval)
                continue

            # 3. 加载已处理文件记录
            processed_log = load_processed_log(processed_log_path)

            # 4. 遍历作业信息，处理未完成的文件
            print(f"{LogColor.INFO}[{get_time_stamp()}] [开始检查] 共 {len(work_info_map)} 个作业待检查...{LogColor.RESET}")
            for file_path, work_name in work_info_map.items():
                if process_single_file(file_path, work_name, current_date_str, processed_log):
                    save_processed_log(processed_log_path, file_path)

            # 5. 等待下一次检查
            print(f"{LogColor.INFO}[{get_time_stamp()}] [检查结束] {check_interval}秒后再次检查...{LogColor.RESET}")
            
            # 等待期间监听用户输入
            wait_for_input_with_timeout(check_interval)

            # 6. 跨月处理
            new_date_str = datetime.now().strftime("%Y%m")
            if new_date_str != current_date_str:
                current_date_str = new_date_str
                print(f"{LogColor.SUCCESS}[{get_time_stamp()}] [跨月更新] 切换年月目录至：{current_date_str}{LogColor.RESET}")

    except KeyboardInterrupt:
        print(f"\n{LogColor.WARNING}[{get_time_stamp()}] 程序已手动停止{LogColor.RESET}")
    except Exception as e:
        print(f"\n{LogColor.ERROR}[{get_time_stamp()}] 程序异常停止：{str(e)}{LogColor.RESET}")