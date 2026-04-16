import os
import logging
import tempfile
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq
import google.generativeai as genai
from flask import Flask, request

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]  # Cloud Run URL (배포 후 입력)

groq_client = Groq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

ANALYSIS_PROMPT = """
당신은 영어 회화 코치입니다. 아래는 전화영어 수업 녹음의 전사본입니다.

[전사본]
{transcript}

다음 형식으로 분석해주세요:

---
## 📌 대화 맥락 요약
(어떤 주제로 대화했는지 2-3줄 요약)

## ✏️ 틀린 표현 교정
(학습자가 말한 어색하거나 틀린 표현을 찾아 교정)
| 내가 한 말 | 교정된 표현 | 설명 |
|-----------|------------|------|

## 💬 더 자연스러운 표현
(같은 의미를 원어민처럼 말하는 방법)

## 📚 문법 포인트
(핵심 문법 오류 2-3개 짚어주기)

## 🔁 이런 표현도 알아두세요
(대화 주제와 관련된 유용한 문장 5개)

## ⭐ 핵심 단어 & 숙어 (5분 복습)
| 단어/숙어 | 뜻 | 예문 |
|----------|-----|------|
(5~10개)
---
"""

flask_app = Flask(__name__)
bot_app = None

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙️ 녹음 파일 받았습니다! 분석 중... (30초~1분 소요)")
    try:
        if update.message.voice:
            file = await update.message.voice.get_file()
            suffix = ".ogg"
        elif update.message.audio:
            file = await update.message.audio.get_file()
            suffix = ".mp3"
        elif update.message.document:
            file = await update.message.document.get_file()
            suffix = os.path.splitext(update.message.document.file_name)[-1]
        else:
            await update.message.reply_text("❌ 음성 파일을 전송해주세요.")
            return

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name

        await file.download_to_drive(tmp_path)

        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                language="en"
            )

        transcript = transcription.text
        if not transcript.strip():
            await update.message.reply_text("❌ 음성을 인식하지 못했습니다. 다시 시도해주세요.")
            return

        prompt = ANALYSIS_PROMPT.format(transcript=transcript)
        response = gemini_model.generate_content(prompt)
        result = response.text

        await update.message.reply_text(f"🗣️ *전사본:*\n{transcript}", parse_mode="Markdown")

        max_len = 4000
        for i in range(0, len(result), max_len):
            await update.message.reply_text(result[i:i+max_len])

        os.unlink(tmp_path)

    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 안녕하세요!\n\n"
        "전화영어 녹음 파일을 보내주시면 분석해드립니다.\n"
        "• 텔레그램 음성메시지 ✅\n"
        "• MP3/M4A/OGG 파일 ✅"
    )

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    import asyncio
    import json
    data = request.get_json()
    update = Update.de_json(data, bot_app.bot)
    asyncio.run(bot_app.process_update(update))
    return "ok", 200

@flask_app.route("/", methods=["GET"])
def health():
    return "Bot is running!", 200

async def setup_webhook():
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logging.info(f"Webhook set to {WEBHOOK_URL}/webhook")

if __name__ == "__main__":
    import asyncio

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.Document.AUDIO, handle_voice))
    bot_app.add_handler(MessageHandler(filters.TEXT, handle_text))

    asyncio.run(setup_webhook())

    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)
