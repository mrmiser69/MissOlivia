# ===============================
# IMPORTS
# ===============================
import os
import time
import asyncio
import contextlib
from html import escape
from datetime import datetime
import logging

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from telegram.error import RetryAfter, Forbidden, BadRequest, ChatMigrated
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ChatMemberHandler,
    PreCheckoutQueryHandler,
)

from psycopg_pool import ConnectionPool  # ✅ ONLY THIS (Supabase safe)

# ===============================
# CONFIG / CONSTANTS
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
START_IMAGE = "https://i.postimg.cc/3xkFCTnR/Start-Image.png"
WELCOME_IMAGE = "https://i.postimg.cc/L6hVSnp3/WELCOME.png"
GOODBYE_IMAGE = "https://i.postimg.cc/bdXNCLc2/Untitled-design-(12).png"

# ===============================
# PHOTO PACKS
# ===============================
WELCOME_PHOTO_PACKS = {
    "oggy": [
        "https://i.postimg.cc/cLSyZPMG/WELCOME-OGGY-PHOTO-1.png",
        "https://i.postimg.cc/1XqXxpm5/WELCOME-OGGY-PHOTO-2.png",
    ],
    "olivia": [
        "https://i.postimg.cc/xd6cLfpn/WELCOME-OLIVIA-PHOTO-1.png",
        "https://i.postimg.cc/5tyztKbD/WELCOME-OLIVIA-PHOTO-2.png",
    ]
}

GOODBYE_PHOTO_PACKS = {
    "oggy": [
        "https://i.postimg.cc/MZ5zs6ys/GOODBYE-OGGY-PHOTO-1.png",
        "https://i.postimg.cc/rwLgKkPj/GOODBYE-OGGY-PHOTO-2.png",
    ],
    "olivia": [
        "https://i.postimg.cc/t45dJVPW/GOODBYE-OLIVIA-PHOTO-1.png",
        "https://i.postimg.cc/W168ZyR0/GOODBYE-OLIVIA-PHOTO-2.png",
    ]
}

WELCOME_PREVIEW_PACKS = {
    "oggy": [
        "https://i.postimg.cc/cLSyZPMG/WELCOME-OGGY-PHOTO-1.png",
        "https://i.postimg.cc/1XqXxpm5/WELCOME-OGGY-PHOTO-2.png",
    ],
    "olivia": [
        "https://i.postimg.cc/xd6cLfpn/WELCOME-OLIVIA-PHOTO-1.png",
        "https://i.postimg.cc/5tyztKbD/WELCOME-OLIVIA-PHOTO-2.png",
    ]
}

GOODBYE_PREVIEW_PACKS = {
    "oggy": [
        "https://i.postimg.cc/MZ5zs6ys/GOODBYE-OGGY-PHOTO-1.png",
        "https://i.postimg.cc/rwLgKkPj/GOODBYE-OGGY-PHOTO-2.png",
    ],
    "olivia": [
        "https://i.postimg.cc/t45dJVPW/GOODBYE-OLIVIA-PHOTO-1.png",
        "https://i.postimg.cc/W168ZyR0/GOODBYE-OLIVIA-PHOTO-2.png",
    ]
}

DB_HOST = os.getenv("SUPABASE_HOST")
DB_NAME = os.getenv("SUPABASE_DB")
DB_USER = os.getenv("SUPABASE_USER")
DB_PASS = os.getenv("SUPABASE_PASSWORD")
DB_PORT = int(os.getenv("SUPABASE_PORT", "6543"))

DB_READY = False

# ===============================
# GLOBAL CACHES
# ===============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.ERROR,
)
logger = logging.getLogger(__name__)

STATS_CACHE = {"users": 0, "groups": 0, "admin_groups": 0, "last_update": 0}
STATS_TTL = 300

BOT_ADMIN_CACHE: set[int] = set()
USER_ADMIN_CACHE: dict[int, set[int]] = {}
REMINDER_MESSAGES: dict[int, list[int]] = {}

# ✅ Broadcast (from link-delete bot — improved version)
PENDING_BROADCAST = {}
PENDING_TARGET = {}
PENDING_BUTTON_WAIT = {}
PENDING_PREVIEW = {}

PHOTO_PACK_SELECTION = {}
PHOTO_PREVIEW_STATE = {}
BOT_START_TIME = int(time.time())

LAST_WELCOME = {}
LAST_GOODBYE = {}
LAST_WELCOME_TS = {}
LAST_GOODBYE_TS = {}

FALLBACK_EVENT_TS = {}
FALLBACK_DEBOUNCE_SECONDS = 3
HELP_CALLBACK = "help_menu"

LOG_RATE_CACHE = {}
LOG_RATE_SECONDS = 60

# ✅ Longer TTL from link-delete bot (300s vs 60s)
ADMIN_VERIFY_CACHE = {}
ADMIN_VERIFY_SECONDS = 300

# =====================================
# DB POOL
# =====================================
pool = None

async def db_execute(query, params=None, fetch=False):
    loop = asyncio.get_running_loop()

    def _run():
        if pool is None:
            raise RuntimeError("DB pool not initialized")
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                if fetch:
                    cols = [d.name for d in (cur.description or [])]
                    rows = cur.fetchall()
                    conn.commit()
                    return [dict(zip(cols, r)) for r in rows] if cols else rows
                conn.commit()

    return await loop.run_in_executor(None, _run)

async def safe_db_execute(query, params=None, fetch=False):
    if pool is None or not DB_READY:
        return None
    try:
        return await db_execute(query, params=params, fetch=fetch)
    except Exception as e:
        rate_limited_log("db_error", f"❌ DB ERROR: {e}")
        return None

# ===============================
# INIT DB
# ===============================
async def init_db():
    if pool is None:
        return

    # ✅ Use safe_db_execute (crash-safe) from link-delete bot
    await safe_db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY
        )
    """)
    await safe_db_execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id BIGINT PRIMARY KEY,
            is_admin_cached BOOLEAN DEFAULT FALSE,
            last_checked_at BIGINT,
            fail_count INT DEFAULT 0,
            last_fail_at BIGINT
        )
    """)
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS fail_count INT DEFAULT 0")
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS last_fail_at BIGINT")
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS custom_welcome_photo TEXT")
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS custom_goodbye_photo TEXT")
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS welcome_photo_pack TEXT")
    await safe_db_execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS goodbye_photo_pack TEXT")

async def is_group_admin_cached_db(chat_id: int) -> bool:
    rows = await safe_db_execute(
        "SELECT is_admin_cached FROM groups WHERE group_id=%s",
        (chat_id,),
        fetch=True
    )
    return bool(rows and rows[0].get("is_admin_cached"))

# ===============================
# GENERIC HELPERS
# ===============================
def rate_limited_log(key: str, message: str):
    now = int(time.time())
    last = LOG_RATE_CACHE.get(key, 0)
    if now - last >= LOG_RATE_SECONDS:
        LOG_RATE_CACHE[key] = now
        print(message)

