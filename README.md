# Hackerman Minecraft Launcher

A simple Minecraft launcher for Linux built with GTK and Python, supporting offline accounts.

## Features

*   **Offline Account Management:** Add and manage offline Minecraft accounts.
*   **Version Selection:** Select different Minecraft versions from Mojang's official manifest.
*   **Configuration Saving:** Automatically saves and loads selected accounts and versions.

## Setup and Running

1.  **Dependencies:**
    Ensure you have Python 3, pip, and GTK+ 3 development files installed. On Debian/Ubuntu-based systems, you can install them using:

    ## Ubuntu (or Ubuntu-based distros)
    ```bash
    sudo apt update
    sudo apt install -y python3 python3-pip python3-gi gir1.2-gtk-3.0
    ```
    ## Arch Linux (or Arch-based distros)
    ```bash
    sudo pacman -Syu
    sudo pacman -S python python-pip python-pobject gtk-3
    ```

2.  **Install Python packages:**
    First, create and activate a Python virtual environment with system site packages enabled to access GTK bindings:
    ```bash
    python3 -m venv .venv --system-site-packages
    . .venv/bin/activate
    ```
    Then, install the required packages:
    ```bash
    pip install requests minecraft-launcher-lib
    ```

3.  **Run the launcher:**
    Make sure your virtual environment is activated, then run:
    ```bash
    python3 launcher.py
    ```

## Project Structure

The launcher stores its data (accounts, downloaded versions, assets, libraries, and configuration) in `~/.hackerman-launcher/`.

## Next Steps (Planned)

*   Install Forge, Fabric, OptiFine, and ForgeOptiFine for selected Minecraft versions.
*   Implement actual game launching logic.
*   Add game settings and user feedback mechanisms.