"""
Local AI Chat - thin desktop client for a remote AI brain.
"""

import sys
import os
import json
import codecs
import requests

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=2"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QComboBox, QLabel, QFileDialog,
    QMessageBox, QSplitter, QDialog, QListWidget, QListWidgetItem, QLineEdit,
    QTabWidget, QCheckBox, QInputDialog
)

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QKeyEvent, QFont, QTextCharFormat, QColor

DEFAULT_SERVER_URL = "http://localhost:5000"
DEFAULT_AI_NAME = "AI"
DEFAULT_SYSTEM_PROMPT = (
    "You are a sharp, practical assistant and hands-on mentor. "
    "Your #1 rule: always ask a clarifying question before giving a long answer. "
    "When someone asks if you can help with something, say yes and ask ONE specific question to understand what they actually need. "
    "When teaching: ask what they already know first, then tailor from there. Show one small example at a time. "
    "When answering factual questions: answer directly in 1-3 sentences, then ask if they want to go deeper. "
    "Never give lists, overviews, or multi-part explanations unless specifically asked. "
    "One idea at a time. One question at a time. Short messages always. "
    "You can update your own behavior mid-conversation by emitting [UPDATE_PROMPT: your revised instruction] at the END of your reply. "
    "Only emit this when the user is explicitly asking you to change how you behave permanently."
)

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LocalAIChat")
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(CONFIG_DIR, "client_config.json")


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("server_url", DEFAULT_SERVER_URL)
                data.setdefault("ai_name", DEFAULT_AI_NAME)
                return data
        except Exception:
            pass
    return {"server_url": DEFAULT_SERVER_URL, "ai_name": DEFAULT_AI_NAME}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "server_url": cfg.get("server_url", DEFAULT_SERVER_URL),
            "ai_name": cfg.get("ai_name", DEFAULT_AI_NAME),
        }, f, indent=2)


LATEX_REPLACEMENTS = [
    (r"\times", "×"), (r"\cdot", "·"), (r"\Delta", "Δ"), (r"\delta", "δ"),
    (r"\alpha", "α"), (r"\beta", "β"), (r"\pi", "π"), (r"\Sigma", "Σ"),
    (r"\sigma", "σ"), (r"\theta", "θ"), (r"\omega", "ω"), (r"\leq", "≤"),
    (r"\geq", "≥"), (r"\neq", "≠"), (r"\pm", "±"), (r"\sqrt", "√"),
    (r"\infty", "∞"), (r"\rightarrow", "→"),
]


def _markdown_to_html(text):
    import re
    code_blocks = []

    def _stash_code(match):
        code_blocks.append(match.group(1))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```(?:\w+)?\n?(.*?)```", _stash_code, text, flags=re.DOTALL)
    text = text.replace(r"\[", "").replace(r"\]", "")
    text = text.replace(r"\(", "").replace(r"\)", "")
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", text)
    for latex, symbol in LATEX_REPLACEMENTS:
        text = text.replace(latex, symbol)

    lines = text.split("\n")
    html_lines = []
    in_list = False

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def inline_format(s):
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", s)
        s = re.sub(r"`([^`]+)`", r"<code style='background:#2a2d34; padding:1px 5px; border-radius:4px;'>\1</code>", s)
        return s

    for line in lines:
        stripped = line.strip()
        code_match = re.match(r"^\x00CODEBLOCK(\d+)\x00$", stripped)
        if code_match:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            code_content = code_blocks[int(code_match.group(1))]
            html_lines.append(
                f"<pre style='background:#2a2d34; padding:10px; border-radius:6px; "
                f"white-space:pre-wrap;'>{esc(code_content)}</pre>"
            )
            continue

        header_match = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if header_match:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            level = len(header_match.group(1))
            size = {1: "1.3em", 2: "1.15em", 3: "1.05em"}[level]
            html_lines.append(
                f"<div style='font-weight:600; font-size:{size}; margin:6px 0;'>"
                f"{inline_format(header_match.group(2))}</div>"
            )
            continue

        list_match = re.match(r"^[-*]\s+(.*)", stripped)
        if list_match:
            if not in_list:
                html_lines.append("<ul style='margin:4px 0;'>")
                in_list = True
            html_lines.append(f"<li>{inline_format(list_match.group(1))}</li>")
            continue

        if in_list:
            html_lines.append("</ul>")
            in_list = False

        if stripped == "":
            html_lines.append("<br>")
        else:
            html_lines.append(inline_format(line) + "<br>")

    if in_list:
        html_lines.append("</ul>")

    return "".join(html_lines)


