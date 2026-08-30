from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime, BigInteger, Date
from datetime import datetime, timezone


class Projects(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_name: Mapped[str] = mapped_column(String)
    group_link: Mapped[str] = mapped_column(String)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class GroupSetting(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    timer: Mapped[int] = mapped_column(Integer, nullable=True)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=True)
    total_limit: Mapped[int] = mapped_column(Integer, nullable=True)

class DailyUsage(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)