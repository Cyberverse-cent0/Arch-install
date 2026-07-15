#!/usr/bin/env bash
#
# install_arch.sh - Production-ready Arch Linux Installation Script
# Complete automated installation with LUKS2, LVM2, UEFI, GRUB
#
# Author: Expert Linux Systems Engineer
# Version: 1.0.0
# License: MIT
#
# Description:
#   Performs a complete Arch Linux installation with full disk encryption,
#   LVM2 logical volumes, and UEFI boot using GRUB2 bootloader.
#   Supports both Intel and AMD CPU microcode detection.
#

# ============================================================================
# STRICT MODE AND ERROR HANDLING
# ============================================================================
set -Eeuo pipefail

# Trap errors for proper cleanup
trap 'error_handler ${LINENO} "${BASH_COMMAND}"' ERR

# ============================================================================
# GLOBAL VARIABLES
# ============================================================================
SCRIPT_NAME="$(basename "${0}")"
SCRIPT_VERSION="1.0.0"
LOG_FILE="/var/log/arch_install_$(date +%Y%m%d_%H%M%S).log"

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly WHITE='\033[1;37m'
readonly NC='\033[0m' # No Color

# Installation configuration variables
DISK=""
HOSTNAME=""
USERNAME=""
ROOT_PASSWORD=""
USER_PASSWORD=""
LUKS_PASSWORD=""
TIMEZONE=""
LOCALE=""
CPU_VENDOR=""
MICROCODE_PACKAGE=""
LUKS_UUID=""

# Partition and LVM variables
EFI_PART=""
LUKS_PART=""
LUKS_NAME="crypt_root"
VG_NAME="volume_group"
LV_ROOT="root"
LV_VAR="var"
LV_SWAP="swap"
LV_HOME="home"

# ============================================================================
# LOGGING FUNCTIONS
# ============================================================================
log_info() {
    local message="$1"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${GREEN}[INFO]${NC} ${timestamp} - ${message}" | tee -a "${LOG_FILE}"
}

log_warn() {
    local message="$1"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${YELLOW}[WARN]${NC} ${timestamp} - ${message}" | tee -a "${LOG_FILE}"
}

log_error() {
    local message="$1"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${RED}[ERROR]${NC} ${timestamp} - ${message}" | tee -a "${LOG_FILE}" >&2
}

log_success() {
    local message="$1"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo -e "${BLUE}[SUCCESS]${NC} ${timestamp} - ${message}" | tee -a "${LOG_FILE}"
}

log_step() {
    local message="$1"
    echo -e "\n${MAGENTA}========================================${NC}" | tee -a "${LOG_FILE}"
    echo -e "${MAGENTA}  STEP: ${message}${NC}" | tee -a "${LOG_FILE}"
    echo -e "${MAGENTA}========================================${NC}" | tee -a "${LOG_FILE}"
}

# ============================================================================
# ERROR HANDLING FUNCTION
# ============================================================================
error_handler() {
    local line_number="$1"
    local failed_command="$2"
    
    log_error "Script failed at line ${line_number}"
    log_error "Failed command: ${failed_command}"
    
    # Attempt cleanup if something was mounted
    cleanup_on_failure
    
    log_error "Installation failed. Please check ${LOG_FILE} for details"
    exit 1
}

# ============================================================================
# CLEANUP FUNCTION
# ============================================================================
cleanup_on_failure() {
    log_warn "Performing cleanup due to failure..."
    
    # Unmount all mounted filesystems
    if mountpoint -q /mnt/boot 2>/dev/null; then
        log_info "Unmounting /mnt/boot..."
        umount /mnt/boot || true
    fi
    
    if mountpoint -q /mnt/home 2>/dev/null; then
        log_info "Unmounting /mnt/home..."
        umount /mnt/home || true
    fi
    
    if mountpoint -q /mnt/var 2>/dev/null; then
        log_info "Unmounting /mnt/var..."
        umount /mnt/var || true
    fi
    
    if mountpoint -q /mnt 2>/dev/null; then
        log_info "Unmounting /mnt..."
        umount /mnt || true
    fi
    
    # Deactivate swap if active
    if swapon --show | grep -q "swap"; then
        log_info "Deactivating swap..."
        swapoff -a || true
    fi
    
    # Close LUKS container if open
    if cryptsetup status "${LUKS_NAME}" &>/dev/null; then
        log_info "Closing LUKS container ${LUKS_NAME}..."
        cryptsetup close "${LUKS_NAME}" || true
    fi
    
    # Deactivate volume group if active
    if vgdisplay "${VG_NAME}" &>/dev/null; then
        log_info "Deactivating volume group ${VG_NAME}..."
        vgchange -an "${VG_NAME}" || true
    fi
}

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================
validate_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
    log_success "Running with root privileges"
}

