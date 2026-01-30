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
from telegram.ext import PreCheckoutQueryHandler

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
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
)

from psycopg_pool import ConnectionPool  # ✅ ONLY THIS (Supabase safe)

# ===============================
# GLOBAL CACHES
# ===============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.ERROR,
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)

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
LAST_WELCOME_TS = {}   # {(chat_id, user_id): ts}
LAST_GOODBYE_TS = {}   # {(chat_id, user_id): ts}

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
            "( Member Group ထဲဝင်လာရင် Welcome Message ပို့မယ် )\n"
            "✅ Goodbye Message\n"
            "( Member Group ထဲကထွက်သွားရင်ရင် GoodBye Message ပို့မယ် )\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n"
            "➕ ငါ့ကို Group ထဲထည့်ပါ\n"
            "⭐️ ငါ့ကို Admin ပေးပါ"
        )

        buttons = []

        if bot_username:
            buttons.append([
                InlineKeyboardButton(
                    "➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ])
        
        # ✅ Donate Us button (Callback)
        buttons.append([
            InlineKeyboardButton("💖 DONATE US 💖", callback_data="donate_menu")
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
                    "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ]])
        )
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

    # This donate UI only makes sense in private chat
    if query.message.chat.type != "private":
        return

    bot = context.bot
    bot_username = bot.username or ""
    user = update.effective_user

    # --- 1) Donate Menu ---
    if data == "donate_menu":
        donate_text = (
            "<b>💖 Support Us !</b>\n\n"
            "မင်းအတွက် အလုပ်ကောင်းကောင်းလုပ်နေတဲ့ Bot ကို Support ပေးနိုင်ပါတယ်။\n\n"
            "<b>👇 အောက်ကနေ ရွေးပါ</b>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐️ 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗕𝗢𝗧 (5 Stars)", callback_data="donate_stars_5")],
            [InlineKeyboardButton("🪙 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗗𝗘𝗩𝗘𝗟𝗢𝗣𝗘𝗥 (TON)", callback_data="donate_ton")],
            [InlineKeyboardButton("⬅️ Back", callback_data="donate_back_start")],
        ])

        # Your /start is a PHOTO message -> edit_caption
        await query.message.edit_caption(
            caption=donate_text,
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # --- 2) Back to original /start ---
    if data == "donate_back_start":
        # rebuild original caption + keyboard exactly like /start private
        user_name = escape(user.first_name or "User")
        bot_name = escape(bot.first_name or "Bot")
        user_mention = f"<a href='tg://user?id={user.id}'>{user_name}</a>"
        bot_mention = (
            f"<a href='https://t.me/{bot_username}'>{bot_name}</a>"
            if bot_username else bot_name
        )

        start_text = (
            f"<b>────「 {bot_mention} 」────</b>\n\n"
            f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
            "<b>ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။</b>\n"
            "<b>ငါ၏လုပ်နိုင်စွမ်းကို ကောင်းကောင်းအသုံးချပါ။</b>\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📌 ငါ၏လုပ်နိုင်စွမ်း</b>\n\n"
            "✅ Welcome Message\n"
            "( Member Group ထဲဝင်လာရင် Welcome Message ပို့မယ် )\n"
            "✅ Goodbye Message\n"
            "( Member Group ထဲကထွက်သွားရင်ရင် GoodBye Message ပို့မယ် )\n\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
            "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n"
            "➕ ငါ့ကို Group ထဲထည့်ပါ\n"
            "⭐️ ငါ့ကို Admin ပေးပါ"
        )

        buttons = []
        if bot_username:
            buttons.append([
                InlineKeyboardButton(
                    "➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
                    url=f"https://t.me/{bot_username}?startgroup=true"
                )
            ])

        buttons.append([InlineKeyboardButton("💖 DONATE US", callback_data="donate_menu")])

        buttons.append([
            InlineKeyboardButton("👨‍💻 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫", url="tg://user?id=5942810488"),
            InlineKeyboardButton("📢 𝐂𝐡𝐚𝐧𝐧𝐞𝐥", url="https://t.me/MMTelegramBotss"),
        ])

        await query.message.edit_caption(
            caption=start_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # --- 3) TON address page ---
    if data == "donate_ton":
        TON_ADDRESS = os.getenv("TON_ADDRESS", "PUT_YOUR_TON_ADDRESS_HERE")
        ton_text = (
            "<b>🪙 Support Developer (TON)</b>\n\n"
            f"<b>TON Address:</b>\n<code>{escape(TON_ADDRESS)}</code>\n\n"
            "✅ Address ကို copy လုပ်ပြီး TON coin ပေးပို့နိုင်ပါတယ်ဗျ။\n"
            "💙 Thank You For Supporting !"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="donate_menu")],
        ])
        await query.message.edit_caption(
            caption=ton_text,
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # --- 4) Stars 5 invoice ---
    if data == "donate_stars_5":
        # Stars invoice needs pre_checkout + successful payment handlers too
        from telegram import LabeledPrice

        try:
            await context.bot.send_invoice(
                chat_id=query.message.chat.id,
                title="Support Bot ⭐️",
                description=(
                    "⭐️ Telegram Stars ၅ လုံးနဲ့ Bot ကို Support ပေးနိုင်ပါတယ်။\n\n"
                    "မင်းရဲ့ အားပေးမှုက\n"
                    "ဒီ Bot ကို ပိုကောင်းအောင် ဆက်လုပ်နိုင်ဖို့ အားအင်ဖြစ်စေပါတယ် 💙"
                ),
                payload=f"donate_bot_5_{user.id}",
                currency="XTR",
                prices=[LabeledPrice("Support", 5)],
                provider_token="",  # Stars often use empty provider_token
            )
        except Exception as e:
            # Keep UX: show error as alert, not new message spam
            await query.answer(f"❌ Donate မလုပ်နိုင်ပါ: {e}", show_alert=True)
        return

# ===============================
# Precheckout Callback
# ===============================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if not query:
        return

    # ✅ accept only our donate payloads
    if not (query.payload or "").startswith("donate_bot_5_"):
        await query.answer(ok=False, error_message="Invalid payment payload.")
        return

    await query.answer(ok=True)

# ===============================
# Successful Payment Handler
# ===============================
async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text("✅ ကျေးဇူးတင်ပါတယ်! Stars Donate လုပ်ပြီးပါပြီ ⭐️") 

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
def build_welcome_text(chat, member, joined_time: str):
    group_title = escape(chat.title or "Group")
    if getattr(chat, "username", None):
        group_link = f"https://t.me/{chat.username}"
        group_title_link = f"<a href='{group_link}'>{group_title}</a>"
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
# 👋 WELCOME (CHAT_MEMBER) - 100% reliable
# ===============================
async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cm = update.chat_member
    if not chat or chat.type not in ("group", "supergroup") or not cm:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status
    user = cm.new_chat_member.user

    # bot ကို welcome မလုပ်
    me = await context.bot.get_me()
    if user.id == me.id:
        return

    # ✅ JOIN condition (member OR restricted)  << IMPORTANT FIX
    joined = (old_status in ("left", "kicked")) and (new_status in ("member", "restricted", "administrator"))
    if not joined:
        return

    # bot admin မဟုတ်ရင် မပို့
    if not await is_bot_admin(chat.id, context):
        return

    # ✅ debounce duplicates (2-3 sec)  << IMPORTANT FIX
    now_ts = int(time.time())
    last_ts = LAST_WELCOME_TS.get((chat.id, user.id))
    if last_ts and (now_ts - last_ts) < 2:
        return
    LAST_WELCOME_TS[(chat.id, user.id)] = now_ts

    joined_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = build_welcome_text(chat, user, joined_time)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
            url=f"https://t.me/{me.username}?startgroup=true"
        )
    ]])

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
    except BadRequest:
        # fallback text only
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")
    except Exception:
        with contextlib.suppress(Exception):
            await context.bot.send_message(chat.id, text, parse_mode="HTML")


