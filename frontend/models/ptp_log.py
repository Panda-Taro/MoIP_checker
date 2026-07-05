"""SQLAlchemyモデル: ptp_measurement_logs / ptp_event_logs (要件定義書 7.3)"""

from sqlalchemy import create_engine, event, Column, Integer, Text
from sqlalchemy.orm import sessionmaker, declarative_base

DB_PATH = "/app/data/ptp_logs.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class PtpMeasurementLog(Base):
    """計測ログ(1分毎に1行、要件定義書 7.3.1)"""

    __tablename__ = "ptp_measurement_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at = Column(Text, nullable=False)  # OS時計・ISO8601形式
    lock_status = Column(Integer, nullable=False)  # 1=ロック中・0=非ロック
    gm_id = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    offset_avg_ns = Column(Integer, nullable=False)
    offset_max_ns = Column(Integer, nullable=False)
    offset_min_ns = Column(Integer, nullable=False)


class PtpEventLog(Base):
    """イベントログ(要件定義書 7.3.1)"""

    __tablename__ = "ptp_event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    detail = Column(Text, nullable=False)  # JSON文字列


def init_db() -> None:
    Base.metadata.create_all(engine)