validate_uefi() {
    if [[ ! -d "/sys/firmware/efi" ]]; then
        log_error "System is not booted in UEFI mode"
        log_error "Please ensure you boot the Arch ISO in UEFI mode"
        exit 1
    fi
    log_success "UEFI boot mode detected"
}

validate_disk() {
    if [[ ! -b "${DISK}" ]]; then
        log_error "Disk ${DISK} does not exist or is not a block device"
        exit 1
    fi
    
    if [[ "${DISK}" == "/dev/sda" ]] || [[ "${DISK}" == "/dev/nvme0n1" ]]; then
        log_warn "You have selected ${DISK}"
        log_warn "This will destroy ALL data on this disk!"
    fi
}

# ============================================================================
# CPU AND SYSTEM DETECTION
# ============================================================================
detect_cpu() {
    log_info "Detecting CPU vendor..."
    
    local cpu_info
    cpu_info="$(grep -m1 "vendor_id" /proc/cpuinfo)"
    
    if echo "${cpu_info}" | grep -qi "intel"; then
        CPU_VENDOR="intel"
        MICROCODE_PACKAGE="intel-ucode"
        log_success "Intel CPU detected, will install ${MICROCODE_PACKAGE}"
    elif echo "${cpu_info}" | grep -qi "amd"; then
        CPU_VENDOR="amd"
        MICROCODE_PACKAGE="amd-ucode"
        log_success "AMD CPU detected, will install ${MICROCODE_PACKAGE}"
    else
        log_error "Unable to detect CPU vendor"
        log_error "CPU info: ${cpu_info}"
        exit 1
    fi
}

# ============================================================================
# DISK SELECTION
# ============================================================================
select_disk() {
    log_step "Disk Selection"
    
    echo -e "${CYAN}Available disks:${NC}"
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | grep -v "loop\|sr0\|rom"
    
    echo
    read -rp "$(echo -e "${WHITE}Enter target disk (e.g., /dev/sda, /dev/nvme0n1): ${NC}")" DISK
    
    if [[ -z "${DISK}" ]]; then
        log_error "No disk specified"
        exit 1
    fi
    
    validate_disk
    
    # Confirm disk selection
    echo
    echo -e "${RED}WARNING: This will completely erase ${DISK}${NC}"
    echo -e "${RED}ALL data will be permanently destroyed!${NC}"
    echo
    read -rp "$(echo -e "${WHITE}Type 'YES' to confirm: ${NC}")" confirmation
    
    if [[ "${confirmation}" != "YES" ]]; then
        log_error "Installation cancelled by user"
        exit 1
    fi
    
    log_success "Disk ${DISK} selected and confirmed"
}

# ============================================================================
# USER INPUT FUNCTIONS
# ============================================================================
gather_user_input() {
    log_step "Gathering Installation Parameters"
    
    read -rp "$(echo -e "${WHITE}Enter hostname: ${NC}")" HOSTNAME
    if [[ -z "${HOSTNAME}" ]]; then
        log_error "Hostname cannot be empty"
        exit 1
    fi
    
    read -rp "$(echo -e "${WHITE}Enter username: ${NC}")" USERNAME
    if [[ -z "${USERNAME}" ]]; then
        log_error "Username cannot be empty"
        exit 1
    fi
    
    echo -e "${WHITE}Enter root password:${NC}"
    read -rs ROOT_PASSWORD
    if [[ -z "${ROOT_PASSWORD}" ]]; then
        log_error "Root password cannot be empty"
        exit 1
    fi
    echo
    
    echo -e "${WHITE}Enter root password again:${NC}"
    read -rs root_password_confirm
    if [[ "${ROOT_PASSWORD}" != "${root_password_confirm}" ]]; then
        log_error "Root passwords do not match"
        exit 1
    fi
    echo
    
    echo -e "${WHITE}Enter user password for ${USERNAME}:${NC}"
    read -rs USER_PASSWORD
    if [[ -z "${USER_PASSWORD}" ]]; then
        log_error "User password cannot be empty"
        exit 1
    fi
    echo
    
    echo -e "${WHITE}Enter user password again:${NC}"
    read -rs user_password_confirm
    if [[ "${USER_PASSWORD}" != "${user_password_confirm}" ]]; then
        log_error "User passwords do not match"
        exit 1
    fi
    echo
    
    echo -e "${WHITE}Enter LUKS encryption password:${NC}"
    read -rs LUKS_PASSWORD
    if [[ -z "${LUKS_PASSWORD}" ]]; then
        log_error "LUKS password cannot be empty"
        exit 1
    fi
    echo
    
    echo -e "${WHITE}Enter LUKS password again:${NC}"
    read -rs luks_password_confirm
    if [[ "${LUKS_PASSWORD}" != "${luks_password_confirm}" ]]; then
        log_error "LUKS passwords do not match"
        exit 1
    fi
    echo
    
    read -rp "$(echo -e "${WHITE}Enter timezone (e.g., America/Chicago): ${NC}")" TIMEZONE
    if [[ -z "${TIMEZONE}" ]]; then
        TIMEZONE="UTC"
        log_warn "No timezone specified, using UTC"
    fi
    
    read -rp "$(echo -e "${WHITE}Enter locale (e.g., en_US.UTF-8): ${NC}")" LOCALE
    if [[ -z "${LOCALE}" ]]; then
        LOCALE="en_US.UTF-8"
        log_warn "No locale specified, using ${LOCALE}"
    fi
    
    log_success "All installation parameters gathered"
}