# ===============================
# 👋 GOODBYE (CHAT_MEMBER) - 100% reliable
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    cm = update.chat_member
    if not chat or chat.type not in ("group", "supergroup") or not cm:
        return

    old = cm.old_chat_member
    new = cm.new_chat_member
    user = old.user  # leaving user

    # bot ကို goodbye မလုပ်
    me = await context.bot.get_me()
    if user.id == me.id:
        return

    # ✅ LEAVE condition
    left = (old.status in ("member", "restricted")) and (new.status in ("left", "kicked"))
    if not left:
        return

    # Bot kicked ဖြစ်ရင် (chat access မရှိ) silent
    try:
        await context.bot.get_chat(chat.id)
    except Forbidden:
        return
    except Exception:
        pass

    if not await is_bot_admin(chat.id, context):
        return

    # ✅ debounce duplicates (2-3 sec)
    now_ts = int(time.time())
    last_ts = LAST_GOODBYE_TS.get((chat.id, user.id))
    if last_ts and (now_ts - last_ts) < 2:
        return
    LAST_GOODBYE_TS[(chat.id, user.id)] = now_ts

    left_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = build_goodbye_text(user, left_time)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "➕ 𝗔𝗗𝗗 𝗠𝗘 𝗧𝗢 𝗬𝗢𝗨𝗥 𝗚𝗥𝗢𝗨𝗣",
            url=f"https://t.me/{me.username}?startgroup=true"
        )
    ]])

    try:
        await context.bot.send_photo(
            chat_id=chat.id,
            photo=GOODBYE_IMAGE,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
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
# 📢 BROADCAST (OWNER ONLY)
# ===============================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_user or update.effective_user.id != OWNER_ID:
        return

    msg = update.effective_message
    if not msg:
        return

    text = msg.text or msg.caption
    if not text or not text.startswith("/broadcast"):
        return

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

        except ChatMigrated as e:
            # args = (context, chat_id, data) ဆိုတဲ့ pattern ဖြစ်နေလို့
            try:
                context = args[0]
                old_chat_id = args[1]
                new_chat_id = e.new_chat_id

                # DB update (groups table)
                context.application.create_task(
                    db_execute(
                        "UPDATE groups SET group_id=%s WHERE group_id=%s",
                        (new_chat_id, old_chat_id)
                    )
                )

                # retry with new chat id
                new_args = (args[0], new_chat_id, *args[2:])
                args = new_args
                continue
            except Exception:
                return None

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
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=data["photo"],
                caption=text if text else None,
                parse_mode="HTML"
            )

        if data.get("video"):
            return await context.bot.send_video(
                chat_id=chat_id,
                video=data["video"],
                caption=text if text else None,
                parse_mode="HTML"
            )

        if data.get("audio"):
            return await context.bot.send_audio(
                chat_id=chat_id,
                audio=data["audio"],
                caption=text if text else None,
                parse_mode="HTML"
            )

        if data.get("document"):
            return await context.bot.send_document(
                chat_id=chat_id,
                document=data["document"],
                caption=text if text else None,
                parse_mode="HTML"
            )

        if text:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML"
            )

    except Forbidden:
        # bot kicked / blocked → silent
        return
    except BadRequest:
        return
    except Exception:
        return

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
                "🤖 <b>Bot</b> ကို <b>Admin</b> အဖြစ် ခန့်ထားပြီးပါပြီး။\n\n"
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
                    "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
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
                "⭐ 𝗚𝗜𝗩𝗘 𝗔𝗗𝗠𝗜𝗡 𝗣𝗘𝗥𝗠𝗜𝗦𝗦𝗜𝗢𝗡",
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

    now = time.time_ns()

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
            # ✅ API error -> DO NOT TOUCH DB (keeps old values)
            print(f"⚠️ Skip admin check for {gid}: {e}", flush=True)

        await asyncio.sleep(0.1)

    print(f"✅ Admin cache verified: {verified}", flush=True)
    print(f"⚠️ Non-admin groups marked: {skipped}", flush=True)

    return now  # ✅ IMPORTANT: return this run's timestamp

# ===============================
# purge non admin groups verified
# ===============================
async def purge_non_admin_groups_verified(now: int):
    # Only delete rows that were VERIFIED in this startup run
    await db_execute(
        """
        DELETE FROM groups
        WHERE is_admin_cached = FALSE
          AND last_checked_at = %s
        """,
        (now,)
    )
    print("🧹 Startup purge: verified non-admin groups removed", flush=True)

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

    app.add_error_handler(error_handler)
    # -------------------------------
    # Commands
    # -------------------------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("refresh_all", refresh_all))
    app.add_handler(CallbackQueryHandler(donate_callback, pattern=r"^donate"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

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
        ChatMemberHandler(welcome_chat_member, ChatMemberHandler.CHAT_MEMBER),
        group=5
    )

    # -------------------------------
    # GOODBYE
    # -------------------------------
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
            & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL),
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

        now = await refresh_admin_cache(app)
        print("✅ Admin cache refreshed", flush=True)
        
        await purge_non_admin_groups_verified(now)

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