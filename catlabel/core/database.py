from sqlalchemy import URL
from sqlmodel import SQLModel, create_engine

from .paths import DATA_DIRECTORY

DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
sqlite_file_name = str(DATA_DIRECTORY / "catlabel.db")
_database_url = URL.create("sqlite", database=sqlite_file_name)
sqlite_url = _database_url.render_as_string(hide_password=False)
engine = create_engine(
    _database_url, echo=False, connect_args={"check_same_thread": False}
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
