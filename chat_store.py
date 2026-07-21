"""
chat_store.py - shared SQLite persistence layer.

One database, one personality across all devices:
- conversations + messages: full chat history
- memory: long-term facts extracted from conversations
- settings: server-side config (system prompt) shared across all clients
"""

import sqlite3
import datetime

DEFAULT_SYSTEM_PROMPT = (
    "You are a sharp, practical assistant and hands-on mentor. "
    "Your #1 rule: always ask a clarifying question before giving a long answer. "
    "When someone asks if you can help with something, say yes and ask ONE specific question to understand what they actually need — never assume and never dump information unprompted. "
    "When teaching: ask what they already know first, then tailor from there. Show one small example at a time. Wait for their response before continuing. "
    "When answering factual questions: answer directly in 1-3 sentences, then ask if they want to go deeper. "
    "Never give lists, overviews, or multi-part explanations unless specifically asked. "
    "One idea at a time. One question at a time. Short messages always. "
    "You can update your own behavior mid-conversation: if the user asks you to always do something differently, "
    "emit [UPDATE_PROMPT: your revised instruction here] at the END of your reply. "
    "The system will save it and it will take effect from the next message onward. "
    "Only emit this when the user is explicitly asking you to change how you behave permanently — not for one-off requests."
)


class ChatStore:
    """One row per conversation, one row per message, one personality for all devices."""

    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        # Seed the default system prompt if not already set
        existing = self.conn.execute(
            "SELECT value FROM settings WHERE key = 'system_prompt'"
        ).fetchone()
        if not existing:
            now = datetime.datetime.now().isoformat()
            self.conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ("system_prompt", DEFAULT_SYSTEM_PROMPT, now)
            )
        self.conn.commit()

    # ---- settings ----
    def get_setting(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        now = datetime.datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now)
        )
        self.conn.commit()

    def get_system_prompt(self):
        return self.get_setting("system_prompt", DEFAULT_SYSTEM_PROMPT)

    def set_system_prompt(self, prompt):
        self.set_setting("system_prompt", prompt)

    # ---- conversations ----
    def create_conversation(self, title, system_prompt=None):
        prompt = system_prompt or self.get_system_prompt()
        now = datetime.datetime.now().isoformat()
        cur = self.conn.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        conv_id = cur.lastrowid
        self.add_message(conv_id, "system", prompt)
        self.conn.commit()
        return conv_id

    def add_message(self, conversation_id, role, content):
        now = datetime.datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        self.conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
        self.conn.commit()

    def get_latest_conversation_id(self):
        row = self.conn.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def load_messages(self, conversation_id):
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    def list_conversations(self):
        return self.conn.execute(
            "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()

    def rename_conversation(self, conversation_id, title):
        self.conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )
        self.conn.commit()

    def delete_conversation(self, conversation_id):
        self.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self.conn.commit()

    # ---- memory ----
    def add_memory_fact(self, fact):
        now = datetime.datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO memory (fact, created_at) VALUES (?, ?)", (fact, now)
        )
        self.conn.commit()

    def get_memory_facts(self):
        rows = self.conn.execute(
            "SELECT id, fact FROM memory ORDER BY id ASC"
        ).fetchall()
        return [{"id": r[0], "fact": r[1]} for r in rows]

    def get_memory_fact_texts(self):
        return [f["fact"] for f in self.get_memory_facts()]

    def delete_memory_fact(self, fact_id):
        self.conn.execute("DELETE FROM memory WHERE id = ?", (fact_id,))
        self.conn.commit()
