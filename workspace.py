#!/usr/bin/env python3
"""A persistent session sidebar around the real Codex terminal UI."""
from __future__ import annotations

import argparse
import concurrent.futures
import curses
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import sqlite3
import socket
import subprocess
import sys
import threading
import time
import uuid
import signal
import fcntl
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent


def resolve_codex():
    """Find user installs even when a desktop launcher bypasses shell setup."""
    configured = os.environ.get("CODEX_WORKSPACE_CODEX")
    if configured is not None:
        return configured
    found = shutil.which("codex")
    if found:
        return found
    for directory in (Path.home() / ".local/bin", Path.home() / "bin"):
        found = shutil.which(str(directory / "codex"))
        if found:
            return found
    return "codex"


DATA = Path(os.environ.get("CODEX_WORKSPACE_DATA", Path.home() / ".local/share/codex-workspace"))
SOCKET = os.environ.get("CODEX_WORKSPACE_SOCKET", "codex-workspace")
SESSION = "workspace"
CODEX = resolve_codex()
MODES = {"auto": "Auto", "conversation": "Conversation", "project": "Project work"}
MODE_MARKER = "\n\n[Codex Workspace mode]\n"
TOPICS = {"misc": "Misc", "misc/tailscale": "Tailscale",
          "misc/local-models": "Local models", "misc/local-models/qwen": "Qwen"}


def topic_for(thread):
    topic = thread.get("workspaceTopic")
    return topic if topic in TOPICS else None


def set_session_topic(tid, topic):
    """Change sidebar placement only; leave native history and execution intact."""
    if topic is not None and topic not in TOPICS:
        raise ValueError("Unknown topic")
    with drafts() as db:
        if topic is None:
            db.execute("DELETE FROM session_topics WHERE id = ?", (tid,))
        else:
            db.execute("INSERT OR REPLACE INTO session_topics VALUES (?, ?)", (tid, topic))


def run(args, **kwargs):
    p = subprocess.run(args, text=True, capture_output=True, timeout=30, **kwargs)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout or f"Command failed: {args[0]}").strip())
    return p.stdout.strip()


def tmux(*args):
    return run(["tmux", "-L", SOCKET, *map(str, args)])


def command(*args):
    return shlex.join([sys.executable, str(ROOT / "workspace.py"), *map(str, args)])


