
import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the installer configuration is invalid."""


def _reject_json_constant(value: str) -> None:
    """Reject non-standard JSON constants such as NaN and Infinity."""
    raise ValueError(f"Invalid JSON constant: {value}")


def _validate_bool(
    value: Any,
    field_name: str,
) -> None:
    """Validate a strict boolean value."""
    if not isinstance(value, bool):
        raise ConfigError(
            f"'{field_name}' must be true or false"
        )


def validate_config(config: Any) -> dict[str, Any]:
    """
    Validate the structure and types of the installer configuration.

    This function does not execute installer operations.
    """

    if not isinstance(config, dict):
        raise ConfigError(
            "Configuration root must be a JSON object"
        )

    # Validate application settings.
    application = config.get("application", {})

    if not isinstance(application, dict):
        raise ConfigError(
            "'application' must be a JSON object"
        )

    _validate_bool(
        application.get("require_root", True),
        "application.require_root",
    )

    # Validate general settings.
    settings = config.get("settings", {})

    if not isinstance(settings, dict):
        raise ConfigError(
            "'settings' must be a JSON object"
        )

    _validate_bool(
        settings.get("dry_run", True),
        "settings.dry_run",
    )

    _validate_bool(
        settings.get("stop_on_error", True),
        "settings.stop_on_error",
    )

    # Validate operation list.
    operations = config.get("operations", [])

    if not isinstance(operations, list):
        raise ConfigError(
            "'operations' must be a JSON array"
        )

    for index, operation in enumerate(operations):
        operation_name = f"operations[{index}]"

        if not isinstance(operation, dict):
            raise ConfigError(
                f"{operation_name} must be a JSON object"
            )

        function_name = operation.get("function")

        if (
            not isinstance(function_name, str)
            or not function_name.strip()
        ):
            raise ConfigError(
                f"{operation_name} needs a non-empty "
                "string 'function'"
            )

        parameters = operation.get("parameters", {})

        if not isinstance(parameters, dict):
            raise ConfigError(
                f"{operation_name}.parameters "
                "must be a JSON object"
            )

    return config


def load_config(path: str | Path) -> dict[str, Any]:
    """
    Load and validate an installer JSON configuration.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        A validated configuration dictionary.

    Raises:
        ConfigError: If the file cannot be read or its
                     contents are invalid.
    """

    if not isinstance(path, (str, Path)):
        raise ConfigError(
            "Configuration path must be a string or Path"
        )

    if isinstance(path, str) and not path.strip():
        raise ConfigError(
            "Configuration path cannot be empty"
        )

    config_path = Path(path).expanduser()

    try:
        with config_path.open(
            "r",
            encoding="utf-8",
        ) as config_file:

            config = json.load(
                config_file,
                parse_constant=_reject_json_constant,
            )

    except FileNotFoundError as error:
        raise ConfigError(
            f"Configuration file not found: {config_path}"
        ) from error

    except IsADirectoryError as error:
        raise ConfigError(
            f"Configuration path is a directory: {config_path}"
        ) from error

    except PermissionError as error:
        raise ConfigError(
            f"Permission denied reading: {config_path}"
        ) from error

    except UnicodeDecodeError as error:
        raise ConfigError(
            f"Configuration file is not valid UTF-8: {config_path}"
        ) from error

    except json.JSONDecodeError as error:
        raise ConfigError(
            f"Invalid JSON in {config_path}: "
            f"line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error

    except ValueError as error:
        # Includes rejected NaN and Infinity constants.
        raise ConfigError(
            f"Invalid JSON value in {config_path}: {error}"
        ) from error

    except OSError as error:
        raise ConfigError(
            f"Unable to read configuration {config_path}: {error}"
        ) from error

    return validate_config(config)