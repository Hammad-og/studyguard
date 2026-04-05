#!/usr/bin/env python3
"""
📚 StudyGuard Bot v3.1 - Crash-resistant build
Compatible with python-telegram-bot 13.15
Works in ALL group types: normal, supergroups, topic/forum groups
"""

import os
import json
import re
import logging
import time
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ParseMode
)
from telegram.error import (
    TelegramError, Unauthorized, BadRequest, TimedOut, NetworkError, ChatMigrated, RetryAfter
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
    "warns":        {},
    "study_mode":   {},
    "welcome_msgs": {},
    "filters":      {},
    "points":       {},
    "user_names":   {},
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
            logger.info("Data loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load data: {e}")

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save data: {e}")

# ─────────────────────────────────────────────
#  NON-STUDY PATTERNS
# ─────────────────────────────────────────────
NON_STUDY_PATTERNS = [
    r"^\s*(hi|hello|hey|hii+|helo|sup|yo)\s*[!.]*\s*$",
    r"^\s*(lol|lmao|lmfao|rofl|haha|hehe)\s*$",
    r"^\s*(ok|okay|k|kk|kkk)\s*[!.]*\s*$",
    r"^\s*(bye|gn|gm|good night|good morning)\s*[!.]*\s*$",
    r"^\s*(yes|no|yeah|nah|nope|yep)\s*[!.]*\s*$",
]

STUDY_KEYWORDS = [
    "help", "question", "doubt", "explain", "how", "what", "why", "when",
    "where", "problem", "solve", "answer", "exam", "test", "notes", "study",
    "homework", "assignment", "lecture", "concept", "formula", "definition",
    "chapter", "topic", "revision", "practice", "pdf", "book", "link",
    "resource", "material", "class", "quiz"
]

def is_non_study_msg(text: str) -> bool:
    text_lower = text.lower().strip()
    for kw in STUDY_KEYWORDS:
        if kw in text_lower:
            return False
    for pattern in NON_STUDY_PATTERNS:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True
    if len(text.split()) <= 3 and not any(kw in text_lower for kw in STUDY_KEYWORDS):
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
    uid_check = user_id or update.effective_user.id
    try:
        member = context.bot.get_chat_member(update.effective_chat.id, uid_check)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.warning(f"is_admin check failed: {e}")
        return False

def admin_only(update: Update, context: CallbackContext) -> bool:
    if not is_admin(update, context):
        safe_reply(update, "🚫 *Admin only command!*")
        return False
    return True

def user_mention(user) -> str:
    name = (user.first_name or "User").replace("[", "").replace("]", "")
    return f"[{name}](tg://user?id={user.id})"

def safe_reply(update: Update, text: str, **kwargs):
    """Send a reply safely — catches all Telegram errors."""
    try:
        chat = update.effective_chat
        message = update.effective_message
        is_forum = getattr(chat, "is_forum", False)
        thread_id = getattr(message, "message_thread_id", None) if is_forum else None

        send_kwargs = {"parse_mode": ParseMode.MARKDOWN, **kwargs}
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id

        if is_forum and thread_id:
            chat.send_message(text=text, **send_kwargs)
        else:
            message.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except RetryAfter as e:
        logger.warning(f"Rate limited. Sleeping {e.retry_after}s")
        time.sleep(e.retry_after + 1)
    except (Unauthorized, BadRequest) as e:
        logger.warning(f"safe_reply error (non-fatal): {e}")
    except TelegramError as e:
        logger.error(f"safe_reply TelegramError: {e}")
    except Exception as e:
        logger.error(f"safe_reply unexpected error: {e}")

def safe_delete(message):
    """Delete a message safely."""
    try:
        message.delete()
    except (BadRequest, Unauthorized) as e:
        logger.warning(f"Could not delete message: {e}")
    except TelegramError as e:
        logger.warning(f"safe_delete TelegramError: {e}")
    except Exception as e:
        logger.warning(f"safe_delete unexpected: {e}")

def safe_send(context: CallbackContext, chat_id, text: str, thread_id=None, **kwargs):
    """Send a new message safely."""
    try:
        send_kwargs = {"parse_mode": ParseMode.MARKDOWN, **kwargs}
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id
        return context.bot.send_message(chat_id=chat_id, text=text, **send_kwargs)
    except RetryAfter as e:
        logger.warning(f"Rate limited. Sleeping {e.retry_after}s")
        time.sleep(e.retry_after + 1)
    except (Unauthorized, BadRequest) as e:
        logger.warning(f"safe_send error (non-fatal): {e}")
    except TelegramError as e:
        logger.error(f"safe_send TelegramError: {e}")
    except Exception as e:
        logger.error(f"safe_send unexpected error: {e}")
    return None

# ─────────────────────────────────────────────
#  ERROR HANDLER (global)
# ─────────────────────────────────────────────
def error_handler(update: object, context: CallbackContext):
    """Global error handler — logs everything without crashing."""
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning(f"Network/timeout error (will retry): {err}")
    elif isinstance(err, RetryAfter):
        logger.warning(f"Rate limited: retry after {err.retry_after}s")
    elif isinstance(err, ChatMigrated):
        logger.info(f"Chat migrated to supergroup: {err.new_chat_id}")
    elif isinstance(err, Unauthorized):
        logger.info(f"Unauthorized (bot removed or blocked): {err}")
    elif isinstance(err, BadRequest):
        logger.warning(f"BadRequest: {err}")
    else:
        logger.error(f"Unhandled error: {err}", exc_info=context.error)

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    try:
        bot_username = context.bot.username
        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ Add to Any Group",
                    url=f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+restrict_members+ban_users"
                ),
                InlineKeyboardButton("📖 Commands", callback_data="show_commands"),
            ],
            [
                InlineKeyboardButton("📊 Leaderboard", callback_data="show_leaderboard"),
                InlineKeyboardButton("ℹ️ About", callback_data="show_about"),
            ],
        ]
        text = (
            "📚 *Welcome to StudyGuard Bot!*\n\n"
            "I work in *all Telegram group types*:\n"
            "✅ Normal groups\n"
            "✅ Supergroups\n"
            "✅ Topic / Forum groups\n\n"
            "🔹 *Moderation* – Warn, mute, ban\n"
            "🔹 *Study Mode* – Auto-delete off-topic msgs\n"
            "🔹 *Leaderboard* – Reward active learners\n"
            "🔹 *Filters* – Auto-reply or delete keywords\n"
            "🔹 *Reports* – Flag bad actors to admins\n\n"
            "👇 Tap *Add to Any Group* to get started!"
        )
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"/start error: {e}")

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception:
        pass

    try:
        bot_username = context.bot.username
        add_btn = InlineKeyboardButton(
            "➕ Add to Any Group",
            url=f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+restrict_members+ban_users"
        )
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="back_start")]])

        if query.data == "show_commands":
            text = (
                "📋 *All Commands*\n\n"
                "*🛡️ Moderation (Admin)*\n"
                "`/warn` – Warn user (reply to msg)\n"
                "`/warns` – Check warn count\n"
                "`/resetwarn` – Reset warns\n"
                "`/mute [10m/1h/2d]` – Mute user\n"
                "`/unmute` – Unmute user\n"
                "`/ban` – Ban from group\n"
                "`/unban @user` – Unban\n\n"
                "*📚 Study Tools (Admin)*\n"
                "`/study_mode on/off` – Toggle study mode\n"
                "`/setwelcome [msg]` – Custom welcome\n"
                "`/filter word [reply]` – Add filter\n"
                "`/rmfilter word` – Remove filter\n"
                "`/filters` – List all filters\n\n"
                "*📊 Everyone*\n"
                "`/leaderboard` – Top learners\n"
                "`/report` – Report user (reply to msg)\n"
                "`/stats` – Group statistics\n"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_markup)

        elif query.data == "show_about":
            text = (
                "ℹ️ *About StudyGuard Bot v3.1*\n\n"
                "🔸 Works in ALL Telegram group types\n"
                "🔸 Topic/Forum group support built-in\n"
                "🔸 Smart study mode filters casual chat\n"
                "🔸 Point system rewards active learners\n"
                "🔸 Full moderation suite for admins\n"
                "🔸 Customizable filters & welcome messages\n\n"
                "Made with ❤️ for learners everywhere"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_markup)

        elif query.data == "show_leaderboard":
            chat_id = str(update.effective_chat.id)
            ensure_chat(data["points"], chat_id)
            pts = data["points"][chat_id]
            if not pts:
                text = "📊 *Leaderboard*\n\nNo data yet! Start studying to earn points. 🎓"
            else:
                sorted_users = sorted(pts.items(), key=lambda x: x[1], reverse=True)[:10]
                medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
                lines = ["📊 *Top Learners*\n"]
                for i, (u_id, p) in enumerate(sorted_users):
                    name = data["user_names"].get(u_id, f"User{u_id[:4]}")
                    lines.append(f"{medals[i]} {name} — *{p} pts*")
                text = "\n".join(lines)
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_markup)

        elif query.data == "back_start":
            keyboard = [
                [
                    add_btn,
                    InlineKeyboardButton("📖 Commands", callback_data="show_commands"),
                ],
                [
                    InlineKeyboardButton("📊 Leaderboard", callback_data="show_leaderboard"),
                    InlineKeyboardButton("ℹ️ About", callback_data="show_about"),
                ],
            ]
            text = (
                "📚 *Welcome to StudyGuard Bot!*\n\n"
                "I work in *all Telegram group types*:\n"
                "✅ Normal groups\n"
                "✅ Supergroups\n"
                "✅ Topic / Forum groups\n\n"
                "🔹 *Moderation* – Warn, mute, ban\n"
                "🔹 *Study Mode* – Auto-delete off-topic msgs\n"
                "🔹 *Leaderboard* – Reward active learners\n"
                "🔹 *Filters* – Auto-reply or delete keywords\n"
                "🔹 *Reports* – Flag bad actors to admins\n\n"
                "👇 Tap *Add to Any Group* to get started!"
            )
            query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
    except BadRequest as e:
        # "Message is not modified" is harmless — ignore it
        if "not modified" in str(e).lower():
            pass
        else:
            logger.warning(f"button_handler BadRequest: {e}")
    except Exception as e:
        logger.error(f"button_handler error: {e}")