# ============================================================================
# NETWORK CHECK
# ============================================================================
check_network() {
    log_step "Checking Network Connectivity"
    
    if ! ping -c 3 archlinux.org &>/dev/null; then
        log_error "No network connectivity. Please ensure you have an internet connection."
        exit 1
    fi
    
    log_success "Network connectivity verified"
}

# ============================================================================
# SYSTEM CLOCK
# ============================================================================
update_system_clock() {
    log_step "Updating System Clock"
    
    timedatectl set-ntp true
    log_success "System clock synchronized"
}

# ============================================================================
# PARTITIONING
# ============================================================================
partition_disk() {
    log_step "Partitioning Disk ${DISK}"
    
    log_info "Wiping existing partition table and creating GPT..."
    
    # Destroy existing partition table
    sgdisk --zap-all "${DISK}" || {
        log_error "Failed to zap disk ${DISK}"
        exit 1
    }
    
    # Create GPT partition table
    parted "${DISK}" mklabel gpt || {
        log_error "Failed to create GPT partition table"
        exit 1
    }
    
    log_info "Creating EFI System Partition (1 GiB)..."
    parted "${DISK}" mkpart primary fat32 1MiB 1025MiB || {
        log_error "Failed to create EFI partition"
        exit 1
    }
    parted "${DISK}" set 1 esp on || {
        log_error "Failed to set ESP flag"
        exit 1
    }
    
    log_info "Creating LUKS partition (remaining space)..."
    parted "${DISK}" mkpart primary 1025MiB 100% || {
        log_error "Failed to create LUKS partition"
        exit 1
    }
    
    # Wait for kernel to update partition table
    sleep 2
    partprobe "${DISK}" || true
    
    # Determine partition naming scheme
    if [[ "${DISK}" == /dev/nvme* ]]; then
        EFI_PART="${DISK}p1"
        LUKS_PART="${DISK}p2"
    else
        EFI_PART="${DISK}1"
        LUKS_PART="${DISK}2"
    fi
    
    log_info "EFI partition: ${EFI_PART}"
    log_info "LUKS partition: ${LUKS_PART}"
    
    # Verify partitions exist
    if [[ ! -b "${EFI_PART}" ]]; then
        log_error "EFI partition ${EFI_PART} not found"
        exit 1
    fi
    
    if [[ ! -b "${LUKS_PART}" ]]; then
        log_error "LUKS partition ${LUKS_PART} not found"
        exit 1
    fi
    
    log_success "Partitioning completed successfully"
}

