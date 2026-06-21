import os
import asyncio
import json
import time
import boto3
from pyrogram import Client, filters
from pyrogram.types import Message
from pymongo import MongoClient

# ═══ ENV ═══
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
B2_KEY_ID = os.environ.get("B2_KEY_ID")
B2_APP_KEY = os.environ.get("B2_APP_KEY")
B2_BUCKET = os.environ.get("B2_BUCKET")
B2_ENDPOINT = os.environ.get("B2_ENDPOINT")
CDN_URL = os.environ.get("CDN_URL")
MONGO_URI = os.environ.get("MONGO_URI")

# ═══ CLIENTS ═══
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

# ═══ SUBTITLE EXTRACT ═══
async def extract_subtitles(input_path, output_dir, status_msg):
    subtitles = {}
    await status_msg.edit_text("📝 **Extracting subtitles...**")

    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_path]
    process = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await process.communicate()

    try:
        streams = json.loads(stdout)["streams"]
        sub_index = 0
        for stream in streams:
            if stream.get("codec_type") == "subtitle":
                lang = stream.get("tags", {}).get("language", f"sub{sub_index}")
                out_path = f"{output_dir}/{lang}.vtt"
                cmd2 = ["ffmpeg", "-i", input_path, "-map",
                        f"0:s:{sub_index}", "-y", out_path]
                proc2 = await asyncio.create_subprocess_exec(*cmd2,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                await proc2.communicate()
                if os.path.exists(out_path):
                    subtitles[lang] = out_path
                    await status_msg.edit_text(f"📝 **Subtitle extracted:** `{lang}`")
                sub_index += 1
    except:
        pass

    return subtitles

# ═══ REMUX (no re-encode, just container convert) ═══
async def remux_video(input_path, output_dir, status_msg):
    os.makedirs(output_dir, exist_ok=True)
    output_path = f"{output_dir}/1080p.mp4"

    await status_msg.edit_text(
        "⚙️ **Processing video...**\n"
        "🎬 Keeping 1080p quality\n"
        "🎵 Preserving all audio tracks\n"
        "⏳ Please wait..."
    )

    start = time.time()

    # Copy video + all audio tracks, no re-encode (super fast)
    cmd = [
        "ffmpeg", "-i", input_path,
        "-map", "0:v",      # all video
        "-map", "0:a",      # all audio tracks
        "-c:v", "copy",     # no re-encode (fast!)
        "-c:a", "copy",     # audio copy
        "-y", output_path
    ]

    process = await asyncio.create_subprocess_exec(*cmd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await process.communicate()

    elapsed = int(time.time() - start)
    size_mb = round(os.path.getsize(output_path) / (1024*1024), 1)

    await status_msg.edit_text(
        f"✅ **Video processed!**\n"
        f"📦 Size: `{size_mb} MB`\n"
        f"⏱️ Time: `{elapsed}s`\n\n"
        f"📤 Uploading to B2..."
    )

    return output_path

# ═══ B2 UPLOAD ═══
async def upload_to_b2(file_path, b2_key, content_type='video/mp4'):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: s3.upload_file(file_path, B2_BUCKET, b2_key,
            ExtraArgs={'ContentType': content_type})
    )
    return f"{CDN_URL}/{b2_key}"

# ═══ MAIN PROCESS ═══
async def process_video(message: Message):
    media = message.video or message.document
    file_name = getattr(media, 'file_name', None) or 'video.mp4'
    video_id = file_name.replace(" ", "_").replace(".mp4", "").replace(".mkv", "")

    status_msg = await message.reply_text("⬇️ **Downloading...**", quote=True)
    start_total = time.time()

    try:
        local_path = await app.download_media(message)
        dl_time = int(time.time() - start_total)

        await status_msg.edit_text(
            f"✅ **Downloaded!**\n"
            f"⏱️ Time: `{dl_time}s`\n\n"
            f"⚙️ Processing..."
        )

        output_dir = f"/tmp/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Remux video (keep 1080p + all audio)
        output_path = await remux_video(local_path, output_dir, status_msg)

        # Extract subtitles
        subtitles = await extract_subtitles(local_path, output_dir, status_msg)

        # Upload video
        await status_msg.edit_text("📤 **Uploading video to B2...**")
        b2_key = f"videos/{video_id}/1080p.mp4"
        video_url = await upload_to_b2(output_path, b2_key)
        os.remove(output_path)

        # Upload subtitles
        sub_urls = {}
        for lang, path in subtitles.items():
            await status_msg.edit_text(f"📤 **Uploading subtitle:** `{lang}`")
            b2_key = f"videos/{video_id}/subs/{lang}.vtt"
            url = await upload_to_b2(path, b2_key, 'text/vtt')
            sub_urls[lang] = url
            os.remove(path)

        # MongoDB save
        videos_col.insert_one({
            "video_id": video_id,
            "file_name": file_name,
            "url": video_url,
            "subtitles": sub_urls
        })

        os.remove(local_path)

        total_time = int(time.time() - start_total)
        subs_text = "\n".join([f"**{l}:** `{u}`" for l, u in sub_urls.items()]) if sub_urls else "❌ None found"

        await status_msg.edit_text(
            f"✅ **Complete!**\n\n"
            f"🎬 **File:** `{file_name}`\n"
            f"⏱️ **Total Time:** `{total_time}s`\n\n"
            f"🎥 **1080p URL:**\n`{video_url}`\n\n"
            f"📝 **Subtitles:**\n{subs_text}"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

# ═══ QUEUE ═══
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
            f"⏳ Pehli file complete hone ke baad process hogi",
            quote=True
        )

print("🚀 Bot Started!")
app.run()