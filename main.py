import os
import logging
import tempfile
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]

groq_client = Groq(api_key=GROQ_API_KEY)

ANALYSIS_PROMPT = """
당신은 친절한 영어 회화 코치입니다. 아래는 전화영어 수업 녹음의 전사본입니다.
학습자(한국인)가 한 말을 중심으로 분석해주세요.

[전사본]
{transcript}

아래 형식으로 한국어로 분석해주세요:

📌 대화 맥락 요약
어떤 주제로 대화했는지 2~3줄로 요약

✏️ 틀린 표현 교정
학습자가 말한 어색하거나 틀린 표현 위주로:
- 내가 한 말: (원문)
  교정: (올바른 표현)
  설명: (왜 틀렸는지 간단히)

💬 더 자연스러운 표현
같은 의미를 원어민처럼 말하는 방법 3~5개

📚 문법 포인트
핵심 문법 실수 2~3개를 짚어주기

🔁 이런 표현도 알아두세요
대화 주제와 관련된 유용한 영어 문장 5개 (한국어 뜻 포함)

⭐ 핵심 단어 & 숙어 (5분 복습)
중요 단어/숙어 5~10개를 아래 형식으로:
- 단어/숙어 : 뜻 / 예문
"""

# 처리 중인 사용자 추적
processing_users = set()

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in processing_users:
        await update.message.reply_text("처리중입니다. 기다려 주세요.")
        return

    processing_users.add(user_id)
    tmp_path = None

    try:
        await update.message.reply_text("수신 완료. 분석중입니다...")

        # 파일 종류 판단
        if update.message.voice:
            tg_file = await update.message.voice.get_file()
            suffix = ".ogg"
        elif update.message.audio:
            tg_file = await update.message.audio.get_file()
            fname = update.message.audio.file_name or "audio.mp3"
            suffix = os.path.splitext(fname)[-1] or ".mp3"
        elif update.message.document:
            doc = update.message.document
            mime = doc.mime_type or ""
            if not any(x in mime for x in ["audio", "ogg", "mp3", "m4a", "wav", "flac"]):
                await update.message.reply_text("동작중, 파일을 업로드 해주세요.\n(mp3, m4a, ogg, wav 형식 지원)")
                processing_users.discard(user_id)
                return
            tg_file = await doc.get_file()
            suffix = os.path.splitext(doc.file_name)[-1] or ".mp3"
        else:
            await update.message.reply_text("동작중, 파일을 업로드 해주세요.")
            processing_users.discard(user_id)
            return

        # 임시파일 다운로드
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)

        # Groq Whisper 전사
        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                language="en",
                response_format="text"
            )

        transcript = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()

        if not transcript:
            await update.message.reply_text("음성을 인식하지 못했습니다. 다시 시도해주세요.")
            return

        # Groq LLM 분석
        prompt = ANALYSIS_PROMPT.format(transcript=transcript)
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096
        )
        result = response.choices[0].message.content

        # 결과 전송 (2000자 단위 분할)
        for i in range(0, len(result), 2000):
            await update.message.reply_text(result[i:i+2000])

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text(f"오류 발생: {str(e)}")
    finally:
        processing_users.discard(user_id)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in processing_users:
        await update.message.reply_text("처리중입니다. 기다려 주세요.")
        return
    await update.message.reply_text("동작중, 파일을 업로드 해주세요.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(
        filters.VOICE | filters.AUDIO | filters.Document.ALL,
        handle_voice
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
