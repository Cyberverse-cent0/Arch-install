
import os
import subprocess
from typing import Any

from lib.print_fn import pr_dry, pr_error, pr_info


def _run_command(
    command: list[str],
    function_name: str,
    dry_run: bool = False,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str] | None:
    """Run a command safely, or preview it in dry-run mode."""

    if dry_run:
        # Do not log commands containing passwords.
        pr_dry(
            f"Would execute: {command[0]} "
            f"(arguments hidden)",
            function_name,
        )
        return None

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )

    except subprocess.TimeoutExpired:
        pr_error(
            f"Command timed out: {command[0]}",
            function_name,
        )

    except FileNotFoundError:
        pr_error(
            f"Required command not found: {command[0]}",
            function_name,
        )

    except subprocess.CalledProcessError as error:
        # Avoid printing command arguments because they
        # could contain sensitive information.
        message = error.stderr.strip() if error.stderr else str(error)

        pr_error(
            f"Command failed: {message}",
            function_name,
        )

    except OSError as error:
        pr_error(
            f"Unable to execute command: {error}",
            function_name,
        )

    return None


def set_time_date(dry_run: bool = False) -> bool:
    """Enable network time synchronization."""

    result = _run_command(
        ["timedatectl", "set-ntp", "true"],
        "set_time_date",
        dry_run,
    )

    if dry_run:
        pr_dry(
            "Would enable NTP synchronization.",
            "set_time_date",
        )
        return True

    if result is None:
        return False

    pr_info(
        "Network time synchronization enabled.",
        "set_time_date",
    )
    return True


def check_internet_connection(
    dry_run: bool = False,
) -> bool:
    """Check connectivity using ICMP."""

    if dry_run:
        pr_dry(
            "Would check internet connectivity using ping.",
            "check_internet_connection",
        )
        return True

    try:
        subprocess.run(
            ["ping", "-c", "2", "-W", "3", "8.8.8.8"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )

        pr_info(
            "Internet connection is active.",
            "check_internet_connection",
        )
        return True

    except subprocess.CalledProcessError:
        pr_error(
            "No internet connection detected.",
            "check_internet_connection",
        )

    except FileNotFoundError:
        pr_error(
            "ping command not found.",
            "check_internet_connection",
        )

    except subprocess.TimeoutExpired:
        pr_error(
            "Internet connection check timed out.",
            "check_internet_connection",
        )

    except OSError as error:
        pr_error(
            f"Unable to check internet connection: {error}",
            "check_internet_connection",
        )

    return False


def connect_to_wifi(
    ssid: str,
    password: str,
    device: str | None = None,
    dry_run: bool = False,
) -> bool:
    """
    Connect to a Wi-Fi network using iwd.

    Note:
        The password is passed to iwctl as a command-line
        argument. Avoid using this method on systems where
        other users can inspect process arguments.
    """

    if not isinstance(ssid, str) or not ssid.strip():
        pr_error(
            "SSID cannot be empty.",
            "connect_to_wifi",
        )
        return False

    if not isinstance(password, str) or not password:
        pr_error(
            "Wi-Fi password cannot be empty.",
            "connect_to_wifi",
        )
        return False

    if dry_run:
        pr_dry(
            f"Would connect to Wi-Fi network '{ssid}'. "
            "Password hidden.",
            "connect_to_wifi",
        )
        return True

    # If already connected to the internet, no need
    # to initiate another connection.
    if check_internet_connection():
        pr_info(
            "Internet connection is already active.",
            "connect_to_wifi",
        )
        return True

    # Ensure iwd is running.
    start_result = _run_command(
        ["systemctl", "start", "iwd"],
        "connect_to_wifi",
    )

    if start_result is None:
        return False

    # Select the requested device or discover one.
    if device is None:
        device = get_wifi_device()

    if not device:
        pr_error(
            "No Wi-Fi device found.",
            "connect_to_wifi",
        )
        return False

    # iwctl accepts the passphrase through this option.
    # The password is not printed by this module.
    result = _run_command(
        [
            "iwctl",
            "--passphrase",
            password,
            "station",
            device,
            "connect",
            ssid,
        ],
        "connect_to_wifi",
        timeout=60,
    )

    if result is None:
        return False

    pr_info(
        f"Wi-Fi connection requested for '{ssid}'.",
        "connect_to_wifi",
    )

    return True


def set_essentials(
    keymap: str,
    installation_font: str,
    dry_run: bool = False,
) -> bool:
    """Set the keyboard layout and console font."""

    if not keymap or not installation_font:
        pr_error(
            "Keyboard layout and font are required.",
            "set_essentials",
        )
        return False

    if dry_run:
        pr_dry(
            f"Would set keyboard layout to '{keymap}' "
            f"and console font to '{installation_font}'.",
            "set_essentials",
        )
        return True

    keymap_result = _run_command(
        ["loadkeys", keymap],
        "set_essentials",
    )

    if keymap_result is None:
        return False

    pr_info(
        f"Keyboard layout set to {keymap}.",
        "set_essentials",
    )

    font_result = _run_command(
        ["setfont", installation_font],
        "set_essentials",
    )

    if font_result is None:
        return False

    pr_info(
        f"Console font set to {installation_font}.",
        "set_essentials",
    )

    return True


def get_wifi_device() -> str | None:
    """Return the first wireless device reported by iwctl."""

    try:
        result = subprocess.run(
            ["iwctl", "device", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )

        # Parse the device list, rather than assuming wlan0.
        for line in result.stdout.splitlines():
            parts = line.split()

            if parts and parts[0].startswith(("wlan", "wlp")):
                return parts[0]

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError,
    ) as error:
        pr_error(
            f"Unable to discover Wi-Fi devices: {error}",
            "get_wifi_device",
        )

    return None


def get_all_wifi(
    device: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Scan for Wi-Fi networks using iwd."""

    if dry_run:
        pr_dry(
            "Would scan for available Wi-Fi networks.",
            "get_all_wifi",
        )
        return []

    if device is None:
        device = get_wifi_device()

    if not device:
        pr_error(
            "No Wi-Fi device found.",
            "get_all_wifi",
        )
        return []

    result = _run_command(
        [
            "iwctl",
            "station",
            device,
            "get-networks",
        ],
        "get_all_wifi",
        timeout=30,
    )

    if result is None:
        return []

    wifi_list = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    pr_info(
        f"Retrieved Wi-Fi networks for {device}.",
        "get_all_wifi",
    )

    return wifi_list


# Backward-compatible alias for the old misspelling.
set_essetials = set_essentials