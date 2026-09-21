# Codecrafters Arch Installer

A JSON-driven Arch Linux installation helper. The application can inspect the host, prepare storage, install packages and desktop environments, configure GRUB, and collect a non-secret system profile.

## Quick Start

Run the global configuration in its safe default mode:

```bash
python3 main.py
```

Use another configuration file with:

```bash
python3 main.py --config path/to/config.json
```

Validate and format a configuration copy:

```bash
python3 config_gen.py --source app.json --output app.generated.json
```

The default `app.json` uses `"dry_run": true`. Read-only operations run, while disk, package, AUR, and bootloader changes are skipped.

## Project Layout

- `main.py`: command-line entry point, function registry, dry-run gate, and operation dispatcher.
- `config.py`: JSON loading and top-level configuration validation.
- `app.json`: global application workflow.
- `config_gen.py`: validates and writes a formatted configuration copy.
- `src/disk/`: disk discovery, encryption, LVM, Btrfs, fstab, and partition planning.
- `src/pkgs/`: pacman packages, desktop environments, and AUR helper setup.
- `src/boot/`: BIOS and UEFI GRUB installation.
- `src/profile/`: non-secret user and system profile collection.
- `lib/`: logging and terminal output helpers.

## Execution Model

Each operation in JSON names a function registered in `main.py` and supplies keyword arguments in `parameters`. The runner resolves the function, skips functions marked destructive when dry-run is enabled, and stops when an operation returns `False`.

The storage and boot operations are destructive. They require both root privileges and an explicit `confirm: true` parameter. Package and AUR installation have their own confirmation and user checks.

## Requirements

- Python 3.10 or newer
- Arch Linux for real installation operations
- Root privileges for system changes
- `pacman` for official packages
- `git`, `makepkg`, and a non-root build account for AUR helpers
- `grub-install` and `grub-mkconfig` for bootloader setup

Check syntax before running changes:

```bash
python3 -m py_compile main.py config.py config_gen.py lib/*.py src/boot/*.py src/disk/*.py src/pkgs/*.py src/profile/*.py
```

Read [docs/CONFIGURATION.md](docs/CONFIGURATION.md) before changing `dry_run` to `false`.
