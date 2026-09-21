import os
import sys
from . import log


# --- Print helpers -----------------------------------------------------------

def pr_info(message: str, func_name: str) -> None:
    if not message:
        return
    log.log(message, func_name, "info")


def pr_warn(message: str, func_name: str) -> None:
    if not message:
        return
    log.log(message, func_name, "warning")


def pr_error(message: str, func_name: str) -> None:
    if not message:
        return
    log.log(message, func_name, "error")


def pr_debug(message: str, func_name: str) -> None:
    if not message:
        return
    if os.getenv("DEBUG", "0") != "1":
        return
    log.log(message, func_name, "debug")


def pr_dry(message: str, func_name: str) -> None:
    if not message:
        return
    log.log(message, func_name, "info")
