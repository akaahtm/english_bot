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

# 환경 변수
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# 클라이언트 초기화
groq_client = Groq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

ANALYSIS_PROMPT = """
당신은 영어 회화 코치입니다. 아래는 전화영어 수업 녹음의 전사본입니다.
[전사본]
{transcript}

위 내용을 분석하여 대화 요약, 교정 표현, 더 자연스러운 표현 등을 포함한 리포트를 작성해주세요.
"""

app = Flask(__name__)
# Webhook 모드에서는 updater를 None으로 설정
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).updater(None).build()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """음성/오디오 파일 수신 시 처리"""
    # 1. 수신 즉시 메시지 전송
    status_message = await update.message.reply_text("✅ 수신 완료! 분석 중입니다... (약 30초 소요)")
    
    try:
        # 파일 가져오기
        audio_source = update.message.voice or update.message.audio or update.message.document
        file = await audio_source.get_file()
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        # 2. Groq Whisper로 전사 (음성 -> 텍스트)
        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                language="en"
            )
        
        transcript_text = transcription.text
        if not transcript_text.strip():
            await status_message.edit_text("❌ 음성을 인식하지 못했습니다.")
            return

        # 3. Gemini로 분석
        response = gemini_model.generate_content(ANALYSIS_PROMPT.format(transcript=transcript_text))
        result = response.text

        # 4. 결과 전송 (원본 전사본 + 분석 결과)
        await update.message.reply_text(f"🗣️ **[전사본]**\n{transcript_text}", parse_mode="Markdown")
        
        # 텔레그램 메시지 길이 제한(4000자) 대응
        if len(result) > 4000:
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i+4000])
        else:
            await update.message.reply_text(result)

        # 임시 파일 삭제
        os.unlink(tmp_path)

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text(f"❌ 분석 중 오류가 발생했습니다: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일반 텍스트 메시지에 대한 응답"""
    await update.message.reply_text(
        "👋 안녕하세요! 영어 회화 코치 봇입니다.\n\n"
        "영어 녹음 파일(음성 메시지 또는 오디오 파일)을 보내주시면 "
        "전사 및 분석 리포트를 만들어 드립니다."
    )

# 핸들러 등록
bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | (filters.Document.AUDIO), handle_voice))
bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

@app.route("/webhook", methods=["POST"])
def webhook():
    """텔레그램 웹훅 엔드포인트"""
    # Flask의 동기 함수 내에서 비동기 처리 실행
    asyncio.run(bot_app.initialize())
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    asyncio.run(bot_app.process_update(update))
    return "ok", 200

@app.route("/")
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    # 서버 시작 시 한 번만 웹훅 설정
    async def set_webhook():
        await bot_app.initialize()
        await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        logging.info(f"Webhook set to {WEBHOOK_URL}/webhook")

    # 비동기로 웹훅 설정 후 Flask 실행
    asyncio.run(set_webhook())
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
