import os
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

BOT_TOKEN = os.environ.get("BOT_TOKEN")
LIBRARY_ID = os.environ.get("LIBRARY_ID")
API_KEY = os.environ.get("API_KEY")

app = Client("bunny_bot", bot_token=BOT_TOKEN)

bunny_headers = {
    "AccessKey": API_KEY,
    "Content-Type": "application/json",
    "accept": "application/json"
}

@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    media = message.video or message.document
    file_name = getattr(media, 'file_name', None) or 'video.mp4'

    msg = await message.reply_text("⏳ **Downloading...**")

    try:
        local_path = await client.download_media(message)
        await msg.edit_text("📤 **Uploading to BunnyCDN...**")

        create_url = f"https://video.bunnycdn.com/library/{LIBRARY_ID}/videos"

        async with aiohttp.ClientSession() as session:
            async with session.post(create_url, json={"title": file_name}, headers=bunny_headers) as resp:
                create_res = await resp.json()

        video_id = create_res.get("guid") or create_res.get("id")
        if not video_id:
            await msg.edit_text("❌ **Bunny API Error!**")
            return

        upload_url = f"https://video.bunnycdn.com/library/{LIBRARY_ID}/videos/{video_id}"
        upload_headers = {
            "AccessKey": API_KEY,
            "Content-Type": "video/*"
        }

        async with aiohttp.ClientSession() as session:
            with open(local_path, 'rb') as f:
                await session.put(upload_url, headers=upload_headers, data=f)

        os.remove(local_path)

        player_url = f"https://player.mediadelivery.net/play/{LIBRARY_ID}/{video_id}"
        embed_url = f"https://player.mediadelivery.net/embed/{LIBRARY_ID}/{video_id}"

        await msg.delete()
        await message.reply_text(
            f"✅ **Upload Successful!**\n\n"
            f"🎬 **File:** `{file_name}`\n"
            f"🆔 **ID:** `{video_id}`\n\n"
            f"▶️ **Player Link:**\n`{player_url}`\n\n"
            f"🔗 **Embed Link:**\n`{embed_url}`\n\n"
            f"_(Processing mein 1-2 min lagega)_"
        )

    except Exception as e:
        await msg.edit_text(f"❌ **Error:** `{str(e)}`")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

print("🚀 Bot Started!")
app.run()