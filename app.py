import os
import json
import logging
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, FlexSendMessage

import google.generativeai as genai

app = Flask(__name__)

# 設定 Log
logging.basicConfig(level=logging.INFO)

# 1. 讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 2. 設定 Gemini 與除錯資訊
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 強制印出版本與模型清單 (Debug 用)
    print(f"【系統檢查】目前 GenAI 套件版本: {genai.__version__}", flush=True)
    try:
        print("【系統檢查】正在查詢可用模型...", flush=True)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f" - 可用: {m.name}", flush=True)
    except Exception as e:
        print(f"【系統檢查】無法列出模型 (可能 Key 有誤): {e}", flush=True)

    # 設定模型 (使用目前最通用的 1.5-flash)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("【嚴重錯誤】找不到 GEMINI_API_KEY，請檢查 Render 環境變數！", flush=True)

# 3. 核心功能：取得推薦
def get_gemini_recommendation(location, food_type, budget):
    prompt = f"""
    你是一個美食導遊。請推薦 3 間位於「{location}」的「{food_type}」，預算「{budget}」。
    規則：
    1. 回傳純 JSON Array。
    2. 不要 Markdown。
    3. 欄位: name, rating, address, description。
    """
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        logging.error(f"Gemini 生成失敗: {e}")
        return []

# 4. 製作卡片
def create_bubble(store):
    return {
        "type": "bubble",
        "size": "micro",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": store.get('name', '店名'), "weight": "bold", "wrap": True},
                {"type": "text", "text": f"⭐ {store.get('rating', 'N/A')}", "size": "xs", "color": "#ffc107"},
                {"type": "text", "text": store.get('address', '地址'), "size": "xxs", "color": "#aaaaaa", "wrap": True},
                {"type": "text", "text": store.get('description', ''), "size": "xxs", "wrap": True, "margin": "md"}
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
                        "label": "查看地圖",
                        "uri": f"https://www.google.com/maps/search/?api=1&query={store.get('name')}"
                    },
                    "height": "sm",
                    "style": "link"
                }
            ]
        }
    }

# 5. LINE Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    inputs = msg.replace(',', ' ').split()
    
    if len(inputs) >= 2:
        location = inputs[0]
        food_type = inputs[1]
        budget = inputs[2] if len(inputs) > 2 else "不限"
        
        try:
            stores = get_gemini_recommendation(location, food_type, budget)
            if not stores:
                line_bot_api.reply_message(event.reply_token, TextMessage(text="抱歉，AI 找不到資料。"))
                return
            
            bubbles = [create_bubble(s) for s in stores]
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="推薦結果", contents={"type": "carousel", "contents": bubbles}))
        except Exception as e:
            logging.error(f"處理失敗: {e}")
            line_bot_api.reply_message(event.reply_token, TextMessage(text="系統發生錯誤，請稍後再試。"))
    else:
        line_bot_api.reply_message(event.reply_token, TextMessage(text="請輸入：地點 種類 價位\n例如：台中 火鍋 500"))

if __name__ == "__main__":
    app.run()
