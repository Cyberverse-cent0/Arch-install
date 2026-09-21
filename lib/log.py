import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = "/var/log/arch_installer_jhiuqdiua"
LOG_FILE = "installer_log.log"
LOG_PATH = os.path.join(LOG_DIR, LOG_FILE)

# --- ANSI color formatter ----------------------------------------------------
class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG:    "\033[34m",  # blue
        logging.INFO:     "\033[32m",  # green
        logging.WARNING:  "\033[33m",  # yellow
        logging.ERROR:    "\033[31m",  # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, datefmt: str, use_color: bool = True):
        super().__init__(fmt, datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            color = self.COLORS.get(record.levelno, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logger(name: str = "installer") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(logging.DEBUG)

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Console handler (colored if TTY)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColorFormatter(fmt, datefmt, use_color=sys.stdout.isatty()))
    logger.addHandler(console)

    # File handler (no color, rotating)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3
        )
        file_handler.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning("Could not open log file %s: %s", LOG_PATH, e)

    return logger


def log(message: str, func_name: str, log_level: str) -> None:
    logger = setup_logger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.log(level, f"{func_name}: {message}")
    
