from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
import io
import csv  
import json  
import math

def convert_kg_to_pound(kg_value: str) -> str:
    """
    将千克值转换为磅值，并进行取整处理
    例如: "17.6-22.3千克" -> "18-22磅"
    """
    try:
        # 检查是否是范围值
        if '-' in kg_value:
            start, end = kg_value.split('-')
            # 移除单位
            start = start.replace('千克', '').strip()
            end = end.replace('千克', '').strip()

            # 转换为浮点数
            start_kg = float(start)
            end_kg = float(end)

            # 转换为磅 (1千克 = 2.20462262185磅)
            start_pound = start_kg * 2.20462262185
            end_pound = end_kg * 2.20462262185

            # 对开始值向上取整，对结束值向下取整
            start_pound = math.ceil(start_pound)
            end_pound = math.floor(end_pound)

            return f"{start_pound}-{end_pound}磅"
        else:
            # 处理单个值
            value = kg_value.replace('千克', '').strip()
            pound_value = float(value) * 2.20462262185
            return f"{round(pound_value)}磅"
    except:
        return kg_value  # 如果转换失败，返回原始值

def validate_pound_conversion(original_kg: str, recommended_pound: str) -> bool:
    """
    验证千克到磅的转换是否正确
    """
    try:
        converted = convert_kg_to_pound(original_kg)
        # 移除单位后比较数值
        converted_clean = converted.replace('磅', '').strip()
        recommended_clean = recommended_pound.replace('磅', '').strip()
        return converted_clean == recommended_clean
    except:
        return False
    
app = FastAPI()



# 跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议设置具体前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求模型：通过 URL 上传
class FileUrl(BaseModel):
    url: str

