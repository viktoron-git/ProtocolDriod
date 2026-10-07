import os
from dotenv import load_dotenv
import telebot
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_migrate import Migrate


load_dotenv()
TOKEN = os.getenv('TOKEN')
bot = telebot.TeleBot(token=TOKEN)
ADMIN_ID = os.getenv('ADMIN_ID')

app = Flask(__name__)

# create DB
class Base(DeclarativeBase):
    pass

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", 'sqlite:///projects.db')
db = SQLAlchemy(model_class=Base)
db.init_app(app)

# keeps track of changes to the database structure (see the migrations/ folder)
migrate = Migrate(app, db, render_as_batch=True)
