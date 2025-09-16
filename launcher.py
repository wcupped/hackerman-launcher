#! /usr/bin/env python3
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
import os
import json
import subprocess
import minecraft_launcher_lib as mll
import uuid
import logging


class DownloadProgressCallback:
    def __init__(self):
        self.total = 0
        self.current = 0
        self.status = ""

    def set_max(self, max_value):
        self.total = max_value
        logging.debug(f"Download Max Set: {self.total}")

    def set_progress(self, progress):
        self.current = progress
        if self.total > 0:
            percentage = (self.current / self.total) * 100
            logging.debug(f"Download Progress: {self.current}/{self.total} ({percentage:.2f}%)")
        else:
            logging.debug(f"Download Progress: {self.current}")

    def set_status(self, status):
        self.status = status
        logging.debug(f"Download Status: {self.status}")

    def get(self, key, default=None):
        if key == "setStatus":
            return self.set_status
        elif key == "setMax":
            return self.set_max
        elif key == "setProgress":
            return self.set_progress
        return default

class MinecraftLauncher(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.minecraft.launcher")
        self.connect("activate", self.on_activate)
        
        self.data_dir = os.path.join(os.path.expanduser("~"), ".hackerman-launcher")
        # mll will manage its own directories within self.data_dir
        self.mll_data_dir = self.data_dir

        # Configure logging
        os.makedirs(self.data_dir, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(self.data_dir, "launcher.log")),
                logging.StreamHandler() # Also print to console for immediate feedback
            ]
        )
        logging.info("Launcher initialized and logging configured.")

        # Initializing mll is not necessary in __init__, but we need self.data_dir
        # for mll functions that require it. MLL functions will be called as needed.

        # The following mll-managed directories are no longer manually created:
        # os.makedirs(os.path.join(self.data_dir, "versions"), exist_ok=True)
        # os.makedirs(os.path.join(self.data_dir, "assets"), exist_ok=True)
        # os.makedirs(os.path.join(self.data_dir, "libraries"), exist_ok=True)

        self.version_manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest.json"
        self.versions = {}

        self.config_file = os.path.join(self.data_dir, "config.json")
        self.config = {
            "accounts": [],
            "selected_account": None,
            "selected_version_id": None,
            "selected_account_uuid": None
        }

        self.selected_account = None
        self.selected_version_id = None
        self.selected_account_uuid = self.config.get("selected_account_uuid", None)

    def on_activate(self, app):
        self.window = Gtk.ApplicationWindow(application=app, title="Minecraft Launcher")
        self.window.set_default_size(800, 600)

        header_bar = Gtk.HeaderBar()
        header_bar.set_show_close_button(True)
        header_bar.props.title = "Minecraft Launcher"
        self.window.set_titlebar(header_bar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(500)

        stack_switcher = Gtk.StackSwitcher()
        stack_switcher.set_stack(self.stack)
        header_bar.set_custom_title(stack_switcher)

        self.account_page = self.create_account_page()
        self.stack.add_titled(self.account_page, "account_page", "Accounts")

        self.game_page = self.create_game_page()
        self.stack.add_titled(self.game_page, "game_page", "Game")

        self.window.add(self.stack)
        self.window.show_all()

        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                try:
                    self.config = json.load(f)
                except json.JSONDecodeError:
                    logging.error("Error: Could not decode config.json. Starting with default config.")

        self.account_list_store.clear()
        for account in self.config["accounts"]:
            self.account_list_store.append([account])
        
        if self.config.get("selected_account"):
            self.selected_account = self.config["selected_account"]
            for row in self.account_list_store:
                if row[0] == self.selected_account:
                    path = row.path
                    self.account_list_view.get_selection().select_path(path)
                    break

        self.selected_version_id = self.config.get("selected_version_id")
        self.selected_account_uuid = self.config.get("selected_account_uuid")

    def save_config(self):
        # Save accounts
        accounts = []
        for row in self.account_list_store:
            accounts.append(row[0])
        self.config["accounts"] = accounts
        self.config["selected_account"] = self.selected_account
        self.config["selected_version_id"] = self.selected_version_id
        self.config["selected_account_uuid"] = self.selected_account_uuid

        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def create_account_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Username entry
        username_label = Gtk.Label(label="Username:")
        self.username_entry = Gtk.Entry()
        self.username_entry.set_placeholder_text("Enter username")
        
        hbox_username = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox_username.pack_start(username_label, False, False, 0)
        hbox_username.pack_start(self.username_entry, True, True, 0)
        vbox.pack_start(hbox_username, False, False, 0)

        # Add Account button
        add_account_button = Gtk.Button(label="Add Account")
        add_account_button.connect("clicked", self.on_add_account_clicked)
        vbox.pack_start(add_account_button, False, False, 0)

        # Account list
        self.account_list_store = Gtk.ListStore(str) # Stores usernames
        self.account_list_view = Gtk.TreeView(model=self.account_list_store)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Offline Accounts", renderer, text=0)
        self.account_list_view.append_column(column)
        
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        scrolled_window.add(self.account_list_view)
        vbox.pack_start(scrolled_window, True, True, 0)

        # Select/Delete Account buttons
        hbox_account_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        select_account_button = Gtk.Button(label="Select Account")
        select_account_button.connect("clicked", self.on_select_account_clicked)
        hbox_account_actions.pack_start(select_account_button, True, True, 0)
        
        delete_account_button = Gtk.Button(label="Delete Account")
        delete_account_button.connect("clicked", self.on_delete_account_clicked)
        hbox_account_actions.pack_start(delete_account_button, True, True, 0)
        vbox.pack_start(hbox_account_actions, False, False, 0)

        return vbox

    def create_game_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Version selection (placeholder for now)
        version_label = Gtk.Label(label="Minecraft Version:")
        self.version_combo = Gtk.ComboBoxText()
        self.version_combo.connect("changed", self.on_version_selected)
        self.load_versions()

        hbox_version = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox_version.pack_start(version_label, False, False, 0)
        hbox_version.pack_start(self.version_combo, True, True, 0)
        vbox.pack_start(hbox_version, False, False, 0)

        # Launch Game button
        launch_button = Gtk.Button(label="Launch Game")
        launch_button.connect("clicked", self.on_launch_game_clicked)
        vbox.pack_start(launch_button, False, False, 0)

        return vbox

    def _download_version_files(self, version_id):
        self.show_notification("Info", f"Downloading Minecraft version {version_id}...")
        logging.info(f"Downloading Minecraft version {version_id} using minecraft-launcher-lib...")
        try:
            mll.install.install_minecraft_version(version_id, self.mll_data_dir, callback=DownloadProgressCallback())
            self.show_notification("Success", f"Minecraft version {version_id} downloaded successfully.")
            logging.info(f"Successfully downloaded Minecraft {version_id} using minecraft-launcher-lib.")
        except Exception as e:
            self.show_notification("Error", f"Failed to download Minecraft {version_id}: {e}")
            logging.exception(f"Error downloading Minecraft {version_id} using minecraft-launcher-lib: {e}")

    def show_notification(self, title, message):
        dialog = Gtk.MessageDialog(
            parent=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.set_title(title)
        dialog.run()
        dialog.destroy()

    def load_versions(self):
        self.version_combo.remove_all()
        self.version_combo.append_text("Loading versions...")
        self.version_combo.set_active(0)

        try:
            # Use mll to get versions
            raw_versions = mll.utils.get_available_versions(self.mll_data_dir)
            logging.info(f"Found {len(raw_versions)} raw versions.")
            # Sort versions by release date (most recent first)
            self.versions = {entry["id"]: entry for entry in sorted(raw_versions, key=lambda x: x.get("releaseTime", ""), reverse=True)}
            logging.info(f"Processed {len(self.versions)} unique versions.")

            for version_id in self.versions:
                self.version_combo.append_text(version_id)

            self.version_combo.remove(0)

            # Set active version if previously selected and still exists
            if self.selected_version_id and self.selected_version_id in self.versions:
                index = 0
                for i, version_id in enumerate(self.versions):
                    if version_id == self.selected_version_id:
                        index = i
                        break
                self.version_combo.set_active(index)
                logging.info(f"Pre-selected version from config: {self.selected_version_id}")
            elif self.versions:
                self.version_combo.set_active(0)
                self.selected_version_id = self.version_combo.get_active_text()
                logging.info(f"No config selection, setting active version to: {self.selected_version_id}")
            else:
                self.version_combo.append_text("No versions found")
                self.version_combo.set_active(0)
                self.selected_version_id = None
                logging.info("No versions found to display.")

        except Exception as e:
            logging.exception(f"Error loading versions using minecraft-launcher-lib: {e}")
            self.show_notification("Error", f"Failed to load Minecraft versions: {e}")
            self.version_combo.remove_all()
            self.version_combo.append_text("Error loading versions")
            self.version_combo.set_active(0)
            self.selected_version_id = None

    def on_version_selected(self, combo_box):
        old_selected_version_id = self.selected_version_id
        self.selected_version_id = combo_box.get_active_text()
        if self.selected_version_id:
            logging.info(f"Version selected in UI: {self.selected_version_id} (previously {old_selected_version_id})")
        else:
            logging.info(f"No version selected in UI (previously {old_selected_version_id}).")
        self.save_config()

    def on_add_account_clicked(self, button):
        username = self.username_entry.get_text().strip()
        if username:
            self.account_list_store.append([username])
            self.username_entry.set_text("")
            self.save_config()

    def on_select_account_clicked(self, button):
        selection = self.account_list_view.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            self.selected_account = model[treeiter][0]
            logging.info(f"Selected account: {self.selected_account}")
            self.save_config()

    def on_delete_account_clicked(self, button):
        selection = self.account_list_view.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            model.remove(treeiter)
            self.selected_account = None
            self.save_config()

    def on_launch_game_clicked(self, button):
        selected_version_id = self.version_combo.get_active_text()
        if not selected_version_id:
            self.show_notification("Error", "Please select a Minecraft version first.")
            return

        if not self.selected_account:
            self.show_notification("Error", "Please select an offline account first.")
            return

        self._download_version_files(selected_version_id)

        # Generate a random UUID for offline mode (if not already stored for the account)
        # Use uuid.uuid3 with NAMESPACE_OID and the username to generate a consistent UUID
        player_uuid = str(uuid.uuid3(uuid.NAMESPACE_OID, self.selected_account)) # Generate UUID based on username
        self.config["selected_account_uuid"] = player_uuid # Store it for consistency
        self.save_config()

        java_executable_path = mll.utils.get_java_executable()
        if not java_executable_path:
            self.show_notification("Error", "Java executable not found or not correctly configured by minecraft-launcher-lib.")
            return
        logging.info(f"Using Java executable: {java_executable_path}")

        # Get the full Minecraft command
        options = {
            "username": self.selected_account,
            "uuid": player_uuid,
            "token": "0", # Access token for offline mode is often "0" or a dummy value
            "auth_type": "offline" # Explicitly set auth_type to offline mode
        }
        command = mll.command.get_minecraft_command(
            version=selected_version_id,
            minecraft_directory=self.mll_data_dir,
            options=options
        )

        logging.info("Launching command: %s", " ".join(command))
        self.show_notification("Launching Game", f"Launching Minecraft {selected_version_id} with account {self.selected_account}...")
        
        try:
            subprocess.Popen(command, cwd=self.mll_data_dir)
        except FileNotFoundError:
            self.show_notification("Error", "Java executable not found or not correctly configured. Please ensure Java is installed and in your PATH.")
            logging.exception("Java executable not found during launch.")
        except Exception as e:
            self.show_notification("Error", f"Failed to launch Minecraft: {e}")
            logging.exception(f"Error launching Minecraft: {e}")

if __name__ == "__main__":
    app = MinecraftLauncher()
    app.run(None)
