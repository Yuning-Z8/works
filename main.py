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

while True:
    filename = input("name: ")

    # 获取当前日期（YYYYMM格式）
    current_date = datetime.now()
    date_str = current_date.strftime("%Y%m")  # 如202508

    # 输入输出路径
    input_path = f"/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/{date_str}/{filename}.txt"
    try:
        with open(input_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        print(f"错误：文件 {input_path} 未找到，请检查路径和文件名。")
        exit(1)
    except json.JSONDecodeError:
        print(f"错误：文件 {filename}.txt 不是有效JSON格式。")
        exit(1)

    # 输出目录配置
    root_output_dir = "/storage/emulated/0/1/answers"  # answers根目录
    date_output_dir = f"{root_output_dir}/{date_str}"  # 日期子目录
    os.makedirs(date_output_dir, exist_ok=True)  # 确保日期目录存在
    html_output_path = f"{date_output_dir}/{filename}.html"  # HTML输出路径

    # 按questionId分组答案
    answers_by_question = {}
    for answer in data['questionAnswers']:
        qid = answer['questionId']
        if qid not in answers_by_question:
            answers_by_question[qid] = []
        answers_by_question[qid].append(answer)

    # 创建题目ID到题目内容的映射
    question_map = {}
    for question in data['questionPoolContentInfos']:
        qid = question['questionId']
        question_map[qid] = question

    # 建立父题目到子题目的映射
    parent_to_children = {}
    for question in data['questionPoolContentInfos']:
        parent_id = question.get('parentQuestionId', '0')
        if parent_id != "0":  # 如果是子题目
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(question)

    # 找出所有顶级题目（没有父题目或父题目不在题库中）
    top_level_questions = []
    for question in data['questionPoolContentInfos']:
        parent_id = question.get('parentQuestionId', '0')
        if parent_id == "0" or parent_id not in question_map:
            top_level_questions.append(question)

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
            .stem {
                margin-bottom: 15px;
            }
            .answer {
                padding: 10px;
                background-color: #e8f5e9;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            .explanation {
                padding: 10px;
                background-color: #e3f2fd;
                border-radius: 4px;
                margin-top: 10px;
            }
            .blank-answer {
                margin: 5px 0;
                padding-left: 15px;
            }
            .blank-number {
                font-weight: bold;
                color: #d32f2f;
            }
            .sub-question {
                margin-left: 20px;
                border-left: 2px solid #FF9800;
                padding-left: 15px;
            }
            .sub-question-number {
                font-weight: bold;
                color: #FF9800;
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

    # 生成题目内容
    qn = 0
    for question in top_level_questions:
        qid = question['questionId']
        qn += 1
        
        # 处理题目内容
        stem_content = process_html_content(question.get('stemContent', ''))
        
        # 处理解析内容
        explain_content = process_html_content(question.get('explainContent', ''))
        
        # 获取该题目的所有答案
        answers = answers_by_question.get(qid, [])
        
        # 检查是否有子题目
        has_children = qid in parent_to_children
        
        # 开始题目块
        html_content += f"""
        <div class="question">
            <div class="question-number">{qn}:</div>
            <div class="stem">{stem_content}</div>"""
        
        # 处理答案（只有没有子题目时才显示答案）
        if not has_children and answers:
            html_content += "<div class='answer'>"
            # 按index排序答案
            answers.sort(key=lambda x: x.get('index', 0))
            
            # 单空题
            if len(answers) == 1:
                answer_content = process_html_content(answers[0]['answerContent'])
                html_content += f"<div>答案: {answer_content}</div>"
            
            # 多空题
            else:
                html_content += "<div>答案:</div>"
                for i, answer in enumerate(answers):
                    answer_content = process_html_content(answer['answerContent'])
                    blank_num = i + 1
                    html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> {answer_content}</div>"
            
            html_content += "</div>"  # 关闭answer div
        
        # 添加解析（如果有）
        if explain_content and explain_content.strip() != "<p>无</p>" and explain_content.strip():
            html_content += f"<div class='explanation'>解析: {explain_content}</div>"
        
        # 处理子题目
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
                
                # 处理子题目答案
                if sub_answers:
                    html_content += "<div class='answer'>"
                    # 按index排序答案
                    sub_answers.sort(key=lambda x: x.get('index', 0))
                    
                    # 单空题
                    if len(sub_answers) == 1:
                        answer_content = process_html_content(sub_answers[0]['answerContent'])
                        html_content += f"<div>答案: {answer_content}</div>"
                    
                    # 多空题
                    else:
                        html_content += "<div>答案:</div>"
                        for i, answer in enumerate(sub_answers):
                            answer_content = process_html_content(answer['answerContent'])
                            blank_num = i + 1
                            html_content += f"<div class='blank-answer'><span class='blank-number'>空{blank_num}:</span> {answer_content}</div>"
                    
                    html_content += "</div>"  # 关闭answer div
                
                # 添加子题目解析（如果有）
                if sub_explain_content and sub_explain_content.strip() != "<p>无</p>" and sub_explain_content.strip():
                    html_content += f"<div class='explanation'>解析: {sub_explain_content}</div>"
                
                html_content += "</div>"  # 关闭sub-question div
                sub_qn += 1
        
        html_content += "</div>"  # 关闭question div

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