def clear_reminders(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    job_queue = context.job_queue
    if job_queue is None:
        return
    for job in list(job_queue.jobs()):
        data = job.data or {}
        if data.get("chat_id") != chat_id:
            continue
        name = job.name or ""
        if name.startswith("auto_leave_") or data.get("type") == "admin_reminder":
            job.schedule_removal()

async def iter_db_ids(query, batch_size=500):
    offset = 0
    while True:
        rows = await safe_db_execute(
            f"{query} LIMIT %s OFFSET %s",
            (batch_size, offset),
            fetch=True
        )
        if rows is None:
            break
        if not rows:
            break
        yield rows
        offset += batch_size

async def update_progress(msg, done, total):
    if total <= 0:
        percent = 100
    else:
        percent = int((done / total) * 100)
    bar_blocks = min(10, percent // 10)
    bar = "█" * bar_blocks + "░" * (10 - bar_blocks)
    try:
        await msg.edit_text(
            "📢 <b>Broadcasting...</b>\n\n"
            f"⏳ Progress: {bar} {percent}%",
            parse_mode="HTML"
        )
    except:
        pass

# ===============================
# ADMIN / PERMISSION HELPERS
# ===============================
async def is_bot_admin(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if chat_id in BOT_ADMIN_CACHE:
        return True
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator") and getattr(me, "can_delete_messages", False):
            BOT_ADMIN_CACHE.add(chat_id)
            return True
        return False
    except:
        return False

async def can_bot_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("restricted", "member") and not getattr(me, "can_send_messages", True):
            return False
        if me.status in ("left", "kicked"):
            return False
        return True
    except Exception:
        return False

async def ensure_bot_admin_live(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    now = int(time.time())
    last = ADMIN_VERIFY_CACHE.get(chat_id, 0)
    if now - last < ADMIN_VERIFY_SECONDS:
        return chat_id in BOT_ADMIN_CACHE
    ADMIN_VERIFY_CACHE[chat_id] = now

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except ChatMigrated as e:
        new_id = e.new_chat_id
        ADMIN_VERIFY_CACHE.pop(chat_id, None)
        ADMIN_VERIFY_CACHE.pop(new_id, None)

        if chat_id in BOT_ADMIN_CACHE:
            BOT_ADMIN_CACHE.discard(chat_id)
            BOT_ADMIN_CACHE.add(new_id)
        USER_ADMIN_CACHE[new_id] = USER_ADMIN_CACHE.pop(chat_id, set())
        REMINDER_MESSAGES[new_id] = REMINDER_MESSAGES.pop(chat_id, [])

        context.application.create_task(
            safe_db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                VALUES (%s, TRUE, %s)
                ON CONFLICT (group_id)
                DO UPDATE SET
                  is_admin_cached = TRUE,
                  last_checked_at = EXCLUDED.last_checked_at
                """,
                (new_id, now)
            )
        )
        context.application.create_task(
            safe_db_execute("DELETE FROM groups WHERE group_id=%s", (chat_id,))
        )
        return await ensure_bot_admin_live(new_id, context)
    except Exception:
        ADMIN_VERIFY_CACHE.pop(chat_id, None)
        BOT_ADMIN_CACHE.discard(chat_id)
        USER_ADMIN_CACHE.pop(chat_id, None)
        REMINDER_MESSAGES.pop(chat_id, None)
        return False

    is_admin = me.status in ("administrator", "creator")
    can_delete = getattr(me, "can_delete_messages", False)
    if is_admin and can_delete:
        BOT_ADMIN_CACHE.add(chat_id)
        context.application.create_task(
            safe_db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                VALUES (%s, TRUE, %s)
                ON CONFLICT (group_id)
                DO UPDATE SET
                  is_admin_cached = TRUE,
                  last_checked_at = EXCLUDED.last_checked_at
                """,
                (chat_id, now)
            )
        )
        return True

    BOT_ADMIN_CACHE.discard(chat_id)
    USER_ADMIN_CACHE.pop(chat_id, None)
    REMINDER_MESSAGES.pop(chat_id, None)

    context.application.create_task(
        safe_db_execute(
            """
            INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
            VALUES (%s, FALSE, %s)
            ON CONFLICT (group_id)
            DO UPDATE SET
              is_admin_cached = FALSE,
              last_checked_at = EXCLUDED.last_checked_at
            """,
            (chat_id, now)
        )
    )

    if context.job_queue:
        context.job_queue.run_once(
            leave_if_not_admin,
            when=60,
            data={"chat_id": chat_id},
            name=f"auto_leave_{chat_id}"
        )
    return False

async def is_user_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admins = USER_ADMIN_CACHE.setdefault(chat_id, set())
    if user_id in admins:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ("administrator", "creator"):
            admins.add(user_id)
            return True
        return False
    except:
        return False

# ===============================
# /start
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message

    if not chat or not user or not msg:
        return

    bot = context.bot
    bot_username = bot.username or ""

    if chat.type == "private":
        context.application.create_task(
            safe_db_execute(
                "INSERT INTO users VALUES (%s) ON CONFLICT DO NOTHING",
                (user.id,)
            )
        )

        user_name = escape(user.first_name or "User")
        bot_name = escape(bot.first_name or "Bot")
        user_mention = f"<a href='tg://user?id={user.id}'>{user_name}</a>"
        bot_mention = (
            f"<a href='https://t.me/{bot_username}'>{bot_name}</a>"
            if bot_username else bot_name
        )

        text = (
            f"<b>────「 {bot_mention} 」</b>\n\n"
            f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
            "<b>ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။</b>\n"
            "<b>ငါ၏လုပ်နိုင်စွမ်းကို ကောင်းကောင်းအသုံးချပါ။</b>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📌 ငါ၏လုပ်နိုင်စွမ်း</b>\n\n"
            "<blockquote>"
            "<b>✅ Welcome Message</b>\n"
            "<b>( Member တစ်ယောက် Group ထဲဝင်လာရင် Welcome Message ပို့မယ် )</b>\n"
            "<b>✅ Goodbye Message</b>\n"
            "<b>( Member တစ်ယောက် Group ထဲကထွက်သွားရင် Goodbye Message ပို့မယ် )</b>"
            "</blockquote>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n"
            "<blockquote>"
            "<b>➊ ငါ့ကို Group ထဲထည့်ပါ</b>\n"
            "<b>➋ ငါ့ကို Admin ပေးပါ</b>"
            "</blockquote>"
        )

        buttons = []
        if bot_username:
            buttons.append([
                InlineKeyboardButton(
                    "➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ])
        buttons.append([InlineKeyboardButton("🤍 𝗗𝗢𝗡𝗔𝗧𝗘 𝗨𝗦 🤍", callback_data="donate_menu")])
        buttons.append([InlineKeyboardButton("🖼 𝗦𝗘𝗧 𝗣𝗛𝗢𝗧𝗢 🖼", callback_data="photo_menu")])
        buttons.append([
            InlineKeyboardButton("👨‍💻 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫", url="tg://user?id=5942810488"),
            InlineKeyboardButton("📢 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/MMTelegramBotss"),
        ])
        buttons.append([
            InlineKeyboardButton("📖 အသုံးပြုနည်း နှင့် သတိပေးချက် 📖", callback_data="help_menu")
        ])
        
        try:
            await msg.reply_photo(
                photo=START_IMAGE,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        except BadRequest:
            await msg.reply_text(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        return

    if chat.type in ("group", "supergroup"):
        try:
            me = await bot.get_chat_member(chat.id, bot.id)
        except:
            return

        if me.status in ("member", "restricted"):
            if not getattr(me, "can_send_messages", True):
                return

        if me.status in ("administrator", "creator"):
            try:
                await bot.send_message(
                    chat.id,
                    "✅ Bot ကို Admin အဖြစ်ခန့်ထားပြီးသားပါ။\n\n"
                    "✅ <b>Welcome Message</b>\n"
                    "✅ <b>Goodbye Message</b>\n\n"
                    "🤖 Bot က လက်ရှိ Group မှာ ကောင်းကောင်းအလုပ်လုပ်နေပါပြီး။",
                    parse_mode="HTML"
                )
            except RetryAfter:
                return
            except Exception:
                return
            return

        try:
            await bot.send_message(
                chat.id,
                "⚠️ <b>Bot သည် Admin မဟုတ်သေးပါ</b>\n\n"
                "🤖 <b>Bot ကို အလုပ်လုပ်စေရန်</b>\n"
                "⭐️ <b>Admin Permission ပေးပါ</b>\n\n"
                "Required: Permission",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
                        url=f"https://t.me/{bot_username}?startgroup=true"
                    )
                ]])
            )
        except RetryAfter:
            return
        except Exception:
            return
        return

# ===============================
# Donate Callback
# ===============================
async def donate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()
    data = (query.data or "").strip()

    if query.message.chat.type != "private":
        return

    bot = context.bot
    bot_username = bot.username or ""
    user = update.effective_user

    if data == "donate_menu":
        donate_text = (
            "<b>🤍 Support Us !</b>\n\n"
            "မင်းအတွက် အလုပ်ကောင်းကောင်းလုပ်နေတဲ့ Bot ကို Support ပေးနိုင်ပါတယ်။\n\n"
            "<b>👇 အောက်ကနေ ရွေးပါ</b>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐️ 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗕𝗢𝗧 (5 Stars)", callback_data="donate_stars_5")],
            [InlineKeyboardButton("🪙 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗗𝗘𝗩𝗘𝗟𝗢𝗣𝗘𝗥 (TON)", callback_data="donate_ton")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="donate_back_start")],
        ])
        await query.message.edit_caption(caption=donate_text, parse_mode="HTML", reply_markup=kb)
        return

    if data in ("photo_menu", "setphoto_home"):
        text = (
            "<b>🖼 Photo Setting Menu</b>\n\n"
            "သတ်မှတ်ချင်တဲ့ပုံကို အောက်ကနေရွေးနိုင်ပါတယ်။"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼 Set [ WELCOME ] Photo", callback_data="setwelcome_menu")],
            [InlineKeyboardButton("🖼 Set [ GOODBYE ] Photo", callback_data="setgoodbye_menu")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="donate_back_start")]
        ])
        await query.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "setwelcome_menu":
        text = (
            "<b>🖼 Welcome Photo Setting</b>\n\n"
            "OGGY ပုံလား Olivia ပုံလား အောက်မှာရွေးနိုင်ပါတယ်။"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🐱 OGGY", callback_data="welcome_pack_oggy")],
            [InlineKeyboardButton("💜 Olivia", callback_data="welcome_pack_olivia")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="photo_menu")]
        ])
        await query.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "setgoodbye_menu":
        text = (
            "<b>🖼 Goodbye Photo Setting</b>\n\n"
            "OGGY ပုံလား Olivia ပုံလား အောက်မှာရွေးနိုင်ပါတယ်။"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🐱 OGGY", callback_data="goodbye_pack_oggy")],
            [InlineKeyboardButton("💜 Olivia", callback_data="goodbye_pack_olivia")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="photo_menu")]
        ])
        await query.message.edit_caption(caption=text, parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("welcome_pack_"):
        pack_name = data.replace("welcome_pack_", "")
        photos = WELCOME_PREVIEW_PACKS.get(pack_name)
        if not photos:
            return
        PHOTO_PREVIEW_STATE[user.id] = {"type": "welcome", "pack": pack_name, "index": 0}
        current = photos[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️", callback_data="photo_prev"),
             InlineKeyboardButton("➡️", callback_data="photo_next")],
            [InlineKeyboardButton("✅ Set Photo ✅", callback_data="setphoto_selectgroup")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="setwelcome_menu")]
        ])
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=query.message.chat.id,
            photo=current,
            caption=f"🖼 Welcome Photo Preview\n\nPack: {pack_name.upper()}\nPhoto: 1/{len(photos)}",
            reply_markup=kb
        )
        return

    if data.startswith("goodbye_pack_"):
        pack_name = data.replace("goodbye_pack_", "")
        photos = GOODBYE_PREVIEW_PACKS.get(pack_name)
        if not photos:
            return
        PHOTO_PREVIEW_STATE[user.id] = {"type": "goodbye", "pack": pack_name, "index": 0}
        current = photos[0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️", callback_data="photo_prev"),
             InlineKeyboardButton("➡️", callback_data="photo_next")],
            [InlineKeyboardButton("✅ Set Photo ✅", callback_data="setphoto_selectgroup")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="setgoodbye_menu")]
        ])
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=query.message.chat.id,
            photo=current,
            caption=f"🖼 Goodbye Photo Preview\n\nPack: {pack_name.upper()}\nPhoto: 1/{len(photos)}",
            reply_markup=kb
        )
        return

    if data in ("photo_next", "photo_prev"):
        state = PHOTO_PREVIEW_STATE.get(user.id)
        if not state:
            return
        photo_type = state["type"]
        pack_name = state["pack"]
        index = state["index"]
        if photo_type == "welcome":
            photos = WELCOME_PREVIEW_PACKS.get(pack_name, [])
            back_callback = "setwelcome_menu"
            title = "Welcome"
        else:
            photos = GOODBYE_PREVIEW_PACKS.get(pack_name, [])
            back_callback = "setgoodbye_menu"
            title = "Goodbye"
        if not photos:
            return
        if data == "photo_next":
            index = (index + 1) % len(photos)
        else:
            index = (index - 1) % len(photos)
        state["index"] = index
        current_photo = photos[index]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️", callback_data="photo_prev"),
             InlineKeyboardButton("➡️", callback_data="photo_next")],
            [InlineKeyboardButton("✅ Set Photo ✅", callback_data="setphoto_selectgroup")],
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data=back_callback)]
        ])
        try:
            await query.message.edit_media(
                media=InputMediaPhoto(
                    media=current_photo,
                    caption=f"🖼 {title} Photo Preview\n\nPack: {pack_name.upper()}\nPhoto: {index + 1}/{len(photos)}"
                ),
                reply_markup=kb
            )
        except Exception:
            pass
        return

    if data == "setphoto_selectgroup":
        state = PHOTO_PREVIEW_STATE.get(user.id)
        if not state:
            return
        groups = await get_user_admin_groups(user.id, context)
        if not groups:
            await query.answer("❌ Admin Group မတွေ့ပါ", show_alert=True)
            return
        buttons = []
        for g in groups:
            buttons.append([InlineKeyboardButton(g["title"][:40], callback_data=f"applyphoto_{g['id']}")])
        buttons.append([InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data=f"preview_{state['type']}_{state['pack']}")])
        await query.message.edit_caption(
            caption="🏘 Photo အသုံးပြုမယ့် Group ကိုရွေးပါ",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("applyphoto_"):
        state = PHOTO_PREVIEW_STATE.get(user.id)
        if not state:
            return
        try:
            chat_id = int(data.split("_")[1])
        except:
            return
        try:
            member = await context.bot.get_chat_member(chat_id, user.id)
            if member.status not in ("administrator", "creator"):
                await query.answer("❌ You are not admin", show_alert=True)
                return
        except Exception:
            return

        photo_type = state["type"]
        pack_name = state["pack"]
        index = state.get("index", 0)

        if photo_type == "welcome":
            selected_url = WELCOME_PREVIEW_PACKS[pack_name][index]
            await safe_db_execute(
                """
                INSERT INTO groups (group_id, custom_welcome_photo, welcome_photo_pack)
                VALUES (%s, %s, NULL)
                ON CONFLICT (group_id)
                DO UPDATE SET custom_welcome_photo = EXCLUDED.custom_welcome_photo, welcome_photo_pack = NULL
                """,
                (chat_id, selected_url)
            )
        else:
            selected_url = GOODBYE_PREVIEW_PACKS[pack_name][index]
            await safe_db_execute(
                """
                INSERT INTO groups (group_id, custom_goodbye_photo, goodbye_photo_pack)
                VALUES (%s, %s, NULL)
                ON CONFLICT (group_id)
                DO UPDATE SET custom_goodbye_photo = EXCLUDED.custom_goodbye_photo, goodbye_photo_pack = NULL
                """,
                (chat_id, selected_url)
            )

        try:
            group = await context.bot.get_chat(chat_id)
            group_name = group.title or str(chat_id)
        except Exception:
            group_name = str(chat_id)

        await query.message.edit_caption(
            caption=(
                "✅ Successfully Set Photo\n\n"
                f"🏘 Group: {escape(group_name)}\n"
                f"🖼 Pack: {pack_name.upper()}\n"
                f"📦 Type: {photo_type.title()}"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back To Menu", callback_data="setphoto_home")
            ]])
        )
        return

    if data == "donate_back_start":
        user_name = escape(user.first_name or "User")
        bot_name = escape(bot.first_name or "Bot")
        user_mention = f"<a href='tg://user?id={user.id}'>{user_name}</a>"
        bot_mention = (
            f"<a href='https://t.me/{bot_username}'>{bot_name}</a>"
            if bot_username else bot_name
        )
        start_text = (
            f"<b>────「 {bot_mention} 」</b>\n\n"
            f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
            "<b>ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။</b>\n"
            "<b>ငါ၏လုပ်နိုင်စွမ်းကို ကောင်းကောင်းအသုံးချပါ။</b>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📌 ငါ၏လုပ်နိုင်စွမ်း</b>\n\n"
            "<blockquote>"
            "<b>✅ Welcome Message</b>\n"
            "<b>( Member တစ်ယောက် Group ထဲဝင်လာရင် Welcome Message ပို့မယ် )</b>\n"
            "<b>✅ Goodbye Message</b>\n"
            "<b>( Member တစ်ယောက် Group ထဲကထွက်သွားရင် Goodbye Message ပို့မယ် )</b>"
            "</blockquote>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n"
            "<blockquote>"
            "<b>➊ ငါ့ကို Group ထဲထည့်ပါ</b>\n"
            "<b>➋ ငါ့ကို Admin ပေးပါ</b>"
            "</blockquote>"
        )
        buttons = []
        if bot_username:
            buttons.append([InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣", url=f"https://t.me/{bot_username}?startgroup=true")])
        buttons.append([InlineKeyboardButton("🤍 𝗗𝗢𝗡𝗔𝗧𝗘 𝗨𝗦 🤍", callback_data="donate_menu")])
        buttons.append([InlineKeyboardButton("🖼 𝗦𝗘𝗧 𝗣𝗛𝗢𝗧𝗢 🖼", callback_data="photo_menu")])
        buttons.append([
            InlineKeyboardButton("👨‍💻 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫", url="tg://user?id=5942810488"),
            InlineKeyboardButton("📢 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/MMTelegramBotss"),
        ])
        buttons.append([
            InlineKeyboardButton("📖 အသုံးပြုနည်း နှင့် သတိပေးချက် 📖", callback_data="help_menu")
        ])        

        await query.message.edit_caption(
            caption=start_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data == "donate_ton":
        TON_ADDRESS = os.getenv("TON_ADDRESS", "PUT_YOUR_TON_ADDRESS_HERE")
        ton_text = (
            "<b>🪙 Support Developer (TON)</b>\n\n"
            f"<b>TON Address:</b>\n<code>{escape(TON_ADDRESS)}</code>\n\n"
            "<blockquote><b>✅ Address ကို copy လုပ်ပြီး TON coin ပေးပို့နိုင်ပါတယ်ဗျ။</b></blockquote>\n"
            "<b>💙 Thank You For Supporting !</b>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤", callback_data="donate_menu")]])
        await query.message.edit_caption(caption=ton_text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "donate_stars_5":
        from telegram import LabeledPrice
        try:
            await context.bot.send_invoice(
                chat_id=query.message.chat.id,
                title="Support Bot",
                description=(
                    "⭐️ Telegram Stars ၅ လုံးနဲ့ Bot ကို Support ပေးနိုင်ပါတယ်။\n\n"
                    "မင်းရဲ့ အားပေးမှုက ဒီ Bot ကို ပိုကောင်းအောင် ဆက်လုပ်နိုင်ဖို့ အားအင်ဖြစ်စေပါတယ် 💙"
                ),
                payload=f"donate_bot_5_{user.id}",
                currency="XTR",
                prices=[LabeledPrice("Support", 5)],
                provider_token="",
            )
        except Exception as e:
            await query.answer(f"❌ Donate မလုပ်နိုင်ပါ: {e}", show_alert=True)
        return


    # ========================
    # HELP MENU
    # ========================
    if data == "help_menu":
        help_text = (
            "<b>⚠️ သတိပေးချက်</b>\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<blockquote>"
            "မိမိရဲ့ Group မှာ အရင်ကအသုံးပြုထားသည့် Welcome And Goodbye Message ပို့သည့် Bot များကို Group ထဲကအရင်ဆုံးထုတ်ထားပေးပါဗျ။ ဒါမှ Oggy And Olivia က ကောင်းကောင်းအလုပ်လုပ်နိုင်မှာဖြစ်ပါတယ်။\n\n"
            "အရင်ထည့်ထားတဲ့ Bot ရှိနေရင် အရင်ထည့်ထားတဲ့ Bot ကပဲ Welcome And GoodBye Message ကို အရင်ပို့သွားမှာဖြစ်လို့ Oggy And Olivia ရဲ့ Welcome And GoodBye Message က အလုပ်မလုပ်ပဲဖြစ်နေမှာဖြစ်ပါတယ်။"
            "</blockquote>\n\n"
            "<b>📖 အသုံးပြုနည်း</b>\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<blockquote>"
            "<b>➊ Welcome And GoodBye Message သည် Bot ကို Group ထဲထည့်ပြီး Admin ပေးလိုက်တာနဲ့ အလုပ်လုပ်မှာဖြစ်ပါတယ်။</b>\n\n"
            "<b>➋ 🖼 Set Photo 🖼 ခလုတ်ကိုနှိပ်ပြီး မိမိရဲ့ Group မှာ Welcome And Goodbye Message ပုံတွေကိုရွေးချယ်အသုံးပြုနိုင်ပါတယ်။</b>"
            "</blockquote>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ 𝐁𝐚𝐜𝐤 𝐭𝐨 𝐌𝐚𝐢𝐧 𝐌𝐞𝐧𝐮", callback_data="donate_back_start")]
        ])
        await query.message.edit_caption(
            caption=help_text,
            parse_mode="HTML",
            reply_markup=kb
        )
        return

