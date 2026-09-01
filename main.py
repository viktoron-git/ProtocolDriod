from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup , ReplyKeyboardRemove
from apscheduler.schedulers.background import BackgroundScheduler
from time import time
from datetime import datetime, timezone
from extensions import app, db, bot, ADMIN_ID
from models import GroupSetting, Projects, DailyUsage
from botfunctions import daily_usage_count, increase_daily, decrease_daily, total_claimed, daily_limit, get_msg_details, cleanup_expired_projects, get_total_limit, is_user_admin, set_timer


with app.app_context():
    db.create_all()


# Inline keyboard buttons
reach_owner = InlineKeyboardMarkup(row_width=2)
owner = InlineKeyboardButton(text='Contact Owner', callback_data='owner')
channel = InlineKeyboardButton(text="Reach out on Channel", callback_data="channel")
set_time = InlineKeyboardMarkup(row_width=1)
set_time.add(InlineKeyboardButton(text='Set the timer for your group', callback_data='timer'))
reach_owner.add(owner, channel)


# Start command
@bot.message_handler(commands=['start'])
def welcome(message):
    welcome_text = "ProtocolDriod is ready to serve you!"
    if message.chat.type in ['group', 'supergroup']:
        if is_user_admin(message.chat.id, message.from_user.id):
            bot.send_message(message.chat.id, welcome_text, reply_markup=set_time)
        else:
            bot.send_message(message.chat.id, 'Only Admins can use me 🤖')
    else:
        bot.send_message(message.chat.id, welcome_text)

# Contact Command
@bot.message_handler(commands=['contact'])
def contact(message):
    if message.chat.type in ['group', 'supergroup']:
        if is_user_admin(message.chat.id, message.from_user.id):
            bot.send_message(message.chat.id, "Please reach out through the the below methods.",
                     reply_markup=reach_owner)
        return
    else:
        bot.send_message(message.chat.id, "Please reach out through the the below methods.",
                         reply_markup=reach_owner)

# stop timer command
@bot.message_handler(commands=['stoptimer'])
def stop_timer(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, 'Only group admins can do this.')
        return

    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if not setting:
            bot.send_message(message.chat.id, 'No custom timer is set - will use group auto delete setting (if any).')
            return

        setting.timer = None
        db.session.commit()
    bot.reply_to(message, 'Custom timer ⌛️ removed.')

@bot.message_handler(commands=['unclaim'])
def unclaim_group(message):

    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    args = message.text.split()

    if len(args) < 2:
        bot.reply_to(message, '⚠️ Usage: /unclaim <link>')
        return

    link_to_delete = args[1]
    with app.app_context():
        project = db.session.execute(db.select(Projects).filter_by(chat_id = message.chat.id, group_link=link_to_delete)).scalar()
        if not project:
            bot.reply_to(message, "⚠️ Couldn't find link in the database" )
            return

        if project.user_id != message.from_user.id:
            bot.reply_to(message, '⚠️ Only the person who reported this can unclaim it')
            return
        user_info = bot.get_chat(message.from_user.id)
        group_name = project.group_name
        db.session.delete(project)
        db.session.commit()
        decrease_daily(chat_id=message.chat.id, user_id=message.from_user.id)
    bot.reply_to(message, f"{user_info.first_name} unclaimed {group_name}")

@bot.message_handler(commands=['setlimit'])
def set_limit(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, 'Only group admins can do this.')
        return

    args = message.text.split()

    if len(args) < 2:
        bot.reply_to(message, '⚠️ Usage: /setlimit <number>')
        return

    try:
        limit = int(args[1])
    except ValueError:
        bot.reply_to(message, "⚠️ Please provide a valid number.")
        return

    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if setting:
            setting.total_limit = limit
        else:
            db.session.add(GroupSetting(chat_id=message.chat.id, total_limit=limit))
        db.session.commit()

    bot.reply_to(message, f"Total report limit set to {limit} per scout.")

@bot.message_handler(commands=['setdailylimit'])
def set_daily_limit(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, 'Only group admins can do this.')
        return

    args = message.text.split()

    if len(args) < 2:
        bot.reply_to(message, '⚠️ Usage: /setdailylimit <number>')
        return

    try:
        limit = int(args[1])
    except ValueError:
        bot.reply_to(message, "⚠️ Please provide a valid number.")
        return

    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if setting:
            setting.daily_limit = limit
        else:
            db.session.add(GroupSetting(chat_id=message.chat.id, daily_limit=limit))
        db.session.commit()

    bot.reply_to(message, f"Daily report limit set to {limit} per scout.")

