# ===============================
# IMPORTS
# ===============================
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember
)
from telegram.ext import (
    ChatMemberHandler,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from datetime import datetime
import os
import logging
import asyncio
from telegram.error import BadRequest, Forbidden
from psycopg_pool import ConnectionPool

# ===============================
# GLOBAL CACHES
# ===============================
FILTER_CACHE = {}        # {chat_id: {keyword: reply}}
ADMIN_REMINDER_COUNT = {}  # {chat_id: count}
ADMIN_THANKED = set()      # chat_id set

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

# ===============================
# DB POOL (SUPABASE SAFE)
# ===============================
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
    kwargs={"prepare_threshold": None},
)

# ===============================
# CORE DB EXECUTOR (ASYNC SAFE)
# ===============================
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
# INIT DB (POSTGRES)
# ===============================
async def init_db():
    await db_execute("""
        CREATE TABLE IF NOT EXISTS filters (
            chat_id BIGINT,
            keyword TEXT,
            reply TEXT
        )
    """)

    await db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY
        )
    """)

    await db_execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY
        )
    """)

# ===============================
# FILTERS
# ===============================
async def db_add_filter(chat_id: int, keyword: str, reply: str):
    await db_execute(
        "INSERT INTO filters (chat_id, keyword, reply) VALUES (%s, %s, %s)",
        (chat_id, keyword, reply),
    )

async def db_remove_filter(chat_id: int, keyword: str):
    await db_execute(
        "DELETE FROM filters WHERE chat_id=%s AND keyword=%s",
        (chat_id, keyword),
    )

async def db_get_filters(chat_id: int):
    rows = await db_execute(
        "SELECT keyword, reply FROM filters WHERE chat_id=%s",
        (chat_id,),
        fetch=True,
    )
    return rows or []

# ===============================
# USERS
# ===============================
async def add_user(user_id: int):
    await db_execute(
        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (user_id,),
    )

async def get_users():
    rows = await db_execute(
        "SELECT user_id FROM users",
        fetch=True,
    )
    return [r[0] for r in rows] if rows else []

# ===============================
# GROUPS
# ===============================
async def add_group(chat_id: int):
    await db_execute(
        "INSERT INTO groups (chat_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (chat_id,),
    )

async def get_groups():
    rows = await db_execute(
        "SELECT chat_id FROM groups",
        fetch=True,
    )
    return [r[0] for r in rows] if rows else []

# ===============================
# /start (PRIVATE)
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat or update.effective_chat.type != "private":
        return

    if not update.message or not update.effective_user:
        return

    user = update.effective_user

    # ✅ SUPABASE SAFE (ASYNC)
    await add_user(user.id)

    bot = await context.bot.get_me()
    bot_username = bot.username or ""

    user_name = user.first_name or "User"
    user_mention = f"<a href='tg://user?id={user.id}'>{user_name}</a>"

    bot_mention = (
        f"<a href='https://t.me/{bot_username}'>{bot.first_name}</a>"
        if bot_username else bot.first_name
    )

    text = (
        f"────「 {bot_mention} 」────\n\n"
        f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
        "ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။\n"
        "ငါ၏လုပ်နိုင်စွမ်းများကို ကောင်းကောင်းအသုံးချပါ။\n\n"
        "<b>📌 ငါ၏လုပ်နိုင်စွမ်းများ</b>\n\n"
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
        "✅ Welcome Message\n"
        "✅ Goodbye Message\n"
        "✅ Filters\n\n"
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
        "<b>📥 အသုံးပြုရန်</b>\n"
        "➕ Group ထဲထည့်ပါ\n"
        "⭐️ Admin ပေးပါ"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ ADD ME TO YOUR GROUP",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫",
                url="tg://user?id=5942810488"
            ),
            InlineKeyboardButton(
                "📢 𝐂𝐡𝐚𝐧𝐧𝐞𝐥",
                url="https://t.me/MMTelegramBotss"
            )
        ]
    ])

    try:
        await update.message.reply_photo(
            photo=START_IMAGE,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Forbidden:
        # user blocked the bot → ignore
        pass

# ===============================
# ADMIN CHECK (USER)
# ===============================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in (
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        )
    except Exception:
        return False


