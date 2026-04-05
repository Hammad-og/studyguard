#!/usr/bin/env python3
"""
📚 StudyGuard Bot v4.0 - Rose Edition
Compatible with python-telegram-bot 13.15
Fixes: setwelcome, unwarn, sticker filters, welcome video/username/id
New: /afk, AFK auto-detection, rich welcome with video/photo, section-divided topics
"""

import os
import json
import re
import logging
import time
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, ParseMode
)
from telegram.error import (
    TelegramError, Unauthorized, BadRequest,
    TimedOut, NetworkError, ChatMigrated, RetryAfter
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler,
    Filters, CallbackContext
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  DATA STORE
# ─────────────────────────────────────────────
data = {
    "warns":        {},   # {chat_id: {user_id: count}}
    "study_mode":   {},   # {chat_id: bool}
    "welcome_msgs": {},   # {chat_id: {"text": str, "media": str|None, "media_type": "photo"|"video"|None}}
    "welcome_off":  {},   # {chat_id: bool}
    "filters":      {},   # {chat_id: {keyword: {"response": str|None, "is_sticker": bool, "sticker_id": str|None}}}
    "points":       {},   # {chat_id: {user_id: int}}
    "user_names":   {},   # {user_id: str}
    "afk":          {},   # {user_id: {"reason": str, "time": str}}
}

DATA_FILE = "studybot_data.json"

def load_data():
    global data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                loaded = json.load(f)
                for k in data:
                    if k in loaded:
                        data[k] = loaded[k]
            logger.info("Data loaded.")
        except Exception as e:
            logger.error(f"load_data: {e}")

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"save_data: {e}")

# ─────────────────────────────────────────────
#  STUDY DETECTION
# ─────────────────────────────────────────────
NON_STUDY_PATTERNS = [
    r"^\s*(hi|hello|hey|hii+|helo|sup|yo)\s*[!.]*\s*$",
    r"^\s*(lol|lmao|lmfao|rofl|haha|hehe)\s*$",
    r"^\s*(ok|okay|k|kk|kkk)\s*[!.]*\s*$",
    r"^\s*(bye|gn|gm|good night|good morning)\s*[!.]*\s*$",
    r"^\s*(yes|no|yeah|nah|nope|yep)\s*[!.]*\s*$",
]

STUDY_KEYWORDS = [
    "help","question","doubt","explain","how","what","why","when",
    "where","problem","solve","answer","exam","test","notes","study",
    "homework","assignment","lecture","concept","formula","definition",
    "chapter","topic","revision","practice","pdf","book","link",
    "resource","material","class","quiz"
]

def is_non_study_msg(text: str) -> bool:
    t = text.lower().strip()
    for kw in STUDY_KEYWORDS:
        if kw in t:
            return False
    for p in NON_STUDY_PATTERNS:
        if re.match(p, t, re.IGNORECASE):
            return True
    if len(text.split()) <= 3 and not any(kw in t for kw in STUDY_KEYWORDS):
        if not any(c.isdigit() for c in text):
            return True
    return False

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def cid(update: Update) -> str:
    return str(update.effective_chat.id)

def ensure_chat(d: dict, chat_id: str):
    if chat_id not in d:
        d[chat_id] = {}

def add_points(chat_id: str, user_id: str, pts: int = 1):
    ensure_chat(data["points"], chat_id)
    data["points"][chat_id][user_id] = data["points"][chat_id].get(user_id, 0) + pts

def is_admin(update: Update, context: CallbackContext, user_id: int = None) -> bool:
    uid = user_id or update.effective_user.id
    try:
        m = context.bot.get_chat_member(update.effective_chat.id, uid)
        return m.status in ("administrator", "creator")
    except Exception as e:
        logger.warning(f"is_admin: {e}")
        return False

def admin_only(update: Update, context: CallbackContext) -> bool:
    if not is_admin(update, context):
        safe_reply(update, "🚫 *Admin only command!*")
        return False
    return True

def user_mention(user) -> str:
    name = (user.first_name or "User").replace("[","").replace("]","")
    return f"[{name}](tg://user?id={user.id})"

def get_thread_id(update: Update):
    chat = update.effective_chat
    msg  = update.effective_message
    if getattr(chat, "is_forum", False):
        return getattr(msg, "message_thread_id", None)
    return None

