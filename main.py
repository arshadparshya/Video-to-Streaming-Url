import os
import asyncio
import boto3
from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
B2_KEY_ID = os.environ.get("B2_KEY_ID")
B2_APP_KEY = os.environ.get("B2_APP_KEY")
B2_BUCKET = os.environ.get("B2_BUCKET")
B2_ENDPOINT = os.environ.get("B2_ENDPOINT")
CDN_URL = os.environ.get("CDN_URL")
MONGO_URI = os.environ.get("MONGO_URI")

app = Client("b2_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
mongo = MongoClient(MONGO_URI)
db = mongo["infiniteanimes"]
videos_col = db["videos"]

s3 = boto3.client(
    's3',
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY
)

upload_queue = asyncio.Queue()
is_processing = False

async def process_video(message: Message):
    media = message.video or message.document
    file_name = getattr(media, 'file_name', None) or 'video.mp4'
    video_id = file_name.replace(" ", "_").replace(".mp4", "").replace(".mkv", "")

    status_msg = await message.reply_text("⬇️ **Downloading...**", quote=True)

    try:
        local_path = await app.download_media(message)
        await status_msg.edit_text("📤 **Uploading to B2...**")

        b2_key = f"videos/{video_id}/1080p.mp4"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: s3.upload_file(
                local_path, B2_BUCKET, b2_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
        )

        video_url = f"{CDN_URL}/{b2_key}"

        videos_col.insert_one({
            "video_id": video_id,
            "file_name": file_name,
            "url": video_url
        })

        os.remove(local_path)

        await status_msg.edit_text(
            f"✅ **Done!**\n\n"
            f"🎬 **File:** `{file_name}`\n"
            f"🔗 **URL:**\n`{video_url}`"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

async def worker():
    global is_processing
    is_processing = True
    while True:
        try:
            message = upload_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await process_video(message)
        upload_queue.task_done()
    is_processing = False

@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    global is_processing
    await upload_queue.put(message)
    pos = upload_queue.qsize()
    if not is_processing:
        asyncio.create_task(worker())
    else:
        await message.reply_text(
            f"📋 **Queue mein add hua!**\n"
            f"🔢 **Position:** `{pos}`\n"
            f"⏳ Pehli file complete hone ke baad",
            quote=True
        )

print("🚀 Bot Started!")
app.run()