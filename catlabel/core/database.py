import os

from sqlmodel import SQLModel, create_engine

os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/catlabel.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(
    sqlite_url, echo=False, connect_args={"check_same_thread": False}
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _ensure_column(
        "printerprofile",
        "paper_mode",
        "ALTER TABLE printerprofile ADD COLUMN paper_mode VARCHAR",
    )
    _ensure_column(
        "project",
        "revision",
        "ALTER TABLE project ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
    )


def _ensure_column(table_name: str, column_name: str, ddl: str) -> None:
    with engine.begin() as connection:
        columns = connection.exec_driver_sql(f"PRAGMA table_info({table_name})").all()
        if any(row[1] == column_name for row in columns):
            return
        connection.exec_driver_sql(ddl)
