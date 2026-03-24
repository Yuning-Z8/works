import json
import os
import re
from datetime import datetime
import html
import argparse

# 修复的HTML内容处理函数
def process_html_content(text):
    if text is None:
        return ""
    
    # 先处理HTML实体
    text = html.unescape(text)
    
    # 优先处理mathquill标签（最关键的修复）
    # 确保所有<span class="mathquill-embedded-latex">内容都被\( ... \)包裹
    mathquill_pattern = r'<span\s+class="mathquill-embedded-latex"\s*>(.*?)</span>'
    # 使用DOTALL模式确保匹配跨换行的内容，同时去除可能的残留标签
    text = re.sub(mathquill_pattern, r'\(\1\)', text, flags=re.DOTALL)
    
    # 图片处理
    img_pattern = r'<img[^>]*src="([^"]*)"[^>]*>'
    text = re.sub(
        img_pattern, 
        r'<img src="\1" style="max-width: 100%; height: auto; margin: 10px 0;">', 
        text
    )
    
    # 统一换行标签
    text = re.sub(r'<br\s*/?>', '<br>', text)
    
    # 删除不必要的标签
    unnecessary_tags_pattern = r'<(?!img|br)\w+[^>]*>'
    text = re.sub(unnecessary_tags_pattern, '', text)
    
    return text

# 解析命令行参数
parser = argparse.ArgumentParser(description='处理题目答案JSON文件并生成HTML')
parser.add_argument('filename', type=str, help='要处理的文件名（不含路径，假设在指定输入路径下）')
args = parser.parse_args()

# 获取当前日期（YYYYMM格式）
current_date = datetime.now()
date_str = current_date.strftime("%Y%m")  # 如202508

# 输入输出路径
input_path = f"/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/{date_str}/{args.filename}.txt"
try:
    with open(input_path, "r", encoding="utf-8") as file:
        a = json.load(file)
except FileNotFoundError:
    print(f"错误：文件 {input_path} 未找到，请检查路径和文件名。")
    exit(1)
except json.JSONDecodeError:
    print(f"错误：文件 {args.filename}.txt 不是有效JSON格式。")
    exit(1)

# 输出目录配置
root_output_dir = "/storage/emulated/0/1/answers"  # answers根目录
date_output_dir = f"{root_output_dir}/{date_str}"  # 日期子目录
os.makedirs(date_output_dir, exist_ok=True)  # 确保日期目录存在
html_output_path = f"{date_output_dir}/{args.filename}.html"  # HTML输出路径

# HTML内容
html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>题目答案</title>
    <!-- 引用answers/根目录的es5文件夹 -->
    <!-- ../es5/tex-mml-chtml.js -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.0/es5/tex-mml-chtml.js"></script>
    <!-- MathJax配置 -->
    <script>
        MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\(', '\\)']],
                packages: {'[+]': ['ams', 'boldsymbol', 'amsmath']} // 新增 amsmath 扩展
            },
            svg: {
                fontCache: 'global'
            }
        };
    </script>
    <!-- 样式 -->
    <style>
        body {
            font-family: "Microsoft YaHei", Arial, sans-serif;
            line-height: 1.8;
            margin: 20px auto;
            padding: 0 15px;
            max-width: 850px;
        }
        .question {
            margin-bottom: 25px;
            padding: 15px;
            border-left: 4px solid #4CAF50;
            background-color: #f9f9f9;
            border-radius: 0 4px 4px 0;
        }
        .question-number {
            font-weight: bold;
            color: #2E7D32;
            font-size: 1.05em;
            margin-bottom: 8px;
        }
        .answer {
            padding-left: 5px;
        }
        .option {
            margin: 8px 0 8px 25px;
            position: relative;
        }
        .option:before {
            content: "";
            position: absolute;
            left: -25px;
            width: 20px;
            text-align: right;
        }
        img {
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .MathJax {
            line-height: 1.5 !important;
        }
    </style>
</head>
<body>
    <h1 style="text-align: center; color: #2E7D32;">题目答案</h1>
"""

# 题目内容生成逻辑
qn = 0
is_answer_open = False
current_question_id = ""
paragraph_content = ""  # 初始化变量，解决可能未绑定问题

for idx, item in enumerate(a['questionAnswers']):
    answer_content = process_html_content(item['answerContent'])
    item_qid = item['questionId']
    item_input_type = item['inputType']
    item_index = item['index']

    # 处理inputType=1（独立题型）
    if item_input_type == 1:
        if is_answer_open:
            html_content += "</div></div>"
            is_answer_open = False
        qn += 1
        html_content += f"""
    <div class="question">
        <div class="question-number">{qn}:</div>
        <div class="answer">{answer_content}</div>
    </div>"""

    # 处理inputType=7（段落题型）
    elif item_input_type == 7:
        if is_answer_open:
            html_content += "</div></div>"
            is_answer_open = False
        if item_index == 0:
            paragraph_content = answer_content  # 确保变量被赋值
        else:
            # 确保paragraph_content是字符串类型
            paragraph_content = f"{paragraph_content}{answer_content}"
        # 检查是否是最后一个元素或下一个是新段落
        if (idx == len(a['questionAnswers']) - 1) or (a['questionAnswers'][idx+1]['inputType'] != 7):
            qn += 1
            html_content += f"""
    <div class="question">
        <div class="question-number">{qn}:</div>
        <div class="answer">{paragraph_content}</div>
    </div>"""
            paragraph_content = ""  # 重置变量

    # 处理inputType=2（无序号选项）
    elif item_input_type == 2:
        if item_index == 0 or item_qid != current_question_id:
            if is_answer_open:
                html_content += "</div></div>"
                is_answer_open = False
            qn += 1
            current_question_id = item_qid
            html_content += f"""
    <div class="question">
        <div class="question-number">{qn}:</div>
        <div class="answer">"""
            is_answer_open = True
        html_content += f"<div class='option'>{answer_content}</div>"

    # 处理inputType=3（有序号选项，含公式）
    elif item_input_type == 3:
        if item_index == 0 or item_qid != current_question_id:
            if is_answer_open:
                html_content += "</div></div>"
                is_answer_open = False
            qn += 1
            current_question_id = item_qid
            html_content += f"""
    <div class="question">
        <div class="question-number">{qn}:</div>
        <div class="answer">"""
            is_answer_open = True
        html_content += f"<div class='option'>{item_index + 1}: {answer_content}</div>"

    # 未知题型
    else:
        if is_answer_open:
            html_content += "</div></div>"
            is_answer_open = False
        qn += 1
        html_content += f"""
    <div class="question">
        <div class="question-number">{qn}:</div>
        <div class="answer">未知题型（inputType={item_input_type}）</div>
    </div>"""

# 闭合最后一个未闭合的标签
if is_answer_open:
    html_content += "</div></div>"

# 完成HTML结构
html_content += """
    <script>
        // 页面加载后强制渲染MathJax
        window.addEventListener('load', function() {
            MathJax.typeset();
        });
    </script>
</body>
</html>
"""

# 写入HTML文件
with open(html_output_path, "w", encoding="utf-8") as html_file:
    html_file.write(html_content)

print(f"处理完成！HTML文件路径：{html_output_path}")