# ===============================
# Precheckout + Payment
# ===============================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if not query:
        return
    if not (query.payload or "").startswith("donate_bot_5_"):
        await query.answer(ok=False, error_message="Invalid payment payload.")
        return
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text("✅ ကျေးဇူးတင်ပါတယ်! Stars Donate လုပ်ပြီးပါပြီ ⭐️")

# ===============================
# /stats
# ===============================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if (not chat or chat.type != "private" or not user or user.id != OWNER_ID or not msg):
        return

    now = time.time()
    if now - STATS_CACHE["last_update"] > STATS_TTL:
        users = await safe_db_execute("SELECT COUNT(*) AS c FROM users", fetch=True)
        groups = await safe_db_execute("SELECT COUNT(*) AS c FROM groups", fetch=True)
        admin_groups = await safe_db_execute("SELECT COUNT(*) AS c FROM groups WHERE is_admin_cached = TRUE", fetch=True)

        if users is None or groups is None or admin_groups is None:
            await msg.reply_text("⚠️ Stats မတွက်နိုင်ပါ (DB unavailable)")
            return

        STATS_CACHE["users"] = int(users[0]["c"]) if users else 0
        STATS_CACHE["groups"] = int(groups[0]["c"]) if groups else 0
        STATS_CACHE["admin_groups"] = int(admin_groups[0]["c"]) if admin_groups else 0
        STATS_CACHE["last_update"] = now

    no_admin = max(0, STATS_CACHE["groups"] - STATS_CACHE["admin_groups"])
    uptime = int(time.time()) - BOT_START_TIME
    h, m = divmod(uptime // 60, 60)

    await msg.reply_text(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👤 Users: <b>{STATS_CACHE['users']}</b>\n"
        f"👥 Groups: <b>{STATS_CACHE['groups']}</b>\n\n"
        f"🔐 Admin Groups: <b>{STATS_CACHE['admin_groups']}</b>\n"
        f"⚠️ No Admin Groups: <b>{no_admin}</b>\n\n"
        f"⏱️ Uptime: <b>{h}h {m}m</b>",
        parse_mode="HTML"
    )

# ===============================
# PHOTO PACK HELPERS
# ===============================
async def get_user_admin_groups(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    groups = []
    rows = await safe_db_execute("SELECT group_id FROM groups ORDER BY group_id", fetch=True) or []
    for row in rows:
        gid = row["group_id"]
        try:
            member = await context.bot.get_chat_member(gid, user_id)
            if member.status not in ("administrator", "creator"):
                continue
            chat = await context.bot.get_chat(gid)
            groups.append({"id": gid, "title": chat.title or str(gid)})
        except Exception:
            continue
    return groups

async def set_group_photo_pack(chat_id: int, welcome_pack: str, goodbye_pack: str):
    await safe_db_execute(
        """
        INSERT INTO groups (group_id, welcome_photo_pack, goodbye_photo_pack)
        VALUES (%s, %s, %s)
        ON CONFLICT (group_id)
        DO UPDATE SET
            welcome_photo_pack = EXCLUDED.welcome_photo_pack,
            goodbye_photo_pack = EXCLUDED.goodbye_photo_pack
        """,
        (chat_id, welcome_pack, goodbye_pack)
    )

async def get_group_welcome_photo(chat_id: int):
    rows = await safe_db_execute(
        "SELECT custom_welcome_photo, welcome_photo_pack FROM groups WHERE group_id=%s",
        (chat_id,), fetch=True
    )
    if rows:
        custom_photo = rows[0].get("custom_welcome_photo")
        if custom_photo:
            return custom_photo
        pack = rows[0].get("welcome_photo_pack")
        if pack and pack in WELCOME_PHOTO_PACKS:
            import random
            return random.choice(WELCOME_PHOTO_PACKS[pack])
    return WELCOME_IMAGE

async def get_group_goodbye_photo(chat_id: int):
    rows = await safe_db_execute(
        "SELECT custom_goodbye_photo, goodbye_photo_pack FROM groups WHERE group_id=%s",
        (chat_id,), fetch=True
    )
    if rows:
        custom_photo = rows[0].get("custom_goodbye_photo")
        if custom_photo:
            return custom_photo
        pack = rows[0].get("goodbye_photo_pack")
        if pack and pack in GOODBYE_PHOTO_PACKS:
            import random
            return random.choice(GOODBYE_PHOTO_PACKS[pack])
    return GOODBYE_IMAGE

# ===============================
# TEXT BUILDERS
# ===============================
def build_welcome_text(chat, member, joined_time: str):
    group_title = escape(chat.title or "Group")
    if getattr(chat, "username", None):
        group_title_link = f"<a href='https://t.me/{chat.username}'>{group_title}</a>"
    else:
        group_title_link = group_title

    name = escape(member.first_name or "User")
    mention = f"<a href='tg://user?id={member.id}'>{name}</a>"

    if member.username:
        uname = escape(member.username)
        username_link = f"<a href='https://t.me/{uname}'>@{uname}</a>"
    else:
        username_link = "No Username"

    return (
        f"✨ <b>Welcome to {group_title_link}</b> ✨\n\n"
        f"👤 Name: {mention}\n"
        f"🆔 User ID: <code>{member.id}</code>\n"
        f"👤 Username: {username_link}\n"
        f"⏰ Joined at: {escape(joined_time)}"
    )

def build_goodbye_text(member, left_time: str):
    name = escape(member.first_name or "User")
    mention = f"<a href='tg://user?id={member.id}'>{name}</a>"
    return (
        f"⛔️ <b>ထွက်သွားပြီးပေါ့</b>\n"
        f"<b>နှစ်တစ်ထောင် Fa ဖြစ်ပါစေ။</b>\n\n"
        f"👤 Name: {mention}\n"
        f"🆔 User ID: <code>{member.id}</code>\n"
        f"⏰ Left at: {escape(left_time)}"
    )

# ===============================
# 👋 WELCOME
# ===============================
async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cm = update.chat_member
    if not chat or chat.type not in ("group", "supergroup") or not cm:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status
    user = cm.new_chat_member.user

    if user.is_bot:
        return

    JOIN_STATUSES = {"member", "restricted", "administrator"}
    LEFT_STATUSES = {"left", "kicked"}

    joined = (old_status in LEFT_STATUSES and new_status in JOIN_STATUSES)

    if old_status == "member" and new_status == "administrator":
        return
    if old_status == "restricted" and new_status == "member":
        return
    if not joined:
        return

    if not await can_bot_send(chat.id, context):
        return

    now_ts = int(time.time())
    last_ts = LAST_WELCOME_TS.get((chat.id, user.id))
    if last_ts and (now_ts - last_ts) < 5:
        return
    LAST_WELCOME_TS[(chat.id, user.id)] = now_ts
    FALLBACK_EVENT_TS[(chat.id, user.id, "join")] = now_ts

    joined_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = build_welcome_text(chat, user, joined_time)

    bot_username = context.bot.username or ""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
                             url=f"https://t.me/{bot_username}?startgroup=true")
    ]]) if bot_username else None

    try:
        msg = await context.bot.send_photo(
            chat_id=chat.id,
            photo=await get_group_welcome_photo(chat.id),
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        LAST_WELCOME[chat.id] = msg.message_id
        LAST_WELCOME_TS[(chat.id, user.id)] = int(time.time())
    except RetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        with contextlib.suppress(Exception):
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=await get_group_welcome_photo(chat.id),
                caption=text, parse_mode="HTML", reply_markup=keyboard
            )
    except Forbidden:
        return
    except BadRequest:
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")
    except Exception:
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")

