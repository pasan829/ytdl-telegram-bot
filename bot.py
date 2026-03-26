"""
Video Downloader Telegram Bot — Clean Rewrite
Fixes: accurate file sizes, proper error messages, clean API responses
"""

import os, re, json, tempfile, subprocess, sys, shutil

def pip(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

for pkg in ["python-telegram-bot==20.7", "yt-dlp"]:
    try:
        __import__(pkg.split("==")[0].replace("-","_"))
    except ImportError:
        pip(pkg)

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import yt_dlp

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")   # optional — for API mode

URL_RE = re.compile(r'https?://[^\s]+')

# ── Helpers ───────────────────────────────────────────────────────────────

def platform_of(url):
    for pat, name in [
        (r'youtube\.com|youtu\.be',   "YouTube"),
        (r'facebook\.com|fb\.watch',  "Facebook"),
        (r'instagram\.com',           "Instagram"),
        (r'twitter\.com|x\.com',      "Twitter/X"),
        (r'tiktok\.com',              "TikTok"),
    ]:
        if re.search(pat, url, re.I):
            return name
    return "Video"

def fmt_size(b):
    """Human readable file size."""
    if not b or b <= 0:
        return ""
    if b < 1024:
        return f"{b} B"
    if b < 1024 ** 2:
        return f"{b/1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"

def fmt_dur(s):
    if not s: return ""
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02}:{sec:02}"
    return f"{m}:{sec:02}"

def quality_label(height):
    if not height: return "Best"
    s = f"{height}p"
    if height >= 2160: s += " 4K"
    elif height >= 1080: s += " Full HD"
    elif height >= 720:  s += " HD"
    elif height >= 480:  s += " SD"
    return s


# ── Core: extract info + actual file sizes ────────────────────────────────

