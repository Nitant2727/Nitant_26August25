from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid
import pandas as pd
import threading
import pytz
from datetime import datetime, timedelta

app = FastAPI()

DATABASE_URL = "sqlite:///./store_monitoring.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StoreStatus(Base):
    __tablename__ = "store_status"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, index=True)
    status = Column(String)
    timestamp_utc = Column(String)


class BusinessHour(Base):
    __tablename__ = "business_hours"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, index=True)
    dayOfWeek = Column(Integer)
    start_time_local = Column(String)
    end_time_local = Column(String)


class Timezone(Base):
    __tablename__ = "timezones"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, index=True)
    timezone_str = Column(String)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String, unique=True, index=True)
    status = Column(String)
    file_path = Column(String)


Base.metadata.create_all(bind=engine)


def load_csv_to_db():
    db = SessionLocal()

    if db.query(StoreStatus).first() is None:
        df = pd.read_csv("store_status.csv")
        for _, row in df.iterrows():
            db.add(
                StoreStatus(
                    store_id=row["store_id"],
                    status=row["status"],
                    timestamp_utc=row["timestamp_utc"],
                )
            )
        db.commit()

    if db.query(BusinessHour).first() is None:
        df = pd.read_csv("menu_hours.csv")
        for _, row in df.iterrows():
            db.add(
                BusinessHour(
                    store_id=row["store_id"],
                    dayOfWeek=row["dayOfWeek"],
                    start_time_local=row["start_time_local"],
                    end_time_local=row["end_time_local"],
                )
            )
        db.commit()

    if db.query(Timezone).first() is None:
        df = pd.read_csv("timezones.csv")
        for _, row in df.iterrows():
            db.add(Timezone(store_id=row["store_id"], timezone_str=row["timezone_str"]))
        db.commit()

    db.close()


load_csv_to_db()


@app.post("/trigger_report")
def trigger_report():
    db = SessionLocal()
    report_id = str(uuid.uuid4())

    report = Report(report_id=report_id, status="Running", file_path="")
    db.add(report)
    db.commit()
    db.close()

    threading.Thread(target=generate_report, args=(report_id,)).start()
    return {"report_id": report_id}


def get_current_timestamp():
    db = SessionLocal()
    latest = db.query(StoreStatus).order_by(StoreStatus.timestamp_utc.desc()).first()
    db.close()

    if latest:
        timestamp_str = latest.timestamp_utc.replace(" UTC", "")
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
        return pytz.utc.localize(dt)
    return pytz.utc.localize(datetime.utcnow())


def get_store_timezone(db, store_id):
    tz_row = db.query(Timezone).filter(Timezone.store_id == store_id).first()
    if tz_row:
        return pytz.timezone(tz_row.timezone_str)
    return pytz.timezone("America/Chicago")


def get_business_hours(db, store_id):
    hours = db.query(BusinessHour).filter(BusinessHour.store_id == store_id).all()
    if hours:
        return hours

    default_hours = []
    for day in range(7):
        default_hours.append(
            BusinessHour(
                store_id=store_id,
                dayOfWeek=day,
                start_time_local="00:00:00",
                end_time_local="23:59:59",
            )
        )
    return default_hours