@bot.message_handler(commands=['rmlimits'])
def remove_group_limits(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, 'Only group admins can do this.')
        return

    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if not setting or (setting.total_limit is None and setting.daily_limit is None):
            bot.send_message(message.chat.id, 'No group limits set.')
            return

        setting.daily_limit = None
        setting.total_limit = None
        db.session.commit()
    bot.reply_to(message, 'All group limits removed. ')

@bot.message_handler(commands=['show'])
def show_links(message):
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(message.chat.id, 'This command only works in groups.')
        return

    with app.app_context():
        projects = db.session.execute(db.select(Projects).filter_by(chat_id=message.chat.id, user_id=message.from_user.id)).scalars().all()

    if not projects:
        bot.reply_to(message, "You haven't reported any links in this group yet")
        return

    lines = [f"{i}. {r.group_name} — {r.group_link}" for i, r in enumerate(projects, start=1)]
    text = "📋 Your reported links:\n\n" + "\n".join(lines)
    bot.reply_to(message, text)


# @bot.message_handler(commands=['clear'])
# def clear(message):
#     bot.send_message(message.chat.id, 'Keyboard removed', reply_markup=ReplyKeyboardRemove())

# A callback query handler

# check if user is admin


# Inline button for query handlers
@bot.callback_query_handler(func= lambda call: True)
def click_button(call):
    if call.data == 'owner':
        username = "kvngvicktor"
        bot.answer_callback_query(call.id, text=f"Please reach out to @{username}", show_alert=True )
    elif call.data == "channel":
        my_channel = "apexpraycasino"
        bot.answer_callback_query(call.id, text=f"Please reach out through the channel @{my_channel}", show_alert=True)
    elif call.data == 'timer':
        if is_user_admin(call.message.chat.id, call.from_user.id):
            msg = bot.send_message(call.message.chat.id, text='How long should the group timer last? Must be a number.\n\n ⚠️ This affects reports in the database.')
            bot.register_next_step_handler(msg, set_timer, call.from_user.id, time())
        else:
            bot.answer_callback_query(call.id, text='Only Admins can set this', show_alert=True)


@bot.message_handler(func=lambda message: message.chat.type in ['group', 'supergroup'])
def reply_text(message):
    with app.app_context():

        g_link, name = get_msg_details(message.text.split())
        if not name:
            bot.reply_to(message, '⚠️ Please include a name along with the link.')
            return

        existing = db.session.execute(db.select(Projects).filter_by(chat_id = message.chat.id, group_link = g_link)).scalar()

        if existing:
            if existing.user_id != message.from_user.id:
                user_info = bot.get_chat(existing.user_id)
                display_name = f'@{user_info.username}' if user_info.username else user_info.first_name
                bot.reply_to(message, text=f'Group already reported by {display_name}')
                return
            else:
                existing.group_name = name
                existing.submitted_at = datetime.now(timezone.utc)
                db.session.commit()
                return

        if 't.me/' in message.text or 'https://' in message.text or 'x.com/' in message.text:
            limit_per_day = daily_limit(message.chat.id)

            if limit_per_day is not None:
                if daily_usage_count(chat_id=message.chat.id, user_id=message.from_user.id) >= limit_per_day:
                    #bot.reply_to(message, f"⚠️ You've reached your daily limit. Try again tomorrow or unclaim your previous links.")
                    if ADMIN_ID:
                        display_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                        try:
                            bot.send_message(ADMIN_ID, f"⚠️ {display_name} has exceeded {limit_per_day} on {message.chat.title}")
                        except ApiTelegramException:
                            pass
                    return

            total_limit = get_total_limit(message.chat.id)
            if total_limit is not None:
                total_claim = total_claimed(message.chat.id, message.from_user.id)
                if total_claim >= total_limit:
                    bot.reply_to(message, f"⚠️ You've exceeded your total limits, unclaim previous links.")
                    if ADMIN_ID:
                        display_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
                        try:
                            bot.send_message(ADMIN_ID, f"⚠️ {display_name} has exceeded {total_limit} on {message.chat.title}")
                        except ApiTelegramException:
                            pass
                    return

            new_project = Projects(user_id=message.from_user.id, chat_id=message.chat.id, group_name=name, group_link=g_link)
            db.session.add(new_project)
            db.session.commit()
            increase_daily(chat_id=message.chat.id, user_id=message.from_user.id)



schedular = BackgroundScheduler()
schedular.add_job(cleanup_expired_projects, 'interval', hours=24)
schedular.start()


bot.polling()