# ===============================
# 👋 GOODBYE
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cm = update.chat_member
    if not chat or chat.type not in ("group", "supergroup") or not cm:
        return

    old = cm.old_chat_member
    new = cm.new_chat_member
    user = cm.new_chat_member.user

    if user.is_bot:
        return

    ACTIVE_STATUSES = {"member", "restricted", "administrator"}
    LEFT_STATUSES = {"left", "kicked"}

    left = (old.status in ACTIVE_STATUSES and new.status in LEFT_STATUSES)

    if old.status == "administrator" and new.status == "member":
        return
    if not left:
        return

    try:
        await context.bot.get_chat(chat.id)
    except Forbidden:
        return
    except Exception:
        pass

    if not await can_bot_send(chat.id, context):
        return

    now_ts = int(time.time())
    last_ts = LAST_GOODBYE_TS.get((chat.id, user.id))
    if last_ts and (now_ts - last_ts) < 5:
        return
    LAST_GOODBYE_TS[(chat.id, user.id)] = now_ts
    FALLBACK_EVENT_TS[(chat.id, user.id, "left")] = now_ts

    left_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = build_goodbye_text(user, left_time)

    bot_username = context.bot.username or ""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
                             url=f"https://t.me/{bot_username}?startgroup=true")
    ]]) if bot_username else None

    try:
        await context.bot.send_photo(
            chat_id=chat.id,
            photo=await get_group_goodbye_photo(chat.id),
            caption=text, parse_mode="HTML", reply_markup=keyboard
        )
    except RetryAfter as e:
        await asyncio.sleep(getattr(e, "retry_after", 1))
        with contextlib.suppress(Exception):
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=await get_group_goodbye_photo(chat.id),
                caption=text, parse_mode="HTML", reply_markup=keyboard
            )
    except Forbidden:
        return
    except BadRequest:
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")
    except Exception:
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")