def save_preferences(**values):
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (DATA / "preferences.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prefs = preferences()
        prefs.update(values)
        temp = DATA / "preferences.tmp"
        temp.write_text(json.dumps(prefs, indent=2) + "\n")
        temp.chmod(0o600)
        temp.replace(DATA / "preferences.json")


def preferences():
    try:
        return json.loads((DATA / "preferences.json").read_text())
    except (OSError, ValueError):
        return {}


def initialize_projects():
    if "projects" in preferences():
        return
    root = Path(os.environ.get("CODEX_WORKSPACE_PROJECTS_ROOT", Path.home()))
    markers = ("README.md", ".git", "pyproject.toml", "package.json", "pubspec.yaml", "Cargo.toml")
    projects = []
    for folder in root.iterdir():
        if not folder.name.startswith(".") and folder.is_dir() and any((folder / marker).exists() for marker in markers):
            projects.append(str(folder.resolve()))
    save_preferences(projects=sorted(projects))


@contextmanager
def drafts():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / "drafts.sqlite")
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, data TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS session_modes (id TEXT PRIMARY KEY, mode TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS session_projects (id TEXT PRIMARY KEY, project TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS session_models (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS session_topics (id TEXT PRIMARY KEY, topic TEXT NOT NULL)")
            yield db
    finally:
        db.close()


def session_mode(tid):
    with drafts() as db:
        row = db.execute("SELECT mode FROM session_modes WHERE id = ?", (tid,)).fetchone()
    return row[0] if row and row[0] in MODES else "auto"


def set_session_mode(tid, mode):
    if mode not in MODES:
        raise ValueError("Unknown workspace mode")
    with drafts() as db:
        db.execute("INSERT OR REPLACE INTO session_modes VALUES (?, ?)", (tid, mode))


def session_model(tid):
    with drafts() as db:
        row = db.execute("SELECT data FROM session_models WHERE id = ?", (tid,)).fetchone()
    return json.loads(row[0]) if row else {}


def set_session_model(tid, model):
    with drafts() as db:
        db.execute("INSERT OR REPLACE INTO session_models VALUES (?, ?)", (tid, json.dumps(model)))


def model_label(model):
    return ("Local · " if model.get("provider") == "ollama" else "") + model.get("model", "Codex default")


def available_models(rpc):
    choices = [{}]
    errors = []
    try:
        cursor = None
        while True:
            result = rpc.call("model/list", {"cursor": cursor})
            choices.extend({"provider": "openai", "model": m["model"]} for m in result["data"])
            cursor = result.get("nextCursor")
            if not cursor:
                break
    except (RuntimeError, OSError) as exc:
        errors.append("Codex catalog unavailable: " + str(exc))
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if result.returncode:
            errors.append("Ollama unavailable; start its service")
        else:
            choices.extend({"provider": "ollama", "model": line.split()[0]}
                           for line in result.stdout.splitlines()[1:] if line.strip())
    except (OSError, subprocess.TimeoutExpired):
        errors.append("Ollama unavailable")
    return choices, "; ".join(errors)


def set_session_project(tid, project):
    """Organize history without changing its execution directory or AI mode."""
    if project:
        folder = Path(project).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("Project folder does not exist")
        project = str(folder)
    with drafts() as db:
        db.execute("INSERT OR REPLACE INTO session_projects VALUES (?, ?)", (tid, project or ""))


def project_for(thread):
    if "workspaceProject" in thread:
        return thread["workspaceProject"] or None
    cwd = str(Path(thread.get("cwd") or Path.home()).expanduser())
    mode = thread.get("workspaceMode", "auto")
    return None if mode == "conversation" or (cwd == str(Path.home()) and mode == "auto") else cwd


def mode_transform(mode, baseline="", model=None):
    if mode not in MODES:
        raise ValueError("Unknown workspace mode")
    instruction = (ROOT / "policies" / (mode + ".md")).read_text()
    def transform(request):
        if request.get("method") not in ("thread/start", "thread/resume"):
            return None
        params = request.setdefault("params", {})
        existing = params.get("developerInstructions")
        if existing is None:
            existing = (params.get("config") or {}).get("developer_instructions", baseline)
        existing = (existing or "").split(MODE_MARKER, 1)[0]
        params["developerInstructions"] = existing + MODE_MARKER + instruction
        if model:
            params["model"] = model["model"]
            params["modelProvider"] = model["provider"]
        return request
    return transform


def wait_service():
    deadline = time.monotonic() + 15
    while True:
        try:
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                probe.connect(str(DATA / "server.sock"))
            return
        except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
            if time.monotonic() >= deadline:
                raise RuntimeError("Session service did not start. Check " + str(DATA / "app-server.log"))
            time.sleep(0.1)


class Rpc:
    """JSON-RPC transport; no shell interpolation and no model turns of its own."""

    def __init__(self, standalone=False):
        DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = (DATA / "app-server.log").open("a")
        args = [CODEX, "app-server", "--stdio"] if standalone else [
            sys.executable, str(ROOT / "workspace.py"), "proxy", str(DATA / "server.sock")]
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, text=True, bufsize=1)
        self.pending = {}
        self.lock = threading.Lock()
        self.counter = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "codex_workspace", "version": "0.1.0"}})
            self._write({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def _write(self, data):
        with self.lock:
            self.process.stdin.write(json.dumps(data) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                if not line.strip():
                    continue
                data = json.loads(line)
                if "method" in data:
                    # This client never starts a turn. Interactive approvals belong to Codex.
                    if "id" in data:
                        self._write({"id": data["id"], "error": {
                            "code": -32601, "message": "Use the Codex conversation for this request"}})
                    continue
                with self.lock:
                    waiter = self.pending.get(data.get("id"))
                if waiter:
                    waiter.put(data)
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({"error": {"message": "Codex connection closed; press r to reconnect"}})

    def call(self, method, params, timeout=30):
        waiter = queue.Queue()
        with self.lock:
            self.counter += 1
            request_id = self.counter
            self.pending[request_id] = waiter
        try:
            self._write({"id": request_id, "method": method, "params": params})
            try:
                result = waiter.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError(f"Codex timed out: {method}") from None
            if "error" in result:
                raise RuntimeError(result["error"].get("message", str(result["error"])))
            return result["result"]
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def threads(self, archived=False, live_ids=None):
        items, cursor = [], None
        while True:
            result = self.call("thread/list", {"limit": 100, "cursor": cursor,
                "archived": archived, "sortKey": "updated_at",
                "sourceKinds": ["cli", "vscode", "appServer"], "modelProviders": []})
            items.extend(result["data"])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        # Codex intentionally omits conversations that have no first user message.
        # Keep only those drafts indexed locally; history remains owned by Codex.
        with drafts() as db:
            for tid, data, is_archived in db.execute("SELECT id, data, archived FROM drafts").fetchall():
                if any(t["id"] == tid for t in items):
                    db.execute("DELETE FROM drafts WHERE id = ?", (tid,))
                elif bool(is_archived) == archived:
                    draft = json.loads(data)
                    # Older blank-session buttons created persistent placeholders.
                    temporary = draft.get("temporary") or (draft.get("name") == "New session"
                        and draft.get("cwd") == str(Path.home()) and not draft.get("preview"))
                    if temporary:
                        if live_ids is None:
                            continue
                        if tid not in live_ids and draft.get("workspaceDraftId") not in live_ids:
                            # Only remove our placeholder; Codex owns real history.
                            db.execute("DELETE FROM drafts WHERE id = ?", (tid,))
                            continue
                        draft["temporary"] = True
                    items.append(draft)
            modes = dict(db.execute("SELECT id, mode FROM session_modes"))
            projects = dict(db.execute("SELECT id, project FROM session_projects"))
            models = dict(db.execute("SELECT id, data FROM session_models"))
            topics = dict(db.execute("SELECT id, topic FROM session_topics"))
        for item in items:
            item["workspaceMode"] = modes.get(item["id"], "auto")
            item["workspaceModel"] = json.loads(models.get(item["id"], "{}"))
            item["workspaceTopic"] = topics.get(item["id"])
            if item["id"] in projects:
                item["workspaceProject"] = projects[item["id"]]
        return sorted(items, key=lambda t: t.get("updatedAt", 0), reverse=True)

    def create(self, name, cwd, mode="auto", temporary=False):
        if mode not in MODES:
            raise ValueError("Unknown workspace mode")
        thread = {"id": str(uuid.uuid4()), "name": name, "cwd": cwd,
                  "updatedAt": int(time.time()), "path": None, "draft": True,
                  "workspaceMode": mode, "temporary": temporary}
        with drafts() as db:
            db.execute("INSERT OR REPLACE INTO drafts (id, data) VALUES (?, ?)",
                       (thread["id"], json.dumps(thread)))
            db.execute("INSERT INTO session_modes VALUES (?, ?)", (thread["id"], mode))
        model = preferences().get("new_session_model", {})
        set_session_model(thread["id"], model)
        thread["workspaceModel"] = model
        return thread

    def create_or_reuse(self, name, cwd, mode, live_ids, topic=None):
        if topic is not None and topic not in TOPICS:
            raise ValueError("Unknown topic")
        for thread in self.threads(live_ids=live_ids):
            if (thread.get("temporary") and thread.get("cwd") == cwd
                    and topic_for(thread) == topic
                    and thread.get("workspaceModel", {}) == preferences().get("new_session_model", {})
                    and (cwd == str(Path.home()) or thread.get("workspaceMode") == mode)):
                return thread
        thread = self.create(name, cwd, mode, temporary=True)
        if topic:
            set_session_topic(thread["id"], topic)
            thread["workspaceTopic"] = topic
        return thread

    def change(self, action, tid, name=None):
        params = {"threadId": tid}
        if name is not None:
            params["name"] = name
        with drafts() as db:
            row = db.execute("SELECT data FROM drafts WHERE id = ?", (tid,)).fetchone()
        draft = json.loads(row[0]) if row else None
        empty = draft and not Path(draft.get("path") or "/nonexistent").exists()
        # Empty drafts have no Codex rollout yet. Their lifecycle is local until
        # the first message is sent; never fabricate a user message to persist one.
        result = {} if empty else self.call("thread/" + action, params)
        if empty and action == "name/set" and not draft.get("draft"):
            try:
                self.call("thread/name/set", params)
            except RuntimeError as exc:
                if "not found" not in str(exc) and "no rollout" not in str(exc):
                    raise
        with drafts() as db:
            if action == "delete":
                db.execute("DELETE FROM drafts WHERE id = ?", (tid,))
                db.execute("DELETE FROM session_modes WHERE id = ?", (tid,))
                db.execute("DELETE FROM session_projects WHERE id = ?", (tid,))
                db.execute("DELETE FROM session_models WHERE id = ?", (tid,))
                db.execute("DELETE FROM session_topics WHERE id = ?", (tid,))
            elif action in ("archive", "unarchive"):
                db.execute("UPDATE drafts SET archived = ? WHERE id = ?", (action == "archive", tid))
            elif action == "name/set":
                row = db.execute("SELECT data FROM drafts WHERE id = ?", (tid,)).fetchone()
                if row:
                    data = json.loads(row[0])
                    data["name"] = name
                    db.execute("UPDATE drafts SET data = ? WHERE id = ?", (json.dumps(data), tid))
        return result

    def ensure(self, thread):
        # A draft opens a fresh native TUI; only Codex creates its live thread.
        return thread

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.log.close()


class Workspace:
    def repair(self):
        """Restart crashed support panes without disturbing conversations."""
        for pane in self.panes():
            mode = {"service": "server", "sidebar": "sidebar"}.get(pane["thread"])
            if mode and pane["dead"] == "1":
                tmux("respawn-pane", "-k", "-t", pane["pane"], command(mode))
                if mode == "server":
                    wait_service()

    def panes(self):
        fields = "#{pane_id}\t#{window_id}\t#{@workspace_thread}\t#{pane_dead}\t#{@workspace_mode}"
        rows = tmux("list-panes", "-s", "-t", SESSION, "-F", fields)
        return [dict(zip(("pane", "window", "thread", "dead", "mode"), line.split("\t")))
                for line in rows.splitlines()]

    def visible_window(self):
        return tmux("show-options", "-qv", "-t", SESSION, "@workspace_window")

    def main(self):
        return next(p for p in self.panes()
                    if p["window"] == self.visible_window() and p["thread"] != "sidebar")

    def focus(self):
        tmux("select-pane", "-t", self.main()["pane"])

    def open(self, thread):
        tid = thread["id"]
        cwd = thread.get("cwd") or str(Path.home())
        if not Path(cwd).is_dir():
            raise RuntimeError(f"Project directory no longer exists: {cwd}")
        found = next((p for p in self.panes() if p["thread"] == tid), None)
        if found and found["dead"] == "1":
            tmux("respawn-pane", "-k", "-t", found["pane"], "-c", cwd, command("run", tid, cwd))
        elif not found:
            pane = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", SESSION + ":",
                        "-n", "conversation", "-c", cwd, command("run", tid, cwd))
            tmux("set-option", "-p", "-t", pane, "@workspace_thread", tid)
            found = next(p for p in self.panes() if p["pane"] == pane)
        main = self.main()
        if main["pane"] != found["pane"]:
            tmux("swap-pane", "-d", "-s", found["pane"], "-t", main["pane"])
        save_preferences(last_session=tid)
        self.focus()

    def close(self, tid):
        found = next((p for p in self.panes() if p["thread"] == tid), None)
        if not found:
            return
        if found["pane"] == self.main()["pane"]:
            home = next(p for p in self.panes() if p["thread"] == "home")
            tmux("swap-pane", "-d", "-s", home["pane"], "-t", found["pane"])
            found = next(p for p in self.panes() if p["thread"] == tid)
        tmux("kill-pane", "-t", found["pane"])


def clean(text):
    return " ".join(str(text).split())


def title(thread):
    return clean(thread.get("name") or thread.get("preview") or "Untitled conversation")


def session_copy(thread, kind):
    if kind == "id":
        return thread["id"]
    if kind == "path":
        return project_for(thread) or thread.get("cwd", "")
    if kind == "resume":
        if thread.get("draft") or not thread.get("path"):
            raise RuntimeError("No saved history yet; open this draft from the sidebar")
        return "cd " + shlex.quote(thread.get("cwd") or str(Path.home())) + " && " + shlex.join([CODEX, "resume", thread["id"]])
    reference = f"{title(thread)}\nSession: {thread['id']}\nProject: {project_for(thread) or thread.get('cwd', '')}"
    if project_for(thread) and project_for(thread) != thread.get("cwd"):
        reference += f"\nWorking folder: {thread.get('cwd', '')}"
    return reference


def copy_text(value):
    # tmux forwards OSC 52 to the attached terminal's clipboard, including WSL.
    run(["tmux", "-L", SOCKET, "load-buffer", "-w", "-"], input=value)


def configure_mouse():
    tmux("bind-key", "-n", "MouseDown3Pane", "select-pane -t = ; send-keys -M")


def configure_keys(sidebar):
    # F2 belongs to the native Codex warnings screen.
    tmux("unbind-key", "-n", "F2")
    tmux("bind-key", "-n", "F6", "select-pane", "-t", sidebar)
    tmux("bind-key", "-n", "F3", "run-shell", command("focus"))
    tmux("bind-key", "-n", "F4", "detach-client")


class Sidebar:
    def __init__(self, screen):
        self.screen = screen
        self.workspace = Workspace()
        self.rpc = None
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.after = None
        self.items = []
        self.index = 0
        self.archived = False
        self.query = ""
        self.message = "Connecting to Codex…"
        self.next_refresh = 0
        self.offset = 0
        self.panes = []
        self.panes_at = 0
        self.main_id = ""
        self.expanded = set(preferences().get("tree_expanded", ["projects"]))
        self.projects = list(preferences().get("projects", []))
        self.project_tags = preferences().get("project_tags", {})
        self.project_names = preferences().get("project_names", {})

    def connection(self):
        if self.rpc is None or self.rpc.process.poll() is not None:
            self.workspace.repair()
            if self.rpc:
                self.rpc.close()
            self.rpc = Rpc()
        return self.rpc

    def submit(self, fn, after=None, message="Working…"):
        if self.future:
            return
        self.message = message
        self.future = self.pool.submit(fn)
        self.after = after

    def refresh(self):
        archived = self.archived
        def loaded(items):
            selected = self.selected_row()
            self.items = items
            if selected:
                self.index = next((i for i, row in enumerate(self.rows())
                                   if row["key"] == selected["key"]), 0)
            saved = sum(not t.get("temporary") for t in items)
            self.message = f"{saved} {'archived' if archived else 'saved'} conversations"
        self.submit(lambda: self.connection().threads(archived, self.live_ids()), loaded, "Refreshing…")

    def live_ids(self):
        return {p["thread"] for p in self.workspace.panes() if p["dead"] != "1"}

    def filtered(self):
        q = self.query.casefold()
        def searchable(thread):
            topic = topic_for(thread)
            labels = [label for key, label in TOPICS.items()
                      if topic and (topic == key or topic.startswith(key + "/"))]
            return " ".join([title(thread), thread.get("cwd", ""), project_for(thread) or "",
                             self.project_names.get(project_for(thread), ""), *labels]).casefold()
        return [thread for thread in self.items if q in searchable(thread)]

    def selected(self):
        return self.selected_row().get("thread")

    def rows(self):
        trivia = []
        topics = {key: [] for key in TOPICS}
        projects = {cwd: [] for cwd in self.projects if not self.query or self.query.casefold() in (cwd + " " + self.project_names.get(cwd, "")).casefold()}
        for thread in self.filtered():
            topic = topic_for(thread)
            if topic:
                topics[topic].append(thread)
                continue
            cwd = project_for(thread)
            if cwd is None:
                trivia.append(thread)
            else:
                projects.setdefault(cwd, []).append(thread)
        rows = []
        def group(key, label, depth, cwd=None, parent=None, topic=None):
            opened = bool(self.query) or key in self.expanded
            rows.append({"key": key, "label": label, "depth": depth, "cwd": cwd, "opened": opened,
                         "tags": self.project_tags.get(cwd, []) if cwd else [],
                         "parent": parent or key, "topic": topic})
            return opened
        def leaf(thread, depth, parent):
            rows.append({"key": "session:" + thread["id"], "thread": thread,
                         "label": title(thread), "depth": depth, "parent": parent,
                         "topic": topic_for(thread),
                         "cwd": project_for(thread) or thread.get("cwd")})
        if group("trivia", f"Trivia ({len(trivia)})", 0):
            for thread in trivia:
                leaf(thread, 1, "trivia")
        if group("projects", f"Projects ({len(projects)})", 0):
            names = [self.project_names.get(cwd) or Path(cwd).name for cwd in projects]
            for cwd, threads in sorted(projects.items(), key=lambda pair: pair[0].casefold()):
                key = "project:" + cwd
                name = self.project_names.get(cwd) or Path(cwd).name or cwd
                if names.count(name) > 1:
                    name = cwd
                if group(key, f"{name} ({len(threads)})", 1, cwd, "projects"):
                    for thread in threads:
                        leaf(thread, 2, key)
        def topic_group(topic):
            count = sum(len(items) for key, items in topics.items()
                        if key == topic or key.startswith(topic + "/"))
            depth = topic.count("/")
            if group(topic, f"{TOPICS[topic]} ({count})", depth,
                     parent=topic.rpartition("/")[0] or topic, topic=topic):
                for thread in topics[topic]:
                    leaf(thread, depth + 1, topic)
                for child in TOPICS:
                    if child.rpartition("/")[0] == topic:
                        topic_group(child)
        topic_group("misc")
        return rows

    def selected_row(self):
        rows = self.rows()
        return rows[max(0, min(self.index, len(rows) - 1))]

    def toggle_group(self):
        row = self.selected_row()
        if "thread" in row:
            return
        if self.query:
            self.message = "Clear search to collapse folders"
            return
        if row["key"] in self.expanded:
            self.expanded.remove(row["key"])
        else:
            self.expanded.add(row["key"])
        save_preferences(tree_expanded=sorted(self.expanded))

    def select_thread(self, thread):
        cwd = project_for(thread) or str(Path.home())
        self.expanded.update(["trivia", "projects", "project:" + cwd])
        topic = topic_for(thread)
        if topic:
            self.expanded.update(key for key in TOPICS if topic == key or topic.startswith(key + "/"))
        self.index = next((i for i, row in enumerate(self.rows())
                           if row["key"] == "session:" + thread["id"]), 0)

    def put(self, y, text, attr=0):
        h, w = self.screen.getmaxyx()
        if 0 <= y < h:
            try:
                safe = "".join(c if c.isprintable() else " " for c in str(text))
                self.screen.addnstr(y, 1, safe, max(0, w - 2), attr)
            except curses.error:
                pass

    def prompt(self, label, default=""):
        value = default
        while True:
            self.draw()
            h, w = self.screen.getmaxyx()
            for y in range(max(0, h - 5), h):
                self.screen.move(y, 0)
                self.screen.clrtoeol()
            self.put(h - 5, label, curses.A_BOLD)
            self.put(h - 3, "> " + value[-max(1, w - 6):])
            self.put(h - 1, "Enter: accept · Esc: cancel")
            self.screen.refresh()
            key = self.screen.get_wch()
            if key == "\x1b":
                return None
            if key in ("\n", "\r", curses.KEY_ENTER):
                return value.strip()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                value = value[:-1]
            elif key == "\x15":
                value = ""
            elif isinstance(key, str) and key.isprintable():
                value += key

    def confirm(self, label):
        return (self.prompt(label + " Type yes:") or "").lower() == "yes"

    def choose_mode(self, default="auto"):
        while True:
            self.message = "a Auto / c Chat / p Project"
            value = self.prompt("Mode a/c/p [" + MODES[default] + "]")
            if value is None:
                return None
            if not value:
                return default
            value = {"a": "auto", "c": "conversation", "chat": "conversation", "p": "project"}.get(value.lower(), value.lower())
            if value in MODES:
                return value
            self.message = "Choose a, c, or p"

    def choose_model(self, current, catalog):
        choices, warning = catalog
        index = next((i for i, model in enumerate(choices) if model == current), 0)
        while True:
            h, w = self.screen.getmaxyx()
            if h < 7 or w < 16:
                self.message = "Enlarge terminal to choose a model"
                return None
            visible = h - 5
            offset = max(0, index - visible + 1)
            self.screen.erase()
            self.put(0, "CHOOSE MODEL", curses.A_BOLD)
            for y, model in enumerate(choices[offset:offset + visible], 2):
                self.put(y, model_label(model), curses.A_REVERSE if y - 2 + offset == index else 0)
            self.put(h - 2, warning, curses.A_DIM)
            self.put(h - 1, "↑↓ / click · Enter · Esc cancel", curses.A_DIM)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("\x1b", curses.KEY_RESIZE):
                return None
            if key in ("j", curses.KEY_DOWN):
                index = (index + 1) % len(choices)
            elif key in ("k", curses.KEY_UP):
                index = (index - 1) % len(choices)
            elif key in ("\n", "\r", curses.KEY_ENTER):
                return choices[index]
            elif key == curses.KEY_MOUSE:
                _, _, y, _, buttons = curses.getmouse()
                if buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED) and 2 <= y < 2 + min(visible, len(choices)):
                    return choices[offset + y - 2]

    def apply_model_choice(self, selected, catalog):
        current = session_model(selected["id"]) if selected else preferences().get("new_session_model", {})
        self.screen.timeout(-1)
        try:
            model = self.choose_model(current, catalog)
        finally:
            self.screen.timeout(200)
        if model is None:
            return
        if selected:
            if any(p["thread"] == selected["id"] and p["dead"] != "1" for p in self.workspace.panes()):
                self.message = "Close terminal before changing model"
                return
            set_session_model(selected["id"], model or {"default": True})
            selected["workspaceModel"] = model
        else:
            save_preferences(new_session_model=model)
        self.message = ("Session model: " if selected else "New sessions: ") + model_label(model)

    def context_menu(self):
        entries = [("Open conversation", "\n"), ("New conversation", "n"),
                   ("Close terminal", "c"), ("Rename", "e"),
                   ("Restore" if self.archived else "Archive", "a"),
                   ("Show saved" if self.archived else "Show archived", "v"),
                   ("Search", "/"), ("Refresh / reconnect", "r"),
                   ("Delete permanently", "D"), ("Detach workspace", "q"),
                   ("Focus conversation", "\t"), ("Focus sidebar", "sidebar"),
                   ("Start blank session", "b"),
                   ("Change session mode", "m"),
                   ("Move to Misc topic / restore grouping", "g"),
                   ("Change session model", "M"),
                   ("Model for new sessions", "model:default"),
                   ("Copy session reference", "copy:reference"),
                   ("Copy session ID", "copy:id"), ("Copy project path", "copy:path"),
                   ("Copy resume command", "copy:resume")]
        if self.selected() is None:
            entries = [("Expand / collapse", "\n"), ("New conversation here", "n"),
                       ("Show saved" if self.archived else "Show archived", "v"),
                       ("Search", "/"), ("Refresh / reconnect", "r"),
                       ("Focus conversation", "\t"), ("Detach workspace", "q")]
            if self.selected_row().get("cwd"):
                entries.append(("Copy project path", "copy:path"))
            entries.append(("Start blank session", "b"))
            entries.append(("Model for new sessions", "model:default"))
            if self.selected_row().get("cwd"):
                entries.append(("Start session in project", "+"))
            elif self.selected_row().get("topic"):
                entries.append(("Start session in topic", "+"))
        index = 0
        while True:
            h, w = self.screen.getmaxyx()
            if h < 5 or w < 12:
                self.message = "Enlarge the terminal to show the menu"
                return
            visible = min(len(entries), h - 4)
            offset = max(0, index - visible + 1)
            self.screen.erase()
            self.put(0, "SESSION ACTIONS", curses.A_BOLD)
            for row, (label, _) in enumerate(entries[offset:offset + visible], 2):
                self.put(row, label, curses.A_REVERSE if row - 2 + offset == index else 0)
            self.put(h - 1, "↑↓ / click · Enter · Esc cancel", curses.A_DIM)
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ("\x1b", curses.KEY_RESIZE):
                return
            if key in (curses.KEY_DOWN, "j"):
                index = (index + 1) % len(entries)
            elif key in (curses.KEY_UP, "k"):
                index = (index - 1) % len(entries)
            elif key == curses.KEY_MOUSE:
                _, _, y, _, buttons = curses.getmouse()
                if buttons & curses.BUTTON4_PRESSED:
                    index = max(0, index - 1)
                elif buttons & getattr(curses, "BUTTON5_PRESSED", 0):
                    index = min(len(entries) - 1, index + 1)
                elif buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                    if not 2 <= y < 2 + visible:
                        return
                    self.action(entries[offset + y - 2][1])
                    return
            elif key in ("\n", "\r", curses.KEY_ENTER):
                self.action(entries[index][1])
                return

    def draw(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        self.put(0, "CODEX WORKSPACE" + (" · ARCHIVED" if self.archived else ""), curses.A_BOLD | curses.color_pair(1))
        self.put(1, "M Model: " + model_label(preferences().get("new_session_model", {})), curses.A_DIM)
        self.put(2, "/ " + (self.query or "Search conversations"), curses.A_DIM)
        self.put(3, "b  Start blank session", curses.A_BOLD | curses.color_pair(1))
        if time.monotonic() > self.panes_at:
            self.panes = self.workspace.panes()
            window = self.workspace.visible_window()
            self.main_id = next((p["thread"] for p in self.panes
                                 if p["window"] == window and p["thread"] != "sidebar"), "")
            self.panes_at = time.monotonic() + 1
        open_ids = {p["thread"]: p for p in self.panes}
        main_id = self.main_id
        items = self.rows()
        self.index = max(0, min(self.index, len(items) - 1))
        count = max(0, (h - 14) // 2)
        self.offset = max(0, min(self.offset, self.index))
        if self.index >= self.offset + count:
            self.offset = self.index - count + 1
        for i, row in enumerate(items[self.offset:self.offset + count], self.offset):
            y = 4 + (i - self.offset) * 2
            attr = curses.A_REVERSE if i == self.index else 0
            indent = " " * row["depth"]
            thread = row.get("thread")
            if thread is None:
                heading_color = curses.color_pair(1 if row["depth"] == 0 else 2)
                heading = indent + ("▾ " if row["opened"] else "▸ ") + row["label"]
                if (row.get("cwd") or row.get("topic")) and w >= 10:
                    heading = heading[:w - 5].ljust(w - 5) + "[+]"
                self.put(y, heading,
                         attr | curses.A_BOLD | heading_color)
                if row.get("cwd"):
                    detail = " ".join("[" + ("sd" if tag == "Software development" else tag) + "]" for tag in row["tags"]) if row["tags"] else row["cwd"]
                    self.put(y + 1, indent + detail, curses.A_DIM)
                elif i == self.index:
                    self.put(y + 1, "n: new here · Enter: expand", curses.A_DIM)
                continue
            pane = open_ids.get(thread["id"])
            status = "Unsaved" if thread.get("temporary") else "Saved"
            if pane:
                status = "Exited" if pane["dead"] == "1" else "Open"
            if thread["id"] == main_id:
                status = "Viewing" if pane["dead"] != "1" else "Exited"
            if thread.get("temporary") and pane:
                status += " · Unsaved"
            raw = thread.get("status", {})
            if raw.get("type") == "active":
                flags = raw.get("activeFlags", [])
                status += " · " + ("Needs input" if flags else "Working")
            self.put(y, indent + title(thread), attr)
            mode = MODES.get(thread.get("workspaceMode", "auto"), "Auto")
            if pane and pane["dead"] != "1" and not pane.get("mode"):
                mode = "Reopen: " + mode
            label = model_label(thread["workspaceModel"]) if thread.get("workspaceModel") else ""
            self.put(y + 1, indent + f"{mode} · {status}" + (" · " + label if label else ""), curses.A_DIM)
        if self.query and not self.filtered() and not any(row.get("cwd") for row in items):
            self.put(4, "No matching conversations", curses.A_DIM)
        self.put(h - 10, self.message, curses.color_pair(1))
        self.put(h - 8, "Enter Open/fold  + Quick new")
        self.put(h - 7, "c Close       e Rename")
        self.put(h - 6, "a Archive    m Mode")
        self.put(h - 5, "v Saved/archive  M Model")
        self.put(h - 4, "/ Search      r Refresh")
        self.put(h - 3, "D Delete      q Detach")
        self.put(h - 2, "Right-click: menu / copy", curses.A_DIM)
        self.put(h - 1, "F6 Sidebar  F3 Conversation", curses.A_DIM)
        self.screen.refresh()

    def action(self, key):
        selected = self.selected()
        if key in (curses.KEY_DOWN, "j"):
            self.index += 1
        elif key in (curses.KEY_UP, "k"):
            self.index = max(0, self.index - 1)
        elif key == curses.KEY_NPAGE:
            self.index += 5
        elif key == curses.KEY_PPAGE:
            self.index = max(0, self.index - 5)
        elif key == curses.KEY_RIGHT and not selected:
            if not self.selected_row()["opened"]:
                self.toggle_group()
        elif key == curses.KEY_LEFT:
            row = self.selected_row()
            if selected or not row.get("opened"):
                parent = row.get("parent", "projects" if row["depth"] else row["key"])
                self.index = next((i for i, r in enumerate(self.rows()) if r["key"] == parent), self.index)
            else:
                self.toggle_group()
        elif key == "\t":
            self.workspace.focus()
        elif key == "q":
            tmux("detach-client", "-s", SESSION)
        elif key == curses.KEY_MOUSE:
            _, x, y, _, buttons = curses.getmouse()
            if y == 1 and buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                self.action("model:default")
                return
            if y == 3 and buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                self.action("b")
                return
            row = self.offset + (y - 4) // 2
            if 4 <= y < 4 + max(0, (self.screen.getmaxyx()[0] - 14) // 2) * 2 and row < len(self.rows()):
                self.index = row
                if buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED | curses.BUTTON1_RELEASED):
                    project_button = ((self.selected_row().get("cwd") or self.selected_row().get("topic")) and not self.selected()
                                      and (y - 4) % 2 == 0 and self.screen.getmaxyx()[1] >= 10
                                      and self.screen.getmaxyx()[1] - 4 <= x < self.screen.getmaxyx()[1] - 1)
                    self.action("+" if project_button else "\n")
            if buttons & (curses.BUTTON3_PRESSED | curses.BUTTON3_CLICKED):
                self.context_menu()
        elif isinstance(key, str) and key.startswith("copy:"):
            if selected:
                copy_text(session_copy(selected, key.split(":", 1)[1]))
                self.message = "Copied to terminal clipboard"
            elif key == "copy:path" and self.selected_row().get("cwd"):
                copy_text(self.selected_row()["cwd"])
                self.message = "Copied project path"
            else:
                self.message = "Select a conversation first"
        elif self.future:
            return
        elif key in ("M", "model:default"):
            target = selected if key == "M" else None
            if target and any(p["thread"] == target["id"] and p["dead"] != "1" for p in self.workspace.panes()):
                self.message = "Close terminal before changing model"
                return
            self.submit(lambda: available_models(self.connection()),
                        lambda catalog: self.apply_model_choice(target, catalog), "Loading models…")
        elif key == "+":
            topic = self.selected_row().get("topic")
            if topic:
                self.submit(lambda: self.connection().create_or_reuse("New session", str(Path.home()), "auto", self.live_ids(), topic=topic),
                            self.open_created, "Starting topic session…")
                return
            cwd = self.selected_row().get("cwd")
            if not cwd:
                self.message = "Select a project first"
                return
            if not Path(cwd).is_dir():
                self.message = "That project folder does not exist"
                return
            self.submit(lambda: self.connection().create_or_reuse("New session", cwd, "project", self.live_ids()),
                        self.open_created, "Starting project session…")
        elif key == "m" and selected:
            if any(p["thread"] == selected["id"] and p["dead"] != "1" for p in self.workspace.panes()):
                self.message = "Close terminal before changing mode"
                return
            mode = self.choose_mode(selected.get("workspaceMode", "auto"))
            if mode:
                set_session_mode(selected["id"], mode)
                selected["workspaceMode"] = mode
                self.select_thread(selected)
                self.message = "Mode: " + MODES[mode]
        elif key == "g" and selected:
            value = self.prompt("Topic: t Tailscale / q Qwen / l Local models / m Misc / r Restore")
            if value is None:
                return
            choices = {"t": "misc/tailscale", "q": "misc/local-models/qwen",
                       "l": "misc/local-models", "m": "misc", "r": None}
            if value.lower() not in choices:
                self.message = "Choose t, q, l, m, or r"
                return
            topic = choices[value.lower()]
            set_session_topic(selected["id"], topic)
            selected["workspaceTopic"] = topic
            self.query = ""
            self.select_thread(selected)
            self.message = "Moved to " + (TOPICS[topic] if topic else "original grouping")
        elif key in ("\n", "\r", curses.KEY_ENTER):
            if not selected:
                self.toggle_group()
            elif self.archived:
                self.message = "Press a to restore before opening"
            else:
                self.submit(lambda: self.connection().ensure(selected), self.workspace.open, "Opening…")
        elif key == "b":
            self.submit(lambda: self.connection().create_or_reuse("New session", str(Path.home()), "auto", self.live_ids()),
                        self.open_created, "Starting blank session…")
        elif key == "n":
            context = self.selected_row()
            name = self.prompt("Conversation name")
            if not name:
                return
            in_trivia = context["key"] == "trivia" or context.get("parent") == "trivia"
            topic = context.get("topic")
            mode = self.choose_mode("auto" if topic else "conversation" if in_trivia else "project")
            if not mode:
                return
            cwd = str(Path.home()) if mode == "conversation" or (topic and mode == "auto") else self.prompt("Project folder (Ctrl-U clears)", context.get("cwd") or preferences().get("project", str(Path.home())))
            if not cwd:
                return
            path = Path(cwd).expanduser().resolve()
            if not path.is_dir():
                self.message = "That project folder does not exist"
                return
            if mode != "conversation" and not topic:
                self.projects = sorted(set(self.projects) | {str(path)})
                save_preferences(project=str(path), projects=self.projects)
            self.submit(lambda: self.connection().create_or_reuse(name, str(path), mode, self.live_ids(), topic=topic), self.open_created, "Creating conversation…")
        elif key == "c" and selected:
            if any(p["thread"] == selected["id"] for p in self.workspace.panes()):
                if self.confirm("Close terminal? In-flight work may stop."):
                    self.workspace.close(selected["id"])
                    if selected.get("temporary"):
                        self.items = [t for t in self.items if t["id"] != selected["id"]]
                        self.next_refresh = 0
                        self.message = "Closed unused session"
                    else:
                        self.message = "Closed. Conversation stays saved."
            else:
                self.message = "Already closed; saved history is available"
        elif key == "e" and selected:
            name = self.prompt("Rename conversation (Ctrl-U clears)", title(selected))
            if name:
                self.submit(lambda: self.connection().change("name/set", selected["id"], name))
        elif key == "a" and selected:
            if any(p["thread"] == selected["id"] for p in self.workspace.panes()):
                self.message = "Close this conversation before archiving"
                return
            action = "unarchive" if self.archived else "archive"
            self.submit(lambda: self.connection().change(action, selected["id"]))
        elif key == "D" and selected:
            if not self.archived:
                self.message = "Archive first; delete is only in archived view"
            elif self.confirm("Permanently delete this conversation?"):
                self.submit(lambda: self.connection().change("delete", selected["id"]))
        elif key == "v":
            self.archived = not self.archived
            self.items = []
            self.index = 0
            self.refresh()
        elif key == "/":
            query = self.prompt("Search name or project", self.query)
            if query is not None:
                self.query = query
                self.index = 0
        elif key == "r":
            def reconnect():
                if self.rpc:
                    self.rpc.close()
                    self.rpc = None
                return self.connection().threads(self.archived)
            self.submit(reconnect, lambda items: setattr(self, "items", items), "Reconnecting…")

    def open_created(self, thread):
        self.archived = False
        self.query = ""
        self.workspace.open(thread)
        self.items = [t for t in self.items if t["id"] != thread["id"]] + [thread]
        self.select_thread(thread)
        self.next_refresh = 0

    def loop(self):
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        self.screen.timeout(200)
        try:
            while True:
                if self.future and self.future.done():
                    future, after = self.future, self.after
                    self.future = self.after = None
                    try:
                        result = future.result()
                        self.message = "Saved"
                        if after:
                            after(result)
                        self.next_refresh = time.monotonic() + (5 if isinstance(result, list) else 0)
                    except Exception as exc:
                        self.message = str(exc)
                        self.next_refresh = time.monotonic() + 15
                if not self.future and time.monotonic() >= self.next_refresh:
                    self.refresh()
                self.draw()
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue
                try:
                    # Prompts need blocking reads; refresh resumes when they close.
                    self.screen.timeout(-1)
                    self.action(key)
                except (RuntimeError, OSError, curses.error) as exc:
                    self.message = str(exc)
                finally:
                    self.screen.timeout(200)
        finally:
            self.pool.shutdown(wait=True)
            if self.rpc:
                self.rpc.close()


def welcome():
    print("\033[2J\033[H\n  CODEX WORKSPACE\n")
    print("  Your conversations, together in one terminal.\n")
    print("  Click a conversation on the right, or press F6 to select one.")
    print("  Click Start blank session, or press F6 then b, to start immediately.")
    print("  Press n to create a session: Auto, Conversation, or Project work.")
    print("  Press m or right-click to change a closed session's mode.\n")
    print("  F2  View warnings in the focused Codex conversation")
    print("  F6  Focus session sidebar")
    print("  F3  Focus conversation")
    print("  F4  Detach workspace; open sessions keep running\n")
    print("  Closing a conversation keeps its saved history.")
    print("  Archived conversations can be restored from the sidebar.\n")
    print("  Reopen this workspace: " + reconnect_command() + "\n", flush=True)
    while True:
        time.sleep(3600)


def run_conversation(tid, cwd):
    with drafts() as db:
        row = db.execute("SELECT data FROM drafts WHERE id = ?", (tid,)).fetchone()
    draft = json.loads(row[0]) if row else None
    endpoint = DATA / "server.sock"
    is_new = bool(draft and not Path(draft.get("path") or "/nonexistent").exists())
    mode = session_mode(tid)
    model = session_model(tid)
    rpc = Rpc()
    try:
        config = rpc.call("config/read", {"cwd": cwd, "includeLayers": False})["config"]
        baseline = config.get("developer_instructions", "")
        if model.get("default"):
            default_model = config.get("model")
            if not default_model:
                catalog = rpc.call("model/list", {})["data"]
                default_model = next((m["model"] for m in catalog if m.get("isDefault")), None)
            if not default_model:
                raise RuntimeError("No configured default model; choose a model explicitly")
            model = {"model": default_model, "provider": config.get("model_provider") or "openai"}
    finally:
        rpc.close()
    transform = mode_transform(mode, baseline, model)
    if os.environ.get("TMUX_PANE"):
        tmux("set-option", "-p", "-t", os.environ["TMUX_PANE"], "@workspace_mode", mode)

    if __package__:
        from .bridge import bridge
    else:
        from bridge import bridge
    path = DATA / ("tui-" + tid[:12] + ".sock")
    path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(1)
    errors = []
    started_at = int(time.time())

    def bind_thread(thread):
        if (thread.get("createdAt", 0) < started_at - 1
                or thread.get("cwd") != cwd or thread.get("preview")
                or thread.get("forkedFromId")):
            raise RuntimeError("Native terminal did not create a new empty conversation in the selected project")
        if not (draft.get("temporary") and title(draft) == "New session"):
            rpc = Rpc()
            try:
                rpc.call("thread/name/set", {"threadId": thread["id"], "name": title(draft)})
            finally:
                rpc.close()
        thread["name"] = title(draft)
        thread["temporary"] = draft.get("temporary", False)
        # A catalog refresh may have sampled pane IDs just before the bridge
        # switches this draft to its native ID. Accept either ID during handoff.
        thread["workspaceDraftId"] = tid
        with drafts() as db:
            if not db.execute("SELECT 1 FROM drafts WHERE id = ?", (tid,)).fetchone():
                return
            db.execute("INSERT OR REPLACE INTO drafts (id, data) VALUES (?, ?)",
                       (thread["id"], json.dumps(thread)))
            db.execute("DELETE FROM drafts WHERE id = ?", (tid,))
            db.execute("INSERT OR REPLACE INTO session_modes VALUES (?, ?)", (thread["id"], mode))
            db.execute("DELETE FROM session_modes WHERE id = ?", (tid,))
            db.execute("INSERT OR REPLACE INTO session_models SELECT ?, data FROM session_models WHERE id = ?", (thread["id"], tid))
            db.execute("DELETE FROM session_models WHERE id = ?", (tid,))
            db.execute("INSERT OR REPLACE INTO session_projects SELECT ?, project FROM session_projects WHERE id = ?", (thread["id"], tid))
            db.execute("DELETE FROM session_projects WHERE id = ?", (tid,))
            db.execute("INSERT OR REPLACE INTO session_topics SELECT ?, topic FROM session_topics WHERE id = ?", (thread["id"], tid))
            db.execute("DELETE FROM session_topics WHERE id = ?", (tid,))
        tmux("set-option", "-p", "-t", os.environ["TMUX_PANE"], "@workspace_thread", thread["id"])
        save_preferences(last_session=thread["id"])

    def forward():
        try:
            bridge(listener, endpoint, bind_thread if is_new else None, transform)
        except Exception as exc:
            errors.append(str(exc))

    worker = threading.Thread(target=forward, daemon=True)
    worker.start()
    child = subprocess.Popen([CODEX, *([] if is_new else ["resume", tid]), "-C", cwd, "--remote", "unix://" + str(path)])
    # The native TUI handles Ctrl-C itself. Closing its pane terminates both
    # processes, including when a terminal disappears during onboarding.
    signal.signal(signal.SIGINT, lambda *_: None)
    def terminate(*_):
        child.terminate()
    signal.signal(signal.SIGHUP, terminate)
    signal.signal(signal.SIGTERM, terminate)
    try:
        code = child.wait()
        worker.join(timeout=2)
        if errors:
            raise RuntimeError(errors[0])
        return code
    finally:
        listener.close()
        path.unlink(missing_ok=True)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def reconnect_command():
    name = os.environ.get("CODEX_WORKSPACE_INSTANCE")
    if name:
        return "codex-workspace --instance " + shlex.quote(name)
    return "CODEX_WORKSPACE_DATA=" + shlex.quote(str(DATA)) + " CODEX_WORKSPACE_SOCKET=" + shlex.quote(SOCKET) + " codex-workspace"


def select_instance(name=None):
    """Isolate launch state; children inherit the selected data and tmux socket."""
    global DATA, SOCKET
    # Explicit sockets retain the existing automation/integration-test contract.
    if name is None and os.environ.get("CODEX_WORKSPACE_SOCKET"):
        return
    name = name or uuid.uuid4().hex[:12]
    if not (1 <= len(name) <= 16 and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in name)):
        raise RuntimeError("Instance names must contain 1–16 letters, digits, hyphens or underscores.")
    base = Path(os.environ.get("CODEX_WORKSPACE_BASE_DATA", str(DATA)))
    target = base if name == "legacy" else base / "instances" / name
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target != base:
        with (target / "initialize.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not (target / "initialized").exists():
                if (base / "preferences.json").exists():
                    shutil.copyfile(base / "preferences.json", target / "preferences.json")
                if (base / "drafts.sqlite").exists():
                    with sqlite3.connect(base / "drafts.sqlite") as source, sqlite3.connect(target / "drafts.sqlite") as dest:
                        source.backup(dest)
                        # Live placeholders belong exclusively to their original instance.
                        dest.execute("DELETE FROM drafts")
                (target / "initialized").touch()
    DATA = target
    SOCKET = "codex-workspace" if name == "legacy" else "codex-workspace-" + name
    os.environ.update(CODEX_WORKSPACE_BASE_DATA=str(base), CODEX_WORKSPACE_DATA=str(DATA),
                      CODEX_WORKSPACE_SOCKET=SOCKET, CODEX_WORKSPACE_INSTANCE=name)
    print(f"Workspace instance: {name}. Reconnect with: codex-workspace --instance {name}", flush=True)


def start(detached=False):
    for executable in ("tmux", CODEX):
        if not shutil.which(executable):
            raise RuntimeError(f"Required Linux tool is missing: {executable}")
    if not detached and not sys.stdin.isatty():
        raise RuntimeError("Run codex-workspace in an interactive terminal (or use --detached).")
    initialize_projects()
    try:
        tmux("has-session", "-t", SESSION)
    except RuntimeError:
        tmux("-f", "/dev/null", "new-session", "-d", "-s", SESSION,
             "-n", "workspace", "-x", "140", "-y", "40", command("welcome"))
        try:
            DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
            window = tmux("display-message", "-p", "-t", SESSION, "#{window_id}")
            main = tmux("display-message", "-p", "-t", SESSION, "#{pane_id}")
            tmux("set-option", "-t", SESSION, "@workspace_window", window)
            tmux("set-option", "-p", "-t", main, "@workspace_thread", "home")
            tmux("set-option", "-g", "mouse", "on")
            tmux("set-option", "-g", "status", "off")
            tmux("set-option", "-g", "default-terminal", "tmux-256color")
            tmux("set-option", "-g", "remain-on-exit", "on")
            tmux("set-option", "-g", "destroy-unattached", "off")
            tmux("set-option", "-g", "history-limit", "20000")
            # One app server owns both catalog and live conversations. This also
            # lets native Codex attach to a new thread before its first message.
            service = tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", SESSION + ":",
                           "-n", "session-service", command("server"))
            tmux("set-option", "-p", "-t", service, "@workspace_thread", "service")
            wait_service()
            sidebar = tmux("split-window", "-h", "-d", "-l", "33%", "-t", main,
                           "-P", "-F", "#{pane_id}", command("sidebar"))
            tmux("set-option", "-p", "-t", sidebar, "@workspace_thread", "sidebar")
            tmux("select-pane", "-t", sidebar)
        except Exception:
            tmux("kill-session", "-t", SESSION)
            raise
    Workspace().repair()
    configure_mouse()
    sidebar = next(p["pane"] for p in Workspace().panes() if p["thread"] == "sidebar")
    configure_keys(sidebar)
    tmux("set-hook", "-t", SESSION, "client-resized",
         f"resize-pane -t {sidebar} -x 33%")
    tmux("resize-pane", "-t", sidebar, "-x", "33%")
    if detached:
        print("Workspace running. Open with: " + reconnect_command())
        return
    env = dict(os.environ)
    env.pop("TMUX", None)
    os.execvpe("tmux", ["tmux", "-L", SOCKET, "attach-session", "-t", SESSION], env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["start", "sidebar", "welcome", "server", "proxy", "run", "focus", "doctor"], default="start")
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--detached", action="store_true", help="Start in the background without attaching")
    parser.add_argument("--instance", help="Open or reconnect to a named workspace (legacy reconnects to the original)")
    args = parser.parse_args()
    if args.mode == "start":
        select_instance(args.instance)
        start(args.detached)
    elif args.mode == "sidebar":
        curses.wrapper(lambda screen: Sidebar(screen).loop())
    elif args.mode == "welcome":
        welcome()
    elif args.mode == "focus":
        Workspace().focus()
    elif args.mode == "proxy":
        if __package__:
            from .transport import proxy
        else:
            from transport import proxy
        proxy(args.arguments[0])
    elif args.mode == "server":
        path = DATA / "server.sock"
        if path.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise RuntimeError("Session service is already running")
            finally:
                probe.close()
        with (DATA / "app-server.log").open("a") as log:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            os.execvp(CODEX, [CODEX, "app-server", "--listen", "unix://" + str(path)])
    elif args.mode == "run":
        tid, cwd = args.arguments
        sys.exit(run_conversation(tid, cwd))
    elif args.mode == "doctor":
        print(run([CODEX, "--version"]))
        print(run(["tmux", "-V"]))
        print(f"Python {sys.version.split()[0]}")
        print(f"Workspace settings: {DATA}")
        rpc = Rpc(standalone=True)
        try:
            print(f"Codex connection OK; {len(rpc.threads())} saved conversations")
        finally:
            rpc.close()


def cli():
    try:
        main()
    except (RuntimeError, OSError) as exc:
        print(f"codex-workspace: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli()