# ============================================================================
# ENCRYPTION
# ============================================================================
setup_encryption() {
    log_step "Setting up LUKS2 Encryption"
    
    log_info "Formatting ${LUKS_PART} with LUKS2..."
    
    # Format LUKS partition with password
    echo -n "${LUKS_PASSWORD}" | cryptsetup luksFormat \
        --type luks2 \
        --cipher aes-xts-plain64 \
        --hash sha512 \
        --key-size 512 \
        --pbkdf argon2id \
        --iter-time 5000 \
        "${LUKS_PART}" - || {
        log_error "LUKS format failed"
        exit 1
    }
    
    log_info "Opening LUKS container as ${LUKS_NAME}..."
    echo -n "${LUKS_PASSWORD}" | cryptsetup open "${LUKS_PART}" "${LUKS_NAME}" - || {
        log_error "Failed to open LUKS container"
        exit 1
    }
    
    # Get LUKS UUID for GRUB configuration
    LUKS_UUID="$(cryptsetup luksUUID "${LUKS_PART}")"
    log_info "LUKS UUID: ${LUKS_UUID}"
    
    if [[ -z "${LUKS_UUID}" ]]; then
        log_error "Failed to get LUKS UUID"
        exit 1
    fi
    
    log_success "LUKS2 encryption setup completed"
}

# ============================================================================
# LVM SETUP
# ============================================================================
setup_lvm() {
    log_step "Setting up LVM2"
    
    local luks_device="/dev/mapper/${LUKS_NAME}"
    
    log_info "Creating Physical Volume on ${luks_device}..."
    pvcreate "${luks_device}" || {
        log_error "Failed to create physical volume"
        exit 1
    }
    
    log_info "Creating Volume Group ${VG_NAME}..."
    vgcreate "${VG_NAME}" "${luks_device}" || {
        log_error "Failed to create volume group"
        exit 1
    }
    
    log_info "Creating Logical Volume ${LV_ROOT} (8GiB)..."
    lvcreate -L 8G -n "${LV_ROOT}" "${VG_NAME}" || {
        log_error "Failed to create root logical volume"
        exit 1
    }
    
    log_info "Creating Logical Volume ${LV_VAR} (4GiB)..."
    lvcreate -L 4G -n "${LV_VAR}" "${VG_NAME}" || {
        log_error "Failed to create var logical volume"
        exit 1
    }
    
    log_info "Creating Logical Volume ${LV_SWAP} (2GiB)..."
    lvcreate -L 2G -n "${LV_SWAP}" "${VG_NAME}" || {
        log_error "Failed to create swap logical volume"
        exit 1
    }
    
    log_info "Creating Logical Volume ${LV_HOME} (remaining space)..."
    lvcreate -l 100%FREE -n "${LV_HOME}" "${VG_NAME}" || {
        log_error "Failed to create home logical volume"
        exit 1
    }
    
    log_success "LVM2 setup completed"
}

# ============================================================================
# FILESYSTEM CREATION
# ============================================================================
create_filesystems() {
    log_step "Creating Filesystems"
    
    log_info "Formatting EFI partition (FAT32)..."
    mkfs.fat -F32 "${EFI_PART}" || {
        log_error "Failed to format EFI partition"
        exit 1
    }
    
    log_info "Formatting root LV (ext4)..."
    mkfs.ext4 "/dev/${VG_NAME}/${LV_ROOT}" || {
        log_error "Failed to format root filesystem"
        exit 1
    }
    
    log_info "Formatting var LV (ext4)..."
    mkfs.ext4 "/dev/${VG_NAME}/${LV_VAR}" || {
        log_error "Failed to format var filesystem"
        exit 1
    }
    
    log_info "Formatting home LV (Btrfs)..."
    mkfs.btrfs "/dev/${VG_NAME}/${LV_HOME}" || {
        log_error "Failed to format home filesystem"
        exit 1
    }
    
    log_info "Setting up swap..."
    mkswap "/dev/${VG_NAME}/${LV_SWAP}" || {
        log_error "Failed to setup swap"
        exit 1
    }
    
    log_success "All filesystems created successfully"
}

# ============================================================================
# MOUNTING
# ============================================================================
mount_filesystems() {
    log_step "Mounting Filesystems"
    
    log_info "Mounting root filesystem..."
    mount "/dev/${VG_NAME}/${LV_ROOT}" /mnt || {
        log_error "Failed to mount root"
        exit 1
    }
    
    log_info "Creating mount points..."
    mkdir -p /mnt/{boot,var,home} || {
        log_error "Failed to create mount points"
        exit 1
    }
    
    log_info "Mounting EFI partition..."
    mount "${EFI_PART}" /mnt/boot || {
        log_error "Failed to mount EFI partition"
        exit 1
    }
    
    log_info "Mounting home filesystem..."
    mount "/dev/${VG_NAME}/${LV_HOME}" /mnt/home || {
        log_error "Failed to mount home"
        exit 1
    }
    
    log_info "Mounting var filesystem..."
    mount "/dev/${VG_NAME}/${LV_VAR}" /mnt/var || {
        log_error "Failed to mount var"
        exit 1
    }
    
    log_info "Enabling swap..."
    swapon "/dev/${VG_NAME}/${LV_SWAP}" || {
        log_error "Failed to enable swap"
        exit 1
    }
    
    log_success "All filesystems mounted successfully"
}

