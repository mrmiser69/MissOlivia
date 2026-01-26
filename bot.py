# ===============================
# IMPORTS
# ===============================
import os
import time
import asyncio
import contextlib
from html import escape
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from telegram.error import RetryAfter, Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ChatMemberHandler,
)

from psycopg_pool import ConnectionPool  # ✅ ONLY THIS (Supabase safe)

# ===============================
# GLOBAL CACHES
# ===============================
STATS_CACHE = {
    "users": 0,
    "groups": 0,
    "admin_groups": 0,
    "last_update": 0
}
STATS_TTL = 300  # 5 minutes

BOT_ADMIN_CACHE: set[int] = set()
USER_ADMIN_CACHE: dict[int, set[int]] = {}
REMINDER_MESSAGES: dict[int, list[int]] = {}
PENDING_BROADCAST = {}
BOT_START_TIME = int(time.time())
LAST_WELCOME = {}   # {chat_id: message_id}
LAST_GOODBYE = {}   # {(chat_id, user_id): timestamp}

# ===============================
# CONFIG
# ===============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
START_IMAGE = "https://i.postimg.cc/tJF69SbN/ICON.jpg"
WELCOME_IMAGE = "https://i.postimg.cc/L6hVSnp3/WELCOME.png"
GOODBYE_IMAGE = "https://i.postimg.cc/bdXNCLc2/Untitled-design-(12).png"

DB_HOST = os.getenv("SUPABASE_HOST")
DB_NAME = os.getenv("SUPABASE_DB")
DB_USER = os.getenv("SUPABASE_USER")
DB_PASS = os.getenv("SUPABASE_PASSWORD")
DB_PORT = int(os.getenv("SUPABASE_PORT", "6543"))

# =====================================
# DB POOL (RAILWAY SAFE)
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
                    cols = [d.name for d in cur.description]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
                conn.commit()

    return await loop.run_in_executor(None, _run)