def get_info(url: str) -> dict:
    """
    Extract video metadata + format list.
    File sizes: first try yt-dlp reported size,
    then HEAD request for actual Content-Length.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
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

    all_formats = info.get("formats", [])
    options = []

    # ── Video + Audio combined (mp4 preferred) ────────────────────────
    seen_heights = set()
    combined = [
        f for f in all_formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("url")
        and f.get("ext") in ("mp4", "webm", "mov")
    ]
    combined.sort(key=lambda f: (f.get("height") or 0), reverse=True)

    for f in combined:
        h = f.get("height") or 0
        if h in seen_heights:
            continue
        seen_heights.add(h)

        size = (
            f.get("filesize")
            or f.get("filesize_approx")
            or _head_size(f["url"])
            or 0
        )

        options.append({
            "type":    "video",
            "label":   quality_label(h),
            "ext":     f.get("ext", "mp4"),
            "url":     f["url"],
            "size":    size,
            "size_fmt": fmt_size(size),
            "height":  h,
        })

        if len(seen_heights) >= 4:
            break

    # ── Fallback: best available (may be video-only) ──────────────────
    if not options:
        best = next(
            (f for f in reversed(all_formats)
             if f.get("vcodec") not in (None, "none") and f.get("url")),
            None,
        )
        if best:
            size = best.get("filesize") or best.get("filesize_approx") or _head_size(best["url"]) or 0
            options.append({
                "type":     "video",
                "label":    quality_label(best.get("height")),
                "ext":      best.get("ext", "mp4"),
                "url":      best["url"],
                "size":     size,
                "size_fmt": fmt_size(size),
                "height":   best.get("height") or 0,
            })

    # ── Best audio-only ───────────────────────────────────────────────
    audio_fmts = [
        f for f in all_formats
        if f.get("vcodec") in (None, "none")
        and f.get("acodec") not in (None, "none")
        and f.get("url")
    ]
    audio_fmts.sort(key=lambda f: f.get("abr") or 0, reverse=True)

    if audio_fmts:
        af = audio_fmts[0]
        size = af.get("filesize") or af.get("filesize_approx") or _head_size(af["url"]) or 0
        options.append({
            "type":     "audio",
            "label":    "Audio Only (MP3)",
            "ext":      af.get("ext", "m4a"),
            "url":      af["url"],
            "size":     size,
            "size_fmt": fmt_size(size),
        })

    return {
        "title":     info.get("title", "Video"),
        "thumbnail": info.get("thumbnail", ""),
        "duration":  info.get("duration", 0),
        "dur_fmt":   fmt_dur(info.get("duration")),
        "uploader":  info.get("uploader", ""),
        "platform":  info.get("extractor_key", ""),
        "options":   options,
    }


def _head_size(url: str) -> int:
    """Try to get file size via HTTP HEAD request."""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            cl = r.headers.get("Content-Length")
            return int(cl) if cl else 0
    except Exception:
        return 0


# ── Bot handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        "👋 *Video Downloader Bot*\n\n"
        "Supported: YouTube · Facebook · Instagram · Twitter/X · TikTok\n\n"
        "*Usage:*\n"
        "• Video URL paste කරන්න → file ලැබෙනවා\n"
        "• `/audio <URL>` → MP3 extract\n"
        "• `/id` → ඔයාගෙ Chat ID\n\n"
        f"🆔 Your Chat ID: `{cid}`",
        parse_mode="Markdown",
    )

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"🆔 Your Chat ID: `{cid}`\n\n"
        "Blogger widget config ගෙ `CHAT_ID` ගෙ මේ value දාන්න.",
        parse_mode="Markdown",
    )

async def cmd_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/audio <URL>`", parse_mode="Markdown")
        return
    await _do_download(update, ctx.args[0], audio_only=True)

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ── API request from Blogger widget ──────────────────────────────
    # Format: "APIGET:<req_id>:<url>" or "APIGET_AUDIO:<req_id>:<url>"
    if text.startswith("APIGET"):
        parts = text.split(":", 2)
        if len(parts) < 3:
            return
        mode, req_id, url = parts[0], parts[1], parts[2].strip()
        audio_only = (mode == "APIGET_AUDIO")

        try:
            data = get_info(url)
            if audio_only:
                data["options"] = [o for o in data["options"] if o["type"] == "audio"]
            result = {"ok": True, "req_id": req_id, **data}
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "bot" in msg.lower() or "sign in" in msg.lower():
                user_msg = "Platform ගෙ bot detection block කළා. ටිකක් ඉඳලා retry කරන්න."
            elif "private" in msg.lower():
                user_msg = "මේ video private / restricted — download කරන්න බෑ."
            elif "unavailable" in msg.lower():
                user_msg = "Video unavailable — delete වෙලා හෝ region blocked."
            else:
                user_msg = f"Download error: {msg[:200]}"
            result = {"ok": False, "req_id": req_id, "error": user_msg}
        except Exception as e:
            result = {"ok": False, "req_id": req_id, "error": str(e)[:200]}

        await update.message.reply_text(
            f"APIRESULT:{json.dumps(result, ensure_ascii=False)}"
        )
        return

    # ── Regular URL download ──────────────────────────────────────────
    m = URL_RE.search(text)
    if m:
        await _do_download(update, m.group(0), audio_only=False)
    else:
        await update.message.reply_text(
            "⚠️ Valid video URL එකක් paste කරන්න.\n"
            "Supported: YouTube, Facebook, Instagram, Twitter/X, TikTok"
        )


async def _do_download(update: Update, url: str, audio_only: bool):
    platform = platform_of(url)
    msg = await update.message.reply_text(
        f"⏳ *{platform}* {'audio' if audio_only else 'video'} download කරනවා...",
        parse_mode="Markdown",
    )

    tmpdir = tempfile.mkdtemp()
    try:
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "%(title).60s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        }

        if audio_only:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            # Best quality ≤ 720p to stay within Telegram 50MB limit
            ydl_opts["format"] = (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=720][ext=mp4]/"
                "best[height<=720]/"
                "best"
            )

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        files = [
            os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
            if os.path.isfile(os.path.join(tmpdir, f))
        ]
        if not files:
            raise RuntimeError("yt-dlp file download failed — no output file")

        fp = files[0]
        size_mb = os.path.getsize(fp) / 1024 ** 2

        if size_mb > 49.5:
            await msg.edit_text(
                f"⚠️ File size {size_mb:.1f} MB — Telegram 50MB limit ඉක්මවා ගියා.\n"
                "Blogger site ගෙ download button use කරන්න."
            )
            return

        await msg.edit_text(f"📤 Uploading {size_mb:.1f} MB...")

        ext = os.path.splitext(fp)[1].lower()
        title = info.get("title", "Video")[:100]

        with open(fp, "rb") as fh:
            if audio_only or ext == ".mp3":
                await update.message.reply_audio(
                    audio=fh,
                    caption=f"🎵 *{title}*",
                    parse_mode="Markdown",
                )
            elif ext in (".mp4", ".mov", ".webm", ".mkv"):
                await update.message.reply_video(
                    video=fh,
                    caption=f"🎬 *{title}*\n_via Video Downloader Bot_",
                    parse_mode="Markdown",
                    supports_streaming=True,
                )
            else:
                await update.message.reply_document(
                    document=fh,
                    caption=f"📎 *{title}*",
                    parse_mode="Markdown",
                )

        await msg.delete()

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "bot" in err.lower() or "sign in" in err.lower():
            friendly = "❌ Platform bot detection — ටිකක් ඉඳලා retry කරන්න."
        elif "private" in err.lower():
            friendly = "❌ Video private / restricted."
        elif "unavailable" in err.lower():
            friendly = "❌ Video unavailable (deleted / region blocked)."
        else:
            friendly = f"❌ Download failed:\n`{err[:200]}`"
        await msg.edit_text(friendly, parse_mode="Markdown")

    except Exception as e:
        await msg.edit_text(f"❌ Error: `{str(e)[:200]}`", parse_mode="Markdown")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN secret not set in GitHub!")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("id",    cmd_id))
    app.add_handler(CommandHandler("audio", cmd_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Bot started — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
