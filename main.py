import os
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

BOT_TOKEN = os.environ.get("BOT_TOKEN")
LIBRARY_ID = os.environ.get("LIBRARY_ID")
API_KEY = os.environ.get("API_KEY")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")

app = Client("bunny_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

bunny_headers = {
    "AccessKey": API_KEY,
    "Content-Type": "application/json",
    "accept": "application/json"
}

# ═══ QUEUE ═══
upload_queue = asyncio.Queue()
is_processing = False

async def worker():
    global is_processing
    is_processing = True
    while True:
        try:
            message = upload_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        await upload_file(message)
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

async def upload_file(message: Message):
    media = message.video or message.document
    file_name = getattr(media, 'file_name', None) or 'video.mp4'

    status_msg = await message.reply_text("⬇️ **Downloading...**", quote=True)

    try:
        local_path = await app.download_media(message)
        await status_msg.edit_text("📤 **Uploading to BunnyCDN...**")

        create_url = f"https://video.bunnycdn.com/library/{LIBRARY_ID}/videos"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                create_url,
                json={"title": file_name},
                headers=bunny_headers
            ) as resp:
                create_res = await resp.json()

        video_id = create_res.get("guid") or create_res.get("id")
        if not video_id:
            await status_msg.edit_text("❌ **Bunny API Error!**")
            return

        upload_url = f"https://video.bunnycdn.com/library/{LIBRARY_ID}/videos/{video_id}"
        upload_headers = {"AccessKey": API_KEY, "Content-Type": "video/*"}

        async with aiohttp.ClientSession() as session:
            with open(local_path, 'rb') as f:
                await session.put(upload_url, headers=upload_headers, data=f)

        os.remove(local_path)

        player_url = f"https://player.mediadelivery.net/play/{LIBRARY_ID}/{video_id}"
        embed_url = f"https://player.mediadelivery.net/embed/{LIBRARY_ID}/{video_id}"

        await status_msg.delete()

        await message.reply_text(
            f"✅ **Upload Successful!**\n\n"
            f"🎬 **File:** `{file_name}`\n"
            f"🆔 **ID:** `{video_id}`\n\n"
            f"▶️ **Player Link:**\n`{player_url}`\n\n"
            f"🔗 **Embed Link:**\n`{embed_url}`\n\n"
            f"_(RUK JAAAAAAAA Time Lagegaaaaaaa)_",
            quote=True
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

print("🚀 Bot Started!")
app.run()