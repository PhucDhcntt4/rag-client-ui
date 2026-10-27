from collections.abc import Iterator
from typing import Any

import psycopg  # type: ignore
from psycopg.rows import dict_row  # type: ignore

from app.config import get_settings


def get_database_connection(
) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Cấp một kết nối PostgreSQL cho mỗi request và tự đóng sau khi dùng."""
    settings = get_settings()

    with psycopg.connect(
        settings.database_url.get_secret_value(),
        row_factory=dict_row,
        autocommit=True,
    ) as connection:
        yield connection