# ============================================================================
# PACKAGE INSTALLATION
# ============================================================================
install_base_system() {
    log_step "Installing Base System"
    
    log_info "Refreshing package database..."
    pacman -Sy || {
        log_error "Failed to refresh package database"
        exit 1
    }
    
    local packages=(
        "base"
        "base-devel"
        "linux"
        "linux-firmware"
        "linux-headers"
        "grub"
        "efibootmgr"
        "lvm2"
        "cryptsetup"
        "btrfs-progs"
        "networkmanager"
        "sudo"
        "vim"
        "nano"
        "git"
        "man-db"
        "man-pages"
        "texinfo"
        "openssh"
        "bash-completion"
        "reflector"
        "curl"
        "wget"
        "htop"
        "fastfetch"
        "tree"
        "dosfstools"
        "e2fsprogs"
        "mtools"
        "${MICROCODE_PACKAGE}"
    )
    
    log_info "Installing packages: ${packages[*]}"
    
    pacstrap /mnt "${packages[@]}" || {
        log_error "Package installation failed"
        exit 1
    }
    
    log_success "Base system installed successfully"
}

# ============================================================================
# FSTAB GENERATION
# ============================================================================
generate_fstab() {
    log_step "Generating fstab"
    
    genfstab -U /mnt >> /mnt/etc/fstab || {
        log_error "Failed to generate fstab"
        exit 1
    }
    
    log_info "Generated fstab:"
    cat /mnt/etc/fstab | tee -a "${LOG_FILE}"
    
    log_success "fstab generated successfully"
}

