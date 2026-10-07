from datetime import datetime, timezone, timedelta
from time import time
from extensions import app, db, bot, ADMIN_ID
from models import GroupSetting, Projects, DailyUsage, LinkAlias
from telebot.apihelper import ApiTelegramException
from functools import wraps
from url_utils import telegram_username, normalize_url
from requests.exceptions import RequestException
from sqlalchemy import or_
import csv
import io
from zoneinfo import ZoneInfo

# the timezone your "day" runs on (daily stats + the 11:59pm post).
TIMEZONE = ZoneInfo('Africa/Lagos')

# all links that count as the same group as `normalized` (itself + anything an admin paired with it)
# call this inside app.app_context()
def equivalent_urls(chat_id, normalized):
    urls = {normalized}
    rows = db.session.execute(db.select(LinkAlias).filter(
        LinkAlias.chat_id == chat_id,
        or_(LinkAlias.url_a == normalized, LinkAlias.url_b == normalized)
    )).scalars().all()
    for row in rows:
        urls.add(row.url_a)
        urls.add(row.url_b)
    return urls


# saves a pair of links as "same group"
def add_alias(chat_id, url_a, url_b):
    with app.app_context():
        db.session.add(LinkAlias(chat_id=chat_id, url_a=url_a, url_b=url_b))
        db.session.commit()


# removes every pairing that involves this link, returns how many were removed
def remove_aliases(chat_id, normalized):
    with app.app_context():
        rows = db.session.execute(db.select(LinkAlias).filter(
            LinkAlias.chat_id == chat_id,
            or_(LinkAlias.url_a == normalized, LinkAlias.url_b == normalized)
        )).scalars().all()
        for row in rows:
            db.session.delete(row)
        db.session.commit()
        return len(rows)


# asks Telegram for the permanent chat id behind a public link like t.me/username
def resolve_public_chat_id(normalized_url):
    username = telegram_username(normalized_url)
    if not username:
        return None          # not a plain public link (e.g. a private invite)
    try:
        chat = bot.get_chat(f"@{username}")
    except (ApiTelegramException, RequestException):
        return None          # Telegram doesn't know it, or the network failed
    if chat.type in ('channel', 'group', 'supergroup'):
        return chat.id
    return None              # it was a person or a bot, not a group

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

def delete_link(message, link=None):
    group_link = link or message.text
    normalized = normalize_url(group_link) or group_link
    with app.app_context():
        project = db.session.execute(
            db.select(Projects).filter(
                Projects.chat_id == message.chat.id,
                Projects.normalized_link.in_(equivalent_urls(message.chat.id, normalized))
            )).scalar()
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


# stops Excel from running a cell as a formula if a name starts with = + - @
def _safe_cell(value):
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text


# builds the CSV file for /export, returns (file, number_of_rows)
def build_export_csv(chat_id):
    with app.app_context():
        projects = db.session.execute(
            db.select(Projects).filter_by(chat_id=chat_id).order_by(Projects.submitted_at)
        ).scalars().all()
        rows = [(p.user_id, p.group_name, p.group_link, p.submitted_at) for p in projects]

    names = {}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['reported_by', 'user_id', 'group_name', 'link', 'reported_at_utc'])
    for user_id, group_name, group_link, submitted_at in rows:
        if user_id not in names:
            names[user_id] = display_name(user_id).removeprefix('@')
        writer.writerow([_safe_cell(names[user_id]), user_id, _safe_cell(group_name),
                         _safe_cell(group_link), submitted_at.strftime('%Y-%m-%d %H:%M')])

    file = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    file.name = 'reports.csv'
    return file, len(rows)


# every saved report from one user in one group, oldest first: [(group_name, group_link, submitted_at), ...]
def reports_by_each_user(chat_id, user_id):
    with app.app_context():
        projects = db.session.execute(
            db.select(Projects).filter_by(chat_id=chat_id, user_id=user_id).order_by(Projects.submitted_at)
        ).scalars().all()
        return [(p.group_name, p.group_link, p.submitted_at) for p in projects]

# a readable name for a user id: @username, or first name, or a fallback
def display_name(user_id):
    try:
        user_info = bot.get_chat(user_id)
    except (ApiTelegramException, RequestException):
        return f'user {user_id}'
    if user_info.username:
        return f'@{user_info.username}'
    return user_info.first_name or f'user {user_id}'

