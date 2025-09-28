import sys
import os
import json
import subprocess
import requests
import psutil
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTextEdit, QPushButton, QLineEdit, QLabel, QComboBox, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal, QThread
from PyQt5.QtWebEngineWidgets import QWebEngineView

# Default API endpoint
OLLAMA_API = "http://localhost:11434/api/chat"

# Common Ollama commands
OLLAMA_COMMANDS = [
    "ollama serve", "ollama create", "ollama show", "ollama run",
    "ollama stop", "ollama pull", "ollama push", "ollama signin",
    "ollama signout", "ollama list", "ollama ps", "ollama cp",
    "ollama rm", "ollama help",
    "systemctl restart ollama", "systemctl stop ollama", "systemctl start ollama"
]

# ----- Worker to call the Ollama chat endpoint -----
class ResponseWorker(QThread):
    append_text = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, api_url, model, history, timeout=60):
        super().__init__()
        self.api_url = api_url
        self.model = model
        self.history = list(history)
        self.timeout = timeout

    def run(self):
        try:
            resp = requests.post(
                self.api_url,
                json={"model": self.model, "messages": self.history, "stream": True},
                stream=True,
                timeout=self.timeout,
            )
            reply = ""
            for line in resp.iter_lines():
                if self.isInterruptionRequested():
                    self.error.emit("[Stopped ❌]")
                    return
                if not line:
                    continue
                try:
                    data = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if "message" in data and "content" in data["message"]:
                    chunk = data["message"]["content"]
                    reply += chunk
                if data.get("done", False):
                    break
            self.append_text.emit(reply)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished_signal.emit()

# ----- Worker to run shell commands line by line -----
class CommandWorker(QThread):
    output = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, command):
        super().__init__()
        self.command = command
        self._stop_requested = False

    def run(self):
        try:
            process = subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in process.stdout:
                if self._stop_requested:
                    process.terminate()
                    self.output.emit("[Command stopped ❌]")
                    break
                self.output.emit(line.rstrip())

            process.wait()
        except Exception as e:
            self.output.emit(f"Error running command `{self.command}`: {e}")
        finally:
            self.finished_signal.emit()

    def stop(self):
        self._stop_requested = True

