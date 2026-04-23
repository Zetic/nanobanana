import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional
import config

# Third-party loggers that produce excessive output and should only show warnings
_SUPPRESSED_LOGGERS = [
    'discord',
    'discord.client',
    'discord.gateway',
    'discord.http',
    'discord.voice_client',
    'discord.ext',
    'aiohttp',
    'aiohttp.access',
    'aiohttp.client',
    'aiohttp.connector',
    'google',
    'google.auth',
    'openai',
    'openai._base_client',
    'httpcore',
    'httpx',
    'websockets',
    'asyncio',
    'urllib3',
    'PIL',
    'charset_normalizer',
]

LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 5 MB per file, keep 3 rotated backups (max ~20 MB total on disk)
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


class LogManager:
    """Manages rotating log files for the bot."""

    def __init__(self):
        self.file_handler: Optional[logging.handlers.RotatingFileHandler] = None
        self._setup_logging()

    def _setup_logging(self):
        """Configure root logger with a rotating file handler and a console handler."""
        os.makedirs(config.LOGS_DIR, exist_ok=True)

        formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

        # Rotating file handler: caps each file at 5 MB, keeps 3 backups
        log_file = os.path.join(config.LOGS_DIR, 'bot.log')
        self.file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding='utf-8',
        )
        self.file_handler.setFormatter(formatter)
        self.file_handler.setLevel(logging.INFO)

        # Console handler (stdout) so logs are still visible when running interactively
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        # Replace any handlers already on the root logger to avoid duplicates
        root_logger = logging.getLogger()
        root_logger.handlers.clear()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self.file_handler)
        root_logger.addHandler(console_handler)

        # Quiet down noisy third-party libraries
        for name in _SUPPRESSED_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

        self._write_startup_banner()

    def _write_startup_banner(self):
        """Write a visible separator and timestamp whenever the bot (re)starts."""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sep = '=' * 72
        logging.info(
            '\n%s\n  NANOBANANA BOT  |  Started %s\n%s', sep, now, sep
        )

    def get_current_log_file(self) -> Optional[str]:
        """Return the path of the active log file."""
        if self.file_handler:
            return self.file_handler.baseFilename
        return None

    def get_most_recent_log_file(self) -> Optional[str]:
        """Return the path of the active log file (kept for /log command compatibility)."""
        return self.get_current_log_file()

    def set_debug_logging(self, enabled: bool = True) -> None:
        """
        Enable or disable debug-level logging.

        When enabled, verbose diagnostic output from bot modules will be written
        to the log.  Third-party library suppression is preserved regardless.

        Args:
            enabled: True to enable DEBUG level, False to restore INFO level.
        """
        level = logging.DEBUG if enabled else logging.INFO

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        if self.file_handler:
            self.file_handler.setLevel(level)

        # Keep third-party loggers quiet even in debug mode
        for name in _SUPPRESSED_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

        status = "enabled" if enabled else "disabled"
        logging.info("Debug logging %s", status)


# Global instance – importing this module configures logging for the whole app
log_manager = LogManager()