import os
import json
import logging
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FlexSendMessage

import google.generativeai as genai

app = Flask(__name__)

# --- 強制印出版本資訊 ---
print(f"目前使用的 GenAI 套件版本: {genai.__version__}", flush=True) 
# ----------------------

# ... (後面接原本的程式碼)
app = Flask(__name__)

# 設定 Log，方便除錯
logging.basicConfig(level=logging.INFO)

# 從環境變數讀取 Key (安全做法)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 設定 Gemini ---
genai.configure(api_key=GEMINI_API_KEY)

# 嘗試列出所有可用模型 (Debug 用)
# 這段會把你的 API Key 能用的模型印在 Render Log 裡
try:
    print("正在檢查可用模型...", flush=True)
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"可用模型: {m.name}", flush=True)
except Exception as e:
    print(f"無法列出模型: {e}", flush=True)

# 使用目前最標準的模型
model = genai.GenerativeModel('gemini-1.5-flash')

def get_gemini_recommendation(location, food_type, budget):
    prompt = f"""
    請推薦 3 間位於「{location}」的「{food_type}」，預算約「{budget}」。
    請嚴格遵守以下規則：
    1. 回傳純 JSON 格式 List。
    2. 不要包含 Markdown (如 ```json)。
    3. 欄位包含: name, rating(數值), address, description(簡短評價)。
    
    範例格式:
    [
        {{"name": "店家名", "rating": 4.5, "address": "地址", "description": "評價"}}
    ]
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        logging.error(f"Gemini Error: {e}")
        return []

def create_bubble(store):
    # 製作單一餐廳的卡片
    return {
        "type": "bubble",
        "size": "micro",  # 設為 micro 讓卡片小一點，適合橫向滑動
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": store.get('name', '未知店家'), "weight": "bold", "size": "sm", "wrap": True},
                {"type": "text", "text": f"⭐ {store.get('rating', 'N/A')}", "size": "xs", "color": "#ffc107", "margin": "xs"},
                {"type": "text", "text": store.get('address', '無地址'), "size": "xxs", "color": "#aaaaaa", "wrap": True, "margin": "xs"},
                {"type": "text", "text": store.get('description', ''), "size": "xxs", "wrap": True, "margin": "md", "color": "#666666"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "地圖",
                        "uri": f"[https://www.google.com/maps/search/?api=1&query=](https://www.google.com/maps/search/?api=1&query=){store.get('name')}"
                    },
                    "height": "sm",
                    "style": "link"
                }
            ]
        }
    }

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    
    # 簡單防呆：需要兩個空白或是逗號
    # 支援: "台中 火鍋 500" 或 "台中,火鍋,500"
    inputs = msg.replace(',', ' ').split()
    
    if len(inputs) >= 2:
        location = inputs[0]
        food_type = inputs[1]
        budget = inputs[2] if len(inputs) > 2 else "不限"

        try:
            stores = get_gemini_recommendation(location, food_type, budget)
            
            if not stores:
                line_bot_api.reply_message(event.reply_token, TextMessage(text="AI 找不到相關資料，請換個關鍵字試試。"))
                return

            bubbles = [create_bubble(s) for s in stores]
            carousel = {
                "type": "carousel",
                "contents": bubbles
            }
            
            line_bot_api.reply_message(
                event.reply_token, 
                FlexSendMessage(alt_text="美食推薦清單", contents=carousel)
            )
        except Exception as e:
            logging.error(f"Process Error: {e}")
            line_bot_api.reply_message(event.reply_token, TextMessage(text="系統忙碌中，請稍後再試。"))
    else:
        # 如果格式不對，回傳引導文字
        line_bot_api.reply_message(event.reply_token, TextMessage(text="請輸入：地點 種類 價位\n例如：新竹 拉麵 300"))

if __name__ == "__main__":
    app.run()
