import os
import logging
import tempfile
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
import google.generativeai as genai

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 환경 변수 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# 클라이언트 초기화
groq_client = Groq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

ANALYSIS_PROMPT = """(기존 프롬프트 내용 유지)"""

# Flask 및 Telegram Application 설정
app = Flask(__name__)
# ApplicationBuilder에서 .updater(None)을 설정해야 Webhook 모드로 동작하기 편합니다.
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).updater(None).build()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 기존 handle_voice 로직과 동일 (생략 없이 그대로 사용)
    await update.message.reply_text("🎙️ 분석 중... (잠시만 기다려주세요)")
    try:
        # 파일 다운로드 및 Groq/Gemini 처리 로직...
        # (제공해주신 코드의 try-except 내부 로직을 여기에 그대로 넣으시면 됩니다)
        pass 
    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 음성 파일을 보내주시면 분석해드려요!")

# 핸들러 등록
bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_voice))
bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

@flask_app.route("/webhook", methods=["POST"])
async def webhook():
    """텔레그램으로부터 업데이트를 받아 처리하는 엔드포인트"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        # 비동기 큐에 업데이트를 넣어 처리
        await bot_app.process_update(update)
        return "ok", 200

@flask_app.route("/", methods=["GET"])
def health():
    return "Bot is running!", 200

# 서버 시작 시 Webhook 자동 설정
async def main_setup():
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logging.info(f"Webhook set to {WEBHOOK_URL}/webhook")

# Cloud Run 등에서는 이 방식으로 실행하는 것이 안정적입니다.
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_setup())
    
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