# ============================================================================
# CHROOT CONFIGURATION
# ============================================================================
configure_system() {
    log_step "Configuring System in chroot"
    
    # Create a script to run in chroot
    cat > /mnt/root/chroot_setup.sh << 'CHROOT_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

# Color codes for chroot
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_success() { echo -e "${BLUE}[SUCCESS]${NC} $1"; }

# Get variables passed from parent script
HOSTNAME="$1"
USERNAME="$2"
ROOT_PASSWORD="$3"
USER_PASSWORD="$4"
TIMEZONE="$5"
LOCALE="$6"
LUKS_UUID="$7"
VG_NAME="$8"

log_info "Starting chroot configuration..."

# Timezone
log_info "Setting timezone to ${TIMEZONE}..."
ln -sf "/usr/share/zoneinfo/${TIMEZONE}" /etc/localtime || {
    log_error "Failed to set timezone"
    exit 1
}
hwclock --systohc || {
    log_error "Failed to set hardware clock"
    exit 1
}

# Locale
log_info "Configuring locale ${LOCALE}..."
sed -i "s/^#${LOCALE} UTF-8/${LOCALE} UTF-8/" /etc/locale.gen
locale-gen || {
    log_error "Failed to generate locale"
    exit 1
}
echo "LANG=${LOCALE}" > /etc/locale.conf

# Virtual console
log_info "Configuring virtual console..."
echo "KEYMAP=us" > /etc/vconsole.conf
echo "FONT=lat9w-16" >> /etc/vconsole.conf

# Hostname
log_info "Setting hostname to ${HOSTNAME}..."
echo "${HOSTNAME}" > /etc/hostname

# Hosts file
log_info "Configuring /etc/hosts..."
cat > /etc/hosts << HOSTS_EOF
127.0.0.1   localhost
::1         localhost
127.0.1.1   ${HOSTNAME}.localdomain ${HOSTNAME}
HOSTS_EOF

# Root password
log_info "Setting root password..."
echo "root:${ROOT_PASSWORD}" | chpasswd || {
    log_error "Failed to set root password"
    exit 1
}

# User account
log_info "Creating user ${USERNAME}..."
useradd -m -G wheel -s /bin/bash "${USERNAME}" || {
    log_error "Failed to create user"
    exit 1
}
echo "${USERNAME}:${USER_PASSWORD}" | chpasswd || {
    log_error "Failed to set user password"
    exit 1
}

# Sudo configuration
log_info "Configuring sudo..."
echo "%wheel ALL=(ALL:ALL) ALL" >> /etc/sudoers.d/wheel
echo "%wheel ALL=(ALL:ALL) NOPASSWD: /usr/bin/pacman" >> /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

# Pacman configuration
log_info "Configuring pacman..."
sed -i 's/^#Color/Color/' /etc/pacman.conf
sed -i 's/^#ParallelDownloads = 5/ParallelDownloads = 5/' /etc/pacman.conf
sed -i 's/^#VerbosePkgLists/VerbosePkgLists/' /etc/pacman.conf

# Enable multilib repository
sed -i '/\[multilib\]/,/Include/s/^#//' /etc/pacman.conf

# Makepkg configuration
log_info "Configuring makepkg..."
sed -i "s/^#MAKEFLAGS=\"-j2\"/MAKEFLAGS=\"-j$(nproc)\"/" /etc/makepkg.conf
sed -i 's/^COMPRESSXZ=(xz -c -z -)/COMPRESSXZ=(xz -c -z - --threads=0)/' /etc/makepkg.conf

# Journald configuration
log_info "Configuring journald..."
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/00-journal-size.conf << JOURNALD_EOF
[Journal]
SystemMaxUse=100M
MaxFileSec=7day
ForwardToSyslog=no
JOURNALD_EOF

# Machine ID
log_info "Generating machine-id..."
systemd-machine-id-setup || {
    log_error "Failed to generate machine-id"
    exit 1
}

# Create useful aliases
log_info "Creating useful aliases..."
cat > /etc/profile.d/aliases.sh << 'ALIASES_EOF'
#!/bin/bash
alias ll='ls -la --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
alias pacupg='sudo pacman -Syu'
alias pacins='sudo pacman -S'
alias pacrem='sudo pacman -Rns'
alias pacsearch='pacman -Ss'
alias pacinfo='pacman -Si'
alias net-restart='sudo systemctl restart NetworkManager'
alias ssh-restart='sudo systemctl restart sshd'
alias sysinfo='fastfetch'
alias disks='lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,LABEL'
alias update-mirrors='sudo reflector --latest 20 --sort rate --save /etc/pacman.d/mirrorlist'
ALIASES_EOF
chmod +x /etc/profile.d/aliases.sh

# Add aliases for root as well
cat >> /root/.bashrc << 'ROOTALIASES_EOF'
alias ll='ls -la --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
ROOTALIASES_EOF

# Configure reflector for automatic mirror updates
log_info "Configuring reflector service..."
cat > /etc/systemd/system/reflector.service << REFLECTOR_EOF
[Unit]
Description=Pacman mirrorlist update
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/reflector --latest 20 --sort rate --save /etc/pacman.d/mirrorlist

[Install]
WantedBy=multi-user.target
REFLECTOR_EOF

cat > /etc/systemd/system/reflector.timer << REFLECTORTIMER_EOF
[Unit]
Description=Run reflector weekly

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
REFLECTORTIMER_EOF

systemctl enable reflector.timer || log_error "Failed to enable reflector timer"

log_success "Chroot configuration completed"
CHROOT_EOF

    chmod +x /mnt/root/chroot_setup.sh
    
    # Copy log file to chroot for reference
    cp "${LOG_FILE}" /mnt/root/install_log.txt
    
    # Execute chroot script
    arch-chroot /mnt /root/chroot_setup.sh \
        "${HOSTNAME}" \
        "${USERNAME}" \
        "${ROOT_PASSWORD}" \
        "${USER_PASSWORD}" \
        "${TIMEZONE}" \
        "${LOCALE}" \
        "${LUKS_UUID}" \
        "${VG_NAME}" || {
        log_error "Chroot configuration failed"
        exit 1
    }
    
    # Clean up chroot script
    rm /mnt/root/chroot_setup.sh
    
    log_success "System configuration completed"
}

# ============================================================================
# MKINITCPIO CONFIGURATION
# ============================================================================
configure_mkinitcpio() {
    log_step "Configuring mkinitcpio"
    
    # Detect if systemd hooks are used
    local hooks_line='HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt lvm2 filesystems fsck)'
    
    log_info "Configuring mkinitcpio hooks for LUKS2 + LVM2 + systemd..."
    
    # Backup original mkinitcpio.conf
    cp /mnt/etc/mkinitcpio.conf /mnt/etc/mkinitcpio.conf.backup
    
    # Replace HOOKS line
    sed -i "s/^HOOKS=.*/${hooks_line}/" /mnt/etc/mkinitcpio.conf
    
    # Verify the configuration
    log_info "Verifying mkinitcpio configuration..."
    grep "^HOOKS=" /mnt/etc/mkinitcpio.conf | tee -a "${LOG_FILE}"
    
    # Regenerate initramfs
    log_info "Regenerating initramfs..."
    arch-chroot /mnt mkinitcpio -P || {
        log_error "Failed to regenerate initramfs"
        exit 1
    }
    
    log_success "mkinitcpio configured successfully"
}

