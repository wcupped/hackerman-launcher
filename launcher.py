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
        # Just keeping track of download progress - nothing fancy here
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
        # This is basically a callback dispatcher for the minecraft-launcher-lib
        # They expect certain method names, so we're just routing them
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
        
        # Store everything in the proper XDG config directory (because we're not savages)
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
        self.data_dir = os.path.join(xdg_config_home, "hackerman-launcher")
        self.mll_data_dir = self.data_dir

        # Set up logging so we can actually debug things when they break
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

        # We don't need to initialize mll here, but we do need self.data_dir ready
        # for when mll functions get called later

        # These directories used to be created manually, but mll handles them now
        # (thankfully, because I was getting tired of managing all these paths)
        # os.makedirs(os.path.join(self.data_dir, "versions"), exist_ok=True)
        # os.makedirs(os.path.join(self.data_dir, "assets"), exist_ok=True)
        # os.makedirs(os.path.join(self.data_dir, "libraries"), exist_ok=True)

        self.version_manifest_url = "https://piston-meta.mojang.com/mc/game/version_manifest.json"
        self.versions = {}

        self.config_file = os.path.join(self.data_dir, "config.json")
        self.config = {
            "accounts": [],
            "selected_account": None,
            "selected_version_id": None
        }

        self.selected_account = None
        self.selected_version_id = None
        self.selected_account_uuid = None

        self.config_loaded = False  # Don't save until we've actually loaded something

        # Handle migration from the old config location (because I moved it to XDG)
        old_config_path = os.path.join(os.path.expanduser("~"), ".hackerman-launcher", "config.json")
        if os.path.exists(old_config_path) and not os.path.exists(self.config_file):
            os.makedirs(self.data_dir, exist_ok=True)
            with open(old_config_path, "r") as src, open(self.config_file, "w") as dst:
                dst.write(src.read())

    def on_activate(self, app):
        self.window = Gtk.ApplicationWindow(application=app, title="Minecraft Launcher")
        self.window.set_default_size(800, 600)

        # Make sure we save settings when the user closes the window
        self.window.connect("delete-event", self.on_window_close)

        # Set up the header bar (looks more modern than the old title bar)
        header_bar = Gtk.HeaderBar()
        header_bar.set_show_close_button(True)
        header_bar.props.title = "Minecraft Launcher"
        self.window.set_titlebar(header_bar)

        # Create the main stack for switching between pages
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(500)  # Half a second transition - feels snappy

        # Add the page switcher to the header bar
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

    def on_window_close(self, *args):
        # Only save if we actually have something worth saving
        if self.config and self.config.get("accounts") is not None:
            self.save_config()
        return False  # Let the window actually close

    def load_config(self):
        # Try to load the config file, but don't crash if it's missing or broken
        loaded = {}
        file_was_empty = False
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    content = f.read().strip()
                    if content:
                        loaded = json.loads(content)
                    else:
                        file_was_empty = True
                        logging.warning("Config file is empty, starting with defaults.")
            except json.JSONDecodeError:
                logging.error("Error: Could not decode config.json. Starting with default config.")

        # Fill in any missing fields with defaults (backwards compatibility)
        for key, value in self.config.items():
            if key not in loaded:
                loaded[key] = value
        self.config = loaded

        # Refresh the account list from our config
        self.account_list_store.clear()
        migration_needed = False

        for i, account in enumerate(self.config["accounts"]):
            # Handle old configs that stored accounts as just strings
            if isinstance(account, str):
                username = account
                uuid_val = str(uuid.uuid3(uuid.NAMESPACE_OID, username))
                account = {"username": username, "uuid": uuid_val}
                self.config["accounts"][i] = account
                migration_needed = True
            # Make sure every account has a UUID (generate one if missing)
            if not account.get("uuid"):
                account["uuid"] = str(uuid.uuid3(uuid.NAMESPACE_OID, account["username"]))
                self.config["accounts"][i] = account
                migration_needed = True
            self.account_list_store.append([account["username"]])
        # Save the migrated config if we actually changed something
        if migration_needed and not file_was_empty:
            self.save_config()

        # Restore the previously selected account if it exists
        if self.config.get("selected_account"):
            self.selected_account = self.config["selected_account"]
            for row in self.account_list_store:
                if row[0] == self.selected_account:
                    path = row.path
                    self.account_list_view.get_selection().select_path(path)
                    break
        else:
            self.selected_account = None

        self.selected_version_id = self.config.get("selected_version_id")
        self.config_loaded = True  # Okay, now it's safe to save config

    def save_config(self):
        if not getattr(self, 'config_loaded', False):
            logging.warning("Attempted to save config before it was loaded. Skipping save.")
            return
        # Build the accounts list from what's currently in the UI
        accounts = []
        usernames_in_store = set()
        for row in self.account_list_store:
            username = row[0]
            usernames_in_store.add(username)
            # Try to keep the existing UUID if we have one
            existing = next((a for a in self.config["accounts"] if a.get("username") == username), None)
            if existing and existing.get("uuid"):
                uuid_val = existing["uuid"]
            else:
                uuid_val = str(uuid.uuid3(uuid.NAMESPACE_OID, username))
            accounts.append({"username": username, "uuid": uuid_val})
        self.config["accounts"] = accounts
        self.config["selected_account"] = self.selected_account
        self.config["selected_version_id"] = self.selected_version_id
        # Clean up any old fields we don't use anymore
        if "selected_account_uuid" in self.config:
            del self.config["selected_account_uuid"]
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def create_account_page(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Username input field
        username_label = Gtk.Label(label="Username:")
        self.username_entry = Gtk.Entry()
        self.username_entry.set_placeholder_text("Enter username")
        
        hbox_username = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox_username.pack_start(username_label, False, False, 0)
        hbox_username.pack_start(self.username_entry, True, True, 0)
        vbox.pack_start(hbox_username, False, False, 0)

        # Button to add the account
        add_account_button = Gtk.Button(label="Add Account")
        add_account_button.connect("clicked", self.on_add_account_clicked)
        vbox.pack_start(add_account_button, False, False, 0)

        # List of all the offline accounts
        self.account_list_store = Gtk.ListStore(str) # Just storing usernames for now
        self.account_list_view = Gtk.TreeView(model=self.account_list_store)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Offline Accounts", renderer, text=0)
        self.account_list_view.append_column(column)
        
        # Make the list scrollable in case there are lots of accounts
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_vexpand(True)
        scrolled_window.add(self.account_list_view)
        vbox.pack_start(scrolled_window, True, True, 0)

        # Buttons for managing accounts
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

        # Version selector dropdown
        version_label = Gtk.Label(label="Minecraft Version:")
        self.version_combo = Gtk.ComboBoxText()
        self.version_combo.connect("changed", self.on_version_selected)
        self.load_versions()  # This will populate the dropdown

        hbox_version = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox_version.pack_start(version_label, False, False, 0)
        hbox_version.pack_start(self.version_combo, True, True, 0)
        vbox.pack_start(hbox_version, False, False, 0)

        # The big red button that launches Minecraft
        launch_button = Gtk.Button(label="Launch Game")
        launch_button.connect("clicked", self.on_launch_game_clicked)
        vbox.pack_start(launch_button, False, False, 0)

        return vbox

    def _download_version_files(self, version_id):
        self.show_notification("Info", f"Downloading Minecraft version {version_id}...")
        logging.info(f"Downloading Minecraft version {version_id} using minecraft-launcher-lib...")
        try:
            # Let the minecraft-launcher-lib handle all the heavy lifting
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
        # Clear the dropdown and show loading message
        self.version_combo.remove_all()
        self.version_combo.append_text("Loading versions...")
        self.version_combo.set_active(0)

        try:
            # Get all available versions from Mojang's servers
            raw_versions = mll.utils.get_available_versions(self.mll_data_dir)
            logging.info(f"Found {len(raw_versions)} raw versions.")
            # Sort by release date so newest versions appear first
            self.versions = {entry["id"]: entry for entry in sorted(raw_versions, key=lambda x: x.get("releaseTime", ""), reverse=True)}
            logging.info(f"Processed {len(self.versions)} unique versions.")

            # Populate the dropdown with all versions
            for version_id in self.versions:
                self.version_combo.append_text(version_id)

            # Remove the "Loading..." placeholder
            self.version_combo.remove(0)

            # Try to restore the previously selected version
            if self.selected_version_id and self.selected_version_id in self.versions:
                index = 0
                for i, version_id in enumerate(self.versions):
                    if version_id == self.selected_version_id:
                        index = i
                        break
                self.version_combo.set_active(index)
                logging.info(f"Pre-selected version from config: {self.selected_version_id}")
            elif self.versions:
                # Default to the first (newest) version
                self.version_combo.set_active(0)
                self.selected_version_id = self.version_combo.get_active_text()
                logging.info(f"No config selection, setting active version to: {self.selected_version_id}")
            else:
                # No versions found at all
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
            # Don't add duplicate usernames
            if not any(a.get("username") == username for a in self.config["accounts"]):
                player_uuid = str(uuid.uuid3(uuid.NAMESPACE_OID, username))
                self.config["accounts"].append({"username": username, "uuid": player_uuid})
                self.account_list_store.append([username])
                self.save_config()
            self.username_entry.set_text("")  # Clear the input field

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
            username_to_delete = model[treeiter][0]
            model.remove(treeiter)
            # Remove from config as well
            self.config["accounts"] = [a for a in self.config["accounts"] if a.get("username") != username_to_delete]
            # If this was the selected account, clear the selection
            if self.selected_account == username_to_delete:
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

        # Find the UUID for the selected account
        player_uuid = None
        for account in self.config["accounts"]:
            if account.get("username") == self.selected_account:
                player_uuid = account.get("uuid")
                break
        if not player_uuid:
            # Generate a UUID if we somehow don't have one
            player_uuid = str(uuid.uuid3(uuid.NAMESPACE_OID, self.selected_account))

        self.save_config()
        
        # Generate a random session token (Minecraft needs this even for offline mode)
        session_token = str(uuid.uuid4())

        # Make sure Java is available
        java_executable_path = mll.utils.get_java_executable()
        if not java_executable_path:
            self.show_notification("Error", "Java executable not found or not correctly configured by minecraft-launcher-lib.")
            return
        logging.info(f"Using Java executable: {java_executable_path}")

        # Build the command line arguments for Minecraft
        options = {
            "username": self.selected_account,
            "uuid": player_uuid,
            "token": session_token, # Random session token for offline mode
            "auth_type": "offline", # We're not using Mojang authentication
            "user_type": "legacy", # Legacy user type for offline accounts
            "sessionid": session_token # Same token for session ID
        }
        command = mll.command.get_minecraft_command(
            version=selected_version_id,
            minecraft_directory=self.mll_data_dir,
            options=options
        )

        logging.info("Launching command: %s", " ".join(command))
        self.show_notification("Launching Game", f"Launching Minecraft {selected_version_id} with account {self.selected_account}...")
        
        try:
            # Actually launch the game
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
