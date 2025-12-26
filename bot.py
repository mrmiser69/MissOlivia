from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from database import (
    init_db,
    db_add_filter,
    db_remove_filter,      # ✅ ဒီနေရာ ပြင်
    db_get_filters,
    add_user,
    get_users,
    add_group,
    get_groups
)
from datetime import datetime

# ===============================
# CONFIG
# ===============================
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

START_IMAGE = "https://i.postimg.cc/tJF69SbN/ICON.jpg"
WELCOME_IMAGE = "https://i.postimg.cc/L6hVSnp3/WELCOME.png"
GOODBYE_IMAGE = "https://i.postimg.cc/bdXNCLc2/Untitled-design-(12).png"

# ===============================
# CHECK ADMIN / OWNER
# ===============================
from telegram import ChatMember, Update
from telegram.ext import ContextTypes

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    # ✅ ERROR FIX: chat / user None safeguard
    if not chat or not user:
        return False

    if chat.type not in ["group", "supergroup"]:
        return False

    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)

# In-memory storage (RAM)
GROUPS = set()

# Last welcome message per group
LAST_WELCOME = {}

# keyword => reply
FILTERS = {}

# ===============================
# /start (PRIVATE)
# ===============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_chat or update.effective_chat.type != "private":
        return

    if not update.message:
        return

    if not update.effective_user:
        return

    user = update.effective_user
    add_user(user.id)

    bot = await context.bot.get_me()

    user_name = user.first_name or "User"
    user_mention = f"<a href='tg://user?id={user.id}'>{user_name}</a>"
    bot_mention = f"<a href='https://t.me/{bot.username}'>{bot.first_name}</a>"

    text = (
        f"────「 {bot_mention} 」────\n\n"
        f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
        "ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။\n"
        "ငါ၏လုပ်နိုင်စွမ်းများကို ကောင်းကောင်းအသုံးချပါ။\n\n"
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
        "<b>📌 ငါ၏လုပ်နိုင်စွမ်းများ</b>\n\n"
        "✅ Welcome Message\n"
        "✅ Goodbye Message\n"
        "✅ Auto Link Delete\n"
        "✅ Filters\n\n"
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
        "<b>📥 အသုံးပြုရန်</b>\n"
        "➕ Group ထဲထည့်ပါ\n"
        "⭐️ Admin ပေးပါ"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "➕ ADD ME TO YOUR GROUP",
            url=f"https://t.me/{bot.username}?startgroup=true"
        )],
        [InlineKeyboardButton("👨‍💻 DEVELOPER", url="https://t.me/callmeoggy")]
    ])

    await update.message.reply_photo(
        photo=START_IMAGE,
        caption=text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

# ===============================
# CHECK BOT ADMIN
# ===============================
from telegram import ChatMember
from telegram.error import Forbidden

async def bot_is_admin(chat_id, context):
    try:
        me = await context.bot.get_me()
        member = await context.bot.get_chat_member(chat_id, me.id)

        return member.status in (
            ChatMember.ADMINISTRATOR,
            ChatMember.OWNER
        )

    except Forbidden:
        return False
    except:
        return False

# ===============================
# WELCOME MESSAGE (ON JOIN)
# ===============================
async def track_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        return

    # Admin check (မပြောင်း)
    if not await bot_is_admin(chat.id, context):
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⭐️ GIVE ADMIN PERMISSION",
                    url=f"https://t.me/{(await context.bot.get_me()).username}?startgroup=true"
                )
            ]
        ])
        await context.bot.send_message(
            chat.id,
            "⚠️ <b>Admin Permission Required</b>\n\n"
            "ဒီ Bot ကို အသုံးပြုရန်\n"
            "⭐️ <b>Admin အဖြစ် အရင်ပေးပါ</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    # ✅ ERROR FIX: members detect
    members = []
    if update.message and update.message.new_chat_members:
        members = update.message.new_chat_members
    elif update.chat_member:
        members = [update.chat_member.new_chat_member.user]

    if not members:
        return

    # ✅ ERROR FIX: safe time
    joined_time = (
        update.message.date.strftime("%Y-%m-%d %H:%M:%S")
        if update.message else
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    if chat.id in LAST_WELCOME:
        try:
            await context.bot.delete_message(chat.id, LAST_WELCOME[chat.id])
        except:
            pass

    for member in members:
        text = (
            f"✨ Welcome to {chat.title} ✨\n\n"
            f"🏷 Name: {member.first_name}\n"
            f"🆔 User ID: {member.id}\n"
            f"👤 Username: @{member.username if member.username else 'No Username'}\n"
            f"🔗 Mention: <a href='tg://user?id={member.id}'>{member.first_name}</a>\n"
            f"⏰ Joined at: {joined_time}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ ADD ME TO YOUR GROUP",
                    url=f"https://t.me/{(await context.bot.get_me()).username}?startgroup=true"
                )
            ]
        ])

        msg = await context.bot.send_photo(
            chat_id=chat.id,
            photo=WELCOME_IMAGE,
            caption=text,
            parse_mode="HTML"
        )
        LAST_WELCOME[chat.id] = msg.message_id