# ============================================================================
# GRUB BOOTLOADER
# ============================================================================
install_grub() {
    log_step "Installing GRUB Bootloader"
    
    # Enable cryptodisk support
    log_info "Enabling GRUB cryptodisk support..."
    if ! grep -q "^GRUB_ENABLE_CRYPTODISK=y" /mnt/etc/default/grub; then
        echo "GRUB_ENABLE_CRYPTODISK=y" >> /mnt/etc/default/grub
    else
        sed -i 's/^#GRUB_ENABLE_CRYPTODISK=y/GRUB_ENABLE_CRYPTODISK=y/' /mnt/etc/default/grub
    fi
    
    # Configure kernel command line
    local cmdline="rd.luks.name=${LUKS_UUID}=${LUKS_NAME} rd.lvm.vg=${VG_NAME} root=/dev/mapper/${VG_NAME}-${LV_ROOT} quiet"
    
    log_info "Configuring GRUB_CMDLINE_LINUX..."
    log_info "Kernel parameters: ${cmdline}"
    
    sed -i "s|^GRUB_CMDLINE_LINUX=.*|GRUB_CMDLINE_LINUX=\"${cmdline}\"|" /mnt/etc/default/grub
    
    # Add additional GRUB settings
    if ! grep -q "^GRUB_DISABLE_OS_PROBER=false" /mnt/etc/default/grub; then
        echo "GRUB_DISABLE_OS_PROBER=false" >> /mnt/etc/default/grub
    fi
    
    log_info "GRUB configuration file:"
    cat /mnt/etc/default/grub | tee -a "${LOG_FILE}"
    
    # Install GRUB for UEFI
    log_info "Installing GRUB to EFI system partition..."
    arch-chroot /mnt grub-install \
        --target=x86_64-efi \
        --efi-directory=/boot \
        --bootloader-id=GRUB \
        --recheck || {
        log_error "GRUB installation failed"
        exit 1
    }
    
    # Generate GRUB configuration
    log_info "Generating GRUB configuration..."
    arch-chroot /mnt grub-mkconfig -o /boot/grub/grub.cfg || {
        log_error "GRUB configuration generation failed"
        exit 1
    }
    
    log_success "GRUB bootloader installed successfully"
}

# ============================================================================
# SYSTEMD SERVICE ENABLEMENT
# ============================================================================
enable_services() {
    log_step "Enabling Systemd Services"
    
    log_info "Enabling NetworkManager..."
    arch-chroot /mnt systemctl enable NetworkManager.service || {
        log_error "Failed to enable NetworkManager"
        exit 1
    }
    
    log_info "Enabling SSH daemon..."
    arch-chroot /mnt systemctl enable sshd.service || {
        log_error "Failed to enable SSH daemon"
        exit 1
    }
    
    log_info "Enabling fstrim timer for SSD optimization..."
    arch-chroot /mnt systemctl enable fstrim.timer || {
        log_error "Failed to enable fstrim timer"
        exit 1
    }
    
    log_info "Enabling systemd-networkd and systemd-resolved as backup..."
    arch-chroot /mnt systemctl enable systemd-networkd.service || true
    arch-chroot /mnt systemctl enable systemd-resolved.service || true
    
    log_success "Services enabled successfully"
}

# ============================================================================
# POST INSTALLATION OPTIMIZATIONS
# ============================================================================
post_install_optimizations() {
    log_step "Post-Installation Optimizations"
    
    # Configure swappiness
    log_info "Configuring swappiness..."
    echo "vm.swappiness=10" > /mnt/etc/sysctl.d/99-sysctl.conf
    echo "vm.vfs_cache_pressure=50" >> /mnt/etc/sysctl.d/99-sysctl.conf
    
    # Configure SSD TRIM if applicable
    log_info "Configuring TRIM for SSDs..."
    cat > /mnt/etc/cron.weekly/trim << 'TRIM_EOF'
#!/bin/bash
fstrim -av
TRIM_EOF
    chmod +x /mnt/etc/cron.weekly/trim
    
    # Create snapshot configuration for Btrfs if desired
    log_info "Creating Btrfs subvolume layout..."
    arch-chroot /mnt btrfs subvolume create /home/@snapshots || true
    arch-chroot /mnt mkdir -p /home/.snapshots || true
    
    log_success "Post-installation optimizations completed"
}

