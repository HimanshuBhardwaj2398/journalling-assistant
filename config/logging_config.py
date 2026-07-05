"""Central logging configuration.

One place to control format, level, and third-party noise.
Entry points (scripts, orchestrator __main__, Streamlit app) call
setup_logging() once; library modules just use logging.getLogger(__name__).

Level resolution order: explicit argument > LOG_LEVEL env var > INFO.
"""

import logging
import os

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Third-party loggers that are noisy at INFO
_QUIET_LIBS = ("httpx", "urllib3", "httpcore", "sentence_transformers")


def setup_logging(level: str | int | None = None) -> None:
    """Configure root logging for an entry point.

    Args:
        level: Logging level name or constant. Falls back to the
            LOG_LEVEL environment variable, then INFO.

    Idempotent: safe to call more than once (force=True re-applies handlers,
    which matters under Streamlit's re-execution model).
    """
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(level=level, format=LOG_FORMAT, force=True)

    for lib in _QUIET_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)
