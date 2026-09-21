import os
import subprocess
import shutil
from typing import Optional

from lib.print_fn import pr_error, pr_info


def _run_command(command: list[str], function_name: str, timeout: int = 300, dry_run: bool = False) -> bool:
    """Run a command with error handling."""
    if dry_run:
        pr_info(f"Dry run: would execute {command[0]}", function_name)
        return True
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        pr_error(f"Command failed: {error}", function_name)
        return False

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        pr_error(f"Command failed: {message}", function_name)
        return False
    return True


def create_user(
    username: str,
    *,
    password: Optional[str] = None,
    home_dir: Optional[str] = None,
    shell: str = "/bin/bash",
    groups: Optional[list[str]] = None,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create a new user with optional password and group membership."""
    function_name = "create_user"
    
    if not username:
        pr_error("Username is required", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would create user {username}", function_name)
        if password:
            pr_info(f"Dry run: would set password for {username}", function_name)
        if groups:
            pr_info(f"Dry run: would add {username} to groups: {', '.join(groups)}", function_name)
        return True
    
    if not confirm:
        pr_error("User creation requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("User creation requires root privileges", function_name)
        return False
    
    # Check if user already exists
    try:
        result = subprocess.run(["id", username], capture_output=True, text=True)
        if result.returncode == 0:
            pr_error(f"User {username} already exists", function_name)
            return False
    except OSError:
        pass
    
    # Create user
    useradd_cmd = ["useradd", "-m", "-s", shell]
    if home_dir:
        useradd_cmd.extend(["-d", home_dir])
    useradd_cmd.append(username)
    
    if not _run_command(useradd_cmd, function_name, timeout, dry_run):
        return False
    
    # Set password if provided
    if password:
        if not set_user_password(username, password, confirm=confirm, timeout=timeout, dry_run=dry_run):
            return False
    
    # Add to groups if specified
    if groups:
        for group in groups:
            if not add_user_to_group(username, group, confirm=confirm, timeout=timeout, dry_run=dry_run):
                pr_error(f"Failed to add {username} to group {group}", function_name)
    
    pr_info(f"User {username} created successfully", function_name)
    return True


def set_user_password(
    username: str,
    password: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Set password for a user."""
    function_name = "set_user_password"
    
    if not username or not password:
        pr_error("Username and password are required", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would set password for {username}", function_name)
        return True
    
    if not confirm:
        pr_error("Password setting requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("Password setting requires root privileges", function_name)
        return False
    
    # Use chpasswd to set password
    echo_cmd = ["echo", f"{username}:{password}"]
    chpasswd_cmd = ["chpasswd"]
    
    try:
        echo_proc = subprocess.Popen(echo_cmd, stdout=subprocess.PIPE, text=True)
        result = subprocess.run(
            chpasswd_cmd,
            stdin=echo_proc.stdout,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        echo_proc.wait()
    except (OSError, subprocess.TimeoutExpired) as error:
        pr_error(f"Password setting failed: {error}", function_name)
        return False
    
    if result.returncode != 0:
        pr_error(f"Password setting failed: {result.stderr.strip()}", function_name)
        return False
    
    pr_info(f"Password set for {username}", function_name)
    return True


def create_group(
    groupname: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create a new group."""
    function_name = "create_group"
    
    if not groupname:
        pr_error("Group name is required", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would create group {groupname}", function_name)
        return True
    
    if not confirm:
        pr_error("Group creation requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("Group creation requires root privileges", function_name)
        return False
    
    # Check if group already exists
    try:
        result = subprocess.run(["getent", "group", groupname], capture_output=True, text=True)
        if result.returncode == 0:
            pr_info(f"Group {groupname} already exists", function_name)
            return True
    except OSError:
        pass
    
    if not _run_command(["groupadd", groupname], function_name, timeout, dry_run):
        return False
    
    pr_info(f"Group {groupname} created successfully", function_name)
    return True


def add_user_to_group(
    username: str,
    groupname: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Add a user to a group."""
    function_name = "add_user_to_group"
    
    if not username or not groupname:
        pr_error("Username and group name are required", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would add {username} to group {groupname}", function_name)
        return True
    
    if not confirm:
        pr_error("Group membership modification requires confirm=True", function_name)
        return False
    
    if os.geteuid() != 0:
        pr_error("Group membership modification requires root privileges", function_name)
        return False
    
    if not _run_command(["usermod", "-aG", groupname, username], function_name, timeout, dry_run):
        return False
    
    pr_info(f"Added {username} to group {groupname}", function_name)
    return True


def setup_default_groups(
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Create default system groups for a typical desktop environment."""
    function_name = "setup_default_groups"
    
    default_groups = [
        "wheel",       # sudo access
        "audio",       # audio devices
        "video",       # video devices
        "storage",     # storage devices
        "network",     # network management
        "lp",          # printers
        "scanner",     # scanners
        "users",       # regular users
    ]
    
    if dry_run:
        pr_info(f"Dry run: would create default groups: {', '.join(default_groups)}", function_name)
        return True
    
    if not confirm:
        pr_error("Default group setup requires confirm=True", function_name)
        return False
    
    for group in default_groups:
        create_group(group, confirm=confirm, timeout=timeout, dry_run=dry_run)
    
    pr_info("Default groups created successfully", function_name)
    return True


def setup_sudo_access(
    username: str,
    *,
    confirm: bool = False,
    timeout: int = 300,
    dry_run: bool = False,
) -> bool:
    """Grant sudo access to a user by adding them to wheel group."""
    function_name = "setup_sudo_access"
    
    if not username:
        pr_error("Username is required", function_name)
        return False
    
    if dry_run:
        pr_info(f"Dry run: would grant sudo access to {username}", function_name)
        return True
    
    if not confirm:
        pr_error("Sudo access setup requires confirm=True", function_name)
        return False
    
    # Add user to wheel group
    if not add_user_to_group(username, "wheel", confirm=confirm, timeout=timeout, dry_run=dry_run):
        return False
    
    # Ensure wheel group has sudo privileges in sudoers
    sudoers_file = "/etc/sudoers.d/wheel"
    sudoers_content = "%wheel ALL=(ALL:ALL) ALL\n"
    
    if dry_run:
        pr_info(f"Dry run: would configure sudoers for wheel group", function_name)
        return True
    
    try:
        # Create sudoers.d directory if it doesn't exist
        os.makedirs("/etc/sudoers.d", exist_ok=True)
        
        # Write wheel sudoers file
        with open(sudoers_file, "w") as f:
            f.write(sudoers_content)
        
        # Set proper permissions
        os.chmod(sudoers_file, 0o440)
        
        pr_info(f"Sudo access configured for {username}", function_name)
        return True
    except OSError as error:
        pr_error(f"Failed to configure sudoers: {error}", function_name)
        return False
