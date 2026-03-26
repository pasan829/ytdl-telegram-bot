"""
Video Downloader Telegram Bot - API Mode
HTML frontend ගෙ download links return කරනවා
"""

import os, re, asyncio, tempfile, subprocess, sys, json, time

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from telegram import Update
    from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
except ImportError:
    install("python-telegram-bot==20.7")
    from telegram import Update
    from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

try:
    import yt_dlp
except ImportError:
    install("yt-dlp")
    import yt_dlp

try:
    import requests
except ImportError:
    install("requests")
    import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
URL_PATTERN = re.compile(r'https?://\S+')

def detect_platform(url):
    if re.search(r'youtube\.com|youtu\.be', url): return "YouTube"
    if re.search(r'facebook\.com|fb\.watch', url): return "Facebook"
    if re.search(r'instagram\.com', url):          return "Instagram"
    if re.search(r'twitter\.com|x\.com', url):    return "Twitter/X"
    if re.search(r'tiktok\.com', url):             return "TikTok"
    return "Video"

def get_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True, "no_warnings": True,
        "skip_download": True, "noplaylist": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats", [])
    options = []

    seen = set()
    vf = [f for f in formats
          if f.get("vcodec") != "none" and f.get("acodec") != "none"
          and f.get("url") and f.get("ext") in ("mp4","webm","mov")]
    vf.sort(key=lambda f: f.get("height") or 0, reverse=True)
    for f in vf:
        h = f.get("height") or 0
        if h and h not in seen:
            seen.add(h)
            lbl = f"{h}p" + (" Full HD" if h>=1080 else " HD" if h>=720 else " SD" if h>=480 else "")
            options.append({"type":"video","label":lbl,"ext":f.get("ext","mp4"),
                            "url":f["url"],"size":f.get("filesize") or f.get("filesize_approx") or 0})
        if len(seen) >= 4: break

    if not options:
        best = next((f for f in reversed(formats)
                     if f.get("vcodec") != "none" and f.get("url")), None)
        if best:
            options.append({"type":"video","label":"Best Quality",
                            "ext":best.get("ext","mp4"),"url":best["url"],"size":0})

    af = [f for f in formats if f.get("vcodec")=="none"
          and f.get("acodec")!="none" and f.get("url")]
    af.sort(key=lambda f: f.get("abr") or 0, reverse=True)
    if af:
        a = af[0]
        options.append({"type":"audio","label":"Audio Only (MP3)",
                        "ext":a.get("ext","m4a"),"url":a["url"],"size":a.get("filesize") or 0})

    return {
        "title": info.get("title","Video"),
        "thumbnail": info.get("thumbnail",""),
        "duration": info.get("duration", 0),
        "uploader": info.get("uploader",""),
        "platform": info.get("extractor_key",""),
        "options": options
    }


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"👋 *Video Downloader Bot*\n\n"
        f"📎 YouTube, Facebook, Instagram, Twitter/X\n\n"
        f"• Video URL paste කරන්න\n"
        f"• `/audio <URL>` — MP3 download\n"
        f"• `/id` — ඔයාගෙ Chat ID\n\n"
        f"🆔 Your Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def get_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🆔 Your Chat ID: `{chat_id}`\n\n"
        f"Blogger widget ගෙ `CHAT_ID` value ගෙ මේ number දාන්න.",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.startswith("APIGET"):
        parts = text.split(":", 2)
        if len(parts) < 3:
            return
        mode   = parts[0]
        req_id = parts[1]
        url    = parts[2].strip()

        audio_only = (mode == "APIGET_AUDIO")

        try:
            data = get_info(url)
            if audio_only:
                data["options"] = [o for o in data["options"] if o["type"] == "audio"]
            result = {"ok": True, "req_id": req_id, **data}
        except Exception as e:
            result = {"ok": False, "req_id": req_id, "error": str(e)}

        await update.message.reply_text(
            f"APIRESULT:{json.dumps(result, ensure_ascii=False)}"
        )
        return

    url_match = URL_PATTERN.search(text)
    if not url_match:
        await update.message.reply_text(
            "⚠️ Valid video URL එකක් paste කරන්න.\n"
            "Supported: YouTube, Facebook, Instagram, Twitter/X, TikTok"
        )
        return

    url = url_match.group(0)
    platform = detect_platform(url)
    msg = await update.message.reply_text(
        f"⏳ *{platform}* video download කරනවා...",
        parse_mode="Markdown"
    )

    try:
        tmpdir = tempfile.mkdtemp()
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "%(title).50s.%(ext)s"),
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=720][ext=mp4]/best[height<=720]/best"
            ),
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
                 if os.path.isfile(os.path.join(tmpdir, f))]
        if not files: raise Exception("No file downloaded")

        fp = files[0]
        size_mb = os.path.getsize(fp) / 1024 / 1024
        await msg.edit_text(f"📤 Uploading... ({size_mb:.1f}MB)")

        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f:
            if ext in (".mp4",".mov",".webm",".mkv"):
                await update.message.reply_video(
                    video=f,
                    caption=f"🎬 *{info.get('title','Video')[:100]}*\n_via Video Downloader Bot_",
                    parse_mode="Markdown", supports_streaming=True,
                )
            else:
                await update.message.reply_document(
                    document=f,
                    caption=f"🎬 *{info.get('title','Video')[:100]}*",
                    parse_mode="Markdown",
                )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/audio <URL>`", parse_mode="Markdown")
        return
    url = args[0]
    msg = await update.message.reply_text("🎵 Audio extract කරනවා...")
    try:
        tmpdir = tempfile.mkdtemp()
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "%(title).50s.%(ext)s"),
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": "bestaudio/best",
            "postprocessors": [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
        with open(files[0], "rb") as f:
            await update.message.reply_audio(
                audio=f,
                caption=f"🎵 *{info.get('title','Audio')[:100]}*",
                parse_mode="Markdown",
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def force_clear_session():
    """පැරණි getUpdates session forcefully terminate කරනවා"""
    print("⏳ Waiting 35s for any old instance to die...")
    time.sleep(35)
    try:
        print("🔄 Forcing Telegram session reset...")
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": -1, "timeout": 0},
            timeout=10
        )
        print("✅ Session reset done")
    except Exception as e:
        print(f"⚠️ Session reset warning (ok): {e}")
    time.sleep(3)


async def post_init(app: Application) -> None:
    await app.bot.delete_webhook(drop_pending_updates=True)
    print("✅ Webhook cleared, old updates dropped.")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set!")

    force_clear_session()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("audio", handle_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