# ===============================
# 👋 GOODBYE MESSAGE (ON LEAVE)
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ["group", "supergroup"]:
        return

    # ✅ ERROR FIX
    member = None
    if update.message and update.message.left_chat_member:
        member = update.message.left_chat_member
    elif update.chat_member:
        member = update.chat_member.old_chat_member.user

    if not member:
        return

    # ✅ ERROR FIX: safe time
    left_time = (
        update.message.date.strftime("%Y-%m-%d %H:%M:%S")
        if update.message else
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    text = (
        f"⛔️ <b>ထွက်သွားပြီးပေါ့</b>\n"
        f"<b>နှစ်တစ်ထောင် Fa ဖြစ်ပါစေ။</b>\n\n"
        f"👤 Name: <a href='tg://user?id={member.id}'>{member.first_name}</a>\n"
        f"🆔 User ID: {member.id}\n"
        f"⏰ Left at: {left_time}"
    )

    await context.bot.send_photo(
        chat_id=chat.id,
        photo=GOODBYE_IMAGE,
        caption=text,
        parse_mode="HTML"
    )

# ===============================
# BROADCAST (OWNER ONLY)
# ===============================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # ✅ ERROR FIX ①: update.message / user မရှိရင် stop
    if not update.message or not update.effective_user:
        return

    # ✅ ERROR FIX ②: OWNER check
    if update.effective_user.id != OWNER_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/broadcast <message>")
        return

    text = " ".join(context.args)

    for uid in get_users():
        try:
            await context.bot.send_message(uid, text)
        except:
            pass

    for gid in get_groups():
        try:
            await context.bot.send_message(gid, text)
        except:
            pass

    await update.message.reply_text("✅ Broadcast sent")

# ===============================
# 🔗 AUTO LINK DELETE
# ===============================
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

async def auto_delete_links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # ❌ ERROR FIX: group / supergroup မဟုတ်ရင် stop
    if update.effective_chat.type not in ["group", "supergroup"]:
        return

    if not update.effective_chat or not update.message or not update.message.text:
        return

    text = update.message.text.lower()

    if "http://" in text or "https://" in text or "t.me/" in text:
        try:
            await update.message.delete()

            warn = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"⚠️ ({update.effective_user.first_name}) "
                    "မင်းရဲ့စာကိုဖျက်လိုက်ပါပြီ။\n"
                    "အကြောင်းပြချက်: 🔗 links ပို့လို့မရပါဘူး။"
                )
            )

            await asyncio.sleep(5)
            await warn.delete()

        except:
            pass

# ===============================
# ADD FILTER (ADMIN ONLY)
# ===============================
async def cmd_add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # ✅ ERROR FIX: update.message None ဖြစ်ရင် stop
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ထည့်နိုင်ပါတယ်")
        return

    # ✅ ERROR FIX: context.args None / length check
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage:\n/filter <keyword> <reply>")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])

    db_add_filter(chat_id, keyword, reply)

    await update.message.reply_text(
        f"✅ Filter added\n🔑 Keyword: {keyword}"
    )

# ===============================
# REMOVE FILTER (ADMIN ONLY)
# ===============================
async def db_remove_filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id

    if not await bot_is_admin(chat_id, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ဖျက်နိုင်ပါတယ်")
        return

    if not context.args:  # ✅ Error fix
        await update.message.reply_text("⚠️ Usage: /removefilter keyword")
        return

    keyword = context.args[0]
    db_remove_filter(chat_id, keyword)  # ✅ FIXED: function name
    await update.message.reply_text("🗑 Filter removed")

# ===============================
# LIST FILTERS (ADMIN ONLY)
# ===============================
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # ✅ update.message မရှိရင် stop
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ကြည့်နိုင်ပါတယ်")
        return

    chat_id = update.effective_chat.id

    db_filters = db_get_filters(chat_id)   # 🔧 filters → db_filters (ERROR FIX)

    if not db_filters:
        await update.message.reply_text("📭 No active filters")
        return

    text = "📌 <b>Active Filters:</b>\n\n"
    for keyword, _ in db_filters:
        text += f"• {keyword}\n"

    await update.message.reply_text(text, parse_mode="HTML")

# ===============================
# AUTO FILTER (REPLY)
# ===============================
async def auto_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # text မပါတဲ့ update တွေကို skip
    if not update.message or not update.message.text:
        return

    text = update.message.text.lower()
    chat_id = update.effective_chat.id

    rows = db_get_filters(chat_id) or []   # 🔧 filters → rows (Error fix)

    for keyword, reply in rows:
        if keyword in text:
            await update.message.reply_text(reply)
            break

# ===============================
# GLOBAL ERROR HANDLER
# ===============================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        print("⚠️ ERROR:", context.error)
    except:
        pass

# ===============================
# MAIN
# ===============================
def main():
    init_db()   # ⭐️ ဒီလိုင်း မဖြစ်မနေလိုပါတယ်
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # ✅ ADD GLOBAL ERROR HANDLER HERE
    app.add_error_handler(error_handler)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # 👋 join / leave
    app.add_handler(
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_group),
        group=5   # 🔧 FIX
    )
    
    app.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye),
        group=5
    )
    
    # 🧠 filter commands
    app.add_handler(CommandHandler("filter", cmd_add_filter))
    app.add_handler(CommandHandler("stop", db_remove_filter_cmd))   # ✅ FIX
    app.add_handler(CommandHandler("filters", list_filters))

    # 🔗 AUTO DELETE LINKS (FIRST)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_delete_links),
        group=0
    )

    # 🤖 AUTO FILTER (REPLY AFTER)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_filter),
        group=1
    )

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":   # ✅ FIX
    main()