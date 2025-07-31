from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求模型：通过 URL 上传
class FileUrl(BaseModel):
    url: str

# ✅ 接口 1：上传csv文件并解析为JSON数组
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
       
# ✅ 接口 2：处理属性值对比并更新优化类型和打分，同时检验数值转换是否正确保持原始JSON格式
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
        # 尝试解析输入的JSON数组
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format")
        
        # 确保输入是数组格式
        if not isinstance(data, list):
            raise HTTPException(status_code=400, detail="Input should be a JSON array")
        
        # 处理数据：检查原属性值和推荐属性值，更新优化类型和打分
        processed_data = []
        for item in data:
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
        
        # 将处理后的数据格式化为与输入相同的JSON格式
        result_json = json.dumps(processed_data, ensure_ascii=False, indent=2)
        result_context = f"```json\n{result_json}\n```"
        
        return {"text": result_context}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app=app, host="127.0.0.1", port=8000)