# ===============================
# INIT DB
# ===============================
async def init_db():
    await db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY
        )
    """)

    await db_execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id BIGINT PRIMARY KEY,
            is_admin_cached BOOLEAN DEFAULT FALSE,
            last_checked_at BIGINT
        )
    """)

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

    # ===============================
    # 🔒 PRIVATE CHAT (/start)
    # ===============================
    if chat.type == "private":

        # save user
        context.application.create_task(
            db_execute(
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
            f"<b>────「 {bot_mention} 」────</b>\n\n"
            f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
            "<b>ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။</b>\n"
            "<b>ငါ၏လုပ်နိုင်စွမ်းကို ကောင်းကောင်းအသုံးချပါ။</b>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📌 ငါ၏လုပ်နိုင်စွမ်း</b>\n\n"
            "✅ Welcome Message\n"
            "✅ Goodbye Message\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n"
            "➕ ငါ့ကို Group ထဲထည့်ပါ\n"
            "⭐️ ငါ့ကို Admin ပေးပါ"
        )

        buttons = []

        if bot_username:
            buttons.append([
                InlineKeyboardButton(
                    "➕ ADD ME TO YOUR GROUP",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ])

        buttons.append([
            InlineKeyboardButton("👨‍💻 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫", url="tg://user?id=5942810488"),
            InlineKeyboardButton("📢 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/MMTelegramBotss"),
        ])

        await msg.reply_photo(
            photo=START_IMAGE,
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return
    
    # ===============================
    # 👥 GROUP / SUPERGROUP (/start)
    # ===============================
    if chat.type in ("group", "supergroup"):

        # 🔐 Check bot status
        try:
            me = await bot.get_chat_member(chat.id, bot.id)
        except:
            return  # cannot access → silent

        # 🔕 No send permission → SILENT
        if me.status in ("member", "restricted"):
            if not getattr(me, "can_send_messages", True):
                return  # silent

        # ---------------------------
        # ✅ BOT IS ADMIN
        # ---------------------------
        if me.status in ("administrator", "creator"):
            await bot.send_message(
                chat.id,
                "✅ Bot ကို Admin အဖြစ်ခန့်ထားပြီးသားပါ။\n\n"
                "✅ <b>Welcome Message</b>\n"
                "✅ <b>Goodbye Message</b>\n\n"
                "🤖 Bot က လက်ရှိ Group မှာ ကောင်းကောင်းအလုပ်လုပ်နေပါပြီး။",
                parse_mode="HTML"
            )
            return

        # ---------------------------
        # ❌ BOT IS NOT ADMIN
        # ---------------------------
        await bot.send_message(
            chat.id,
            "⚠️ <b>Bot သည် Admin မဟုတ်သေးပါ</b>\n\n"
            "🤖 <b>Bot ကို အလုပ်လုပ်စေရန်</b>\n"
            "⭐️ <b>Admin Permission ပေးပါ</b>\n\n"
            "Required: Permission",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⭐️ GIVE ADMIN PERMISSION",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ]])
        )
        return
 
# ===============================
# /stats (OWNER ONLY - PRIVATE)
# ===============================
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if (
        not chat
        or chat.type != "private"
        or not user
        or user.id != OWNER_ID
        or not msg
    ):
        return

    now = time.time()

    # 🔒 Cache valid → DB မထိ
    if now - STATS_CACHE["last_update"] > STATS_TTL:
        try:
            users = await db_execute(
                "SELECT COUNT(*) AS c FROM users",
                fetch=True
            )
            groups = await db_execute(
                "SELECT COUNT(*) AS c FROM groups",
                fetch=True
            )
            admin_groups = await db_execute(
                "SELECT COUNT(*) AS c FROM groups WHERE is_admin_cached = TRUE",
                fetch=True
            )

            STATS_CACHE["users"] = users[0]["c"] if users else 0
            STATS_CACHE["groups"] = groups[0]["c"] if groups else 0
            STATS_CACHE["admin_groups"] = admin_groups[0]["c"] if admin_groups else 0
            STATS_CACHE["last_update"] = now

        except Exception as e:
            print("❌ STATS DB ERROR:", e)

    no_admin = max(
        0,
        STATS_CACHE["groups"] - STATS_CACHE["admin_groups"]
    )

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
# TEXT BUILDERS (SAFE)
# ===============================
def build_welcome_text(chat, member, joined_time):
    name = escape(member.first_name or "User")
    username = f"@{member.username}" if member.username else "No Username"
    mention = f"<a href='tg://user?id={member.id}'>{name}</a>"

    return (
        f"✨ <b>Welcome to {escape(chat.title or 'Group')}</b> ✨\n\n"
        f"👤 Name: {name}\n"
        f"🆔 User ID: {member.id}\n"
        f"👤 Username: {username}\n"
        f"🔗 Mention: {mention}\n"
        f"⏰ Joined at: {joined_time}"
    )


def build_goodbye_text(member, left_time):
    name = escape(member.first_name or "User")
    mention = f"<a href='tg://user?id={member.id}'>{name}</a>"

    return (
        f"⛔️ <b>ထွက်သွားပြီးပေါ့</b>\n"
        f"<b>နှစ်တစ်ထောင် Fa ဖြစ်ပါစေ။</b>\n\n"
        f"👤 Name: {mention}\n"
        f"🆔 User ID: {member.id}\n"
        f"⏰ Left at: {left_time}"
    )

# ===============================
# 👋 WELCOME MESSAGE (ON JOIN)
# ===============================
async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return

    if not update.message or not update.message.new_chat_members:
        return

    if not await is_bot_admin(chat.id, context):
        return

    bot = context.bot
    me = await bot.get_me()

    members = [m for m in update.message.new_chat_members if m.id != me.id]
    if not members:
        return

    joined_time = (
        update.message.date.strftime("%Y-%m-%d %H:%M:%S")
        if update.message.date
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # 🧹 delete previous welcome
    last_msg_id = LAST_WELCOME.get(chat.id)
    if last_msg_id:
        with contextlib.suppress(Exception):
            await bot.delete_message(chat.id, last_msg_id)

    for member in members:
        text = build_welcome_text(chat, member, joined_time)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "➕ ADD ME TO YOUR GROUP",
                url=f"https://t.me/{me.username}?startgroup=true"
            )]
        ])

        try:
            msg = await bot.send_photo(
                chat_id=chat.id,
                photo=WELCOME_IMAGE,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            LAST_WELCOME[chat.id] = msg.message_id
        except:
            # fallback (image fail safe)
            await bot.send_message(chat.id, text, parse_mode="HTML")

# ===============================
# 👋 GOODBYE MESSAGE (ON LEAVE)
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return

    member = None
    left_date = None

    if update.message and update.message.left_chat_member:
        member = update.message.left_chat_member
        left_date = update.message.date
    elif update.chat_member and update.chat_member.old_chat_member:
        member = update.chat_member.old_chat_member.user
        left_date = datetime.now()

    if not member:
        return

    # 🛑 DUPLICATE BLOCK (CRITICAL FIX)
    key = (chat.id, member.id)
    if key in LAST_GOODBYE:
        return
    LAST_GOODBYE[key] = int(time.time())

    if not await is_bot_admin(chat.id, context):
        return

    left_time = (
        left_date.strftime("%Y-%m-%d %H:%M:%S")
        if left_date
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    text = build_goodbye_text(member, left_time)

    try:
        me = await context.bot.get_me()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "➕ ADD ME TO YOUR GROUP",
                url=f"https://t.me/{me.username}?startgroup=true"
            )]
        ])

        await context.bot.send_photo(
            chat_id=chat.id,
            photo=GOODBYE_IMAGE,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except:
        await context.bot.send_message(chat.id, text, parse_mode="HTML")

# ===============================
# 📢 BROADCAST (OWNER ONLY)
# ===============================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return

    msg = update.effective_message
    if not msg:
        return

    text = msg.text or msg.caption
    if text and text.startswith("/broadcast"):
        text = text.replace("/broadcast", "", 1).strip()

    content = {
        "text": text,
        "photo": msg.photo[-1].file_id if msg.photo else None,
        "video": msg.video.file_id if msg.video else None,
        "audio": msg.audio.file_id if msg.audio else None,
        "document": msg.document.file_id if msg.document else None,
    }

    if not any(v for v in content.values() if v):
        await msg.reply_text("❌ Broadcast လုပ်ရန် content မတွေ့ပါ")
        return

    PENDING_BROADCAST[OWNER_ID] = content

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ CONFIRM", callback_data="broadcast_confirm"),
        InlineKeyboardButton("❌ CANCEL", callback_data="broadcast_cancel")
    ]])

    await msg.reply_text(
        "📢 <b>Broadcast Confirm လုပ်ပါ</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# ===============================
# Broadcast Confirm → Choose Target
# ===============================
async def broadcast_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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

    await query.edit_message_text(
        "📢 <b>Broadcast Target ကိုရွေးပါ</b>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# ===============================
# Progress Bar Helper 
# ===============================
def render_progress(done, total):
    if total <= 0:
        return "██████████ 100%"
    percent = int((done / total) * 100)
    blocks = min(10, percent // 10)
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"{bar} {percent}%"

# ===============================
# update progress 
# ===============================
async def update_progress(msg, sent, total):
    if total <= 0:
        percent = 100
    else:
        percent = int((sent / total) * 100)

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
# Broadcast flood-safe 
# ===============================
async def safe_send(func, *args, **kwargs):
    for _ in range(5):
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except (Forbidden, BadRequest):
            return None
    return None

# ===============================
# BATCH DB READ (10k+ SAFE)
# ===============================
async def iter_db_ids(query, batch_size=500):
    offset = 0
    while True:
        rows = await db_execute(
            f"{query} LIMIT %s OFFSET %s",
            (batch_size, offset),
            fetch=True
        )
        if not rows:
            break
        yield rows
        offset += batch_size

# ===============================
# Broadcast Target Handler
# ===============================
async def broadcast_target_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = PENDING_BROADCAST.pop(OWNER_ID, None)
    if not data:
        await query.edit_message_text("❌ Broadcast data မရှိပါ")
        return

    target_type = query.data  # bc_target_users / bc_target_groups / bc_target_all

    progress_msg = await query.edit_message_text(
        "📢 <b>Broadcasting...</b>\n\n⏳ Progress: 0%",
        parse_mode="HTML"
    )
    
    sent = 0
    start_time = time.time()
    
    total = 0

    if target_type in ("bc_target_users", "bc_target_all"):
        rows = await db_execute("SELECT COUNT(*) AS c FROM users", fetch=True)
        total += rows[0]["c"] if rows else 0

    if target_type in ("bc_target_groups", "bc_target_all"):
        rows = await db_execute(
            "SELECT COUNT(*) AS c FROM groups WHERE is_admin_cached = TRUE",
            fetch=True
        )
        total += rows[0]["c"] if rows else 0

    async def send_batch(ids):
        nonlocal sent
        for cid in ids:
            await safe_send(send_content, context, cid, data)
            sent += 1

            # 🔄 update every 50 messages (SAFE)
            if sent % 50 == 0 or sent == total:
                await update_progress(progress_msg, sent, total)

    # 👤 USERS
    if target_type in ("bc_target_users", "bc_target_all"):
        async for rows in iter_db_ids(
            "SELECT user_id FROM users ORDER BY user_id"
        ):
            await send_batch([r["user_id"] for r in rows])

    # 👥 GROUPS (ADMIN ONLY)
    if target_type in ("bc_target_groups", "bc_target_all"):
        async for rows in iter_db_ids(
            "SELECT group_id FROM groups WHERE is_admin_cached = TRUE ORDER BY group_id"
        ):
            await send_batch([r["group_id"] for r in rows])

    elapsed = int(time.time() - start_time)

    await progress_msg.edit_text(
        "✅ <b>Broadcast Completed</b>\n\n"
        f"📨 Sent: <b>{sent}</b>\n"
        f"⏱️ Time: <b>{elapsed // 60}m {elapsed % 60}s</b>",
        parse_mode="HTML"
    )

# ===============================
# Cancel Button 
# ===============================
async def broadcast_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    PENDING_BROADCAST.pop(OWNER_ID, None)

    await query.edit_message_text("❌ Broadcast Cancel လုပ်လိုက်ပါပြီ")

# ===============================
# Media / Text 
# ===============================
async def send_content(context, chat_id, data):
    text = data.get("text") or ""

    try:
        if data.get("photo"):
            await context.bot.send_photo(
                chat_id,
                data["photo"],
                caption=text,
                parse_mode="HTML"
            )

        elif data.get("video"):
            await context.bot.send_video(
                chat_id,
                data["video"],
                caption=text,
                parse_mode="HTML"
            )

        elif data.get("audio"):
            await context.bot.send_audio(
                chat_id,
                data["audio"],
                caption=text,
                parse_mode="HTML"
            )

        elif data.get("document"):
            await context.bot.send_document(
                chat_id,
                data["document"],
                caption=text,
                parse_mode="HTML"
            )

        else:
            await context.bot.send_message(
                chat_id,
                text,
                parse_mode="HTML"
            )

    except Exception:
        # let caller (safe_send) + broadcast logic handle cleanup
        raise

# ===============================
# Auto leave job (FIXED)
# ===============================
async def leave_if_not_admin(context: ContextTypes.DEFAULT_TYPE):
    if not context.job or not context.job.data:
        return

    chat_id = context.job.data.get("chat_id")
    if not chat_id:
        return

    # 🔎 ALWAYS verify with Telegram (cache is NOT source of truth)
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator"):
            BOT_ADMIN_CACHE.add(chat_id)
            return
    except:
        # cannot access chat → treat as removed
        pass

    # ❌ bot is NOT admin → cleanup
    BOT_ADMIN_CACHE.discard(chat_id)
    USER_ADMIN_CACHE.pop(chat_id, None)
    REMINDER_MESSAGES.pop(chat_id, None)

    # 🧹 Supabase cleanup (background, non-blocking)
    context.application.create_task(
        db_execute(
            """
            UPDATE groups
            SET is_admin_cached = FALSE,
                last_checked_at = %s
            WHERE group_id = %s
            """,
            (int(time.time()), chat_id)
        )
    )

    # 🚪 Leave group
    try:
        await context.bot.leave_chat(chat_id)
    except Exception as e:
        print(f"⚠️ Leave chat failed ({chat_id}):", e)

# ===============================
# Helper: Clear all reminder jobs (SAFE)
# ===============================
def clear_reminders(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    job_queue = context.job_queue

    # ❗ JobQueue မရှိရင် ဘာမှမလုပ်
    if job_queue is None:
        return

    for job in list(job_queue.jobs()):
        data = job.data or {}

        # only jobs for this chat
        if data.get("chat_id") != chat_id:
            continue

        name = job.name or ""

        if (
            name.startswith("auto_leave_")
            or data.get("type") == "admin_reminder"
        ):
            job.schedule_removal()

# ===============================
# Admin Permission + ThankYou (SAFE FIX)
# ===============================
async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.my_chat_member:
        return

    chat = update.effective_chat
    if not chat:
        return

    USER_ADMIN_CACHE.pop(chat.id, None)

    old = update.my_chat_member.old_chat_member
    new = update.my_chat_member.new_chat_member
    if not old or not new:
        return

    bot_id = context.bot.id

    # ===============================
    # 🟢 BOT PROMOTED TO ADMIN
    # ===============================
    if (
        new.user.id == bot_id
        and new.status == "administrator"
        and old.status != "administrator"
    ):
        BOT_ADMIN_CACHE.add(chat.id)
        clear_reminders(context, chat.id)

        # 🔥 delete admin request / reminder messages
        for mid in REMINDER_MESSAGES.pop(chat.id, []):
            with contextlib.suppress(Exception):
                await context.bot.delete_message(chat.id, mid)

        # 💾 save group admin status
        context.application.create_task(
            db_execute(
                """
                INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                VALUES (%s, TRUE, %s)
                ON CONFLICT (group_id)
                DO UPDATE SET
                    is_admin_cached = TRUE,
                    last_checked_at = EXCLUDED.last_checked_at
                """,
                (chat.id, int(time.time()))
            )
        )

        # ✅ thank you message (KEEP FOREVER)
        try:
            await context.bot.send_message(
                chat.id,
                "✅ <b>Thank you!</b>\n\n"
                "🤖 <b>Bot</b> ကို <b>Admin</b> အဖြစ် ခန့်ထားပြီးပါပြီး။\n"
                "🐇 <b>Welcome Message</b>\n"
                "🐇 <b>Goodbye Message</b>\n\n"
                "✅  စတင်အလုပ်လုပ်နေပါပြီး.........!",
                parse_mode="HTML"
            )
        except:
            pass

        return

    # ===============================
    # 🔴 BOT DEMOTED OR REMOVED
    # ===============================
    if (
        old.user.id == bot_id
        and old.status in ("administrator", "creator")
        and new.status in ("member", "left", "kicked")
    ):
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

    # ===============================
    # 🟡 BOT ADDED BUT NOT ADMIN
    # ===============================
    if (
        new.user.id == bot_id
        and new.status == "member"
        and old.status in ("left", "kicked")
    ):
        BOT_ADMIN_CACHE.discard(chat.id)
        clear_reminders(context, chat.id)

        try:
            me = await context.bot.get_me()
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⭐️ GIVE ADMIN PERMISSION",
                    url=f"https://t.me/{me.username}?startgroup=true"
                )
            ]])

            msg = await context.bot.send_message(
                chat.id,
                "⚠️ <b>Admin Permission Required</b>\n\n"
                "🤖 Bot ကို အလုပ်လုပ်နိုင်ရန်\n"
                "⭐️ <b>Admin အဖြစ် ခန့်ထားပေးပါ</b>",
                parse_mode="HTML",
                reply_markup=keyboard
            )

            REMINDER_MESSAGES.setdefault(chat.id, []).append(msg.message_id)

            if context.job_queue:
                for i in range(1, 6):
                    context.job_queue.run_once(
                        admin_reminder,
                        when=300 * i,
                        data={
                            "chat_id": chat.id,
                            "count": i,
                            "total": 5,
                            "type": "admin_reminder"
                        }
                    )

                context.job_queue.run_once(
                    leave_if_not_admin,
                    when=1510,
                    data={"chat_id": chat.id},
                    name=f"auto_leave_{chat.id}"
                )
        except:
            pass

