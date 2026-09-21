import os
import sys
from . import log

# --- ANSI colors -------------------------------------------------------------
COLORS = {
    "reset":  "\033[0m",
    "red":    "\033[31m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "blue":   "\033[34m",
    "cyan":   "\033[36m",
}

# Disable colors automatically if not a TTY (e.g. piped to a file)
if not sys.stdout.isatty():
    COLORS = {k: "" for k in COLORS}


# --- Print helpers -----------------------------------------------------------
def _print(tag: str, message: str, color: str) -> None:
    print(f"{color}{tag}{COLORS['reset']} {message}")


def pr_info(message: str, func_name: str) -> None:
    log.log(message, func_name, "info")
    _print("[INFO]", message, COLORS["green"])


def pr_warn(message: str, func_name: str) -> None:
    log.log(message, func_name, "warning")
    _print("[WARN]", message, COLORS["yellow"])


def pr_error(message: str, func_name: str) -> None:
    log.log(message, func_name, "error")
    _print("[ERROR]", message, COLORS["red"])


def pr_debug(message: str, func_name: str) -> None:
    if os.getenv("DEBUG", "0") != "1":
        return
    log.log(message, func_name, "debug")
    _print("[DEBUG]", message, COLORS["blue"])


def pr_dry(message: str, func_name: str) -> None:
    log.log(message, func_name, "info")
    print(message)