def safe_reply(update: Update, text: str, reply_markup=None, **kwargs):
    try:
        msg = update.effective_message
        chat = update.effective_chat
        thread_id = get_thread_id(update)
        kw = {"parse_mode": ParseMode.MARKDOWN}
        if reply_markup:
            kw["reply_markup"] = reply_markup
        if thread_id and getattr(chat, "is_forum", False):
            kw["message_thread_id"] = thread_id
            chat.send_message(text=text, **kw)
        else:
            msg.reply_text(text, **kw)
    except RetryAfter as e:
        time.sleep(e.retry_after + 1)
    except (Unauthorized, BadRequest) as e:
        logger.warning(f"safe_reply: {e}")
    except Exception as e:
        logger.error(f"safe_reply: {e}")

def safe_delete(message):
    try:
        message.delete()
    except Exception as e:
        logger.warning(f"safe_delete: {e}")

def safe_send(context: CallbackContext, chat_id, text: str, thread_id=None, **kwargs):
    try:
        kw = {"parse_mode": ParseMode.MARKDOWN, **kwargs}
        if thread_id:
            kw["message_thread_id"] = thread_id
        return context.bot.send_message(chat_id=chat_id, text=text, **kw)
    except RetryAfter as e:
        time.sleep(e.retry_after + 1)
    except Exception as e:
        logger.error(f"safe_send: {e}")
    return None

