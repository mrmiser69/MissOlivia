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
    db_remove_filter,
    db_get_filters,
    add_user,
    get_users,
    add_group,
    get_groups
)

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
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ["group", "supergroup"]:
        return False

    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]

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
    if update.effective_chat.type != "private":
        return

    user = update.effective_user        # 🔴 ဒီလို ထည့်ရမယ်
    user_id = user.id

    add_user(user_id)

    user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
    bot_mention = f"<a href='https://t.me/{bot.username}'>{bot.first_name}</a>"

    text = (
        f"────「 {bot_mention} 」────\n\n"
        f"<b>ဟယ်လို {user_mention} ! 👋</b>\n\n"
        "ငါသည် Group များအတွက် အသုံးဝင် Bot တစ်ခုဖြစ်တယ်။\n" +
        "ငါ၏လုပ်နိုင်စွမ်းများကို ကောင်းကောင်းအသုံးချပါ။\n\n" +
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n" +
        "<b>📌 ငါ၏လုပ်နိုင်စွမ်းများ</b>\n\n" +
        "✅ Welcome Message ပေးပို့ပေးခြင်း\n" +
        "✅ GoodBye Message ပေးပိုပေးခြင်း\n" +
        "✅ Auto Link Delete လုပ်ပေးခြင်း\n" +
        "✅ Filter များ ထည့်အသုံးပြုနိုင်ခြင်း\n\n" +
        "➖➖➖➖➖➖➖➖➖➖➖➖\n\n" +
        "<b>📥 ငါ့ကိုအသုံးပြုရန်</b>\n\n" +
        "➕ ငါ့ကို Group ထဲသို့ ထည့်သွင်းပါ\n" +
        "⭐️ ငါ့ကို Admin အဖြစ် သတ်မှတ်ပါ"
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
async def bot_is_admin(chat_id, context):
    me = await context.bot.get_me()
    member = await context.bot.get_chat_member(chat_id, me.id)
    return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]

# ===============================
# WELCOME MESSAGE (ON JOIN)
# ===============================
async def track_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat   # 🔴 မဖြစ်မနေ

    if chat.type in ["group", "supergroup"]:
        add_group(chat.id)

    # save group id
    GROUPS.add(chat.id)

    # require admin
    if not await bot_is_admin(chat.id, context):
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ ADD ME TO YOUR GROUP",
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

    # 🔥 DELETE PREVIOUS WELCOME (if exists)
    if chat.id in LAST_WELCOME:
        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=LAST_WELCOME[chat.id]
            )
        except:
            pass

    # handle new members
    for member in update.message.new_chat_members:
        name = member.first_name
        uid = member.id
        username = f"@{member.username}" if member.username else "No Username"
        mention = f"<a href='tg://user?id={uid}'>{name}</a>"
        time = update.message.date.strftime("%Y-%m-%d %H:%M:%S")
        groupName = chat.title

        text = (
            f"✨ Welcome to {groupName} ✨\n\n"
            f"🏷 Name: {name}\n"
            f"🆔 User ID: {uid}\n"
            f"👤 Username: {username}\n"
            f"🔗 Mention: {mention}\n"
            f"⏰ Joined at: {time}"
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
            parse_mode="HTML",
            reply_markup=keyboard
        )

        # ✅ SAVE THIS MESSAGE ID
        LAST_WELCOME[chat.id] = msg.message_id

# ===============================
# 👋 GOODBYE MESSAGE (ON LEAVE)
# ===============================
async def goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["group", "supergroup"]:
        return

    member = update.message.left_chat_member
    if not member:
        return

    name = member.first_name
    uid = member.id
    mention = f"<a href='tg://user?id={uid}'>{name}</a>"
    time = update.message.date.strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"⛔️ <b>ထွက်သွားပြီးပေါ့</b>\n"
        f"<b>နှစ်တစ်ထောင် Fa ဖြစ်ပါစေ။</b>\n\n"
        f"👤 Name: {mention}\n"
        f"🆔 User ID: {uid}\n"
        f"⏰ Left at: {time}"
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
    if update.effective_user.id != OWNER_ID:
        return

    text = " ".join(context.args)
    if not text:
        return

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
    if not update.message or not update.message.text:
        return

    text = update.message.text.lower()

    if "http://" in text or "https://" in text or "t.me/" in text:
        try:
            await update.message.delete()

            warn = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"⚠️ ({update.effective_user.first_name}) "
                    "မင်းရဲ့စာကိုဖျက်လိုက်ပါပြီ。\n"
                    "အကြောင်းပြချက်: 🔗 links ပိုလိုမရပါဘူး။"
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
    chat_id = update.effective_chat.id
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])

    db_add_filter(chat_id, keyword, reply)
    
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ထည့်နိုင်ပါတယ်")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage:\n/filter <keyword> <reply>")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])

    await update.message.reply_text(
        f"✅ Filter added\n🔑 Keyword: {keyword}"
    )

# ===============================
# REMOVE FILTER (ADMIN ONLY)
# ===============================
async def remove_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ဖျက်နိုင်ပါတယ်")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage:\n/stop <keyword>")
        return

    chat_id = update.effective_chat.id
    keyword = context.args[0].lower()

    remove_filter(chat_id, keyword)
    await update.message.reply_text(f"🗑 Filter removed: {keyword}")

# ===============================
# LIST FILTERS (ADMIN ONLY)
# ===============================
async def list_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Admin / Owner ပဲ Filter ကြည့်နိုင်ပါတယ်")
        return

    if not FILTERS:
        await update.message.reply_text("📭 No active filters")
        return

    text = "📌 <b>Active Filters:</b>\n\n"
    for k in FILTERS:
        text += f"• {k}\n"

    await update.message.reply_text(text, parse_mode="HTML")

# ===============================
# AUTO FILTER (REPLY)
# ===============================
async def auto_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    chat_id = update.effective_chat.id

    filters = db_get_filters(chat_id)
    for keyword, reply in filters:
        if keyword in text:
            await update.message.reply_text(reply)
            break

# ===============================
# MAIN
# ===============================
def main():
    init_db()   # ⭐ ဒီလိုင်း မဖြစ်မနေလိုပါတယ်
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # 👋 join / leave
    app.add_handler(
    MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, track_group)
)
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye))

    # 🧠 filter commands
    app.add_handler(CommandHandler("filter", cmd_add_filter))
    app.add_handler(CommandHandler("stop", remove_filter))
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

if __name__ == "__main__":
    main()