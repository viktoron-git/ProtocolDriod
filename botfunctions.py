from datetime import datetime, timezone, timedelta
from time import time
from extensions import app, db, bot, ADMIN_ID
from models import GroupSetting, Projects, DailyUsage
from telebot.apihelper import ApiTelegramException
from functools import wraps


# break down chats into bits, extrack group links and group name
def get_msg_details(message):
    g_link = None
    name_parts = []
    for w in message:
        if 't.me/' in w or 'https://' in w or 'x.com/' in w:
            g_link = w
        else:
            name_parts.append(w)

    g_name = " ".join(name_parts) if name_parts else None
    return g_link, g_name

# def admin_required(func):
#     @wraps(func)
#     def wrapper(message, *args, **kwargs):
#         if not is_user_admin(message.chat.id, message.from_user.id):
#             bot.reply_to(message, "Only group admins can do this")
#             return
#         return func(message, *args, **kwargs)
#     return wrapper

# this returns the value of count in the DailyUsage db
# an admin check
def is_user_admin(chat_id, user_id):
    admins = bot.get_chat_administrators(chat_id)
    for admin in admins:
        if admin.user.id == user_id:
            return True
    return False

# get the daily usage count from the DailyUsage db
def daily_usage_count(chat_id, user_id):
    today = datetime.now(timezone.utc).date()
    with app.app_context():
        row = db.session.execute(db.select(DailyUsage).filter_by(chat_id=chat_id, user_id=user_id, date=today)).scalar()
        return row.count if row else 0


# increases the number of counts in the DailyUsage db this in turn opens new spot for reports
def increase_daily(chat_id, user_id):
    today = datetime.now(timezone.utc).date()
    with app.app_context():
        row = db.session.execute(db.select(DailyUsage).filter_by(chat_id=chat_id, user_id=user_id, date=today)).scalar()
        if row:
            row.count += 1
        else:
            db.session.add(DailyUsage(chat_id=chat_id, user_id=user_id, date=today, count=1))
        db.session.commit()

# decrease the number of counts in the DailyUsage db this in turn opens new spot for reports
def decrease_daily(chat_id, user_id):
    today = datetime.now(timezone.utc).date()
    with app.app_context():
        row = db.session.execute(db.select(DailyUsage).filter_by(chat_id=chat_id, user_id=user_id, date=today)).scalar()
        if row and row.count > 0:
            row.count -= 1
            db.session.commit()

# returns the total amount of groups claimed in db
def total_claimed(chat_id, user_id):
    with app.app_context():
        return db.session.execute(db.select(db.func.count()).select_from(Projects).filter_by(
            chat_id=chat_id, user_id=user_id
        )).scalar()


# returns the value of the set daily limit on the GroupSetting db
def daily_limit(chat_id):
    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=chat_id)).scalar()

        if setting and setting.daily_limit is not None:
            return setting.daily_limit

        return None


# returns the total limit set in the GroupSetting db
def get_total_limit(chat_id):
    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=chat_id)).scalar()
        if setting and setting.total_limit is not None:
            return setting.total_limit

        return None


# sets the timer function and store in the GroupSetting db
def effective_timer(chat_id):
    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=chat_id)).scalar()

        # converting the timer to seconds because telegram auto delete time is in seconds
        if setting and setting.timer is not None:
            return setting.timer * 86400

        try:
            chat = bot.get_chat(chat_id)
        except ApiTelegramException:
            return None

        return chat.message_auto_delete_time or None


# Set timer -- the timer carries the amount of days an input stays in the database
def set_timer(message, admin_id, started_at):

    if time() - started_at > 120:
        bot.send_message(message.chat.id, 'Timer set up incomplete, click the button again to set.')
        return

    if message.from_user.id != admin_id:
        bot.register_next_step_handler(message, set_timer, admin_id, started_at)
        return

    if not is_user_admin(message.chat.id, admin_id):
        bot.reply_to(message, "Couldn't confirm admin status, set timer denied ⚠️")
        return

    try:
        timer_days = int(message.text)
    except ValueError:
        bot.send_message(message.chat.id, " ⚠️ That's not a valid number, please try again.")
        bot.register_next_step_handler(message, set_timer, admin_id, started_at)
        return

    with app.app_context():
        existing = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if existing:
            existing.timer = timer_days
        else:
            db.session.add(GroupSetting(chat_id=message.chat.id, timer=timer_days))

        db.session.commit()
    bot.send_message(message.chat.id, f'Timer set to {timer_days} day{"s" if timer_days != 1 else ""}.')

# the 24hr background cleanups, that deletes project from database
def cleanup_expired_projects():
    with app.app_context():
        chat_ids = db.session.execute(db.select(Projects.chat_id).distinct()).scalars().all()

        for chat_id in chat_ids:
            seconds = effective_timer(chat_id)

            if not seconds:
                continue
            time_up = datetime.now(timezone.utc) - timedelta(seconds=seconds)
            expired = db.session.execute(db.select(Projects).filter(Projects.chat_id == chat_id, Projects.submitted_at < time_up)).scalars().all()

            for group in expired:
                decrease_daily(group.chat_id, group.user_id)
                db.session.delete(group)

        db.session.commit()

def delete_link(message):
    group_link = message.text
    with app.app_context():
        project = db.session.execute(
            db.select(Projects).filter_by(chat_id=message.chat.id, group_link=group_link)).scalar()
        if not project:
            bot.reply_to(message, "⚠️ Couldn't find link.")
            return

        if project.user_id != message.from_user.id:
            bot.reply_to(message, '⚠️ Only who reported this can unclaim it')
            return
        user_info = bot.get_chat(message.from_user.id)
        group_name = project.group_name
        db.session.delete(project)
        db.session.commit()
        decrease_daily(chat_id=message.chat.id, user_id=message.from_user.id)
    bot.reply_to(message, f"{user_info.first_name} unclaimed {group_name}")
