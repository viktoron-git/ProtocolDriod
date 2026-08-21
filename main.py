import os
from load_dotenv import load_dotenv
import telebot
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime
from flask import Flask
from telebot.asyncio_helper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup , ReplyKeyboardRemove
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from time import time

load_dotenv()
TOKEN = os.getenv('TOKEN')
bot = telebot.TeleBot(token=TOKEN)

app = Flask(__name__)

# create DB

class Base(DeclarativeBase):
    pass

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///projects.db'
db = SQLAlchemy(model_class=Base)
db.init_app(app)

class Projects(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str] = mapped_column(String)
    group_link: Mapped[str] = mapped_column(String)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class GroupSetting(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    timer: Mapped[int] = mapped_column(Integer, nullable=False)

with app.app_context():
    db.create_all()



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

# Help command
@bot.message_handler(commands=['help'])
def help_user(message):
    if message.chat.type in ['group', 'supergroup']:
        if is_user_admin(message.chat.id, message.from_user.id):
            bot.send_message(message.chat.id, "If you need any help, please contact our support with the /contact prompt.")
        return
    else:
        bot.send_message(message.chat.id, "If you need any help, please contact our support with the /contact prompt.")


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

        db.session.delete(setting)
        db.session.commit()
    bot.reply_to(message, 'Custom timer ⌛️ removed.')

# @bot.message_handler(commands=['clear'])
# def clear(message):
#     bot.send_message(message.chat.id, 'Keyboard removed', reply_markup=ReplyKeyboardRemove())

# A callback query handler

# check if user is admin
def is_user_admin(chat_id, user_id):
    admins = bot.get_chat_administrators(chat_id)
    for admin in admins:
        if admin.user.id == user_id:
            return True
    return False

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

def effective_timer(chat_id):
    with app.app_context():
        setting = db.session.execute(db.select(GroupSetting)).filter_by(chat_id=chat_id).scalar()

        # converting the timer to seconds because telegram auto delete time is in seconds
        if setting:
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
        return

    with app.app_context():
        existing = db.session.execute(db.select(GroupSetting).filter_by(chat_id=message.chat.id)).scalar()

        if existing:
            existing.timer = timer_days
        else:
            db.session.add(GroupSetting(chat_id=message.chat.id, timer=timer_days))

        db.session.commit()
    bot.send_message(message.chat.id, f'Timer set to {timer_days} day{"s" if timer_days != 1 else ""}.')



@bot.message_handler(func=lambda message: message.chat.type in ['group', 'supergroup'])
def reply_text(message):

    with app.app_context():
        result = db.session.execute(db.select(Projects))
        all_links = result.scalars().all()

        g_link, name = get_msg_details(message.text.split())

        for link in all_links:
            if g_link == link.group_link:
                user_info = bot.get_chat(link.user_id)
                bot.reply_to(message, text=f'Group already reported by {user_info.first_name}')
                return

        if 't.me/' in message.text or 'https://' in message.text or 'x.com/' in message.text:
            g_link, name = get_msg_details(message.text.split())
            if not name:
                bot.reply_to(message, '⚠️ Please include a name along with the link.')
                return
            new_project = Projects(user_id=message.from_user.id, chat_id=message.chat.id, group_name=name, group_link=g_link)
            db.session.add(new_project)
            db.session.commit()

def cleanup_expired_projects():
    with app.app_context():
        chat_ids = db.session.execute(db.select(Projects.chat_id)).distinct().scalars().all()

        for chat_id in chat_ids:
            seconds = effective_timer(chat_id)

            if not seconds:
                continue
            time_up = datetime.now(timezone.utc) - timedelta(seconds=seconds)
            expired = db.session.execute(db.select(Projects).filter(Projects.chat_id == chat_id, Projects.submitted_at < time_up)).scalars().all()

            for group in expired:
                db.session.delete(group)

        db.session.commit()

schedular = BackgroundScheduler()
schedular.add_job(cleanup_expired_projects, 'interval', hours=24)
schedular.start()


bot.polling()