LAST_WELCOME = {}


# ===============================
# CHECK BOT ADMIN (BEST & STABLE)
# ===============================
from telegram.error import Forbidden, BadRequest

async def bot_is_admin(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # ✅ safeguard
    if not context or not context.bot or not chat_id:
        return False

    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)

        # ✅ Only true admin / owner
        return member.status in (
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        )

    except Forbidden:
        # ❌ Bot is not in group OR no permission
        return False

    except BadRequest:
        # ❌ Chat not found / invalid chat_id
        return False

    except Exception as e:
        # ❌ Any unexpected error (large groups safe)
        print(f"[bot_is_admin ERROR] {e}")
        return False

# ===============================
# Admin Reminder
# ===============================
async def admin_reminder(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    # init counter
    count = ADMIN_REMINDER_COUNT.get(chat_id, 0)

    # ⛔ max 5 times
    if count >= 5:
        return

    try:
        me = await context.bot.get_me()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐️ GIVE ADMIN PERMISSION",
                    url=f"https://t.me/{me.username}?startgroup=true"
                )
            ]
        ])

        await context.bot.send_message(
            chat_id,
            (
                "⚠️ <b>Admin Permission Required</b>\n\n"
                "ဒီ Bot ကို အသုံးပြုရန်\n"
                "⭐️ <b>Admin အဖြစ် ပေးပါ</b>"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )

        # ✅ increment only on success
        ADMIN_REMINDER_COUNT[chat_id] = count + 1

    except Forbidden:
        # bot cannot send message
        return
    except Exception as e:
        print(f"[admin_reminder ERROR] chat_id={chat_id} → {e}")


# ===============================
# Thank You Message
# ===============================
async def admin_thank_you(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    # already thanked → skip
    if chat_id in ADMIN_THANKED:
        return

    try:
        await context.bot.send_message(
            chat_id,
            (
                "✅ <b>Thank you!</b>\n\n"
                "Bot ကို <b>Admin</b> အဖြစ် ပေးထားပြီးပါပြီ 🙏\n"
                "အခု Features အကုန် အသုံးပြုနိုင်ပါပြီ"
            ),
            parse_mode="HTML"
        )

        # ✅ mark as thanked
        ADMIN_THANKED.add(chat_id)

        # 🧹 optional: clear reminder counter
        ADMIN_REMINDER_COUNT.pop(chat_id, None)

    except Forbidden:
        return
    except Exception as e:
        print(f"[admin_thank_you ERROR] chat_id={chat_id} → {e}")

# ===============================
# WELCOME MESSAGE (ON JOIN)
# ===============================
async def track_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    # 🔒 group only
    if not chat or chat.type not in ("group", "supergroup"):
        return

    # ✅ save group (async, Supabase-safe)
    try:
        await add_group(chat.id)
    except Exception as e:
        print(f"[add_group ERROR] chat_id={chat.id} → {e}")

    # 🔒 bot admin check
    is_bot_admin = await bot_is_admin(chat.id, context)

    # ❌ Bot is NOT admin → reminder (max 5 times)
    if not is_bot_admin:
        await admin_reminder(chat.id, context)
        return

    # ✅ Bot IS admin → thank you (once)
    await admin_thank_you(chat.id, context)

    # 🔒 message safeguard
    if not update.message or not update.message.new_chat_members:
        return

    me = await context.bot.get_me()

    # 🔒 skip bot self join
    members = [
        m for m in update.message.new_chat_members
        if m.id != me.id
    ]

    if not members:
        return

    # 🔒 time safe (large group OK)
    joined_time = (
        update.message.date.strftime("%Y-%m-%d %H:%M:%S")
        if update.message.date
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # 🔒 delete previous welcome (best effort)
    last_msg_id = LAST_WELCOME.get(chat.id)
    if last_msg_id:
        try:
            await context.bot.delete_message(chat.id, last_msg_id)
        except:
            pass

    # ✅ Welcome message
    for member in members:
        username = f"@{member.username}" if member.username else "No Username"
        mention = f"<a href='tg://user?id={member.id}'>{member.first_name}</a>"

        text = (
            f"✨ <b>Welcome to {chat.title}</b> ✨\n\n"
            f"🏷 Name: {member.first_name}\n"
            f"🆔 User ID: {member.id}\n"
            f"👤 Username: {username}\n"
            f"🔗 Mention: {mention}\n"
            f"⏰ Joined at: {joined_time}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ ADD ME TO YOUR GROUP",
                    url=f"https://t.me/{me.username}?startgroup=true"
                )
            ]
        ])

        try:
            msg = await context.bot.send_photo(
                chat_id=chat.id,
                photo=WELCOME_IMAGE,
                caption=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            LAST_WELCOME[chat.id] = msg.message_id

        except Forbidden:
            return
        except Exception as e:
            print(f"[WELCOME ERROR] chat_id={chat.id} → {e}")

# ===============================
# 👋 GOODBYE MESSAGE (ON LEAVE)
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    # 🔒 group only
    if not chat or chat.type not in ("group", "supergroup"):
        return

    member = None
    left_date = None

    # LEFT_CHAT_MEMBER (message based)
    if update.message and update.message.left_chat_member:
        member = update.message.left_chat_member
        left_date = update.message.date

    # CHAT_MEMBER update (fallback)
    elif update.chat_member and update.chat_member.old_chat_member:
        member = update.chat_member.old_chat_member.user
        left_date = datetime.now()

    if not member:
        return

    # 🔒 bot admin check (avoid Forbidden)
    is_bot_admin = await bot_is_admin(chat.id, context)
    if not is_bot_admin:
        return

    # 🔒 safe timestamp
    left_time = (
        left_date.strftime("%Y-%m-%d %H:%M:%S")
        if left_date
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    text = (
        f"⛔️ <b>ထွက်သွားပြီးပေါ့</b>\n"
        f"<b>နှစ်တစ်ထောင် Fa ဖြစ်ပါစေ။</b>\n\n"
        f"👤 Name: <a href='tg://user?id={member.id}'>{member.first_name}</a>\n"
        f"🆔 User ID: {member.id}\n"
        f"⏰ Left at: {left_time}"
    )

    try:
        me = await context.bot.get_me()
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ ADD ME TO YOUR GROUP",
                    url=f"https://t.me/{me.username}?startgroup=true"
                )
            ]
        ])

        await context.bot.send_photo(
            chat_id=chat.id,
            photo=GOODBYE_IMAGE,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Forbidden:
        # bot has no permission / removed
        return
    except Exception as e:
        print(f"[GOODBYE ERROR] chat_id={chat.id} → {e}")

# ===============================
# ADD FILTER (ADMIN ONLY)
# ===============================
async def cmd_add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return

    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text("❌ Admin / Owner ပဲ Filter ထည့်နိုင်ပါတယ်")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage:\n/filter <keyword> <reply>")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0].lower().strip()
    reply = " ".join(context.args[1:]).strip()

    if not keyword or not reply:
        await update.message.reply_text("⚠️ Keyword နဲ့ Reply မဖြစ်မနေလိုပါတယ်")
        return

    FILTER_CACHE.setdefault(chat_id, {})

    if keyword in FILTER_CACHE[chat_id]:
        await update.message.reply_text("⚠️ ဒီ Keyword ရှိပြီးသားပါ")
        return

    # ✅ DB SAVE (await REQUIRED)
    await db_add_filter(chat_id, keyword, reply)

    # ✅ CACHE SAVE
    FILTER_CACHE[chat_id][keyword] = reply

    await update.message.reply_text(f"✅ Filter added\n🔑 Keyword: {keyword}")

# ===============================
# REMOVE FILTER (ADMIN ONLY)
# ===============================
async def db_remove_filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ဖျက်နိုင်ပါတယ်")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /stop <keyword>")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0].lower()

    # ✅ DB REMOVE (await REQUIRED)
    await db_remove_filter(chat_id, keyword)

    # ✅ CACHE REMOVE
    FILTER_CACHE.get(chat_id, {}).pop(keyword, None)

    await update.message.reply_text(
        f"🗑 Filter removed: <b>{keyword}</b>",
        parse_mode="HTML"
    )

