import os
import logging
import tempfile
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
import google.generativeai as genai

# 로그 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수 로드
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# API 클라이언트 초기화
groq_client = Groq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

ANALYSIS_PROMPT = """당신은 영어 회화 코치입니다. 아래 전사본을 바탕으로 학습 리포트를 만들어주세요.
[전사본]: {transcript}
요약, 교정, 자연스러운 표현을 포함해 한국어로 답변해주세요."""

app = Flask(__name__)
# Webhook 방식에서는 updater(None) 필수
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).updater(None).build()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """음성/오디오 파일 처리"""
    # 봇이 응답을 시작했다는 것을 즉시 알림
    status_msg = await update.message.reply_text("✅ 수신 완료! 분석 중입니다... (30초~1분 소요)")
    
    try:
        audio_file_obj = update.message.voice or update.message.audio or update.message.document
        file = await audio_file_obj.get_file()
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        # Groq (Whisper) 변환
        with open(tmp_path, "rb") as f:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3", file=f, language="en"
            )
        
        # Gemini 분석
        response = gemini_model.generate_content(ANALYSIS_PROMPT.format(transcript=transcription.text))
        
        # 결과 전송
        await update.message.reply_text(f"🗣️ **전사본:**\n{transcription.text}")
        await update.message.reply_text(response.text)
        
        os.unlink(tmp_path)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 영어 음성 파일을 보내주시면 분석해 드릴게요!")

# 핸들러 등록
bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_voice))
bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

@app.route("/webhook", methods=["POST"])
async def webhook_handler():
    """텔레그램에서 오는 신호를 처리"""
    if request.method == "POST":
        try:
            # 봇 앱이 초기화되지 않았다면 실행
            if not bot_app.running:
                await bot_app.initialize()
            
            update = Update.de_json(await request.get_json(), bot_app.bot)
            await bot_app.process_update(update)
        except Exception as e:
            logger.error(f"Webhook Error: {e}")
        return "OK", 200

@app.route("/")
def health():
    return "Bot is running!", 200

if __name__ == "__main__":
    # 웹훅 자동 설정
    async def setup_webhook():
        await bot_app.initialize()
        await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")

    asyncio.run(setup_webhook())
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