# ============================================================================
# FINAL CLEANUP
# ============================================================================
final_cleanup() {
    log_step "Performing Final Cleanup"
    
    # Remove installation log from chroot if it exists
    rm -f /mnt/root/install_log.txt
    
    # Clear bash history in chroot
    if [[ -f /mnt/root/.bash_history ]]; then
        truncate -s 0 /mnt/root/.bash_history
    fi
    
    # Sync filesystems
    log_info "Syncing filesystems..."
    sync
    
    log_success "Final cleanup completed"
}

# ============================================================================
# MAIN INSTALLATION FUNCTION
# ============================================================================
main() {
    # Clear screen for better visibility
    clear
    
    echo -e "${MAGENTA}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${MAGENTA}║                                                          ║${NC}"
    echo -e "${MAGENTA}║     Arch Linux Installation Script v${SCRIPT_VERSION}                   ║${NC}"
    echo -e "${MAGENTA}║     LUKS2 + LVM2 + UEFI + GRUB                          ║${NC}"
    echo -e "${MAGENTA}║                                                          ║${NC}"
    echo -e "${MAGENTA}╚══════════════════════════════════════════════════════════╝${NC}"
    echo
    
    # Initialize logging
    echo "Arch Linux Installation Log - $(date)" > "${LOG_FILE}"
    echo "========================================" >> "${LOG_FILE}"
    
    # Pre-flight checks
    validate_root
    validate_uefi
    check_network
    
    # Gather information
    detect_cpu
    select_disk
    gather_user_input
    
    # Confirmation before proceeding
    echo
    echo -e "${YELLOW}Installation Summary:${NC}"
    echo -e "  Disk:       ${WHITE}${DISK}${NC}"
    echo -e "  Hostname:   ${WHITE}${HOSTNAME}${NC}"
    echo -e "  Username:   ${WHITE}${USERNAME}${NC}"
    echo -e "  Timezone:   ${WHITE}${TIMEZONE}${NC}"
    echo -e "  Locale:     ${WHITE}${LOCALE}${NC}"
    echo -e "  CPU:        ${WHITE}${CPU_VENDOR}${NC}"
    echo -e "  Microcode:  ${WHITE}${MICROCODE_PACKAGE}${NC}"
    echo
    read -rp "$(echo -e "${WHITE}Proceed with installation? (yes/no): ${NC}")" proceed
    
    if [[ "${proceed}" != "yes" ]]; then
        log_error "Installation cancelled by user"
        exit 1
    fi
    
    # Execute installation steps
    update_system_clock
    partition_disk
    setup_encryption
    setup_lvm
    create_filesystems
    mount_filesystems
    install_base_system
    generate_fstab
    configure_system
    configure_mkinitcpio
    install_grub
    enable_services
    post_install_optimizations
    final_cleanup
    
    # Success message
    echo
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}║     Installation Completed Successfully!                 ║${NC}"
    echo -e "${GREEN}║                                                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo
    echo -e "${CYAN}To reboot safely:${NC}"
    echo -e "  1. Exit the chroot environment (if still inside): ${WHITE}exit${NC}"
    echo -e "  2. Unmount all filesystems:"
    echo -e "     ${WHITE}umount -R /mnt${NC}"
    echo -e "  3. Deactivate swap:"
    echo -e "     ${WHITE}swapoff -a${NC}"
    echo -e "  4. Reboot:"
    echo -e "     ${WHITE}reboot${NC}"
    echo
    echo -e "${YELLOW}After reboot:${NC}"
    echo -e "  - Login as: ${WHITE}${USERNAME}${NC}"
    echo -e "  - Network will be managed by NetworkManager"
    echo -e "  - SSH server will be running"
    echo -e "  - Run ${WHITE}sudo pacman -Syu${NC} to update the system"
    echo
    echo -e "${GREEN}Installation log saved to: ${LOG_FILE}${NC}"
    echo
    
    log_success "Script completed successfully"
}

# ============================================================================
# EXECUTION
# ============================================================================
main "$@"