# sends text to a chat id, split in pieces if it is too long for Telegram
def send_long_to_chat(chat_id, text):
    chunk = ''
    for line in text.split('\n'):
        if len(chunk) + len(line) + 1 > 4000:
            bot.send_message(chat_id, chunk)
            chunk = ''
        chunk += line + '\n'
    if chunk.strip():
        bot.send_message(chat_id, chunk)


# same thing, but for when you have a message to answer in
def send_long_message(message, text):
    send_long_to_chat(message.chat.id, text)

# [(user_id, how_many), ...] for one group, biggest first
def reports_per_user(chat_id):
    with app.app_context():
        rows = db.session.execute(
            db.select(Projects.user_id, db.func.count())
            .filter(Projects.chat_id == chat_id)
            .group_by(Projects.user_id)
            .order_by(db.func.count().desc())
        ).all()
        return [(user_id, total) for user_id, total in rows]

# [(user_id, how_many), ...] for reports saved today (in TIMEZONE), biggest first
def reports_today(chat_id):
    local_midnight = datetime.now(TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_day = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)   # the database stores UTC
    with app.app_context():
        rows = db.session.execute(
            db.select(Projects.user_id, db.func.count())
            .filter(Projects.chat_id == chat_id, Projects.submitted_at >= start_of_day)
            .group_by(Projects.user_id)
            .order_by(db.func.count().desc())
        ).all()
        return [(user_id, total) for user_id, total in rows]


# builds the daily stats message, returns (text, were_there_any_reports_today)
def daily_stats_text(chat_id):
    today = reports_today(chat_id)
    saved_total = sum(t for _, t in reports_per_user(chat_id))
    date_text = datetime.now(TIMEZONE).strftime('%d %b %Y')

    if not today:
        return f'📈 Daily stats — {date_text}\n\nNo links reported today.\n\nSaved in total: {saved_total}', False

    lines = [
        f'📈 Daily stats — {date_text}',
        '',
        f'Reported today: {sum(t for _, t in today)}',
        f'People who reported: {len(today)}',
        '',
        'By person:',
    ]
    for i, (user_id, total) in enumerate(today, start=1):
        lines.append(f'{i}. {display_name(user_id).removeprefix("@")} — {total}')
    lines.append('')
    lines.append(f'Saved in total: {saved_total}')
    return '\n'.join(lines), True


# runs every day at 11:59pm: posts the daily stats in every group that had reports today
def post_daily_stats():
    with app.app_context():
        chat_ids = db.session.execute(db.select(Projects.chat_id).distinct()).scalars().all()

    for chat_id in chat_ids:
        text, has_reports = daily_stats_text(chat_id)
        if not has_reports:
            continue   # quiet day, say nothing
        try:
            send_long_to_chat(chat_id, text)
        except (ApiTelegramException, RequestException):
            pass   # the bot was removed from that group, or the network failed: skip it

# turns a number of seconds into words, like "2 days" or "3 hours"
def human_time(seconds):
    seconds = max(int(seconds), 0)
    days = seconds // 86400
    hours = seconds // 3600
    minutes = seconds // 60
    if days:
        return f'{days} day{"s" if days != 1 else ""}'
    if hours:
        return f'{hours} hour{"s" if hours != 1 else ""}'
    if minutes:
        return f'{minutes} minute{"s" if minutes != 1 else ""}'
    return 'less than a minute'


# the reply sent when someone reports a link that another user already reported
def duplicate_reply_text(existing):
    try:
        user_info = bot.get_chat(existing.user_id)
        who = f'@{user_info.username}' if user_info.username else user_info.first_name
    except (ApiTelegramException, RequestException):
        who = None
    who = who or 'another scout'

    reported_at = existing.submitted_at
    if reported_at.tzinfo is None:   # the database gives back UTC times without a label
        reported_at = reported_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - reported_at).total_seconds()
    text = f'This was already claimed by {who} {human_time(age)} ago.'

    seconds = effective_timer(existing.chat_id)
    if seconds is None:
        text += ' No expiry is set.'
    else:
        left = seconds - age
        if left <= 0:
            text += ' It has expired and will be cleared soon.'
        else:
            text += f' Expires in {human_time(left)}.'
    return text

# fills in the cleaned link for any report saved without one (runs every time the bot starts)
def backfill_normalized_urls():
    with app.app_context():
        rows = db.session.execute(db.select(Projects).filter(Projects.normalized_link.is_(None))).scalars().all()
        for row in rows:
            row.normalized_link = normalize_url(row.group_link) or row.group_link
        db.session.commit()