# ===============================
# Fallback
# ===============================
def _fallback_debounce(chat_id: int, user_id: int, kind: str) -> bool:
    now_ts = int(time.time())
    key = (chat_id, user_id, kind)
    last = FALLBACK_EVENT_TS.get(key, 0)
    if last and (now_ts - last) < FALLBACK_DEBOUNCE_SECONDS:
        return True
    FALLBACK_EVENT_TS[key] = now_ts
    return False

async def fallback_join_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type not in ("group", "supergroup") or not msg:
        return
    if not await can_bot_send(chat.id, context):
        return

    new_members = getattr(msg, "new_chat_members", None) or []
    for m in new_members:
        if m.is_bot:
            continue
        if _fallback_debounce(chat.id, m.id, "join"):
            continue
        last_main = LAST_WELCOME_TS.get((chat.id, m.id))
        if last_main and (int(time.time()) - last_main < 5):
            continue
        joined_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = build_welcome_text(chat, m, joined_time)
        with contextlib.suppress(Exception):
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=await get_group_welcome_photo(chat.id),
                caption=text, parse_mode="HTML"
            )

    left_member = getattr(msg, "left_chat_member", None)
    if left_member and not left_member.is_bot:
        last_main = LAST_GOODBYE_TS.get((chat.id, left_member.id))
        if last_main and (int(time.time()) - last_main < 5):
            return
        if not _fallback_debounce(chat.id, left_member.id, "left"):
            left_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            text = build_goodbye_text(left_member, left_time)
            with contextlib.suppress(Exception):
                await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=await get_group_goodbye_photo(chat.id),
                    caption=text, parse_mode="HTML"
                )