# 通用函数：处理 .xlsx 二进制内容，解析为 JSON
def parse_xlsx(xlsx_data: bytes) -> list:
    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_data)) as z:
            # 读取 sharedStrings（共享字符串）
            shared_strings = []
            if 'xl/sharedStrings.xml' in z.namelist():
                with z.open('xl/sharedStrings.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    for si in root.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                        t = si.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
                        shared_strings.append(t.text if t is not None else "")

            # 读取 sheet1.xml
            with z.open('xl/worksheets/sheet1.xml') as f:
                tree = ET.parse(f)
                root = tree.getroot()
                sheet_data = root.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData')

                rows = []
                for row in sheet_data.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                    row_data = []
                    for c in row.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                        value = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        if value is None:
                            row_data.append("")
                        else:
                            if c.attrib.get('t') == 's':
                                idx = int(value.text)
                                row_data.append(shared_strings[idx])
                            else:
                                row_data.append(value.text)
                    rows.append(row_data)

        # 处理为键值对 JSON
        if not rows:
            return []

        headers = rows[0]
        result = []
        for row in rows[1:]:
            item = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            result.append(item)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse .xlsx file: {str(e)}")

# ✅ 接口 1：上传 URL
@app.post("/upload-xlsx-url/")
async def upload_xlsx_url(data: FileUrl):
    try:
        response = urllib.request.urlopen(data.url)
        xlsx_data = response.read()
        result = parse_xlsx(xlsx_data)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ✅ 接口 2：上传本地文件（支持csv）
@app.post("/upload-xlsx-file/")
async def upload_xlsx_file(file: UploadFile = File(...)):
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are supported")
    try:
        if file.filename.endswith(".csv"):
            content = await file.read()
            content_str = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content_str))
            rows = list(reader)
        else:
            xlsx_data = await file.read()
            rows = parse_xlsx(xlsx_data)
        grouped = {}
        for row in rows:
            dsm_code = str(row.get('dsm_code', ''))
            attr_name = row.get('属性名', '')
            attr_value = row.get('属性值', '')
            if not dsm_code or not attr_name:
                continue
            prefixed_code = f"dsm_code:{dsm_code}"
            if prefixed_code not in grouped:
                grouped[prefixed_code] = {}
            grouped[prefixed_code][attr_name] = attr_value
        return grouped
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ✅ 接口 3：上传csv文件并解析为JSON数组
@app.post("/upload-csv-json/")
async def upload_csv_json(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    try:
        content = await file.read()
        content_str = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content_str))
        rows = list(reader)
        # 过滤掉"字段处理"为"删除"的行
        filtered_rows = [row for row in rows if row.get("字段处理", "") != "删除"]
        return {"result": filtered_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV解析失败: {str(e)}")
    
# ✅ 接口 4：上传csv文件并解析为JSON数组
@app.post("/upload-csv-json-2/")
async def upload_csv_json(file:UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    try:
        content = await file.read()
        content_str = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content_str))
        rows = list(reader)
        return {"result": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CSV解析失败: {str(e)}")
    

# ✅ 接口 5：处理属性值对比并更新优化类型和打分，同时检验数值转换是否正确保持原始JSON格式

# ✅ 接口 5：处理属性值对比并更新优化类型和打分，同时检验数值转换是否正确保持原始JSON格式
@app.post("/process-attributes/")
async def process_attributes(request: Request):
    try:
        # 获取原始请求体内容
        body = await request.body()
        body_str = body.decode('utf-8')
        # 去除markdown包裹
        body_str = body_str.strip()
        if body_str.startswith('```json') and body_str.endswith('```'):
            body_str = body_str[7:-3].strip()
        elif body_str.startswith('```') and body_str.endswith('```'):
            body_str = body_str[3:-3].strip()
        
        # 尝试解析输入的JSON
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        
        # 处理不同的输入格式
        if isinstance(data, list):
            # 如果直接是数组，直接使用
            items_to_process = data
            dsm_code = None
            original_structure = "array"
        elif isinstance(data, dict):
            # 检查是否有 "output" 字段
            if "output" in data:
                # 从output中解析JSON
                output_str = data["output"]
                # 去除markdown包裹
                if output_str.startswith('```json\n') and output_str.endswith('\n```'):
                    output_str = output_str[8:-4].strip()
                
                try:
                    output_data = json.loads(output_str)
                    if "检查结果" in output_data:
                        items_to_process = output_data["检查结果"]
                        dsm_code = output_data.get("dsm_code")
                        original_structure = "output_with_result"
                    else:
                        raise HTTPException(status_code=400, detail="Output JSON should contain '检查结果' field")
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="Invalid JSON in output field")
            
            # 如果是对象，检查是否有 "检查结果" 字段
            elif "检查结果" in data:
                items_to_process = data["检查结果"]
                dsm_code = data.get("dsm_code")
                original_structure = "direct_result"
            else:
                raise HTTPException(status_code=400, detail="Input should be a JSON array, contain 'output' field, or contain '检查结果' field")
        else:
            raise HTTPException(status_code=400, detail="Input should be a JSON array or object")
        
        # 确保要处理的数据是数组格式
        if not isinstance(items_to_process, list):
            raise HTTPException(status_code=400, detail="Data to process should be an array")
        
        # 处理数据：检查原属性值和推荐属性值，更新优化类型和打分
        processed_data = []
        for item in items_to_process:
            opt_type = item.get("优化类型", "")
            original_value = item.get("原属性值", "")
            recommended_value = item.get("推荐属性值", "")
            attribute_name = item.get("新属性名", "")
            score = item.get("打分", None)
            
            # 特殊处理穿线磅数的单位转换
            if attribute_name == "穿线磅数" and original_value and recommended_value:
                # 验证千克到磅的转换是否正确
                if not validate_pound_conversion(original_value, recommended_value):
                    item["优化类型"] = "格式转换"
                    item["打分"] = 0
                    item["推荐属性值"] = convert_kg_to_pound(original_value)
                    processed_data.append(item)
                    continue
            
            # 1. "待补充" 跳过
            if opt_type == "待补充":
                processed_data.append(item)
                continue
            
            # 2. "直接引用"
            if opt_type == "直接引用":
                if original_value == recommended_value:
                    if score != 1:
                        item["打分"] = 1
                else:
                    item["优化类型"] = "格式转换"
                    item["打分"] = 0
                processed_data.append(item)
                continue
            
            # 3. "格式转换"
            if opt_type == "格式转换":
                if original_value != recommended_value:
                    processed_data.append(item)
                    continue
                else:
                    item["优化类型"] = "直接引用"
                    item["打分"] = 1
                    processed_data.append(item)
                    continue
            
            processed_data.append(item)
        
        # 构建返回结果，保持原始格式
        if original_structure == "output_with_result":
            # 如果原输入是output格式，保持相同结构
            result_data = {
                "dsm_code": dsm_code,
                "检查结果": processed_data
            }
            result_json = json.dumps(result_data, ensure_ascii=False, indent=2)
            result_context = f"```json\n{result_json}\n```"
            return {"output": result_context}
        elif original_structure == "direct_result":
            # 如果原输入包含dsm_code，保持相同结构
            result_data = {
                "dsm_code": dsm_code,
                "检查结果": processed_data
            }
            result_json = json.dumps(result_data, ensure_ascii=False, indent=2)
            result_context = f"```json\n{result_json}\n```"
            return {"text": result_context}
        else:
            # 如果原输入是纯数组，返回数组格式
            result_json = json.dumps(processed_data, ensure_ascii=False, indent=2)
            result_context = f"```json\n{result_json}\n```"
            return {"text": result_context}
        
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")



# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app=app, host="127.0.0.1", port=8000)
