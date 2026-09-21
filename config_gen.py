import argparse
import json
from pathlib import Path

from config import ConfigError, load_config


def generate_config(source: str = "app.json", output: str = "app.generated.json") -> Path:
    """Validate the global config and write a formatted copy."""
    config = load_config(source)
    output_path = Path(output).expanduser()
    with output_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a validated installer config")
    parser.add_argument("--source", default="app.json")
    parser.add_argument("--output", default="app.generated.json")
    args = parser.parse_args()
    try:
        output_path = generate_config(args.source, args.output)
    except (ConfigError, OSError) as error:
        print(f"config generation failed: {error}")
        return 1
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())