# ===============================
# Admin Reminder (SAFE FIXED)
# ===============================
async def admin_reminder(context: ContextTypes.DEFAULT_TYPE):

    if not context.job or not context.job.data:
        return

    chat_id = context.job.data.get("chat_id")
    count = context.job.data.get("count")
    total = context.job.data.get("total")

    if not chat_id:
        return

    # ✅ already cached as admin → stop everything
    if chat_id in BOT_ADMIN_CACHE:
        clear_reminders(context, chat_id)
        return

    # 🔐 STEP 1: Check bot still in group
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
    except Exception:
        # ❌ bot kicked / group deleted
        clear_reminders(context, chat_id)
        BOT_ADMIN_CACHE.discard(chat_id)
        REMINDER_MESSAGES.pop(chat_id, None)
        return

    # ✅ STEP 2: Bot is admin now → stop reminders
    if me.status in ("administrator", "creator"):
        BOT_ADMIN_CACHE.add(chat_id)
        clear_reminders(context, chat_id)
        return

    # ❌ STEP 3: Bot still member → send reminder
    try:
        bot = await context.bot.get_me()

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "⭐️ GIVE ADMIN PERMISSION",
                url=f"https://t.me/{bot.username}?startgroup=true"
            )
        ]])

        msg = await context.bot.send_message(
            chat_id,
            f"⏰ <b>Reminder ({count}/{total})</b>\n\n"
            "🤖 Bot ကို အလုပ်လုပ်နိုင်ရန်\n"
            "⭐️ <b>Admin Permission ပေးပါ</b>\n\n"
            "⚠️ Required: Permission",
            parse_mode="HTML",
            reply_markup=keyboard
        )

        REMINDER_MESSAGES.setdefault(chat_id, []).append(msg.message_id)

    except Exception:
        # ❌ any unexpected error → stop future reminders
        clear_reminders(context, chat_id)
        BOT_ADMIN_CACHE.discard(chat_id)
        REMINDER_MESSAGES.pop(chat_id, None)

