"""
app.py - Local AI Chat brain server.
"""

import os
import re
import json
import requests
from flask import Flask, request, Response, jsonify, render_template

from chat_store import ChatStore

OLLAMA_URL = "http://localhost:11434"

APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LocalAIChat")
os.makedirs(APPDATA_DIR, exist_ok=True)
DB_PATH = os.path.join(APPDATA_DIR, "chat_history.db")

app = Flask(__name__)
store = ChatStore(DB_PATH)

UPDATE_PROMPT_RE = re.compile(r'\[UPDATE_PROMPT:\s*(.*?)\]', re.DOTALL)


def web_search(query, max_results=5):
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        return results
    except Exception:
        return []


def build_search_context(query, results):
    if not results:
        return None
    lines = [f"{i+1}. {r['title']} — {r['snippet']} ({r['url']})" for i, r in enumerate(results)]
    return (
        f"Web search results for \"{query}\":\n" + "\n".join(lines) +
        "\n\nUse these results to answer accurately with current information. Mention sources naturally."
    )


def build_system_prompt():
    base = store.get_system_prompt()
    facts = store.get_memory_fact_texts()
    if not facts:
        return base
    memory_block = "\n".join(f"- {fact}" for fact in facts)
    return (
        f"{base}\n\n"
        f"Here is what you remember about this person from past conversations:\n"
        f"{memory_block}\n"
        f"Use this naturally, without announcing that you're reading from memory."
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/models")
def models():
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        names = [m["name"] for m in resp.json().get("models", [])]
        return jsonify({"models": names})
    except Exception as e:
        return jsonify({"models": [], "error": str(e)}), 200


@app.route("/api/settings/prompt", methods=["GET", "POST"])
def settings_prompt():
    if request.method == "POST":
        prompt = (request.json or {}).get("prompt", "").strip()
        if prompt:
            store.set_system_prompt(prompt)
        return jsonify({"ok": True, "prompt": store.get_system_prompt()})
    return jsonify({"prompt": store.get_system_prompt()})


@app.route("/api/conversations")
def conversations():
    rows = store.list_conversations()
    return jsonify([{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows])


@app.route("/api/conversations/latest")
def latest_conversation():
    conv_id = store.get_latest_conversation_id()
    if conv_id is None:
        conv_id = store.create_conversation("New Chat")
    messages = [m for m in store.load_messages(conv_id) if m["role"] != "system"]
    return jsonify({"conversation_id": conv_id, "messages": messages})


@app.route("/api/conversations/<int:conv_id>", methods=["GET"])
def get_conversation(conv_id):
    messages = [m for m in store.load_messages(conv_id) if m["role"] != "system"]
    return jsonify({"conversation_id": conv_id, "messages": messages})


@app.route("/api/conversations/new", methods=["POST"])
def new_conversation():
    body = request.json if request.is_json else {}
    title = body.get("title", "New Chat")
    conv_id = store.create_conversation(title)
    return jsonify({"conversation_id": conv_id})


@app.route("/api/conversations/<int:conv_id>/rename", methods=["POST"])
def rename_conversation(conv_id):
    title = (request.json or {}).get("title", "").strip()
    if title:
        store.rename_conversation(conv_id, title)
    return jsonify({"ok": True})


@app.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    store.delete_conversation(conv_id)
    return jsonify({"ok": True})


@app.route("/api/memory", methods=["GET", "POST"])
def memory():
    if request.method == "POST":
        fact = (request.json or {}).get("fact", "").strip()
        if fact:
            store.add_memory_fact(fact)
        return jsonify({"ok": True})
    return jsonify({"facts": store.get_memory_facts()})


@app.route("/api/memory/<int:fact_id>", methods=["DELETE"])
def delete_memory(fact_id):
    store.delete_memory_fact(fact_id)
    return jsonify({"ok": True})


EXTRACTION_PROMPT = (
    "Review the conversation above. List only durable facts worth remembering "
    "about this person for future conversations: their name, preferences, "
    "ongoing projects, goals, skills, or important context. Do NOT include "
    "one-off questions or anything already obvious from a single message. "
    "Reply with ONLY a plain bullet list, one fact per line, starting each "
    "line with '- '. If there is nothing durable worth remembering, reply "
    "with exactly: NONE"
)


@app.route("/api/memory/extract", methods=["POST"])
def extract_memory():
    data = request.json or {}
    conv_id = data.get("conversation_id")
    model = data.get("model")
    if not conv_id or not model:
        return jsonify({"error": "conversation_id and model are required"}), 400

    history = store.load_messages(conv_id)
    extraction_messages = history + [{"role": "user", "content": EXTRACTION_PROMPT}]

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": model, "messages": extraction_messages, "stream": False},
            timeout=120,
        )
        reply = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    new_facts = []
    for line in reply.splitlines():
        line = line.strip()
        if line.startswith("-"):
            line = line.lstrip("-").strip()
        if line and line.upper() != "NONE":
            store.add_memory_fact(line)
            new_facts.append(line)

    return jsonify({"facts_added": new_facts})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    conv_id = data["conversation_id"]
    user_text = data["message"]
    model = data["model"]
    use_search = bool(data.get("search", False))

    store.add_message(conv_id, "user", user_text)
    history = store.load_messages(conv_id)

    fresh_prompt = build_system_prompt()
    if history and history[0]["role"] == "system":
        history = [{"role": "system", "content": fresh_prompt}] + history[1:]

    if use_search:
        results = web_search(user_text)
        context = build_search_context(user_text, results)
        if context:
            history = history[:-1] + [{"role": "system", "content": context}, history[-1]]

    # Insert placeholder immediately — server updates it every 10 chunks.
    # Closing the app mid-stream no longer loses the response.
    placeholder_id = store.insert_message_placeholder(conv_id, "assistant")

    def generate():
        full_response = ""
        chunk_count = 0
        save_interval = 10
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": model, "messages": history, "stream": True},
                stream=True,
                timeout=120,
            )
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk_data = json.loads(line.decode("utf-8"))
                piece = chunk_data.get("message", {}).get("content", "")
                if piece:
                    full_response += piece
                    chunk_count += 1
                    if chunk_count % save_interval == 0:
                        store.update_message(placeholder_id, full_response)
                    yield piece
                if chunk_data.get("done"):
                    break
        except Exception as e:
            yield f"\n[Error: {e}]"
        finally:
            if full_response:
                match = UPDATE_PROMPT_RE.search(full_response)
                if match:
                    new_instruction = match.group(1).strip()
                    if new_instruction:
                        current = store.get_system_prompt()
                        updated = current + "\n" + new_instruction
                        store.set_system_prompt(updated)
                    full_response = UPDATE_PROMPT_RE.sub("", full_response).strip()
                store.update_message(placeholder_id, full_response)

    return Response(generate(), mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)