# ----- Main App -----
class OllamaChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama Chat & Control")
        self.resize(1000, 700)

        self.history_dir = "chat_history"
        os.makedirs(self.history_dir, exist_ok=True)

        self.api_url = OLLAMA_API
        self.history = []
        self.response_worker = None
        self.cmd_worker = None

        # Tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_chat_tab()
        self._build_settings_tab()
        self._build_website_tab()

        # Start updates
        self._update_resources()
        self.refresh_models()
        self.check_connection()

    # ---------------- UI construction ----------------
    def _build_chat_tab(self):
        chat_widget = QWidget()
        layout = QVBoxLayout(chat_widget)

        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        layout.addWidget(self.chat_area)

        input_layout = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.entry)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(send_btn)

        stop_btn = QPushButton("Stop Chat")
        stop_btn.clicked.connect(self.stop_response)
        input_layout.addWidget(stop_btn)

        layout.addLayout(input_layout)
        self.tabs.addTab(chat_widget, "Chat")

    def _build_settings_tab(self):
        settings_widget = QWidget()
        layout = QVBoxLayout(settings_widget)

        # API URL
        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("Ollama API URL:"))
        self.api_edit = QLineEdit(self.api_url)
        api_row.addWidget(self.api_edit)
        save_api_btn = QPushButton("Save & Test")
        save_api_btn.clicked.connect(self.save_settings)
        api_row.addWidget(save_api_btn)
        layout.addLayout(api_row)

        # Status
        self.status_label = QLabel("● Disconnected")
        self.status_label.setStyleSheet("color: red")
        layout.addWidget(self.status_label)

        self.resource_label = QLabel("CPU: 0% | RAM: 0%")
        layout.addWidget(self.resource_label)

        # AI name
        ai_row = QHBoxLayout()
        ai_row.addWidget(QLabel("AI Name:"))
        self.ai_name_edit = QLineEdit("AI")
        ai_row.addWidget(self.ai_name_edit)
        layout.addLayout(ai_row)

        # Model selector
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        model_row.addWidget(self.model_box)
        refresh_btn = QPushButton("↻ Refresh Models")
        refresh_btn.clicked.connect(self.refresh_models)
        model_row.addWidget(refresh_btn)
        layout.addLayout(model_row)

        # Global history toggle
        self.global_history_checkbox = QCheckBox("Use Global History (all models share one chat)")
        self.global_history_checkbox.setChecked(False)
        layout.addWidget(self.global_history_checkbox)

        # History buttons
        hist_row = QHBoxLayout()
        clear_btn = QPushButton("Clear Chat History")
        clear_btn.clicked.connect(self.clear_history)
        hist_row.addWidget(clear_btn)
        new_session_btn = QPushButton("New Session")
        new_session_btn.clicked.connect(self.new_session)
        hist_row.addWidget(new_session_btn)
        layout.addLayout(hist_row)

        # Dropdown commands
        cmd_row = QHBoxLayout()
        self.cmd_box = QComboBox()
        self.cmd_box.addItems(OLLAMA_COMMANDS)
        cmd_row.addWidget(self.cmd_box)
        run_cmd_btn = QPushButton("Run Command")
        run_cmd_btn.clicked.connect(self.run_command)
        cmd_row.addWidget(run_cmd_btn)
        stop_cmd_btn = QPushButton("Stop Command")
        stop_cmd_btn.clicked.connect(self.stop_command)
        cmd_row.addWidget(stop_cmd_btn)
        layout.addLayout(cmd_row)

        # Custom command
        custom_row = QHBoxLayout()
        self.custom_cmd_edit = QLineEdit()
        self.custom_cmd_edit.setPlaceholderText("Enter custom command here...")
        custom_row.addWidget(self.custom_cmd_edit)
        run_custom_btn = QPushButton("Run Custom Command")
        run_custom_btn.clicked.connect(self.run_custom_command)
        custom_row.addWidget(run_custom_btn)
        layout.addLayout(custom_row)

        # Output log
        self.cmd_output = QTextEdit()
        self.cmd_output.setReadOnly(True)
        layout.addWidget(self.cmd_output)

        self.tabs.addTab(settings_widget, "Settings")

    def _build_website_tab(self):
        website_widget = QWidget()
        layout = QVBoxLayout(website_widget)

        self.web_view = QWebEngineView()
        try:
            self.web_view.setUrl(QUrl("https://ollama.com/library"))
        except Exception:
            layout.addWidget(QLabel("Could not embed web view. Click below to open in browser."))
            open_btn = QPushButton("Open Ollama Website")
            open_btn.clicked.connect(lambda: os.system("xdg-open https://ollama.com/library"))
            layout.addWidget(open_btn)
        else:
            layout.addWidget(self.web_view)

        self.tabs.addTab(website_widget, "Ollama Website")

    # ---------------- History helpers ----------------
    def history_file(self):
        if self.global_history_checkbox.isChecked():
            return os.path.join(self.history_dir, "global.json")
        else:
            model = self.model_box.currentText() or "default"
            safe = model.replace(":", "_")
            return os.path.join(self.history_dir, f"{safe}.json")

    def save_history(self):
        try:
            with open(self.history_file(), "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._append_system(f"Error saving history: {e}")

    def load_history(self):
        file = self.history_file()
        if os.path.exists(file):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []
        else:
            self.history = []

        self.chat_area.clear()
        for msg in self.history:
            if msg.get("role") == "user":
                self.chat_area.append(f"You: {msg.get('content')}")
            else:
                name = self.ai_name_edit.text().strip() or "AI"
                model = self.model_box.currentText() or "Unknown"
                self.chat_area.append(f"{name} ({model}): {msg.get('content')}")

    def clear_history(self):
        file = self.history_file()
        if os.path.exists(file):
            try:
                os.remove(file)
            except Exception as e:
                self._append_system(f"Could not remove history file: {e}")
        self.history = []
        self.chat_area.clear()

    def new_session(self):
        self.history = []
        self.chat_area.clear()
        self._append_system("Started a new session (kept saved history file).")

    # ---------------- Resource & connection ----------------
    def _update_resources(self):
        try:
            cpu = psutil.cpu_percent(interval=0)
            ram = psutil.virtual_memory().percent
            self.resource_label.setText(f"CPU: {cpu}% | RAM: {ram}%")
        except Exception:
            pass
        QTimer.singleShot(1000, self._update_resources)

    def check_connection(self, force_status=None):
        url = self.api_url.replace("/api/chat", "/api/tags")
        try:
            if force_status is None:
                requests.get(url, timeout=3)
            status_ok = True if force_status is None else force_status
        except Exception:
            status_ok = False

        if status_ok:
            self.status_label.setText("● Connected")
            self.status_label.setStyleSheet("color: green")
        else:
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet("color: red")

    # ---------------- Models ----------------
    def refresh_models(self):
        url = self.api_url.replace("/api/chat", "/api/tags")
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            if not models:
                raise ValueError("No models found")

            self.model_box.clear()
            self.model_box.addItems(models)
            self.load_history()
            self.chat_area.append(f"System: Models loaded: {', '.join(models)}")
        except Exception as e:
            self.model_box.clear()
            self.chat_area.append(f"System: Could not load models ({e})")

    # ---------------- Chat / LLM ----------------
    def send_message(self):
        user_input = self.entry.text().strip()
        if not user_input:
            return
        self.entry.clear()

        self.chat_area.append(f"You: {user_input}")
        self.history.append({"role": "user", "content": user_input})
        self.save_history()

        model = self.model_box.currentText()
        if not model:
            self._append_system("No model selected.")
            return

        if self.response_worker and self.response_worker.isRunning():
            self.response_worker.requestInterruption()
            self.response_worker.wait(200)

        self.response_worker = ResponseWorker(self.api_url, model, self.history, timeout=60)
        self.response_worker.append_text.connect(self._on_ai_text)
        self.response_worker.error.connect(self._on_worker_error)
        self.response_worker.finished_signal.connect(self._on_worker_finished)
        self.response_worker.start()

    def _on_ai_text(self, text: str):
        name = self.ai_name_edit.text().strip() or "AI"
        model = self.model_box.currentText() or "Unknown"
        self.chat_area.append(f"{name} ({model}): {text}")
        self.history.append({"role": "assistant", "content": text})
        self.save_history()

    def _on_worker_error(self, err: str):
        self.chat_area.append(f"System: Error: {err}")

    def _on_worker_finished(self):
        self.response_worker = None

    def stop_response(self):
        if self.response_worker and self.response_worker.isRunning():
            self.response_worker.requestInterruption()
            self.chat_area.append(f"System: Requested stop of response.")
        else:
            self.chat_area.append("System: No response running.")

    # ---------------- Commands ----------------
    def run_command(self):
        cmd = self.cmd_box.currentText().strip()
        if not cmd:
            return
        self._run_background_command(cmd)

    def run_custom_command(self):
        cmd = self.custom_cmd_edit.text().strip()
        if not cmd:
            self.cmd_output.append("System: No custom command entered.")
            return
        self._run_background_command(cmd)

    def stop_command(self):
        if self.cmd_worker and self.cmd_worker.isRunning():
            self.cmd_worker.stop()
            self.cmd_output.append("System: Requested stop of command.")
        else:
            self.cmd_output.append("System: No command running.")

    def _run_background_command(self, cmd):
        if self.cmd_worker and self.cmd_worker.isRunning():
            self.cmd_output.append("System: command runner busy")
            return
        self.cmd_worker = CommandWorker(cmd)
        self.cmd_worker.output.connect(self._on_command_output)
        self.cmd_worker.finished_signal.connect(lambda: self.cmd_output.append("System: Command finished ✅"))
        self.cmd_worker.start()

    def _on_command_output(self, out: str):
        self.cmd_output.append(out)

    # ---------------- Misc helpers ----------------
    def _append_system(self, msg: str):
        self.chat_area.append(f"System: {msg}")

    def save_settings(self):
        new_url = self.api_edit.text().strip()
        if not new_url.endswith("/api/chat"):
            new_url = new_url.rstrip("/") + "/api/chat"
        self.api_url = new_url
        self._append_system(f"API URL set to {self.api_url}")
        self.check_connection()
        self.refresh_models()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OllamaChatApp()
    window.show()
    sys.exit(app.exec_())