# ─────────────────────────────────────────────
#  ERROR HANDLER
# ─────────────────────────────────────────────
def error_handler(update: object, context: CallbackContext):
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"Network/timeout: {err}")
    elif isinstance(err, RetryAfter):
        logger.warning(f"Rate limited: {err.retry_after}s")
    elif isinstance(err, ChatMigrated):
        logger.info(f"Chat migrated: {err.new_chat_id}")
    elif isinstance(err, Unauthorized):
        logger.info(f"Unauthorized: {err}")
    elif isinstance(err, BadRequest):
        logger.warning(f"BadRequest: {err}")
    else:
        logger.error(f"Unhandled: {err}", exc_info=context.error)

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    try:
        bu = context.bot.username
        kb = [
            [
                InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bu}?startgroup=true&admin=delete_messages+restrict_members+ban_users"),
                InlineKeyboardButton("📖 Commands", callback_data="show_commands"),
            ],
            [
                InlineKeyboardButton("📊 Leaderboard", callback_data="show_leaderboard"),
                InlineKeyboardButton("ℹ️ About", callback_data="show_about"),
            ],
        ]
        text = (
            "📚 *Welcome to StudyGuard Bot v4.0!*\n\n"
            "✅ Normal groups\n✅ Supergroups\n✅ Topic / Forum groups\n\n"
            "🔹 Moderation – Warn, mute, ban, unwarn\n"
            "🔹 Study Mode – Auto-delete off-topic msgs\n"
            "🔹 Leaderboard – Reward active learners\n"
            "🔹 Filters – Text *and* sticker triggers\n"
            "🔹 AFK System – Away status tracking\n"
            "🔹 Rich Welcome – Photo/video + username/ID\n\n"
            "👇 Tap *Add to Group* to get started!"
        )
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"start: {e}")

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception:
        pass
    try:
        bu = context.bot.username
        add_btn = InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bu}?startgroup=true&admin=delete_messages+restrict_members+ban_users")
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_start")]])

        if query.data == "show_commands":
            text = (
                "📋 *All Commands*\n\n"
                "*🛡️ Moderation (Admin)*\n"
                "`/warn` – Warn user (reply)\n"
                "`/unwarn` – Remove 1 warn (reply)\n"
                "`/warns` – Check warn count\n"
                "`/resetwarn` – Reset all warns\n"
                "`/mute [10m/1h/2d]` – Mute user\n"
                "`/unmute` – Unmute user\n"
                "`/ban` – Ban from group\n"
                "`/unban @user` – Unban\n\n"
                "*📚 Study Tools (Admin)*\n"
                "`/study_mode on/off` – Toggle study mode\n"
                "`/setwelcome [msg]` – Set welcome text\n"
                "`/setwelcome off` – Disable welcome\n"
                "`/filter word [reply]` – Add text filter\n"
                "`/filtersticker word` – Add sticker filter (reply to sticker)\n"
                "`/rmfilter word` – Remove filter\n"
                "`/filters` – List all filters\n\n"
                "*💤 AFK*\n"
                "`/afk [reason]` – Go AFK\n\n"
                "*📊 Everyone*\n"
                "`/leaderboard` – Top learners\n"
                "`/report` – Report user (reply)\n"
                "`/stats` – Group statistics\n"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif query.data == "show_about":
            text = (
                "ℹ️ *StudyGuard Bot v4.0 – Rose Edition*\n\n"
                "🔸 All group types supported\n"
                "🔸 AFK system with auto-unafk\n"
                "🔸 Sticker-based filters\n"
                "🔸 Rich welcome: photo/video + user info\n"
                "🔸 Unwarn support\n"
                "🔸 Welcome on/off toggle\n\n"
                "Made with ❤️ for learners everywhere"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif query.data == "show_leaderboard":
            chat_id = str(update.effective_chat.id)
            ensure_chat(data["points"], chat_id)
            pts = data["points"][chat_id]
            if not pts:
                text = "📊 *Leaderboard*\n\nNo data yet! Start studying to earn points. 🎓"
            else:
                top = sorted(pts.items(), key=lambda x: x[1], reverse=True)[:10]
                medals = ["🥇","🥈","🥉"] + ["🏅"]*7
                lines = ["📊 *Top Learners*\n"]
                for i,(u_id,p) in enumerate(top):
                    name = data["user_names"].get(u_id, f"User{u_id[:4]}")
                    lines.append(f"{medals[i]} {name} — *{p} pts*")
                text = "\n".join(lines)
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif query.data == "back_start":
            kb = [
                [add_btn, InlineKeyboardButton("📖 Commands", callback_data="show_commands")],
                [InlineKeyboardButton("📊 Leaderboard", callback_data="show_leaderboard"),
                 InlineKeyboardButton("ℹ️ About", callback_data="show_about")],
            ]
            text = (
                "📚 *Welcome to StudyGuard Bot v4.0!*\n\n"
                "✅ Normal groups\n✅ Supergroups\n✅ Topic / Forum groups\n\n"
                "🔹 Moderation – Warn, mute, ban, unwarn\n"
                "🔹 Study Mode – Auto-delete off-topic msgs\n"
                "🔹 Leaderboard – Reward active learners\n"
                "🔹 Filters – Text *and* sticker triggers\n"
                "🔹 AFK System – Away status tracking\n"
                "🔹 Rich Welcome – Photo/video + username/ID\n\n"
                "👇 Tap *Add to Group* to get started!"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(kb))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning(f"button_handler BadRequest: {e}")
    except Exception as e:
        logger.error(f"button_handler: {e}")

# ─────────────────────────────────────────────
#  WELCOME  (fixed + rich)
# ─────────────────────────────────────────────
def _build_welcome_text(template: str, member, chat) -> str:
    """Replace placeholders with real user info."""
    name      = member.first_name or "User"
    username  = f"@{member.username}" if member.username else "No username"
    user_id   = str(member.id)
    group     = chat.title or "this group"
    count     = ""
    try:
        count = str(chat.get_member_count())
    except Exception:
        pass

    return (template
            .replace("{name}",     f"[{name}](tg://user?id={member.id})")
            .replace("{username}", username)
            .replace("{id}",       user_id)
            .replace("{group}",    group)
            .replace("{count}",    count))

def new_member(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        chat    = update.effective_chat
        thread_id = get_thread_id(update)

        # Welcome disabled?
        if data["welcome_off"].get(chat_id, False):
            return

        for member in update.message.new_chat_members:
            if member.is_bot:
                continue

            data["user_names"][str(member.id)] = member.first_name
            save_data()

            wcfg = data["welcome_msgs"].get(chat_id, {})
            template = wcfg.get("text") or (
                "👋 Welcome {name}!\n\n"
                "🆔 ID: `{id}`\n"
                "👤 Username: {username}\n\n"
                "📌 Stay focused and keep questions on-topic.\n"
                "Type /help to see available commands."
            )
            text = _build_welcome_text(template, member, chat)

            media_id   = wcfg.get("media")
            media_type = wcfg.get("media_type")

            send_kw = {"parse_mode": ParseMode.MARKDOWN}
            if thread_id:
                send_kw["message_thread_id"] = thread_id

            try:
                if media_id and media_type == "photo":
                    context.bot.send_photo(chat_id=chat.id, photo=media_id,
                                           caption=text, **send_kw)
                elif media_id and media_type == "video":
                    context.bot.send_video(chat_id=chat.id, video=media_id,
                                           caption=text, **send_kw)
                else:
                    context.bot.send_message(chat_id=chat.id, text=text, **send_kw)
            except Exception as e:
                logger.warning(f"new_member send: {e}")

    except Exception as e:
        logger.error(f"new_member: {e}")


def setwelcome(update: Update, context: CallbackContext):
    """
    /setwelcome off                      – disable welcome
    /setwelcome <text>                   – set text welcome
    /setwelcome <text> (reply to photo/video) – set media welcome
    Placeholders: {name} {username} {id} {group} {count}
    """
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)

        full_text = " ".join(context.args) if context.args else ""

        # /setwelcome off
        if full_text.strip().lower() == "off":
            data["welcome_off"][chat_id] = True
            save_data()
            safe_reply(update, "✅ Welcome message *disabled*. Use `/setwelcome <text>` to re-enable.")
            return

        # Re-enable if was off
        data["welcome_off"][chat_id] = False

        if not full_text:
            safe_reply(update,
                "Usage:\n"
                "`/setwelcome Hello {name}!` – text welcome\n"
                "`/setwelcome off` – disable welcome\n\n"
                "Placeholders: `{name}` `{username}` `{id}` `{group}` `{count}`\n"
                "Reply to a photo/video while using this command to set media welcome."
            )
            return

        # Check for replied media
        replied = update.message.reply_to_message
        media_id   = None
        media_type = None

        if replied:
            if replied.photo:
                media_id   = replied.photo[-1].file_id
                media_type = "photo"
            elif replied.video:
                media_id   = replied.video.file_id
                media_type = "video"

        ensure_chat(data["welcome_msgs"], chat_id)
        data["welcome_msgs"][chat_id] = {
            "text":       full_text,
            "media":      media_id,
            "media_type": media_type,
        }
        save_data()

        mtype_str = f" + {media_type}" if media_type else ""
        safe_reply(update,
            f"✅ Welcome message set{mtype_str}!\n\n"
            f"Preview text:\n{full_text}"
        )
    except Exception as e:
        logger.error(f"setwelcome: {e}")

# ─────────────────────────────────────────────
#  WARN / UNWARN
# ─────────────────────────────────────────────
def warn(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to warn them.")
            return
        if is_admin(update, context, target.id):
            safe_reply(update, "🚫 Cannot warn an admin.")
            return

        ensure_chat(data["warns"], chat_id)
        t_id = str(target.id)
        data["warns"][chat_id][t_id] = data["warns"][chat_id].get(t_id, 0) + 1
        wc = data["warns"][chat_id][t_id]
        save_data()

        if wc >= 3:
            try:
                context.bot.ban_chat_member(update.effective_chat.id, target.id)
            except TelegramError as e:
                logger.warning(f"ban: {e}")
            data["warns"][chat_id][t_id] = 0
            save_data()
            safe_reply(update, f"🔨 {user_mention(target)} *banned* after 3 warnings!")
        else:
            safe_reply(update,
                f"⚠️ {user_mention(target)} warned!\n"
                f"Warnings: *{wc}/3*\n"
                f"_{3-wc} more = auto ban._"
            )
    except Exception as e:
        logger.error(f"warn: {e}")

def unwarn(update: Update, context: CallbackContext):
    """Remove one warning from a user."""
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to remove a warn.")
            return
        ensure_chat(data["warns"], chat_id)
        t_id = str(target.id)
        current = data["warns"][chat_id].get(t_id, 0)
        if current <= 0:
            safe_reply(update, f"✅ {user_mention(target)} has no warnings to remove.")
            return
        data["warns"][chat_id][t_id] = current - 1
        save_data()
        safe_reply(update,
            f"✅ Removed 1 warning from {user_mention(target)}.\n"
            f"Warnings now: *{current-1}/3*"
        )
    except Exception as e:
        logger.error(f"unwarn: {e}")

def warns(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
        t_id = str(target.id)
        ensure_chat(data["warns"], chat_id)
        count = data["warns"][chat_id].get(t_id, 0)
        safe_reply(update, f"📋 {user_mention(target)} has *{count}/3* warnings.")
    except Exception as e:
        logger.error(f"warns: {e}")

def resetwarn(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message.")
            return
        ensure_chat(data["warns"], chat_id)
        data["warns"][chat_id][str(target.id)] = 0
        save_data()
        safe_reply(update, f"✅ All warnings reset for {user_mention(target)}.")
    except Exception as e:
        logger.error(f"resetwarn: {e}")

# ─────────────────────────────────────────────
#  MUTE / UNMUTE
# ─────────────────────────────────────────────
def parse_duration(text: str):
    m = re.match(r"^(\d+)(m|h|d)$", text.lower())
    if not m: return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {"m":60,"h":3600,"d":86400}[unit]

def mute(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to mute them.")
            return
        if is_admin(update, context, target.id):
            safe_reply(update, "🚫 Cannot mute an admin.")
            return
        duration_sec = None
        dur_str = "indefinitely"
        if context.args:
            duration_sec = parse_duration(context.args[0])
            if duration_sec:
                dur_str = f"for {context.args[0]}"
        until = (datetime.now() + timedelta(seconds=duration_sec)) if duration_sec else None
        perms = ChatPermissions(can_send_messages=False)
        try:
            context.bot.restrict_chat_member(update.effective_chat.id, target.id, perms, until_date=until)
        except TelegramError as e:
            safe_reply(update, f"❌ Could not mute: {e}")
            return
        safe_reply(update, f"🔇 {user_mention(target)} muted *{dur_str}*.")
    except Exception as e:
        logger.error(f"mute: {e}")

def unmute(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to unmute them.")
            return
        perms = ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_polls=True, can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        try:
            context.bot.restrict_chat_member(update.effective_chat.id, target.id, perms)
        except TelegramError as e:
            safe_reply(update, f"❌ Could not unmute: {e}")
            return
        safe_reply(update, f"🔊 {user_mention(target)} unmuted.")
    except Exception as e:
        logger.error(f"unmute: {e}")

# ─────────────────────────────────────────────
#  BAN / UNBAN
# ─────────────────────────────────────────────
def ban(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to ban them.")
            return
        if is_admin(update, context, target.id):
            safe_reply(update, "🚫 Cannot ban an admin.")
            return
        try:
            context.bot.ban_chat_member(update.effective_chat.id, target.id)
        except TelegramError as e:
            safe_reply(update, f"❌ Could not ban: {e}")
            return
        safe_reply(update, f"🔨 {user_mention(target)} *banned*.")
    except Exception as e:
        logger.error(f"ban: {e}")

def unban(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        if not context.args:
            safe_reply(update, "Usage: `/unban @username`")
            return
        username = context.args[0].lstrip("@")
        try:
            user = context.bot.get_chat(f"@{username}")
            context.bot.unban_chat_member(update.effective_chat.id, user.id)
            safe_reply(update, f"✅ @{username} unbanned.")
        except TelegramError as e:
            safe_reply(update, f"❌ Failed: {e}")
    except Exception as e:
        logger.error(f"unban: {e}")

# ─────────────────────────────────────────────
#  STUDY MODE
# ─────────────────────────────────────────────
def study_mode(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args or context.args[0].lower() not in ("on","off"):
            status = "🟢 ON" if data["study_mode"].get(chat_id, False) else "🔴 OFF"
            safe_reply(update, f"📚 Study Mode: *{status}*\nUsage: `/study_mode on` or `/study_mode off`")
            return
        enable = context.args[0].lower() == "on"
        data["study_mode"][chat_id] = enable
        save_data()
        if enable:
            safe_reply(update, "📚 *Study Mode ENABLED!*\n\nOff-topic messages will be auto-deleted. 🎯")
        else:
            safe_reply(update, "📖 *Study Mode DISABLED.*")
    except Exception as e:
        logger.error(f"study_mode: {e}")

# ─────────────────────────────────────────────
#  FILTERS  (text + sticker)
# ─────────────────────────────────────────────
def add_filter(update: Update, context: CallbackContext):
    """
    /filter word [reply text]   – text filter
    """
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args:
            safe_reply(update,
                "Usage:\n"
                "`/filter spam` – auto-delete msgs with 'spam'\n"
                "`/filter doubt Check the pinned post!` – auto-reply\n"
                "`/filtersticker triggerword` – reply to a sticker to set sticker filter"
            )
            return
        ensure_chat(data["filters"], chat_id)
        keyword  = context.args[0].lower()
        response = " ".join(context.args[1:]) if len(context.args) > 1 else None
        data["filters"][chat_id][keyword] = {
            "response":   response,
            "is_sticker": False,
            "sticker_id": None,
        }
        save_data()
        action = f'reply: "{response}"' if response else "delete the message"
        safe_reply(update, f"✅ Filter set!\n`{keyword}` → {action}")
    except Exception as e:
        logger.error(f"add_filter: {e}")

def filter_sticker(update: Update, context: CallbackContext):
    """
    Reply to a sticker + /filtersticker triggerword
    Bot will send that sticker whenever triggerword appears.
    """
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args:
            safe_reply(update, "Usage: Reply to a sticker with `/filtersticker triggerword`")
            return
        replied = update.message.reply_to_message
        if not replied or not replied.sticker:
            safe_reply(update, "↩️ Reply to a sticker with this command.")
            return
        keyword    = context.args[0].lower()
        sticker_id = replied.sticker.file_id
        ensure_chat(data["filters"], chat_id)
        data["filters"][chat_id][keyword] = {
            "response":   None,
            "is_sticker": True,
            "sticker_id": sticker_id,
        }
        save_data()
        safe_reply(update, f"✅ Sticker filter set!\n`{keyword}` → 🎭 sticker reply")
    except Exception as e:
        logger.error(f"filter_sticker: {e}")

def rm_filter(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args:
            safe_reply(update, "Usage: `/rmfilter keyword`")
            return
        keyword = context.args[0].lower()
        ensure_chat(data["filters"], chat_id)
        if keyword in data["filters"][chat_id]:
            del data["filters"][chat_id][keyword]
            save_data()
            safe_reply(update, f"✅ Filter `{keyword}` removed.")
        else:
            safe_reply(update, f"❌ No filter for `{keyword}`.")
    except Exception as e:
        logger.error(f"rm_filter: {e}")

def list_filters(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        ensure_chat(data["filters"], chat_id)
        fd = data["filters"][chat_id]
        if not fd:
            safe_reply(update, "No filters set yet.")
            return
        lines = ["🔍 *Active Filters:*\n"]
        for kw, cfg in fd.items():
            if cfg.get("is_sticker"):
                lines.append(f"• `{kw}` → 🎭 sticker")
            elif cfg.get("response"):
                lines.append(f"• `{kw}` → \"{cfg['response']}\"")
            else:
                lines.append(f"• `{kw}` → delete")
        safe_reply(update, "\n".join(lines))
    except Exception as e:
        logger.error(f"list_filters: {e}")

# ─────────────────────────────────────────────
#  AFK SYSTEM
# ─────────────────────────────────────────────
def afk_cmd(update: Update, context: CallbackContext):
    """
    /afk [reason]
    """
    try:
        user = update.effective_user
        u_id = str(user.id)
        reason = " ".join(context.args) if context.args else "AFK"
        data["afk"][u_id] = {
            "reason": reason,
            "time":   datetime.now().strftime("%H:%M"),
        }
        save_data()
        safe_reply(update,
            f"💤 {user_mention(user)} is now *AFK*\n"
            f"Reason: _{reason}_"
        )
    except Exception as e:
        logger.error(f"afk_cmd: {e}")

def _unafk(user, update: Update, context: CallbackContext):
    u_id = str(user.id)
    if u_id not in data["afk"]:
        return
    afk_info = data["afk"].pop(u_id)
    save_data()
    try:
        safe_reply(update,
            f"👋 Welcome back {user_mention(user)}!\n"
            f"You were AFK since *{afk_info.get('time','?')}*\n"
            f"Reason was: _{afk_info.get('reason','AFK')}_"
        )
    except Exception:
        pass

# ─────────────────────────────────────────────
#  LEADERBOARD
# ─────────────────────────────────────────────
def leaderboard(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        ensure_chat(data["points"], chat_id)
        pts = data["points"][chat_id]
        if not pts:
            safe_reply(update, "📊 No data yet! Send study messages to earn points. 🎓")
            return
        top = sorted(pts.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇","🥈","🥉"] + ["🏅"]*7
        lines = ["📊 *Top Learners Leaderboard*\n"]
        for i,(u_id,p) in enumerate(top):
            name = data["user_names"].get(u_id, f"User{u_id[:4]}")
            lines.append(f"{medals[i]} *{i+1}.* {name} — `{p} pts`")
        safe_reply(update, "\n".join(lines))
    except Exception as e:
        logger.error(f"leaderboard: {e}")

# ─────────────────────────────────────────────
#  REPORT
# ─────────────────────────────────────────────
def report(update: Update, context: CallbackContext):
    try:
        reporter = update.effective_user
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to a message to report that user.")
            return
        if target.id == reporter.id:
            safe_reply(update, "😅 You can't report yourself!")
            return
        try:
            admins = update.effective_chat.get_administrators()
        except TelegramError as e:
            safe_reply(update, "❌ Could not fetch admin list.")
            return
        msg = (
            f"🚨 *Report Alert!*\n\n"
            f"👤 Reporter: {user_mention(reporter)}\n"
            f"🎯 Reported: {user_mention(target)}\n"
            f"📍 Chat: {update.effective_chat.title}\n"
            f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        notified = 0
        for admin in admins:
            if not admin.user.is_bot:
                try:
                    context.bot.send_message(admin.user.id, msg, parse_mode=ParseMode.MARKDOWN)
                    notified += 1
                except Exception:
                    pass
        safe_reply(update, f"✅ Report sent to *{notified}* admin(s). Thank you!")
    except Exception as e:
        logger.error(f"report: {e}")

# ─────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────
def stats(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        chat    = update.effective_chat
        ensure_chat(data["points"],  chat_id)
        ensure_chat(data["warns"],   chat_id)
        ensure_chat(data["filters"], chat_id)

        total_users   = len(data["points"][chat_id])
        total_warns   = sum(data["warns"][chat_id].values())
        total_filters = len(data["filters"][chat_id])
        afk_count     = len(data["afk"])
        study         = "🟢 ON"  if data["study_mode"].get(chat_id, False) else "🔴 OFF"
        welcome       = "🔴 OFF" if data["welcome_off"].get(chat_id, False) else "🟢 ON"
        is_forum      = "✅ Yes" if getattr(chat, "is_forum", False)         else "❌ No"

        safe_reply(update,
            f"📈 *Group Statistics*\n\n"
            f"👥 Active learners: *{total_users}*\n"
            f"⚠️ Total warnings: *{total_warns}*\n"
            f"🔍 Active filters: *{total_filters}*\n"
            f"💤 AFK users: *{afk_count}*\n"
            f"📚 Study Mode: *{study}*\n"
            f"👋 Welcome: *{welcome}*\n"
            f"🗂 Topic group: *{is_forum}*\n"
            f"📌 Group: *{chat.title}*"
        )
    except Exception as e:
        logger.error(f"stats: {e}")

# ─────────────────────────────────────────────
#  HELP
# ─────────────────────────────────────────────
def help_cmd(update: Update, context: CallbackContext):
    try:
        text = (
            "📋 *StudyGuard Bot v4.0 Commands*\n\n"
            "*🛡️ Moderation (Admins Only)*\n"
            "`/warn` – Warn user _(reply)_\n"
            "`/unwarn` – Remove 1 warn _(reply)_\n"
            "`/warns` – Check warn count\n"
            "`/resetwarn` – Reset all warns\n"
            "`/mute [10m/1h/2d]` – Mute user\n"
            "`/unmute` – Unmute user\n"
            "`/ban` – Ban from group\n"
            "`/unban @user` – Unban\n\n"
            "*📚 Study Tools (Admins)*\n"
            "`/study_mode on|off` – Toggle study mode\n"
            "`/setwelcome <msg>` – Set welcome\n"
            "`/setwelcome off` – Disable welcome\n"
            "_Placeholders: {name} {username} {id} {group} {count}_\n"
            "_Reply to photo/video to attach media_\n\n"
            "`/filter word [reply]` – Add text filter\n"
            "`/filtersticker word` – Add sticker filter _(reply to sticker)_\n"
            "`/rmfilter word` – Remove filter\n"
            "`/filters` – List all filters\n\n"
            "*💤 AFK*\n"
            "`/afk [reason]` – Go AFK\n\n"
            "*📊 Everyone*\n"
            "`/leaderboard` – Top learners\n"
            "`/report` – Report user _(reply)_\n"
            "`/stats` – Group statistics\n"
            "`/start` – Main menu\n"
        )
        safe_reply(update, text)
    except Exception as e:
        logger.error(f"help_cmd: {e}")

# ─────────────────────────────────────────────
#  MESSAGE HANDLER (text + sticker)
# ─────────────────────────────────────────────
def handle_message(update: Update, context: CallbackContext):
    try:
        msg  = update.message
        if not msg:
            return
        chat_id = cid(update)
        user    = update.effective_user
        if not user:
            return

        u_id = str(user.id)
        data["user_names"][u_id] = user.first_name

        # ── AFK: sender just sent a message → unafk ──
        if u_id in data["afk"]:
            _unafk(user, update, context)

        # ── AFK: someone mentioned an AFK user ──
        if msg.text and msg.entities:
            for entity in msg.entities:
                if entity.type in ("mention", "text_mention"):
                    if entity.type == "text_mention" and entity.user:
                        m_uid = str(entity.user.id)
                    else:
                        # @username mention — skip (can't resolve without API call risk)
                        continue
                    if m_uid in data["afk"]:
                        afk_info = data["afk"][m_uid]
                        name = data["user_names"].get(m_uid, "That user")
                        safe_reply(update,
                            f"💤 *{name}* is AFK since {afk_info.get('time','?')}\n"
                            f"Reason: _{afk_info.get('reason','AFK')}_"
                        )

        text       = msg.text or ""
        text_lower = text.lower()

        # ── Filters (text) ──
        ensure_chat(data["filters"], chat_id)
        for keyword, cfg in data["filters"][chat_id].items():
            if keyword in text_lower:
                if cfg.get("is_sticker") and cfg.get("sticker_id"):
                    thread_id = get_thread_id(update)
                    kw = {}
                    if thread_id:
                        kw["message_thread_id"] = thread_id
                    try:
                        context.bot.send_sticker(
                            chat_id=update.effective_chat.id,
                            sticker=cfg["sticker_id"],
                            **kw
                        )
                    except Exception as e:
                        logger.warning(f"sticker filter send: {e}")
                elif cfg.get("response"):
                    safe_reply(update, cfg["response"])
                else:
                    safe_delete(msg)
                return

        # ── Study mode ──
        if data["study_mode"].get(chat_id, False) and text:
            if not is_admin(update, context) and is_non_study_msg(text):
                safe_delete(msg)
                chat      = update.effective_chat
                thread_id = get_thread_id(update)
                notice = safe_send(
                    context,
                    chat_id=chat.id,
                    text=f"📚 {user_mention(user)} — *Study mode ON!* Keep it study-related. 🎯",
                    thread_id=thread_id
                )
                if notice:
                    try:
                        context.job_queue.run_once(
                            lambda ctx: ctx.bot.delete_message(chat.id, notice.message_id),
                            5
                        )
                    except Exception as e:
                        logger.warning(f"job_queue: {e}")
                return

        # ── Award points ──
        if text and (any(kw in text_lower for kw in STUDY_KEYWORDS) or len(text.split()) >= 5):
            ensure_chat(data["points"], chat_id)
            add_points(chat_id, u_id, 1)
            save_data()

    except Exception as e:
        logger.error(f"handle_message: {e}")

# ─────────────────────────────────────────────
#  STICKER HANDLER
# ─────────────────────────────────────────────
def handle_sticker(update: Update, context: CallbackContext):
    """Delete stickers in study mode (admins exempt)."""
    try:
        msg = update.message
        if not msg:
            return
        chat_id = cid(update)
        user    = update.effective_user
        if not user:
            return

        u_id = str(user.id)
        data["user_names"][u_id] = user.first_name

        # AFK: sending anything counts as coming back
        if u_id in data["afk"]:
            _unafk(user, update, context)

        if data["study_mode"].get(chat_id, False):
            if not is_admin(update, context):
                safe_delete(msg)
                chat      = update.effective_chat
                thread_id = get_thread_id(update)
                notice = safe_send(
                    context,
                    chat_id=chat.id,
                    text=f"📚 {user_mention(user)} — *Study mode ON!* No stickers allowed. 🎯",
                    thread_id=thread_id
                )
                if notice:
                    try:
                        context.job_queue.run_once(
                            lambda ctx: ctx.bot.delete_message(chat.id, notice.message_id),
                            5
                        )
                    except Exception as e:
                        logger.warning(f"job_queue sticker notice: {e}")
    except Exception as e:
        logger.error(f"handle_sticker: {e}")

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    load_data()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("❌ ERROR: Set BOT_TOKEN environment variable!")
        return

    updater = Updater(
        token,
        use_context=True,
        request_kwargs={"read_timeout": 30, "connect_timeout": 30}
    )
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start",          start))
    dp.add_handler(CommandHandler("help",           help_cmd))
    dp.add_handler(CommandHandler("warn",           warn))
    dp.add_handler(CommandHandler("unwarn",         unwarn))
    dp.add_handler(CommandHandler("warns",          warns))
    dp.add_handler(CommandHandler("resetwarn",      resetwarn))
    dp.add_handler(CommandHandler("mute",           mute))
    dp.add_handler(CommandHandler("unmute",         unmute))
    dp.add_handler(CommandHandler("ban",            ban))
    dp.add_handler(CommandHandler("unban",          unban))
    dp.add_handler(CommandHandler("study_mode",     study_mode))
    dp.add_handler(CommandHandler("setwelcome",     setwelcome))
    dp.add_handler(CommandHandler("filter",         add_filter))
    dp.add_handler(CommandHandler("filtersticker",  filter_sticker))
    dp.add_handler(CommandHandler("rmfilter",       rm_filter))
    dp.add_handler(CommandHandler("filters",        list_filters))
    dp.add_handler(CommandHandler("leaderboard",    leaderboard))
    dp.add_handler(CommandHandler("report",         report))
    dp.add_handler(CommandHandler("stats",          stats))
    dp.add_handler(CommandHandler("afk",            afk_cmd))

    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_member))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.sticker, handle_sticker))

    dp.add_error_handler(error_handler)

    print("🚀 StudyGuard Bot v4.0 (Rose Edition) is running!")
    updater.start_polling(
        drop_pending_updates=True,
        timeout=30,
        allowed_updates=["message", "callback_query", "chat_member"]
    )
    updater.idle()

if __name__ == "__main__":
    main()