# ─────────────────────────────────────────────
#  WELCOME
# ─────────────────────────────────────────────
def new_member(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        for member in update.message.new_chat_members:
            if member.is_bot:
                continue
            data["user_names"][str(member.id)] = member.first_name
            welcome = data["welcome_msgs"].get(chat_id)
            if welcome:
                msg = welcome.replace("{name}", f"[{member.first_name}](tg://user?id={member.id})")
            else:
                msg = (
                    f"👋 Welcome {user_mention(member)} to the study group!\n\n"
                    "📌 Stay focused, be respectful, keep questions on-topic.\n"
                    "Type /help to see available commands."
                )
            safe_reply(update, msg)
    except Exception as e:
        logger.error(f"new_member error: {e}")

def setwelcome(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args:
            safe_reply(update,
                "Usage: `/setwelcome Hello {name}, welcome!`\n"
                "Use `{name}` as placeholder for new member's name."
            )
            return
        welcome_text = " ".join(context.args)
        data["welcome_msgs"][chat_id] = welcome_text
        save_data()
        safe_reply(update, f"✅ Welcome message set!\n\n{welcome_text}")
    except Exception as e:
        logger.error(f"setwelcome error: {e}")

# ─────────────────────────────────────────────
#  WARN
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
        warn_count = data["warns"][chat_id][t_id]
        save_data()

        if warn_count >= 3:
            try:
                context.bot.ban_chat_member(update.effective_chat.id, target.id)
            except TelegramError as e:
                logger.warning(f"ban failed: {e}")
            data["warns"][chat_id][t_id] = 0
            save_data()
            safe_reply(update, f"🔨 {user_mention(target)} has been *banned* after 3 warnings!")
        else:
            safe_reply(update,
                f"⚠️ {user_mention(target)} has been warned!\n"
                f"Warnings: *{warn_count}/3*\n"
                f"_{3 - warn_count} more = auto ban._"
            )
    except Exception as e:
        logger.error(f"warn error: {e}")

def warns(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else update.effective_user
        t_id = str(target.id)
        ensure_chat(data["warns"], chat_id)
        count = data["warns"][chat_id].get(t_id, 0)
        safe_reply(update, f"📋 {user_mention(target)} has *{count}/3* warnings.")
    except Exception as e:
        logger.error(f"warns error: {e}")

def resetwarn(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to reset their warns.")
            return
        ensure_chat(data["warns"], chat_id)
        data["warns"][chat_id][str(target.id)] = 0
        save_data()
        safe_reply(update, f"✅ Warnings reset for {user_mention(target)}.")
    except Exception as e:
        logger.error(f"resetwarn error: {e}")

# ─────────────────────────────────────────────
#  MUTE / UNMUTE
# ─────────────────────────────────────────────
def parse_duration(text: str):
    match = re.match(r"^(\d+)(m|h|d)$", text.lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    return val * {"m": 60, "h": 3600, "d": 86400}[unit]

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
        duration_str = "indefinitely"
        if context.args:
            duration_sec = parse_duration(context.args[0])
            if duration_sec:
                duration_str = f"for {context.args[0]}"

        until = (datetime.now() + timedelta(seconds=duration_sec)) if duration_sec else None
        perms = ChatPermissions(can_send_messages=False)
        try:
            context.bot.restrict_chat_member(
                update.effective_chat.id, target.id, perms, until_date=until
            )
        except TelegramError as e:
            safe_reply(update, f"❌ Could not mute: {e}")
            return
        safe_reply(update, f"🔇 {user_mention(target)} muted *{duration_str}*.")
    except Exception as e:
        logger.error(f"mute error: {e}")

def unmute(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to the user's message to unmute them.")
            return
        perms = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        try:
            context.bot.restrict_chat_member(update.effective_chat.id, target.id, perms)
        except TelegramError as e:
            safe_reply(update, f"❌ Could not unmute: {e}")
            return
        safe_reply(update, f"🔊 {user_mention(target)} has been unmuted.")
    except Exception as e:
        logger.error(f"unmute error: {e}")

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
        safe_reply(update, f"🔨 {user_mention(target)} has been *banned*.")
    except Exception as e:
        logger.error(f"ban error: {e}")

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
            safe_reply(update, f"✅ @{username} has been unbanned.")
        except TelegramError as e:
            safe_reply(update, f"❌ Failed: {e}")
    except Exception as e:
        logger.error(f"unban error: {e}")

# ─────────────────────────────────────────────
#  STUDY MODE
# ─────────────────────────────────────────────
def study_mode(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args or context.args[0].lower() not in ("on", "off"):
            current = data["study_mode"].get(chat_id, False)
            status = "🟢 ON" if current else "🔴 OFF"
            safe_reply(update,
                f"📚 Study Mode is currently *{status}*\n\n"
                "Usage: `/study_mode on` or `/study_mode off`"
            )
            return
        enable = context.args[0].lower() == "on"
        data["study_mode"][chat_id] = enable
        save_data()
        if enable:
            safe_reply(update,
                "📚 *Study Mode ENABLED!*\n\n"
                "Off-topic messages (hi, lol, ok, bye) will be auto-deleted.\n"
                "Keep it focused! 🎯"
            )
        else:
            safe_reply(update, "📖 *Study Mode DISABLED.*\n\nAll messages now allowed.")
    except Exception as e:
        logger.error(f"study_mode error: {e}")

# ─────────────────────────────────────────────
#  FILTERS
# ─────────────────────────────────────────────
def add_filter(update: Update, context: CallbackContext):
    try:
        if not admin_only(update, context): return
        chat_id = cid(update)
        if not context.args:
            safe_reply(update,
                "Usage:\n"
                "`/filter spam` – auto-delete messages with 'spam'\n"
                "`/filter doubt Check pinned notes!` – auto-reply"
            )
            return
        ensure_chat(data["filters"], chat_id)
        keyword = context.args[0].lower()
        response = " ".join(context.args[1:]) if len(context.args) > 1 else None
        data["filters"][chat_id][keyword] = response
        save_data()
        action = f'reply: "{response}"' if response else "delete the message"
        safe_reply(update, f"✅ Filter set!\n`{keyword}` → {action}")
    except Exception as e:
        logger.error(f"add_filter error: {e}")

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
            safe_reply(update, f"❌ No filter found for `{keyword}`.")
    except Exception as e:
        logger.error(f"rm_filter error: {e}")

def list_filters(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        ensure_chat(data["filters"], chat_id)
        filters_dict = data["filters"][chat_id]
        if not filters_dict:
            safe_reply(update, "No filters set for this group yet.")
            return
        lines = ["🔍 *Active Filters:*\n"]
        for kw, resp in filters_dict.items():
            action = f'→ "{resp}"' if resp else "→ delete"
            lines.append(f"• `{kw}` {action}")
        safe_reply(update, "\n".join(lines))
    except Exception as e:
        logger.error(f"list_filters error: {e}")

# ─────────────────────────────────────────────
#  LEADERBOARD
# ─────────────────────────────────────────────
def leaderboard(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        ensure_chat(data["points"], chat_id)
        pts = data["points"][chat_id]
        if not pts:
            safe_reply(update, "📊 No leaderboard data yet!\n\nSend study messages to earn points. 🎓")
            return
        sorted_users = sorted(pts.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = ["📊 *Top Learners Leaderboard*\n"]
        for i, (u_id, p) in enumerate(sorted_users):
            name = data["user_names"].get(u_id, f"User{u_id[:4]}")
            lines.append(f"{medals[i]} *{i+1}.* {name} — `{p} pts`")
        safe_reply(update, "\n".join(lines))
    except Exception as e:
        logger.error(f"leaderboard error: {e}")

# ─────────────────────────────────────────────
#  REPORT
# ─────────────────────────────────────────────
def report(update: Update, context: CallbackContext):
    try:
        reporter = update.effective_user
        target = update.message.reply_to_message.from_user if update.message.reply_to_message else None
        if not target:
            safe_reply(update, "↩️ Reply to a message to report that user to admins.")
            return
        if target.id == reporter.id:
            safe_reply(update, "😅 You can't report yourself!")
            return
        try:
            admins = update.effective_chat.get_administrators()
        except TelegramError as e:
            logger.warning(f"get_administrators failed: {e}")
            safe_reply(update, "❌ Could not fetch admin list.")
            return

        report_msg = (
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
                    context.bot.send_message(admin.user.id, report_msg, parse_mode=ParseMode.MARKDOWN)
                    notified += 1
                except Exception:
                    pass
        safe_reply(update, f"✅ Report sent to *{notified}* admin(s). Thank you!")
    except Exception as e:
        logger.error(f"report error: {e}")

# ─────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────
def stats(update: Update, context: CallbackContext):
    try:
        chat_id = cid(update)
        chat = update.effective_chat
        ensure_chat(data["points"], chat_id)
        ensure_chat(data["warns"], chat_id)
        ensure_chat(data["filters"], chat_id)

        total_users   = len(data["points"][chat_id])
        total_warns   = sum(data["warns"][chat_id].values())
        total_filters = len(data["filters"][chat_id])
        study         = "🟢 ON"  if data["study_mode"].get(chat_id, False) else "🔴 OFF"
        is_forum      = "✅ Yes" if getattr(chat, "is_forum", False)        else "❌ No"

        safe_reply(update,
            f"📈 *Group Statistics*\n\n"
            f"👥 Active learners: *{total_users}*\n"
            f"⚠️ Total warnings: *{total_warns}*\n"
            f"🔍 Active filters: *{total_filters}*\n"
            f"📚 Study Mode: *{study}*\n"
            f"🗂 Topic group: *{is_forum}*\n"
            f"📌 Group: *{chat.title}*"
        )
    except Exception as e:
        logger.error(f"stats error: {e}")

# ─────────────────────────────────────────────
#  HELP
# ─────────────────────────────────────────────
def help_cmd(update: Update, context: CallbackContext):
    try:
        text = (
            "📋 *StudyGuard Bot Commands*\n\n"
            "*🛡️ Moderation (Admins Only)*\n"
            "`/warn` – Warn user _(reply to msg)_\n"
            "`/warns` – Check warn count\n"
            "`/resetwarn` – Reset warns\n"
            "`/mute [10m/1h/2d]` – Mute user\n"
            "`/unmute` – Unmute user\n"
            "`/ban` – Ban from group\n"
            "`/unban @user` – Unban\n\n"
            "*📚 Study Tools (Admins)*\n"
            "`/study_mode on|off` – Toggle study mode\n"
            "`/setwelcome [msg]` – Set welcome message\n"
            "`/filter word [reply]` – Add filter\n"
            "`/rmfilter word` – Remove filter\n"
            "`/filters` – List all filters\n\n"
            "*📊 Everyone*\n"
            "`/leaderboard` – Top learners\n"
            "`/report` – Report user _(reply to msg)_\n"
            "`/stats` – Group stats\n"
            "`/start` – Main menu\n"
        )
        safe_reply(update, text)
    except Exception as e:
        logger.error(f"help_cmd error: {e}")

# ─────────────────────────────────────────────
#  MESSAGE HANDLER
# ─────────────────────────────────────────────
def handle_message(update: Update, context: CallbackContext):
    try:
        if not update.message or not update.message.text:
            return
        chat_id = cid(update)
        user = update.effective_user
        if not user:
            return

        text = update.message.text
        u_id = str(user.id)
        data["user_names"][u_id] = user.first_name
        text_lower = text.lower()

        # ── Filters ──
        ensure_chat(data["filters"], chat_id)
        for keyword, response in data["filters"][chat_id].items():
            if keyword in text_lower:
                if response:
                    safe_reply(update, response)
                else:
                    safe_delete(update.message)
                return

        # ── Study mode ──
        if data["study_mode"].get(chat_id, False):
            if not is_admin(update, context) and is_non_study_msg(text):
                safe_delete(update.message)
                chat = update.effective_chat
                is_forum = getattr(chat, "is_forum", False)
                thread_id = getattr(update.message, "message_thread_id", None) if is_forum else None

                notice = safe_send(
                    context,
                    chat_id=update.effective_chat.id,
                    text=f"📚 {user_mention(user)} — *Study mode ON!* Keep it study-related. 🎯",
                    thread_id=thread_id
                )
                if notice:
                    try:
                        context.job_queue.run_once(
                            lambda ctx: ctx.bot.delete_message(update.effective_chat.id, notice.message_id),
                            5
                        )
                    except Exception as e:
                        logger.warning(f"job_queue schedule failed: {e}")
                return

        # ── Award points ──
        if any(kw in text_lower for kw in STUDY_KEYWORDS) or len(text.split()) >= 5:
            ensure_chat(data["points"], chat_id)
            add_points(chat_id, u_id, 1)
            save_data()

    except Exception as e:
        logger.error(f"handle_message error: {e}")

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
        # Increase timeouts to survive slow connections
        request_kwargs={
            "read_timeout": 30,
            "connect_timeout": 30,
        }
    )
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start",       start))
    dp.add_handler(CommandHandler("help",        help_cmd))
    dp.add_handler(CommandHandler("warn",        warn))
    dp.add_handler(CommandHandler("warns",       warns))
    dp.add_handler(CommandHandler("resetwarn",   resetwarn))
    dp.add_handler(CommandHandler("mute",        mute))
    dp.add_handler(CommandHandler("unmute",      unmute))
    dp.add_handler(CommandHandler("ban",         ban))
    dp.add_handler(CommandHandler("unban",       unban))
    dp.add_handler(CommandHandler("study_mode",  study_mode))
    dp.add_handler(CommandHandler("setwelcome",  setwelcome))
    dp.add_handler(CommandHandler("filter",      add_filter))
    dp.add_handler(CommandHandler("rmfilter",    rm_filter))
    dp.add_handler(CommandHandler("filters",     list_filters))
    dp.add_handler(CommandHandler("leaderboard", leaderboard))
    dp.add_handler(CommandHandler("report",      report))
    dp.add_handler(CommandHandler("stats",       stats))

    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_member))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Global error handler — prevents crashes from unhandled exceptions
    dp.add_error_handler(error_handler)

    print("🚀 StudyGuard Bot v3.1 is running!")
    updater.start_polling(
        drop_pending_updates=True,
        timeout=30,
        allowed_updates=["message", "callback_query", "chat_member"]
    )
    updater.idle()

if __name__ == "__main__":
    main()