# ===============================
# BROADCAST FAIL TRACKING
# ===============================
async def record_broadcast_result(chat_id: int, success: bool):
    rows = await safe_db_execute(
        "SELECT is_admin_cached, fail_count FROM groups WHERE group_id=%s",
        (chat_id,), fetch=True
    )
    now = int(time.time())

    if not rows:
        if success:
            is_admin = (chat_id in BOT_ADMIN_CACHE)
            await safe_db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at, fail_count, last_fail_at)
                VALUES (%s, %s, %s, 0, NULL)
                ON CONFLICT (group_id) DO UPDATE SET last_checked_at = EXCLUDED.last_checked_at
                """,
                (chat_id, is_admin, now)
            )
            return
        await safe_db_execute(
            """
            INSERT INTO groups (group_id, is_admin_cached, last_checked_at, fail_count, last_fail_at)
            VALUES (%s, FALSE, %s, 1, %s)
            ON CONFLICT (group_id)
            DO UPDATE SET
              last_checked_at = EXCLUDED.last_checked_at,
              fail_count = COALESCE(groups.fail_count, 0) + 1,
              last_fail_at = EXCLUDED.last_fail_at
            """,
            (chat_id, now, now)
        )
        return

    is_admin = bool(rows[0].get("is_admin_cached"))
    fails = int(rows[0].get("fail_count") or 0)

    if success:
        await safe_db_execute("UPDATE groups SET fail_count=0, last_fail_at=NULL WHERE group_id=%s", (chat_id,))
        return

    if not is_admin:
        fails += 1
        if fails >= 10:
            await safe_db_execute("DELETE FROM groups WHERE group_id=%s", (chat_id,))
            return
        await safe_db_execute(
            "UPDATE groups SET fail_count=%s, last_fail_at=%s WHERE group_id=%s",
            (fails, now, chat_id)
        )

# ===============================
# BROADCAST SYSTEM (✅ Improved from link-delete bot)
# ===============================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    msg = update.effective_message
    if not msg:
        return

    raw = msg.text or msg.caption or ""
    if not raw.startswith("/broadcast"):
        return

    mode = "content"
    if raw.startswith("/broadcast_fwd"):
        mode = "forward"
        raw = raw.replace("/broadcast_fwd", "", 1).strip()
    elif raw.startswith("/broadcast_copy"):
        mode = "copy"
        raw = raw.replace("/broadcast_copy", "", 1).strip()
    else:
        raw = raw.replace("/broadcast", "", 1).strip()

    src = msg.reply_to_message if msg.reply_to_message else msg
    content = {
        "mode": mode,
        "text": raw,
        "photo": src.photo[-1].file_id if getattr(src, "photo", None) else None,
        "video": src.video.file_id if getattr(src, "video", None) else None,
        "audio": src.audio.file_id if getattr(src, "audio", None) else None,
        "document": src.document.file_id if getattr(src, "document", None) else None,
        "from_chat_id": src.chat.id,
        "message_id": src.message_id,
    }

    has_any_media = any([content["photo"], content["video"], content["audio"], content["document"]])
    has_text = bool(content["text"])

    if mode in ("forward", "copy") and not msg.reply_to_message:
        await msg.reply_text("❌ /broadcast_fwd or /broadcast_copy ကို Reply ပြီး သုံးပါ။")
        return

    if not (has_text or has_any_media or mode in ("forward", "copy")):
        await msg.reply_text("❌ Broadcast လုပ်ရန် content မတွေ့ပါ")
        return

    PENDING_BROADCAST[OWNER_ID] = content

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ CONFIRM", callback_data="broadcast_confirm"),
        InlineKeyboardButton("❌ CANCEL", callback_data="broadcast_cancel")
    ]])
    await msg.reply_text("📢 <b>Broadcast Confirm လုပ်ပါ</b>", parse_mode="HTML", reply_markup=keyboard)

async def broadcast_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        await query.answer()
        return
    await query.answer()
    if OWNER_ID not in PENDING_BROADCAST:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Users only", callback_data="bc_target_users")],
        [InlineKeyboardButton("👥 Groups only", callback_data="bc_target_groups")],
        [InlineKeyboardButton("👥👤 Users + Groups", callback_data="bc_target_all")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ])
    await query.edit_message_text("📢 <b>Broadcast Target ကိုရွေးပါ</b>", parse_mode="HTML", reply_markup=keyboard)

async def broadcast_target_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if OWNER_ID not in PENDING_BROADCAST:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    target_type = query.data
    PENDING_TARGET[OWNER_ID] = target_type

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Post Now", callback_data="bc_post_now")],
        [InlineKeyboardButton("➕ Auto Add Button", callback_data="bc_btn_auto")],
        [InlineKeyboardButton("🔗 Manual Button URL", callback_data="bc_btn_manual")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ])
    await query.edit_message_text("📢 <b>Post Option ကိုရွေးပါ</b>", parse_mode="HTML", reply_markup=keyboard)

async def broadcast_post_now_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = PENDING_BROADCAST.pop(OWNER_ID, None)
    target_type = PENDING_TARGET.pop(OWNER_ID, None)
    PENDING_BUTTON_WAIT.pop(OWNER_ID, None)

    if not data or not target_type:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    PENDING_PREVIEW[OWNER_ID] = {"data": data, "target": target_type, "button_url": None}
    await show_preview(update, context)

async def broadcast_auto_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if OWNER_ID not in PENDING_BROADCAST or OWNER_ID not in PENDING_TARGET:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    bot_username = context.bot.username or ""
    if not bot_username:
        await query.edit_message_text("❌ Bot username မရှိလို့ Auto button မလုပ်နိုင်ပါ")
        return

    url = f"https://t.me/{bot_username}?startgroup=true"
    data = PENDING_BROADCAST.pop(OWNER_ID, None)
    target_type = PENDING_TARGET.pop(OWNER_ID, None)
    PENDING_BUTTON_WAIT.pop(OWNER_ID, None)

    if not data or not target_type:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    PENDING_PREVIEW[OWNER_ID] = {"data": data, "target": target_type, "button_url": url}
    await show_preview(update, context)

async def broadcast_manual_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if OWNER_ID not in PENDING_BROADCAST or OWNER_ID not in PENDING_TARGET:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    PENDING_BUTTON_WAIT[OWNER_ID] = True
    await query.edit_message_text("🔗 Button URL ကို ပို့ပါ\n\nExample:\nhttps://t.me/YourBot")

async def broadcast_button_url_receiver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not user or user.id != OWNER_ID or not msg:
        return
    if OWNER_ID not in PENDING_BUTTON_WAIT:
        return

    url = (msg.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await msg.reply_text("❌ Invalid URL (http/https) ပဲထည့်ပါ")
        return

    PENDING_BUTTON_WAIT.pop(OWNER_ID, None)
    data = PENDING_BROADCAST.pop(OWNER_ID, None)
    target_type = PENDING_TARGET.pop(OWNER_ID, None)

    if not data or not target_type:
        await msg.reply_text("❌ Broadcast data မရှိပါ")
        return

    PENDING_PREVIEW[OWNER_ID] = {"data": data, "target": target_type, "button_url": url}
    await show_preview(update, context)

async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = (query.message.chat.id if query and query.message else None) or (update.effective_chat.id if update.effective_chat else None)
    if not chat_id:
        return

    preview = PENDING_PREVIEW.get(OWNER_ID)
    if not preview:
        return

    data = dict(preview["data"])
    data["button_url"] = preview["button_url"]
    await send_content(context, chat_id, data)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ SEND", callback_data="bc_preview_send"),
        InlineKeyboardButton("❌ CANCEL", callback_data="bc_preview_cancel"),
    ]])
    await context.bot.send_message(
        chat_id=chat_id,
        text="🔍 <b>Preview</b>\n\nဒီပုံစံနဲ့ Broadcast ပို့မယ်",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def broadcast_preview_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    preview = PENDING_PREVIEW.pop(OWNER_ID, None)
    if not preview:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    data = preview["data"]
    target_type = preview["target"]
    button_url = preview["button_url"]

    progress_msg = await query.edit_message_text(
        "📢 <b>Broadcasting...</b>\n\n⏳ Progress: 0%", parse_mode="HTML"
    )
    await run_broadcast(context, data, target_type, progress_msg, button_url=button_url)

async def broadcast_preview_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    PENDING_PREVIEW.pop(OWNER_ID, None)
    PENDING_BROADCAST.pop(OWNER_ID, None)
    PENDING_TARGET.pop(OWNER_ID, None)
    PENDING_BUTTON_WAIT.pop(OWNER_ID, None)
    await context.bot.send_message(chat_id=query.message.chat.id, text="❌ Broadcast Cancel လုပ်လိုက်ပါပြီ")

async def run_broadcast(context, data, target_type, progress_msg, button_url=None):
    if pool is None or not DB_READY:
        try:
            await progress_msg.edit_text(
                "❌ <b>Broadcast မလုပ်နိုင်ပါ</b>\n\n⚠️ <b>DB unavailable</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    sent = 0
    attempted = 0
    start_time = time.time()
    total = 0

    if target_type in ("bc_target_users", "bc_target_all"):
        rows = await safe_db_execute("SELECT COUNT(*) AS c FROM users", fetch=True)
        total += int(rows[0]["c"]) if rows else 0
    if target_type in ("bc_target_groups", "bc_target_all"):
        rows = await safe_db_execute("SELECT COUNT(*) AS c FROM groups", fetch=True)
        total += int(rows[0]["c"]) if rows else 0

    async def send_one(cid, is_group):
        nonlocal sent, attempted
        tmp = dict(data)
        tmp["button_url"] = button_url
        res = await safe_send(send_content, context, cid, tmp)
        attempted += 1
        if res:
            sent += 1
            if is_group:
                context.application.create_task(record_broadcast_result(cid, True))
        else:
            if is_group:
                context.application.create_task(record_broadcast_result(cid, False))
        if attempted % 50 == 0 or attempted == total:
            await update_progress(progress_msg, attempted, total)

    if target_type in ("bc_target_users", "bc_target_all"):
        async for rows in iter_db_ids("SELECT user_id FROM users ORDER BY user_id"):
            for r in rows:
                await send_one(int(r["user_id"]), False)

    if target_type in ("bc_target_groups", "bc_target_all"):
        async for rows in iter_db_ids("SELECT group_id FROM groups ORDER BY group_id"):
            for r in rows:
                await send_one(int(r["group_id"]), True)

    elapsed = int(time.time() - start_time)
    try:
        await progress_msg.edit_text(
            "✅ <b>Broadcast Completed</b>\n\n"
            f"📨 Sent: <b>{sent}</b>\n"
            f"📦 Attempted: <b>{attempted}</b>\n"
            f"⏱️ Time: <b>{elapsed // 60}m {elapsed % 60}s</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

async def safe_send(func, *args, **kwargs):
    for _ in range(5):
        try:
            return await func(*args, **kwargs)
        except ChatMigrated as e:
            try:
                ctx = args[0]
                old_chat_id = args[1]
                new_chat_id = e.new_chat_id
                ADMIN_VERIFY_CACHE.pop(old_chat_id, None)
                ADMIN_VERIFY_CACHE.pop(new_chat_id, None)
                if old_chat_id in BOT_ADMIN_CACHE:
                    BOT_ADMIN_CACHE.discard(old_chat_id)
                    BOT_ADMIN_CACHE.add(new_chat_id)
                USER_ADMIN_CACHE[new_chat_id] = USER_ADMIN_CACHE.pop(old_chat_id, set())
                REMINDER_MESSAGES[new_chat_id] = REMINDER_MESSAGES.pop(old_chat_id, [])
                try:
                    me = await ctx.bot.get_chat_member(new_chat_id, ctx.bot.id)
                    is_admin = me.status in ("administrator", "creator") and getattr(me, "can_delete_messages", False)
                except Exception:
                    is_admin = False
                ctx.application.create_task(
                    safe_db_execute(
                        """
                        INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (group_id)
                        DO UPDATE SET is_admin_cached = EXCLUDED.is_admin_cached, last_checked_at = EXCLUDED.last_checked_at
                        """,
                        (new_chat_id, is_admin, int(time.time()))
                    )
                )
                ctx.application.create_task(safe_db_execute("DELETE FROM groups WHERE group_id=%s", (old_chat_id,)))
                args = (args[0], new_chat_id, *args[2:])
                continue
            except Exception:
                return None
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except (Forbidden, BadRequest):
            return None
    return None

async def broadcast_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        await query.answer()
        return
    await query.answer()
    PENDING_BROADCAST.pop(OWNER_ID, None)
    PENDING_TARGET.pop(OWNER_ID, None)
    PENDING_BUTTON_WAIT.pop(OWNER_ID, None)
    await query.edit_message_text("❌ Broadcast Cancel လုပ်လိုက်ပါပြီ")

async def send_content(context, chat_id, data):
    mode = data.get("mode", "content")
    button_url = (data.get("button_url") or "").strip()
    reply_markup = None
    if button_url:
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣", url=button_url)
        ]])

    if mode in ("forward", "copy"):
        from_chat_id = data.get("from_chat_id")
        message_id = data.get("message_id")
        if not from_chat_id or not message_id:
            return None
        try:
            override_text = (data.get("text") or "").strip()
            if mode == "forward":
                res = await context.bot.forward_message(
                    chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id
                )
                if override_text:
                    with contextlib.suppress(Exception):
                        await context.bot.send_message(chat_id=chat_id, text=override_text, parse_mode="HTML")
                if reply_markup:
                    with contextlib.suppress(Exception):
                        await context.bot.send_message(chat_id=chat_id, text="🔗", reply_markup=reply_markup)
                return res
            else:
                if override_text:
                    with contextlib.suppress(Exception):
                        await context.bot.send_message(chat_id=chat_id, text=override_text, parse_mode="HTML")
                res = await context.bot.copy_message(
                    chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id
                )
                if reply_markup:
                    with contextlib.suppress(Exception):
                        await context.bot.send_message(chat_id=chat_id, text="🔗", reply_markup=reply_markup)
                return res
        except (Forbidden, BadRequest):
            return None
        except Exception:
            return None

    text = (data.get("text") or "").strip()
    try:
        if data.get("photo"):
            try:
                return await context.bot.send_photo(
                    chat_id=chat_id, photo=data["photo"],
                    caption=text or None, parse_mode="HTML", reply_markup=reply_markup
                )
            except BadRequest:
                return await context.bot.send_photo(
                    chat_id=chat_id, photo=data["photo"],
                    caption=text or None, reply_markup=reply_markup
                )
        if data.get("video"):
            try:
                return await context.bot.send_video(
                    chat_id=chat_id, video=data["video"],
                    caption=text or None, parse_mode="HTML", reply_markup=reply_markup
                )
            except BadRequest:
                return await context.bot.send_video(
                    chat_id=chat_id, video=data["video"],
                    caption=text or None, reply_markup=reply_markup
                )
        if data.get("audio"):
            try:
                return await context.bot.send_audio(
                    chat_id=chat_id, audio=data["audio"],
                    caption=text or None, parse_mode="HTML", reply_markup=reply_markup
                )
            except BadRequest:
                return await context.bot.send_audio(
                    chat_id=chat_id, audio=data["audio"],
                    caption=text or None, reply_markup=reply_markup
                )
        if data.get("document"):
            try:
                return await context.bot.send_document(
                    chat_id=chat_id, document=data["document"],
                    caption=text or None, parse_mode="HTML", reply_markup=reply_markup
                )
            except BadRequest:
                return await context.bot.send_document(
                    chat_id=chat_id, document=data["document"],
                    caption=text or None, reply_markup=reply_markup
                )
        if text:
            try:
                return await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup
                )
            except BadRequest:
                return await context.bot.send_message(
                    chat_id=chat_id, text=text, reply_markup=reply_markup
                )
    except (Forbidden, BadRequest):
        return None
    except Exception:
        return None

# ===============================
# CHAT MEMBER EVENTS
# ===============================
async def leave_if_not_admin(context: ContextTypes.DEFAULT_TYPE):
    if not context.job or not context.job.data:
        return
    chat_id = context.job.data.get("chat_id")
    if not chat_id:
        return

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator") and getattr(me, "can_delete_messages", False):
            BOT_ADMIN_CACHE.add(chat_id)
            return
    except:
        pass

    BOT_ADMIN_CACHE.discard(chat_id)
    USER_ADMIN_CACHE.pop(chat_id, None)
    REMINDER_MESSAGES.pop(chat_id, None)

    context.application.create_task(
        safe_db_execute(
            "UPDATE groups SET is_admin_cached = FALSE, last_checked_at = %s WHERE group_id = %s",
            (int(time.time()), chat_id)
        )
    )
    try:
        await context.bot.leave_chat(chat_id)
    except Exception as e:
        print(f"⚠️ Leave chat failed ({chat_id}):", e)

async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.my_chat_member:
        return
    chat = update.effective_chat
    if not chat:
        return

    USER_ADMIN_CACHE.pop(chat.id, None)
    # ✅ From link-delete bot: clear verify throttle immediately
    ADMIN_VERIFY_CACHE.pop(chat.id, None)

    old = update.my_chat_member.old_chat_member
    new = update.my_chat_member.new_chat_member
    if not old or not new:
        return

    bot_id = context.bot.id

    if (new.user.id == bot_id and new.status == "administrator" and old.status != "administrator"):
        is_ok = getattr(new, "can_delete_messages", False)
        if is_ok:
            BOT_ADMIN_CACHE.add(chat.id)
        else:
            BOT_ADMIN_CACHE.discard(chat.id)

        clear_reminders(context, chat.id)
        for mid in REMINDER_MESSAGES.pop(chat.id, []):
            with contextlib.suppress(Exception):
                await context.bot.delete_message(chat.id, mid)

        context.application.create_task(
            safe_db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (group_id)
                DO UPDATE SET
                    is_admin_cached = EXCLUDED.is_admin_cached,
                    last_checked_at = EXCLUDED.last_checked_at,
                    fail_count = 0,
                    last_fail_at = NULL
                """,
                (chat.id, is_ok, int(time.time()))
            )
        )

        try:
            await context.bot.send_message(
                chat.id,
                "✅ <b>Thank you!</b>\n\n"
                "🤖 <b>Bot</b> ကို <b>Admin</b> အဖြစ် ခန့်ထားပြီးပါပြီး။\n\n"
                "🐇 <b>Welcome Message</b>\n"
                "🐇 <b>Goodbye Message</b>\n\n"
                "✅ စတင်အလုပ်လုပ်နေပါပြီး.........!",
                parse_mode="HTML"
            )
        except:
            pass
        return

    if (old.user.id == bot_id and old.status in ("administrator", "creator") and new.status in ("member", "left", "kicked")):
        BOT_ADMIN_CACHE.discard(chat.id)
        clear_reminders(context, chat.id)
        if context.job_queue:
            context.job_queue.run_once(
                leave_if_not_admin,
                when=60,
                data={"chat_id": chat.id},
                name=f"auto_leave_{chat.id}"
            )
        return

    if (new.user.id == bot_id and new.status == "member" and old.status in ("left", "kicked")):
        BOT_ADMIN_CACHE.discard(chat.id)
        clear_reminders(context, chat.id)
        try:
            bot_username = context.bot.username or ""
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ]])
            m = await context.bot.send_message(
                chat.id,
                "⚠️ <b>Admin Permission Required</b>\n\n"
                "🤖 Bot ကို အလုပ်လုပ်နိုင်ရန်\n"
                "⭐️ <b>Admin အဖြစ် ခန့်ထားပေးပါ</b>",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            REMINDER_MESSAGES.setdefault(chat.id, []).append(m.message_id)
            if context.job_queue:
                for i in range(1, 6):
                    context.job_queue.run_once(
                        admin_reminder,
                        when=300 * i,
                        data={"chat_id": chat.id, "count": i, "total": 5, "type": "admin_reminder"}
                    )
                context.job_queue.run_once(
                    leave_if_not_admin,
                    when=1510,
                    data={"chat_id": chat.id},
                    name=f"auto_leave_{chat.id}"
                )
        except:
            pass

async def admin_reminder(context: ContextTypes.DEFAULT_TYPE):
    if not context.job or not context.job.data:
        return
    chat_id = context.job.data.get("chat_id")
    count = context.job.data.get("count")
    total = context.job.data.get("total")
    if not chat_id:
        return

    if chat_id in BOT_ADMIN_CACHE:
        clear_reminders(context, chat_id)
        return

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except Exception:
        clear_reminders(context, chat_id)
        BOT_ADMIN_CACHE.discard(chat_id)
        REMINDER_MESSAGES.pop(chat_id, None)
        return

    # ✅ From link-delete bot: check can_delete_messages too
    if me.status in ("administrator", "creator") and getattr(me, "can_delete_messages", False):
        BOT_ADMIN_CACHE.add(chat_id)
        clear_reminders(context, chat_id)
        return

    try:
        bot_username = context.bot.username or ""
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
        ]])
        m = await context.bot.send_message(
            chat_id,
            f"⏰ <b>Reminder ({count}/{total})</b>\n\n"
            "🤖 Bot ကို အလုပ်လုပ်နိုင်ရန်\n"
            "⭐️ <b>Admin Permission ပေးပါ</b>\n\n"
            "⚠️ Required: Permission",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        REMINDER_MESSAGES.setdefault(chat_id, []).append(m.message_id)
    except Exception:
        clear_reminders(context, chat_id)
        BOT_ADMIN_CACHE.discard(chat_id)
        REMINDER_MESSAGES.pop(chat_id, None)

# ===============================
# PHOTO PACK COMMANDS (Group)
# ===============================
async def packs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not chat or not user or not msg:
        return
    if chat.type != "private":
        return
    groups = await get_user_admin_groups(user.id, context)
    if not groups:
        await msg.reply_text("❌ Admin / Owner ဖြစ်တဲ့ Group မတွေ့ပါ")
        return
    buttons = []
    for g in groups:
        buttons.append([InlineKeyboardButton(g["title"][:50], callback_data=f"pack_group_{g['id']}")])
    await msg.reply_text(
        "🎨 Welcome / Goodbye Photo Pack သတ်မှတ်မယ့် Group ကိုရွေးပါ။",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def pack_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    try:
        chat_id = int(query.data.split("_")[-1])
    except:
        return
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ("administrator", "creator"):
            await query.answer("❌ You are not admin", show_alert=True)
            return
    except Exception:
        return
    buttons = []
    for pack_name in WELCOME_PHOTO_PACKS.keys():
        buttons.append([InlineKeyboardButton(f"🎨 {pack_name.upper()}", callback_data=f"setpack_{chat_id}_{pack_name}")])
    with contextlib.suppress(BadRequest):
        await query.edit_message_text("🖼 Welcome / Goodbye Photo Pack ကိုရွေးပါ။", reply_markup=InlineKeyboardMarkup(buttons))

async def set_pack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    try:
        _, rest = query.data.split("_", 1)
        chat_id, pack_name = rest.split("_", 1)
        chat_id = int(chat_id)
    except:
        return
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ("administrator", "creator"):
            await query.answer("❌ You are not admin", show_alert=True)
            return
    except Exception:
        return
    if pack_name not in WELCOME_PHOTO_PACKS:
        return
    await set_group_photo_pack(chat_id, welcome_pack=pack_name, goodbye_pack=pack_name)
    await query.edit_message_text(
        f"✅ Photo Pack set completed.\n\n🏷 Pack: {pack_name.upper()}\n🆔 Group ID: <code>{chat_id}</code>",
        parse_mode="HTML"
    )

async def set_welcome_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not chat or chat.type not in ("group", "supergroup"):
        return
    if not user or not await is_user_admin(chat.id, user.id, context):
        return
    buttons = []
    for pack_name in WELCOME_PHOTO_PACKS.keys():
        buttons.append([InlineKeyboardButton(f"📸 {pack_name.title()}", callback_data=f"set_welcome_pack:{chat.id}:{pack_name}")])
    buttons.append([InlineKeyboardButton("♻️ Default", callback_data=f"set_welcome_pack:{chat.id}:default")])
    await msg.reply_text("🖼 <b>Choose Welcome Photo Pack</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def set_goodbye_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not chat or chat.type not in ("group", "supergroup"):
        return
    if not user or not await is_user_admin(chat.id, user.id, context):
        return
    buttons = []
    for pack_name in GOODBYE_PHOTO_PACKS.keys():
        buttons.append([InlineKeyboardButton(f"📸 {pack_name.title()}", callback_data=f"set_goodbye_pack:{chat.id}:{pack_name}")])
    buttons.append([InlineKeyboardButton("♻️ Default", callback_data=f"set_goodbye_pack:{chat.id}:default")])
    await msg.reply_text("🖼 <b>Choose Goodbye Photo Pack</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def photo_pack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    user = update.effective_user
    await query.answer()
    data = query.data
    try:
        action, chat_id, pack_name = data.split(":")
        chat_id = int(chat_id)
    except:
        return
    if not user or not await is_user_admin(chat_id, user.id, context):
        await query.answer("❌ You are not admin", show_alert=True)
        return

    if action == "set_welcome_pack":
        if pack_name == "default":
            await safe_db_execute("UPDATE groups SET welcome_photo_pack=NULL, custom_welcome_photo=NULL WHERE group_id=%s", (chat_id,))
            await query.edit_message_text("♻️ Welcome photo reset to default")
            return
        await safe_db_execute("UPDATE groups SET welcome_photo_pack=%s, custom_welcome_photo=NULL WHERE group_id=%s", (pack_name, chat_id))
        await query.edit_message_text(f"✅ Welcome pack set to: {pack_name}")
        return

    if action == "set_goodbye_pack":
        if pack_name == "default":
            await safe_db_execute("UPDATE groups SET goodbye_photo_pack=NULL, custom_goodbye_photo=NULL WHERE group_id=%s", (chat_id,))
            await query.edit_message_text("♻️ Goodbye photo reset to default")
            return
        await safe_db_execute("UPDATE groups SET goodbye_photo_pack=%s, custom_goodbye_photo=NULL WHERE group_id=%s", (pack_name, chat_id))
        await query.edit_message_text(f"✅ Goodbye pack set to: {pack_name}")

# ===============================
# GROUP COMMANDS
# ===============================
async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not chat or not user or not msg:
        return
    if chat.type not in ("group", "supergroup"):
        return

    chat_id = chat.id
    if not await is_user_admin(chat_id, user.id, context):
        return

    BOT_ADMIN_CACHE.discard(chat_id)
    USER_ADMIN_CACHE.pop(chat_id, None)
    ADMIN_VERIFY_CACHE.pop(chat_id, None)

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator") and me.can_delete_messages:
            BOT_ADMIN_CACHE.add(chat_id)
            context.application.create_task(
                safe_db_execute(
                    """
                    INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                    VALUES (%s, TRUE, %s)
                    ON CONFLICT (group_id)
                    DO UPDATE SET is_admin_cached = TRUE, last_checked_at = EXCLUDED.last_checked_at
                    """,
                    (chat_id, int(time.time()))
                )
            )
        else:
            await msg.reply_text(
                "⚠️ <b>Bot မှာ Delete permission မရှိပါ</b>\n\n"
                "🔧 Admin setting ထဲမှာ ✅ <b>Delete Messages</b> ကို ဖွင့်ပေးပါ",
                parse_mode="HTML"
            )
            return
    except:
        return

    await msg.reply_text(
        "🔄 <b>Refresh completed!</b>\n\n✅ Admin cache updated\n✅ Bot permission re-checked",
        parse_mode="HTML"
    )

# ===============================
# STARTUP HELPERS
# ===============================
async def refresh_admin_cache(app):
    rows = await safe_db_execute("SELECT group_id FROM groups WHERE is_admin_cached = TRUE", fetch=True) or []
    BOT_ADMIN_CACHE.clear()
    verified = 0
    skipped = 0
    now = int(time.time())

    for row in rows:
        gid = row["group_id"]
        try:
            me = await app.bot.get_chat_member(gid, app.bot.id)
            if me.status in ("administrator", "creator") and getattr(me, "can_delete_messages", False):
                BOT_ADMIN_CACHE.add(gid)
                verified += 1
                await safe_db_execute("UPDATE groups SET is_admin_cached = TRUE, last_checked_at = %s WHERE group_id = %s", (now, gid))
            else:
                skipped += 1
                await safe_db_execute("UPDATE groups SET is_admin_cached = FALSE, last_checked_at = %s WHERE group_id = %s", (now, gid))
        except ChatMigrated as e:
            new_id = e.new_chat_id
            ADMIN_VERIFY_CACHE.pop(gid, None)
            ADMIN_VERIFY_CACHE.pop(new_id, None)
            await safe_db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                VALUES (%s, TRUE, %s)
                ON CONFLICT (group_id) DO UPDATE SET is_admin_cached = TRUE, last_checked_at = EXCLUDED.last_checked_at
                """,
                (new_id, now)
            )
            await safe_db_execute("DELETE FROM groups WHERE group_id=%s", (gid,))
            if gid in BOT_ADMIN_CACHE:
                BOT_ADMIN_CACHE.discard(gid)
                BOT_ADMIN_CACHE.add(new_id)
            USER_ADMIN_CACHE[new_id] = USER_ADMIN_CACHE.pop(gid, set())
            REMINDER_MESSAGES[new_id] = REMINDER_MESSAGES.pop(gid, [])
            try:
                me2 = await app.bot.get_chat_member(new_id, app.bot.id)
                if me2.status in ("administrator", "creator") and getattr(me2, "can_delete_messages", False):
                    BOT_ADMIN_CACHE.add(new_id)
                    verified += 1
                    await safe_db_execute("UPDATE groups SET is_admin_cached = TRUE, last_checked_at = %s WHERE group_id = %s", (now, new_id))
                else:
                    skipped += 1
                    await safe_db_execute("UPDATE groups SET is_admin_cached = FALSE, last_checked_at = %s WHERE group_id = %s", (now, new_id))
            except Exception as e2:
                print(f"⚠️ Skip migrated admin check for {new_id}: {e2}", flush=True)
        except Exception as e:
            print(f"⚠️ Skip admin check for {gid}: {e}", flush=True)
        await asyncio.sleep(0.2)

    print(f"✅ Admin cache verified: {verified}", flush=True)
    print(f"⚠️ Non-admin groups marked: {skipped}", flush=True)
    return now

async def purge_non_admin_groups_verified(now: int):
    await safe_db_execute(
        """
        DELETE FROM groups
        WHERE is_admin_cached = FALSE
          AND last_checked_at = %s
          AND group_id NOT IN (SELECT group_id FROM groups WHERE is_admin_cached = TRUE)
        """,
        (now,)
    )
    print("🧹 Startup purge: non-admin groups removed", flush=True)

async def refresh_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return
    msg = update.effective_message
    rows = await safe_db_execute("SELECT group_id FROM groups", fetch=True) or []
    BOT_ADMIN_CACHE.clear()
    verified = 0
    skipped = 0
    failed = 0
    for row in rows:
        gid = row["group_id"]
        try:
            me = await context.bot.get_chat_member(gid, context.bot.id)
            if me.status in ("administrator", "creator"):
                BOT_ADMIN_CACHE.add(gid)
                verified += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"⚠️ refresh_all skip {gid}: {e}")
            failed += 1
        await asyncio.sleep(0.1)
    await msg.reply_text(
        "🔄 <b>Refresh All Completed (SAFE)</b>\n\n"
        f"✅ Admin groups (active): {verified}\n"
        f"⚠️ Non-admin groups (kept): {skipped}\n"
        f"❗ API skipped: {failed}\n\n"
        "🛡️ <i>DB was NOT modified</i>",
        parse_mode="HTML"
    )

# ===============================
# RAM cleanup job
# ===============================
async def cleanup_memory_cache(context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())
    cutoff = now - 3600  # 1 hour
    for key in list(LAST_WELCOME_TS.keys()):
        if LAST_WELCOME_TS[key] < cutoff:
            LAST_WELCOME_TS.pop(key, None)
    for key in list(LAST_GOODBYE_TS.keys()):
        if LAST_GOODBYE_TS[key] < cutoff:
            LAST_GOODBYE_TS.pop(key, None)
    for key in list(FALLBACK_EVENT_TS.keys()):
        if FALLBACK_EVENT_TS[key] < cutoff:
            FALLBACK_EVENT_TS.pop(key, None)

# ===============================
# ERROR HANDLER
# ===============================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, RetryAfter):
        return
    logger.error("Unhandled exception", exc_info=context.error)

# ===============================
# MAIN
# ===============================
def main():
    global pool

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    # ✅ concurrent_updates(32) from link-delete bot
    app = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(32).build()

    app.add_error_handler(error_handler)

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("refresh_all", refresh_all))
    app.add_handler(CommandHandler("setwelcomephoto", set_welcome_photo))
    app.add_handler(CommandHandler("setgoodbyephoto", set_goodbye_photo))
    app.add_handler(CommandHandler("packs", packs_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(pack_group_callback, pattern=r"^pack_group_"))
    app.add_handler(CallbackQueryHandler(set_pack_callback, pattern=r"^setpack_"))
    app.add_handler(CallbackQueryHandler(photo_pack_callback, pattern="^(set_welcome_pack|set_goodbye_pack):"))
    app.add_handler(
        CallbackQueryHandler(
            donate_callback,
            pattern=(
                r"^(donate|photo_menu|setwelcome_menu|setgoodbye_menu|"
                r"welcome_pack_|goodbye_pack_|photo_next|photo_prev|"
                r"setphoto_selectgroup|applyphoto_|setphoto_home|help_menu)"
            )
        )
    )

    # Payments
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Chat member
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(welcome_chat_member, ChatMemberHandler.CHAT_MEMBER), group=1)
    app.add_handler(ChatMemberHandler(goodbye, ChatMemberHandler.CHAT_MEMBER), group=2)

    # Fallback
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
            fallback_join_leave
        ),
        group=10
    )

    # Broadcast (✅ improved from link-delete bot)
    app.add_handler(
        MessageHandler(
            filters.User(OWNER_ID) & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.Document.ALL),
            broadcast
        ),
        group=5
    )
    app.add_handler(
        MessageHandler(
            filters.User(OWNER_ID) & filters.TEXT & ~filters.COMMAND,
            broadcast_button_url_receiver
        ),
        group=4  
    )
    app.add_handler(CallbackQueryHandler(broadcast_confirm_handler, pattern="broadcast_confirm"))
    app.add_handler(CallbackQueryHandler(broadcast_target_handler, pattern="^bc_target_"))
    app.add_handler(CallbackQueryHandler(broadcast_post_now_handler, pattern="^bc_post_now$"))
    app.add_handler(CallbackQueryHandler(broadcast_auto_button_handler, pattern="^bc_btn_auto$"))
    app.add_handler(CallbackQueryHandler(broadcast_manual_button_handler, pattern="^bc_btn_manual$"))
    app.add_handler(CallbackQueryHandler(broadcast_cancel_handler, pattern="broadcast_cancel"))
    app.add_handler(CallbackQueryHandler(broadcast_preview_send, pattern="^bc_preview_send$"))
    app.add_handler(CallbackQueryHandler(broadcast_preview_cancel, pattern="^bc_preview_cancel$"))

    # Startup
    async def on_startup(app):
        global pool
        global DB_READY
        print("🟡 Starting bot...", flush=True)

        await app.bot.delete_webhook(drop_pending_updates=True)

        try:
            pool = ConnectionPool(
                conninfo=(
                    f"host={DB_HOST} dbname={DB_NAME} user={DB_USER} "
                    f"password={DB_PASS} port={DB_PORT} sslmode=require"
                ),
                min_size=1,
                max_size=5,
                timeout=5,
                kwargs={"prepare_threshold": None}
            )
            print("✅ DB pool created", flush=True)
            DB_READY = True
        except Exception as e:
            print("❌ DB pool creation failed:", e, flush=True)
            pool = None
            DB_READY = False
            print("⚠️ DB disabled, bot will run without DB features", flush=True)
            return

        await init_db()
        print("✅ DB init done", flush=True)

        if DB_READY:
            now = await refresh_admin_cache(app)
            print("✅ Admin cache refreshed", flush=True)
            await purge_non_admin_groups_verified(now)

        if app.job_queue:
            app.job_queue.run_repeating(cleanup_memory_cache, interval=1800, first=1800)

        print("🤖 MissOlivia Bot running (PRODUCTION READY)", flush=True)

    app.post_init = on_startup

    try:
        app.run_polling(
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "my_chat_member",
                "pre_checkout_query",
            ],
            close_loop=False
        )
    finally:
        if pool:
            pool.close()


if __name__ == "__main__":
    main()