class ChatWorker(QThread):
    response_chunk = pyqtSignal(str)
    finished_response = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, server_url, conversation_id, message, model, search=False):
        super().__init__()
        self.server_url = server_url
        self.conversation_id = conversation_id
        self.message = message
        self.model = model
        self.search = search
        self._stop_requested = False
        self._response = None

    def stop(self):
        self._stop_requested = True
        if self._response is not None:
            try:
                self._response.close()
            except Exception:
                pass

    def run(self):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            self._response = requests.post(
                f"{self.server_url}/api/chat",
                json={
                    "conversation_id": self.conversation_id,
                    "message": self.message,
                    "model": self.model,
                    "search": self.search,
                },
                stream=True,
                timeout=120,
            )
            for raw_chunk in self._response.iter_content(chunk_size=32):
                if self._stop_requested:
                    break
                if not raw_chunk:
                    continue
                text = decoder.decode(raw_chunk)
                if text:
                    self.response_chunk.emit(text)
            self.finished_response.emit()
        except requests.exceptions.ConnectionError:
            if not self._stop_requested:
                self.error.emit(
                    "Can't reach the server. Check that app.py is running and the Server Address in Settings is correct."
                )
            else:
                self.finished_response.emit()
        except Exception as e:
            if not self._stop_requested:
                self.error.emit(str(e))
            else:
                self.finished_response.emit()


class ExtractionWorker(QThread):
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, server_url, conversation_id, model):
        super().__init__()
        self.server_url = server_url
        self.conversation_id = conversation_id
        self.model = model

    def run(self):
        try:
            resp = requests.post(
                f"{self.server_url}/api/memory/extract",
                json={"conversation_id": self.conversation_id, "model": self.model},
                timeout=30,
            )
            self.finished_ok.emit(resp.json().get("facts_added", []))
        except Exception as e:
            self.failed.emit(str(e))