# ===============================
# LIST FILTERS (ADMIN ONLY)
# ===============================
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ကြည့်နိုင်ပါတယ်")
        return

    chat_id = update.effective_chat.id
    filters_dict = FILTER_CACHE.get(chat_id, {})

    if not filters_dict:
        await update.message.reply_text("📭 No active filters")
        return

    text = "📌 <b>Active Filters:</b>\n\n"
    text += "\n".join(f"• {k}" for k in filters_dict.keys())

    await update.message.reply_text(text, parse_mode="HTML")

# ===============================
# AUTO FILTER (REPLY)
# ===============================
async def auto_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.lower()

    filters_dict = FILTER_CACHE.get(chat_id)
    if not filters_dict:
        return

    for keyword, reply in filters_dict.items():
        if keyword in text:
            try:
                await update.message.reply_text(reply)
            except:
                pass
            break

# ===============================
# LOAD FILTERS INTO CACHE (ASYNC)
# ===============================
async def load_filters_to_cache_async():
    global FILTER_CACHE
    FILTER_CACHE.clear()

    # ✅ filters table ကနေ direct chat_id ယူ
    rows = await db_execute(
        "SELECT DISTINCT chat_id FROM filters",
        fetch=True
    ) or []

    for (chat_id,) in rows:
        filters_rows = await db_get_filters(chat_id)
        if filters_rows:
            FILTER_CACHE[chat_id] = {
                keyword: reply for keyword, reply in filters_rows
            }

