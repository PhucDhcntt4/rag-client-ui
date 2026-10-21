"""Application logging independent from Uvicorn's logger configuration."""

from __future__ import annotations

import logging


HANDLER_MARKER = "rag_client_console_handler"


def configure_application_logging(level: str) -> None:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not any(
        getattr(handler, "name", None) == HANDLER_MARKER
        for handler in app_logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.name = HANDLER_MARKER
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        app_logger.addHandler(handler)

    app_logger.propagate = False