class InputBox(QTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
            return
        super().keyPressEvent(event)


class LoadChatDialog(QDialog):
    def __init__(self, conversations, server_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conversations")
        self.resize(550, 420)
        self.selected_id = None
        self.server_url = server_url
        self.conversations = conversations

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Double-click to open a conversation:"))

        self.list_widget = QListWidget()
        self._populate()
        self.list_widget.itemDoubleClicked.connect(self._on_choose)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        load_btn = QPushButton("Open")
        load_btn.clicked.connect(self._on_choose)
        btn_row.addWidget(load_btn)

        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(rename_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet("color: #c0392b;")
        delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(delete_btn)

        btn_row.addStretch(1)
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _populate(self):
        self.list_widget.clear()
        for conv in self.conversations:
            item = QListWidgetItem(
                f"{conv['title']}   —   {conv['updated_at'][:16].replace('T', ' ')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, conv["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, conv["title"])
            self.list_widget.addItem(item)

    def _current_id(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_choose(self):
        item = self.list_widget.currentItem()
        if item:
            self.selected_id = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _on_rename(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "No selection", "Select a conversation first.")
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        old_title = item.data(Qt.ItemDataRole.UserRole + 1)
        new_title, ok = QInputDialog.getText(
            self, "Rename conversation", "New name:", text=old_title
        )
        if ok and new_title.strip():
            try:
                requests.post(
                    f"{self.server_url}/api/conversations/{conv_id}/rename",
                    json={"title": new_title.strip()},
                    timeout=5
                )
                # Refresh the list
                resp = requests.get(f"{self.server_url}/api/conversations", timeout=5)
                self.conversations = resp.json()
                self._populate()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not rename:\n{e}")

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "No selection", "Select a conversation first.")
            return
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        title = item.data(Qt.ItemDataRole.UserRole + 1)
        reply = QMessageBox.question(
            self, "Delete conversation",
            f"Delete \"{title}\"?\n\nMemory facts already extracted from it are not affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                requests.delete(
                    f"{self.server_url}/api/conversations/{conv_id}",
                    timeout=5
                )
                resp = requests.get(f"{self.server_url}/api/conversations", timeout=5)
                self.conversations = resp.json()
                self._populate()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete:\n{e}")


class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local AI Chat")
        self.resize(700, 700)
        self.setAcceptDrops(True)

        self.config = load_config()
        self.conversation_id = None
        self.conversation = []
        self.attached_file_text = None
        self.attached_file_name = None
        self.worker = None
        self._current_response = ""
        self._ai_response_start_pos = 0
        self.font_size = 15
        self.isStreaming = False
        self._last_message_count = 0

        self._build_ui()
        self._apply_font()
        self._build_settings_dialog()
        self._load_models()
        self._resume_or_start_conversation()

        # Poll for responses that finished while the app was closed/away
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll_for_updates)
        self._poll_timer.start()

    def _build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Model:"))
        self.model_dropdown = QComboBox()
        top_bar.addWidget(self.model_dropdown, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._load_models)
        top_bar.addWidget(refresh_btn)

        shrink_btn = QPushButton("A-")
        shrink_btn.setFixedWidth(32)
        shrink_btn.clicked.connect(self.decrease_font)
        top_bar.addWidget(shrink_btn)

        grow_btn = QPushButton("A+")
        grow_btn.setFixedWidth(32)
        grow_btn.clicked.connect(self.increase_font)
        top_bar.addWidget(grow_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        top_bar.addWidget(settings_btn)

        outer.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.document().setDefaultStyleSheet(
            "body { line-height: 160%; } "
            ".you { color: #4a90e2; font-weight: 600; } "
            ".ai { color: #2ecc71; font-weight: 600; } "
            ".note { color: #888; font-style: italic; }"
        )
        self.chat_display.setStyleSheet(
            "QTextEdit { background-color: #1e1f22; color: #e8e8ea; border: none; padding: 14px; }"
        )
        splitter.addWidget(self.chat_display)

        input_container = QWidget()
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)

        self.file_label = QLabel("No file attached — drag a file onto this window, or use Attach File")
        self.file_label.setStyleSheet("color: gray; font-style: italic;")
        input_layout.addWidget(self.file_label)

        self.input_box = InputBox()
        self.input_box.setPlaceholderText("Type your message... Enter to send, Shift+Enter for a new line")
        self.input_box.setStyleSheet(
            "QTextEdit { background-color: #2a2d34; color: #e8e8ea; "
            "border: 1px solid #3a3d45; border-radius: 8px; padding: 10px; }"
        )
        self.input_box.send_requested.connect(self.send_message)
        input_layout.addWidget(self.input_box)

        splitter.addWidget(input_container)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

        button_row = QHBoxLayout()

        attach_btn = QPushButton("Attach File")
        attach_btn.clicked.connect(self.attach_file_dialog)
        button_row.addWidget(attach_btn)

        save_btn = QPushButton("Export .txt")
        save_btn.clicked.connect(self.save_chat)
        button_row.addWidget(save_btn)

        load_btn = QPushButton("Load Chat")
        load_btn.clicked.connect(self.load_chat_dialog)
        button_row.addWidget(load_btn)

        clear_btn = QPushButton("New Chat")
        clear_btn.clicked.connect(self.new_chat)
        button_row.addWidget(clear_btn)

        self.search_checkbox = QCheckBox("Search web")
        self.search_checkbox.setChecked(True)
        self.search_checkbox.setToolTip("When checked, looks up current info online before answering")
        button_row.addWidget(self.search_checkbox)

        button_row.addStretch(1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { color: #b33; font-weight: bold; }")
        self.stop_btn.clicked.connect(self.stop_response)
        button_row.addWidget(self.stop_btn)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        button_row.addWidget(self.send_btn)

        outer.addLayout(button_row)

        # Status bar — shows Thinking..., Syncing..., etc.
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #8a8f98; font-style: italic; font-size: 11px; padding: 2px 8px;"
        )
        outer.addWidget(self.status_label)

        self.setCentralWidget(central)

    def _build_settings_dialog(self):
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Settings")
        self.settings_dialog.resize(520, 500)

        outer_layout = QVBoxLayout(self.settings_dialog)
        tabs = QTabWidget()
        outer_layout.addWidget(tabs, stretch=1)

        general_tab = QWidget()
        gen_layout = QVBoxLayout(general_tab)

        gen_layout.addWidget(QLabel("Server address:"))
        self.server_url_box = QLineEdit(self.config["server_url"])
        self.server_url_box.setPlaceholderText("http://localhost:5000  or  http://100.x.x.x:5000")
        gen_layout.addWidget(self.server_url_box)

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_connection)
        gen_layout.addWidget(test_btn)

        gen_layout.addWidget(QLabel("AI name (shown in chat):"))
        self.ai_name_box = QLineEdit(self.config.get("ai_name", DEFAULT_AI_NAME))
        self.ai_name_box.setPlaceholderText("e.g. Jarvis, Atlas, Nova...")
        gen_layout.addWidget(self.ai_name_box)

        gen_layout.addWidget(QLabel("System prompt (shared across all devices — lives on the server):"))
        self.system_prompt_box = QTextEdit()
        self.system_prompt_box.setPlaceholderText("Loading from server...")
        gen_layout.addWidget(self.system_prompt_box, stretch=1)

        apply_sys_btn = QPushButton("Save to server (starts new chat)")
        apply_sys_btn.clicked.connect(self.apply_settings)
        gen_layout.addWidget(apply_sys_btn)

        tabs.addTab(general_tab, "General")

        memory_tab = QWidget()
        mem_layout = QVBoxLayout(memory_tab)

        mem_layout.addWidget(QLabel("Long-term facts the AI remembers about you:"))
        self.memory_list = QListWidget()
        mem_layout.addWidget(self.memory_list, stretch=1)

        delete_fact_btn = QPushButton("Delete selected fact")
        delete_fact_btn.clicked.connect(self.delete_selected_fact)
        mem_layout.addWidget(delete_fact_btn)

        mem_layout.addWidget(QLabel("Add a fact manually:"))
        add_row = QHBoxLayout()
        self.new_fact_box = QLineEdit()
        self.new_fact_box.setPlaceholderText("e.g. I'm studying for the EPA 608 exam")
        add_row.addWidget(self.new_fact_box, stretch=1)
        add_fact_btn = QPushButton("Add")
        add_fact_btn.clicked.connect(self.add_manual_fact)
        add_row.addWidget(add_fact_btn)
        mem_layout.addLayout(add_row)

        extract_btn = QPushButton("Extract memories from current chat")
        extract_btn.clicked.connect(self.extract_memory)
        mem_layout.addWidget(extract_btn)

        tabs.addTab(memory_tab, "Memory")
        tabs.currentChanged.connect(lambda i: self.refresh_memory_list() if i == 1 else None)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.settings_dialog.accept)
        outer_layout.addWidget(close_btn)

    def open_settings(self):
        try:
            resp = requests.get(f"{self.config['server_url']}/api/settings/prompt", timeout=5)
            prompt = resp.json().get("prompt", "")
            self.system_prompt_box.setPlainText(prompt)
        except Exception:
            self.system_prompt_box.setPlaceholderText("Could not reach server")
        self.refresh_memory_list()
        self.settings_dialog.exec()

    def _apply_font(self):
        font = QFont("Segoe UI", self.font_size)
        self.chat_display.setFont(font)
        self.input_box.setFont(font)

    def increase_font(self):
        if self.font_size < 28:
            self.font_size += 1
            self._apply_font()

    def decrease_font(self):
        if self.font_size > 10:
            self.font_size -= 1
            self._apply_font()

    def _append_html(self, html):
        self.chat_display.append(html)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        bar = self.chat_display.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _render_user_message(self, text):
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self._append_html(f"<div class='you'>You</div><br><div>{safe}</div><br>")

    def _render_ai_label(self):
        name = self.config.get("ai_name", DEFAULT_AI_NAME)
        self._append_html(f"<div class='ai'>{name}</div><br>")
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#e8e8ea"))
        cursor.setCharFormat(fmt)
        self.chat_display.setTextCursor(cursor)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        self._load_file(urls[0].toLocalFile())

    def _load_models(self):
        self.model_dropdown.clear()
        try:
            resp = requests.get(f"{self.config['server_url']}/api/models", timeout=5)
            models = resp.json().get("models", [])
            self.model_dropdown.addItems(models if models else ["No models found"])
        except Exception:
            self.model_dropdown.addItem("Server not reachable")

    def _resume_or_start_conversation(self):
        try:
            resp = requests.get(f"{self.config['server_url']}/api/conversations/latest", timeout=5)
            data = resp.json()
            self.conversation_id = data["conversation_id"]
            self.conversation = data["messages"]
            self._last_message_count = len(self.conversation)
            self.chat_display.clear()
            for msg in self.conversation:
                if msg["role"] == "user":
                    self._render_user_message(msg["content"])
                else:
                    self._render_ai_label()
                    self._append_html(_markdown_to_html(msg["content"]))
            if self.conversation:
                self._append_html("<div class='note'>[Resumed previous conversation]</div>")
        except Exception:
            self._append_html(
                "<div class='note'>[Could not reach the server. Check Settings → "
                "Server Address, and confirm app.py is running on the brain PC.]</div>"
            )

    def _start_new_conversation(self):
        try:
            resp = requests.post(
                f"{self.config['server_url']}/api/conversations/new",
                json={"title": "New Chat"},
                timeout=5,
            )
            data = resp.json()
            self.conversation_id = data["conversation_id"]
            self.conversation = []
            self._last_message_count = 0
            self.chat_display.clear()
        except Exception as e:
            QMessageBox.warning(self, "Server error", f"Could not start a new chat:\n{e}")

    def _load_conversation(self, conversation_id):
        try:
            resp = requests.get(f"{self.config['server_url']}/api/conversations/{conversation_id}", timeout=5)
            data = resp.json()
            self.conversation_id = data["conversation_id"]
            self.conversation = data["messages"]
            self._last_message_count = len(self.conversation)
            self.chat_display.clear()
            for msg in self.conversation:
                if msg["role"] == "user":
                    self._render_user_message(msg["content"])
                else:
                    self._render_ai_label()
                    self._append_html(_markdown_to_html(msg["content"]))
            self._append_html("<div class='note'>[Loaded conversation]</div>")
        except Exception as e:
            QMessageBox.warning(self, "Server error", f"Could not load that conversation:\n{e}")

    def _poll_for_updates(self):
        """Check every 3s if current conversation has new/updated messages.
        Catches responses that finished while the app was closed or away."""
        if self.isStreaming or not self.conversation_id:
            return
        try:
            resp = requests.get(
                f"{self.config['server_url']}/api/conversations/{self.conversation_id}",
                timeout=3
            )
            messages = resp.json().get("messages", [])
            if len(messages) == self._last_message_count:
                return
            if not messages or messages[-1]["role"] != "assistant":
                return
            last_displayed = self.conversation[-1] if self.conversation else None
            last_fetched = messages[-1]
            if (not last_displayed or
                last_displayed["role"] != "assistant" or
                last_displayed["content"] != last_fetched["content"]):
                self.status_label.setText("Syncing...")
                self._last_message_count = len(messages)
                self.conversation = messages
                self.chat_display.clear()
                for msg in messages:
                    if msg["role"] == "user":
                        self._render_user_message(msg["content"])
                    else:
                        self._render_ai_label()
                        self._append_html(_markdown_to_html(msg["content"]))
                self._scroll_to_bottom()
                self.status_label.setText("")
        except Exception:
            pass

    def load_chat_dialog(self):
        try:
            resp = requests.get(f"{self.config['server_url']}/api/conversations", timeout=5)
            conversations = resp.json()
        except Exception as e:
            QMessageBox.warning(self, "Server error", f"Could not fetch conversation list:\n{e}")
            return
        if not conversations:
            QMessageBox.information(self, "No history", "No saved conversations yet.")
            return
        dialog = LoadChatDialog(conversations, self.config["server_url"], self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_id:
            self._load_conversation(dialog.selected_id)

    def attach_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach a text file", "",
            "Text/Code files (*.txt *.py *.md *.csv *.json *.log);;All files (*)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                self.attached_file_text = f.read()
            self.attached_file_name = path.replace("\\", "/").split("/")[-1]
            self.file_label.setText(
                f"Attached: {self.attached_file_name} "
                f"({len(self.attached_file_text)} chars) — will be included in next message"
            )
            self.file_label.setStyleSheet("color: #2a7; font-style: italic;")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not read file:\n{e}")

    def save_chat(self):
        if not self.conversation:
            QMessageBox.information(self, "Nothing to save", "No conversation yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export chat", "chat.txt", "Text files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for msg in self.conversation:
                role = "You" if msg["role"] == "user" else self.config.get("ai_name", DEFAULT_AI_NAME)
                f.write(f"{role}: {msg['content']}\n\n")
        QMessageBox.information(self, "Exported", f"Chat exported to {path}")

    def apply_settings(self):
        if self.conversation_id and self.conversation:
            self._run_extraction(silent=True)
        self.config["server_url"] = self.server_url_box.text().strip().rstrip("/") or DEFAULT_SERVER_URL
        self.config["ai_name"] = self.ai_name_box.text().strip() or DEFAULT_AI_NAME
        save_config(self.config)
        prompt = self.system_prompt_box.toPlainText().strip()
        if prompt:
            try:
                requests.post(
                    f"{self.config['server_url']}/api/settings/prompt",
                    json={"prompt": prompt},
                    timeout=5
                )
            except Exception:
                pass
        self._load_models()
        self._start_new_conversation()
        if self.settings_dialog.isVisible():
            self.settings_dialog.accept()

    def test_connection(self):
        url = self.server_url_box.text().strip().rstrip("/")
        try:
            resp = requests.get(f"{url}/api/models", timeout=5)
            models = resp.json().get("models", [])
            QMessageBox.information(
                self, "Connection OK",
                f"Connected successfully. Found {len(models)} model(s) on the server."
            )
        except Exception as e:
            QMessageBox.warning(self, "Connection failed", f"Could not reach {url}\n\n{e}")

    def refresh_memory_list(self):
        self.memory_list.clear()
        try:
            resp = requests.get(f"{self.config['server_url']}/api/memory", timeout=5)
            facts = resp.json().get("facts", [])
            for f in facts:
                item = QListWidgetItem(f["fact"])
                item.setData(Qt.ItemDataRole.UserRole, f["id"])
                self.memory_list.addItem(item)
        except Exception as e:
            self.memory_list.addItem(f"[Could not load memory: {e}]")

    def add_manual_fact(self):
        fact = self.new_fact_box.text().strip()
        if not fact:
            return
        try:
            requests.post(f"{self.config['server_url']}/api/memory", json={"fact": fact}, timeout=5)
            self.new_fact_box.clear()
            self.refresh_memory_list()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save fact:\n{e}")

    def delete_selected_fact(self):
        item = self.memory_list.currentItem()
        if not item:
            return
        fact_id = item.data(Qt.ItemDataRole.UserRole)
        if fact_id is None:
            return
        try:
            requests.delete(f"{self.config['server_url']}/api/memory/{fact_id}", timeout=5)
            self.refresh_memory_list()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not delete fact:\n{e}")

    def extract_memory(self):
        self._run_extraction(silent=False)

    def _run_extraction(self, silent=False):
        if not self.conversation_id or not self.conversation:
            return
        model = self.model_dropdown.currentText()
        if not model or "not reachable" in model or "No models" in model:
            return
        try:
            resp = requests.post(
                f"{self.config['server_url']}/api/memory/extract",
                json={"conversation_id": self.conversation_id, "model": model},
                timeout=120,
            )
            added = resp.json().get("facts_added", [])
            if hasattr(self, "memory_list"):
                self.refresh_memory_list()
            if not silent:
                if added:
                    QMessageBox.information(
                        self, "Memory updated",
                        "Added:\n" + "\n".join(f"- {f}" for f in added)
                    )
                else:
                    QMessageBox.information(self, "Memory updated", "Nothing new worth remembering was found.")
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "Error", f"Could not extract memories:\n{e}")

    def new_chat(self):
        if self.conversation_id and self.conversation:
            self._append_html("<div class='note'>[Saving memories before starting fresh...]</div>")
            QApplication.processEvents()
            self._run_extraction(silent=True)
        self._start_new_conversation()
        self.attached_file_text = None
        self.attached_file_name = None
        self.file_label.setText("No file attached — drag a file onto this window, or use Attach File")
        self.file_label.setStyleSheet("color: gray; font-style: italic;")

    def send_message(self):
        if self.worker is not None and self.worker.isRunning():
            return

        text = self.input_box.toPlainText().strip()
        if not text or not self.conversation_id:
            return

        model = self.model_dropdown.currentText()
        if not model or "not reachable" in model or "No models" in model:
            QMessageBox.warning(self, "No model", "No valid model selected. Click Refresh.")
            return

        display_text = text
        if self.attached_file_text:
            text = (f"[Attached file: {self.attached_file_name}]\n"
                    f"{self.attached_file_text}\n\n"
                    f"[User message]\n{text}")
            self.attached_file_text = None
            self.attached_file_name = None
            self.file_label.setText("No file attached — drag a file onto this window, or use Attach File")
            self.file_label.setStyleSheet("color: gray; font-style: italic;")

        self.conversation.append({"role": "user", "content": text})
        self._render_user_message(display_text)
        self._render_ai_label()
        self._ai_response_start_pos = self.chat_display.textCursor().position()
        self.input_box.clear()

        self.isStreaming = True
        self.status_label.setText("Thinking...")
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = ChatWorker(
            self.config["server_url"], self.conversation_id, text, model,
            search=self.search_checkbox.isChecked()
        )
        self.worker.response_chunk.connect(self._on_chunk)
        self.worker.finished_response.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self._current_response = ""
        self.worker.start()

    def stop_response(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self._append_html("<div class='note'>[stopped]</div>")

    def _on_chunk(self, chunk):
        self._current_response += chunk
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.insertPlainText(chunk)
        self._scroll_to_bottom()

    def _on_finished(self):
        self.isStreaming = False
        self.status_label.setText("")
        if self._current_response:
            self.conversation.append({"role": "assistant", "content": self._current_response})
            self._last_message_count = len(self.conversation)
            if hasattr(self, "_ai_response_start_pos"):
                cursor = self.chat_display.textCursor()
                cursor.setPosition(self._ai_response_start_pos)
                cursor.movePosition(cursor.MoveOperation.End, cursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                cursor.insertHtml(_markdown_to_html(self._current_response))
        self.chat_display.append("")
        self._scroll_to_bottom()
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.input_box.setFocus()

    def _on_error(self, message):
        self.isStreaming = False
        self.status_label.setText("")
        self._append_html(f"<span style='color:red;'>[Error: {message}]</span>")
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        if getattr(self, "_ready_to_close", False):
            event.accept()
            return
        if not self.conversation_id or not self.conversation:
            event.accept()
            return
        model = self.model_dropdown.currentText()
        if not model or "not reachable" in model or "No models" in model:
            event.accept()
            return
        event.ignore()
        self.setWindowTitle("Local AI Chat — saving memory before closing...")
        self._close_worker = ExtractionWorker(self.config["server_url"], self.conversation_id, model)
        self._close_worker.finished_ok.connect(self._finish_closing)
        self._close_worker.failed.connect(lambda _err: self._finish_closing([]))
        self._close_worker.start()
        QTimer.singleShot(15000, lambda: self._finish_closing([]) if not getattr(self, "_ready_to_close", False) else None)

    def _finish_closing(self, _added):
        if getattr(self, "_ready_to_close", False):
            return
        self._ready_to_close = True
        self.close()

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

def main():
    app = QApplication(sys.argv)
    window = ChatWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()