# ===============================
# bot admin check
# ===============================
async def is_bot_admin(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if chat_id in BOT_ADMIN_CACHE:
        return True

    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator"):
            BOT_ADMIN_CACHE.add(chat_id)
            return True
        return False
    except:
        return False

# ===============================
# USER ADMIN CHECK
# ===============================
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
# /refresh (ADMIN ONLY - FAST) ✅ FIXED
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
    user_id = user.id

    # 👮 USER ADMIN CHECK (SAFE)
    if not await is_user_admin(chat_id, user_id, context):
        return

    # 🔄 Clear caches
    BOT_ADMIN_CACHE.discard(chat_id)
    USER_ADMIN_CACHE.pop(chat_id, None)

    # 🤖 Re-check bot admin (STRICT)
    try:
        me = await context.bot.get_chat_member(chat_id, context.bot.id)
        if me.status in ("administrator", "creator") and me.can_delete_messages:
            BOT_ADMIN_CACHE.add(chat_id)

            context.application.create_task(
                db_execute(
                    """
                    INSERT INTO groups (group_id, is_admin_cached, last_checked_at)
                    VALUES (%s, TRUE, %s)
                    ON CONFLICT (group_id)
                    DO UPDATE SET
                        is_admin_cached = TRUE,
                        last_checked_at = EXCLUDED.last_checked_at
                    """,
                    (chat_id, int(time.time()))
                )
            )
        else:
            await msg.reply_text(
                "⚠️ <b>Bot မှာ Send Message permission မရှိပါ</b>\n\n"
                "🔧 Admin setting ထဲမှာ\n"
                "✅ <b>Send Messages</b> ကို ဖွင့်ပေးပါ",
                parse_mode="HTML"
            )
            return
    except:
        return

    await msg.reply_text(
        "🔄 <b>Refresh completed!</b>\n\n"
        "✅ Admin cache updated\n"
        "✅ Bot permission re-checked",
        parse_mode="HTML"
    )

# ===============================
# 🔄 AUTO REFRESH ADMIN CACHE ON START (SAFE)
# ===============================
async def refresh_admin_cache(app):
    rows = await db_execute(
        "SELECT group_id FROM groups",
        fetch=True
    ) or []

    BOT_ADMIN_CACHE.clear()
    verified = 0
    skipped = 0

    now = int(time.time())

    for row in rows:
        gid = row["group_id"]

        try:
            me = await app.bot.get_chat_member(gid, app.bot.id)

            if me.status in ("administrator", "creator"):
                # ✅ ADMIN
                BOT_ADMIN_CACHE.add(gid)
                verified += 1

                await db_execute(
                    """
                    UPDATE groups
                    SET is_admin_cached = TRUE,
                        last_checked_at = %s
                    WHERE group_id = %s
                    """,
                    (now, gid)
                )

            else:
                # ❌ NOT ADMIN (IMPORTANT FIX)
                skipped += 1
                await db_execute(
                    """
                    UPDATE groups
                    SET is_admin_cached = FALSE,
                        last_checked_at = %s
                    WHERE group_id = %s
                    """,
                    (now, gid)
                )

        except Exception as e:
            # ❗ API error → DB မထိ
            print(f"⚠️ Skip admin check for {gid}: {e}")
            skipped += 1

        await asyncio.sleep(0.1)

    print(f"✅ Admin cache verified: {verified}")
    print(f"⚠️ Non-admin groups marked: {skipped}")

# ===============================
# /refresh_all (OWNER ONLY - FINAL SAFE VERSION)
# ===============================
async def refresh_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return

    msg = update.effective_message

    rows = await db_execute(
        "SELECT group_id FROM groups",
        fetch=True
    ) or []

    BOT_ADMIN_CACHE.clear()

    verified = 0
    skipped = 0
    failed = 0

    for row in rows:
        gid = row["group_id"]

        try:
            me = await context.bot.get_chat_member(gid, context.bot.id)

            # ✅ Bot admin ဖြစ်ရင် cache ထဲထည့်
            if me.status in ("administrator", "creator"):
                BOT_ADMIN_CACHE.add(gid)
                verified += 1
            else:
                skipped += 1

        except Exception as e:
            # ❗ API error / private group / rate limit
            # ❌ DB မဖျက် ❌
            print(f"⚠️ refresh_all skip {gid}: {e}")
            failed += 1

        await asyncio.sleep(0.1)  # rate-limit safe

    await msg.reply_text(
        "🔄 <b>Refresh All Completed (SAFE)</b>\n\n"
        f"✅ Admin groups (active): {verified}\n"
        f"⚠️ Non-admin groups (kept): {skipped}\n"
        f"❗ API skipped: {failed}\n\n"
        "🛡️ <i>DB was NOT modified</i>",
        parse_mode="HTML"
    )

# ===============================
# MAIN (FINAL CORRECT VERSION)
# ===============================
def main():
    global pool

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # -------------------------------
    # Commands
    # -------------------------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("refresh_all", refresh_all))

    # -------------------------------
    # Chat Member
    # -------------------------------
    app.add_handler(
        ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    
    # -------------------------------
    # WELCOME
    # -------------------------------
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome),
        group=5
    )
    
    # -------------------------------
    # GOODBYE
    # -------------------------------
    app.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye),
        group=5
    )
    app.add_handler(
        ChatMemberHandler(goodbye, ChatMemberHandler.CHAT_MEMBER),
        group=6
    )
    
    # -------------------------------
    # Broadcast
    # -------------------------------
    app.add_handler(
        MessageHandler(
            filters.User(OWNER_ID)
            & (filters.TEXT | filters.CAPTION)
            & filters.Regex(r"^/broadcast"),
            broadcast
        )
    )

    app.add_handler(CallbackQueryHandler(
        broadcast_confirm_handler,
        pattern="broadcast_confirm"
    ))
    app.add_handler(CallbackQueryHandler(
        broadcast_target_handler,
        pattern="^bc_target_"
    ))
    app.add_handler(CallbackQueryHandler(
        broadcast_cancel_handler,
        pattern="broadcast_cancel"
    ))

    # -------------------------------
    # STARTUP HOOK (CORRECT)
    # -------------------------------
    async def on_startup(app):
        global pool
        print("🟡 Starting bot...", flush=True)

        await app.bot.delete_webhook(drop_pending_updates=True)

        try:
            pool = ConnectionPool(
                conninfo=(
                    f"host={DB_HOST} "
                    f"dbname={DB_NAME} "
                    f"user={DB_USER} "
                    f"password={DB_PASS} "
                    f"port={DB_PORT} "
                    f"sslmode=require"
                ),
                min_size=1,
                max_size=5,
                timeout=5,
                kwargs={"prepare_threshold": None}
            )
            print("✅ DB pool created", flush=True)
        except Exception as e:
            print("❌ DB pool creation failed:", e, flush=True)
            raise

        await init_db()
        print("✅ DB init done", flush=True)

        await refresh_admin_cache(app)
        print("✅ Admin cache refreshed", flush=True)

        print("🤖 MissOlivia Bot running (PRODUCTION READY)", flush=True)

    # ✅ IMPORTANT
    app.post_init = on_startup

    try:
        app.run_polling(close_loop=False)
    finally:
        if pool:
            pool.close()


if __name__ == "__main__":
    main()