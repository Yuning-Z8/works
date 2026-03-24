import json
import os
from datetime import datetime

# 获取输入文件名
name = input('name:')    # test:83c7ae2ccfaf4937a02fbce9d0931ac8,5c462c53b50b4820b039d457559d430e

# 获取当前日期并格式化为 YYYYMM 格式
current_date = datetime.now()
date_str = current_date.strftime("%Y%m")  # 例如：202505

# 读取原始 JSON 文件
input_path = f"/storage/emulated/0/xuehai/5210/filebases/com.xh.acldstu/1364978/{date_str}/{name}.txt"
with open(input_path, "r") as file:
    a = json.load(file)

# 创建输出目录（如果不存在）
output_dir = f"/storage/emulated/0/1/anwsers/{date_str}"
os.makedirs(output_dir, exist_ok=True)  # 创建目录，exist_ok=True 表示如果目录已存在不报错

# 创建输出文件路径
output_path = f"{output_dir}/{name}.txt"
# 打开输出文件进行写入
with open(output_path, "w") as output_file:
    qn = 0
    s = ""
    wait_end = False
    
    for i in a['questionAnswers']:
        if i['inputType'] == 1:
            if i['index'] == 0:
                if wait_end:
                    wait_end = False
                    if s != '':
                        qn += 1
                        output_file.write(f'{qn}:{s}\n')
                        s = ''
            qn += 1
            output_file.write(f"{qn}:{i['answerContent']}\n")
        
        elif i['inputType'] == 7:
            if i['index'] == 0:
                if wait_end:
                    if s != '':
                        qn += 1
                        output_file.write(f'{qn}:{s}\n')
                        s = ''
                else:
                    wait_end = True
            s += f"{i['answerContent']}"
        
        elif i['inputType'] == 2:
            if i['index'] == 0:
                if wait_end:
                    if s != '':
                        qn += 1
                        output_file.write(f'{qn}:{s}\n')
                        s = ''
                    qn += 1
                    output_file.write(f'{qn}:\n')
                else:
                    qn += 1
                    output_file.write(f'{qn}:\n')
                    wait_end = True
            output_file.write(f"    {i['answerContent']}\n")
        
        elif i['inputType'] == 3:
            if i['index'] == 0:
                if wait_end:
                    if s != '':
                        qn += 1
                        output_file.write(f'{qn}:{s}\n')
                        s = ''
                    qn += 1
                    output_file.write(f'{qn}:\n')
                else:
                    qn += 1
                    output_file.write(f'{qn}:\n')
                    wait_end = True
            output_file.write(f"    {i['index']+1}:{i['answerContent']}\n")
        
        else:
            output_file.write('unknowtype\n')
    
    if wait_end:
        if s != '':
            qn += 1
            output_file.write(f'{qn}:{s}\n')
            s = ''

print(f"处理完成，结果已保存到: {output_path}")