# ===============================
# BROADCAST (OWNER ONLY)
# ===============================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update or not update.effective_user or not update.message:
        return

    if update.effective_user.id != OWNER_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/broadcast <message>")
        return

    text = " ".join(context.args)

    sent = 0
    failed = 0

    # ✅ async DB fetch (REQUIRED)
    users = await get_users()
    groups = await get_groups()

    targets = set(users + groups)

    for chat_id in targets:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            sent += 1

            # 🔹 flood-safe
            await asyncio.sleep(0.05)

        except Exception as e:
            failed += 1
            print(f"Broadcast failed {chat_id}: {e}")

            # ❌ cleanup dead chats (background)
            if chat_id in users:
                asyncio.create_task(
                    db_execute(
                        "DELETE FROM users WHERE user_id=%s",
                        (chat_id,)
                    )
                )
            else:
                asyncio.create_task(
                    db_execute(
                        "DELETE FROM groups WHERE chat_id=%s",
                        (chat_id,)
                    )
                )

    await update.message.reply_text(
        "✅ <b>Broadcast completed</b>\n\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {failed}",
        parse_mode="HTML"
    )

# ===============================
# GLOBAL ERROR HANDLER
# ===============================
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.ERROR,
)

logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.error("Unhandled exception", exc_info=context.error)
    except Exception as e:
        print("⚠️ ERROR HANDLER FAILED:", e)

# ===============================
# MAIN
# ===============================
def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ===============================
    # STARTUP TASKS (ASYNC)
    # ===============================
    async def on_startup(app):
        # ✅ init DB (AWAIT REQUIRED)
        await init_db()

        # ✅ load filters cache (AWAIT REQUIRED)
        await load_filters_to_cache_async()

        print("✅ DB & Cache initialized")

    # 🔥 register startup hook
    app.post_init = on_startup

    # ===============================
    # GLOBAL ERROR HANDLER
    # ===============================
    app.add_error_handler(error_handler)

    # ===============================
    # COMMANDS
    # ===============================
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # ===============================
    # GOODBYE
    # ===============================
    app.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye),
        group=5
    )

    app.add_handler(
        ChatMemberHandler(goodbye, ChatMemberHandler.CHAT_MEMBER),
        group=6
    )

    # ===============================
    # WELCOME
    # ===============================
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_group),
        group=5
    )

    # ===============================
    # FILTER COMMANDS
    # ===============================
    app.add_handler(CommandHandler("filter", cmd_add_filter))
    app.add_handler(CommandHandler("stop", db_remove_filter_cmd))
    app.add_handler(CommandHandler("filters", list_filters))

    # ===============================
    # AUTO FILTER
    # ===============================
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_filter),
        group=1
    )

    print("🤖 MissOlivia Bot is running (SUPABASE READY)")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()