def calculate_uptime_downtime(
    db, store_id, start_time, end_time, business_hours, store_tz
):
    total_uptime = 0
    total_downtime = 0

    if start_time.tzinfo is None:
        start_time = pytz.utc.localize(start_time)
    if end_time.tzinfo is None:
        end_time = pytz.utc.localize(end_time)

    for bh in business_hours:
        current_date = start_time.date()
        end_date = end_time.date()

        while current_date <= end_date:
            if current_date.weekday() == bh.dayOfWeek:
                bh_start = datetime.strptime(bh.start_time_local, "%H:%M:%S").time()
                bh_end = datetime.strptime(bh.end_time_local, "%H:%M:%S").time()

                business_start = datetime.combine(current_date, bh_start)
                business_end = datetime.combine(current_date, bh_end)

                business_start_utc = store_tz.localize(business_start).astimezone(
                    pytz.utc
                )
                business_end_utc = store_tz.localize(business_end).astimezone(pytz.utc)

                if business_end_utc < start_time or business_start_utc > end_time:
                    current_date += timedelta(days=1)
                    continue

                interval_start = max(business_start_utc, start_time)
                interval_end = min(business_end_utc, end_time)

                polls = (
                    db.query(StoreStatus)
                    .filter(
                        StoreStatus.store_id == store_id,
                        StoreStatus.timestamp_utc
                        >= interval_start.strftime("%Y-%m-%d %H:%M:%S"),
                        StoreStatus.timestamp_utc
                        <= interval_end.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    .order_by(StoreStatus.timestamp_utc)
                    .all()
                )

                if not polls:
                    total_downtime += (interval_end - interval_start).total_seconds()
                else:
                    prev_time = interval_start
                    for poll in polls:
                        poll_time_str = poll.timestamp_utc.replace(" UTC", "")
                        poll_time = datetime.strptime(
                            poll_time_str, "%Y-%m-%d %H:%M:%S.%f"
                        )
                        poll_time = pytz.utc.localize(poll_time)

                        if poll.status == "active":
                            total_uptime += (poll_time - prev_time).total_seconds()
                        else:
                            total_downtime += (poll_time - prev_time).total_seconds()

                        prev_time = poll_time

                    last_poll = polls[-1]
                    if last_poll.status == "active":
                        total_uptime += (interval_end - prev_time).total_seconds()
                    else:
                        total_downtime += (interval_end - prev_time).total_seconds()

            current_date += timedelta(days=1)

    return total_uptime, total_downtime


def generate_report(report_id):
    db = SessionLocal()
    report = db.query(Report).filter(Report.report_id == report_id).first()

    file_path = f"report_{report_id}.csv"
    stores = db.query(StoreStatus.store_id).distinct().all()
    current_time = get_current_timestamp()

    with open(file_path, "w") as f:
        f.write(
            "store_id,uptime_last_hour,uptime_last_day,uptime_last_week,downtime_last_hour,downtime_last_day,downtime_last_week\n"
        )

        for store_tuple in stores:
            store_id = store_tuple[0]

            store_tz = get_store_timezone(db, store_id)
            business_hours = get_business_hours(db, store_id)

            hour_start = current_time - timedelta(hours=1)
            day_start = current_time - timedelta(days=1)
            week_start = current_time - timedelta(days=7)

            up_hour, down_hour = calculate_uptime_downtime(
                db, store_id, hour_start, current_time, business_hours, store_tz
            )
            up_day, down_day = calculate_uptime_downtime(
                db, store_id, day_start, current_time, business_hours, store_tz
            )
            up_week, down_week = calculate_uptime_downtime(
                db, store_id, week_start, current_time, business_hours, store_tz
            )

            uptime_hour_min = int(up_hour // 60)
            downtime_hour_min = int(down_hour // 60)
            uptime_day_hours = round(up_day / 3600, 2)
            downtime_day_hours = round(down_day / 3600, 2)
            uptime_week_hours = round(up_week / 3600, 2)
            downtime_week_hours = round(down_week / 3600, 2)

            f.write(
                f"{store_id},{uptime_hour_min},{uptime_day_hours},{uptime_week_hours},{downtime_hour_min},{downtime_day_hours},{downtime_week_hours}\n"
            )

    report.status = "Complete"
    report.file_path = file_path
    db.commit()
    db.close()


@app.get("/get_report")
def get_report(report_id: str):
    db = SessionLocal()
    report = db.query(Report).filter(Report.report_id == report_id).first()
    db.close()

    if not report:
        return {"status": "NotFound"}

    if report.status == "Running":
        return {"status": "Running"}

    if report.status == "Complete":
        return FileResponse(
            report.file_path, media_type="text/csv", filename=report.file_path
        )

    return {"status": "Unknown"}
