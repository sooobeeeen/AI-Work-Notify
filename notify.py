"""KakaoWork "you have an unread answer" notifier shared by Claude Code, Codex, and AGY hooks.

Source of truth: the AI-Work-Notify package (notify.py there); install.py copies it to
%USERPROFILE%\\.kakaowork-notify\\notify.py, which the hooks run. Edit the package copy.

Hook events (event JSON on stdin; print nothing, always exit 0, log to log.txt):
    notify.py <claude|codex|agy> start    remember when the user's request started
    notify.py <claude|codex|agy> stop     queue a message for the finished answer
    notify.py claude permission           queue "waiting for approval"
Internal:
    notify.py wait <pending> <token>      background waiter
    notify.py serve                       page behind the notification's button
    notify.py ping                        exit 0 (install.py checks the hook command runs)
Management (prints results, exit 1 on failure):
    notify.py status                      settings, hooks, recent log
    notify.py set <key> <value>           enabled | unread_seconds | min_seconds | antigravity
    notify.py webhook                     save the webhook URL from the clipboard
    notify.py test                        send a test message
    notify.py server                      start the button's page if it is not running
    notify.py update                      install the latest GitHub release if it is newer
    notify.py focus <claude|codex|app|ide> [conversation id]  bring that app's window (and conversation) to the front

A queued message is sent only if the user does not look at the desktop app within
unread_seconds: "looked" means the app's window is in front and there was keyboard or
mouse input in the last 30 seconds. A new request in the same session cancels it.
Claude Code and Codex may also run inside VS Code (its extensions or terminal); the button
then brings that VS Code window to the front. Runs with no window of their own
(claude -p, codex exec, agy -p from a terminal, SDK scripts) are skipped.

Sending: config.json next to this file. webhook_url (a KakaoWork Incoming Webhook tied to one
room) if set, otherwise app_key + email (a bot); with neither, messages only go to the log.
"""
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from ctypes import wintypes
from pathlib import Path

HOME = Path(__file__).resolve().parent
STATE = HOME / "state"
LOG = HOME / "log.txt"
API = "https://api.kakaowork.com/v1/messages.send_by_email"
NAMES = {"claude": "Claude Code", "codex": "Codex",
         "ide": "Antigravity IDE", "cli": "AGY", "app": "Antigravity"}
# AGY CLI, Antigravity IDE and the Antigravity app share ~/.gemini/config/hooks.json;
# the event's artifact path tells them apart.
AGY_DIRS = {"antigravity-ide": "ide", "antigravity-cli": "cli", "antigravity": "app"}
# Desktop app process that owns the window, and the agent process it runs hooks from.
APPS = {"claude": "claude.exe", "codex": "chatgpt.exe", "app": "antigravity.exe", "ide": "antigravity ide.exe"}
AGENTS = {"claude": "claude.exe", "codex": "codex.exe"}
# Editors that run the agent inside their own window instead (VS Code's Claude Code and Codex
# extensions, or its terminal); the button then brings that editor window to the front.
HOSTS = {"code.exe": "vscode"}
HOST_NAMES = {"vscode": "VS Code"}
HOST_EXES = {host: exe for exe, host in HOSTS.items()}
# Links that open one conversation. Claude's desktop app gives its hooks the conversation's id
# (CLAUDE_CODE_HOST_SESSION_ID); its taskbar jump list uses the same link. Codex's hook event
# carries session_id, the thread id behind codex://threads/<id> (learn.chatgpt.com/docs/reference/commands).
# Antigravity has no such link (docs, changelog and agy --help checked 2026-10-06), so its button
# only prefers the window whose title names the workspace folder.
LINKS = {"claude": (re.compile(r"local_[A-Za-z0-9-]{1,64}"), "claude://code/continue?session={}"),
         "codex": (re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"), "codex://threads/{}")}
ACTIVE_INPUT_MS = 30_000
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindow.restype = wintypes.HWND
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def agy_client(ev):
    parts = Path(ev.get("artifactDirectoryPath") or ev.get("transcriptPath") or "").parts
    return next((AGY_DIRS[p] for p in parts if p in AGY_DIRS), "unknown")


def log(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    if LOG.stat().st_size > 1_000_000:
        LOG.replace(HOME / "log.old.txt")


def config():
    cfg = {"webhook_url": "", "app_key": "", "email": "", "min_seconds": 0, "unread_seconds": 30,
           "enabled": True, "antigravity": ["app"]}
    path = HOME / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
    return cfg


def send(cfg, text, tool=None, session="", folder="", host=""):
    if not cfg["enabled"]:
        return
    payload = {"text": text}
    headers = {"Content-Type": "application/json"}
    if cfg["webhook_url"]:  # posts into the one room the webhook is tied to
        url = cfg["webhook_url"]
    elif cfg["app_key"] and cfg["email"]:
        url = API
        payload["email"] = cfg["email"]
        headers["Authorization"] = "Bearer " + cfg["app_key"]
    else:
        log("DRY " + text.replace("\n", " | "))
        return
    if tool in APPS:  # text stays as the push preview; blocks add the "go to the app" button
        payload["blocks"] = [{"type": "text", "text": text}, button(tool, session, folder, host)]
        ensure_server()
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        res = json.loads(r.read().decode("utf-8") or "{}")
    ok = res.get("success") or res.get("code") == "ok"  # bot API / webhook
    log(("SENT " if ok else f"FAIL {res} ") + text.replace("\n", " | "))


def short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def plain(s):
    """Markdown/LaTeX -> plain text for a one-line preview."""
    out = []
    for line in str(s or "").splitlines():
        line = line.strip()
        if re.fullmatch(r"\|?[\s:|-]*-[\s:|-]*\|?", line) or line.startswith("```"):
            continue  # table separator row, horizontal rule, or code fence
        if line.startswith("|") and line.endswith("|"):
            line = " · ".join(c.strip() for c in line.strip("|").split("|"))
        out.append(re.sub(r"^(#+|>|[-*+])\s+", "", line))  # heading, quote, bullet
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(out))  # [text](url)
    return re.sub(r"\\[()\[\]]|\$|\*\*|~~|`", "", s)  # \( \) \[ \] $ ** ~~ `


def duration(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}시간 {m}분" if h else f"{m}분 {s}초" if m else f"{s}초"


# --- which desktop app window does this run belong to ---------------------------

class ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def processes():
    """pid -> (parent pid, lowercase exe name)."""
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    entry = ProcessEntry(dwSize=ctypes.sizeof(ProcessEntry))
    out = {}
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        out[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return out


def find_app(tool, procs=None, env=os.environ):
    """(pid of the main process owning the window, host name or "") or None for a headless run."""
    procs = procs or processes()
    chain, pid = [], os.getpid()
    while pid in procs and pid not in chain and len(chain) < 64:
        chain.append(pid)
        pid = procs[pid][0]
    names = [procs[p][1] for p in chain]
    host = ""
    if tool in AGENTS:
        if AGENTS[tool] not in names:
            return None
        i = names.index(AGENTS[tool])
        while i + 1 < len(chain) and names[i + 1] == names[i]:  # launcher -> agent (-> Claude app)
            i += 1
        # The desktop app runs the agent as its direct child. Claude's app is named like its
        # agent, so the top of that run is the app only if it owns a window. (Not the
        # entrypoint variable: claude -p started from a desktop session inherits
        # CLAUDE_CODE_ENTRYPOINT=claude-desktop, seen 2026-10-06.)
        if names[i] == APPS[tool] and chain[i] in window_owners():
            pass
        elif i + 1 < len(chain) and names[i + 1] == APPS[tool]:
            i += 1
        else:
            # Inside an editor (VS Code's extensions, or its terminal with a shell between),
            # unless it is an SDK script. claude -p or codex exec from a plain terminal has
            # no editor above it and is skipped.
            j = next((j for j in range(i + 1, len(chain)) if names[j] in HOSTS), None)
            if j is None or env.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
                return None
            i, host = j, HOSTS[names[j]]
    elif tool in APPS:  # Antigravity: the client was already told apart by its data path
        if APPS[tool] in names:
            i = names.index(APPS[tool])
        else:
            mains = [p for p, (pp, n) in procs.items()
                     if n == APPS[tool] and procs.get(pp, (0, ""))[1] != n]
            return (mains[0], "") if mains else None
    else:
        return None
    while i + 1 < len(chain) and names[i + 1] == names[i]:  # climb to the main process
        i += 1
    return chain[i], host


class LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def user_is_watching(app_pid):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    if pid.value != app_pid:
        return False
    info = LastInputInfo(cbSize=ctypes.sizeof(LastInputInfo))
    user32.GetLastInputInfo(ctypes.byref(info))
    return (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF < ACTIVE_INPUT_MS


# --- "go to the app" button ---------------------------------------------------------
# KakaoWork on PC opens only http(s) links, so the button opens a page served on this PC
# (127.0.0.1 only), and serving that page brings the app's window to the front.
PORT = 47615
PAGE = ("<!doctype html><meta charset=utf-8><title>{title}</title>"
        "<body style='font:15px sans-serif;padding:24px'>{title}<br>이 창은 닫아도 됩니다.")


def conversation(tool, ev):
    """The id the app's conversation link takes, or "" when the app has no such link."""
    if tool == "claude":
        return os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "")
    if tool == "codex":
        return str(ev.get("session_id") or "")
    return ""


def label(tool, host=""):
    return NAMES[tool] + (f" ({HOST_NAMES[host]})" if host else "")


def button(tool, session="", folder="", host=""):
    # KakaoWork's own small window, which the server closes; the system browser would
    # leave Chrome on top of the app.
    params = {}
    if host:  # the conversation links open the desktop app, not the editor
        params["host"] = host
    elif tool in LINKS and LINKS[tool][0].fullmatch(session or ""):
        params["session"] = session
    if folder:  # picks the window of that workspace when there are several
        params["folder"] = folder
    url = f"http://127.0.0.1:{PORT}/focus/{tool}" + ("?" + urllib.parse.urlencode(params) if params else "")
    return {"type": "button", "text": f"{HOST_NAMES.get(host) or NAMES[tool]}로 이동", "style": "default",
            "action": {"type": "open_inapp_browser", "value": url,
                       "standalone": True, "width": 360, "height": 160}}


POPUP_TITLE = "카카오워크"  # the main window is "카카오워크 2.0", chat windows carry the room name


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def kakao_popup():
    """KakaoWork's small window that is requesting the page. It is in front when the request
    arrives and is titled just "카카오워크" (seen 2026-10-05); anything else is left alone."""
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = processes().get(pid.value, (0, ""))[1]
    return hwnd if "kakao" in exe and window_title(hwnd) == POPUP_TITLE else None


def close_window(hwnd):
    """KakaoWork's small window ignores the page's window.close(), so close it from here."""
    for message, wparam in ((0x0010, 0), (0x0112, 0xF060)):  # WM_CLOSE, then WM_SYSCOMMAND SC_CLOSE
        user32.PostMessageW(hwnd, message, wparam, 0)
        for _ in range(10):
            time.sleep(0.1)
            if not user32.IsWindow(hwnd):
                return True
    return False


def serve():
    """The page behind the button; started in the background by ensure_server."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urllib.parse.urlsplit(self.path)
            tool = parts.path.removeprefix("/focus/").strip("/")
            if tool not in APPS:  # only the app name is read, so a crafted link can do nothing else
                self.send_error(404)
                return
            popup = kakao_popup()  # before focus() changes what is in front
            # Any web page can reach 127.0.0.1 too, and browsers mark such requests with
            # Sec-Fetch-Site. Only a navigation no page started ("none" or no header) or one made
            # while KakaoWork's small window is in front may move windows.
            site = self.headers.get("Sec-Fetch-Site", "none")
            if site != "none" and not popup:
                log(f"BLOCKED {tool} request from a web page ({site})")
                self.send_error(403)
                return
            if site != "none":
                log(f"REQUEST {tool} from KakaoWork's window ({site})")
            query = urllib.parse.parse_qs(parts.query)
            folder = re.sub(r"[\\/:*?\"<>|]", "", query.get("folder", [""])[0])[:100]  # title text only
            host = query.get("host", [""])[0]
            host = host if host in HOST_EXES else ""
            result = focus(tool, query.get("via", [""])[0], query.get("session", [""])[0], folder, host)
            where = HOST_NAMES.get(host) or NAMES[tool]
            title = (f"{where}로 이동했습니다." if result.startswith("ok")
                     else f"{where} 창으로 이동하지 못했습니다 ({result}).")
            body = PAGE.format(title=title).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            if not popup:
                log("POPUP not found")
            elif not close_window(popup):
                log("POPUP still open")

        def log_message(self, *args):  # pythonw has no stderr
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


def server_running():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_server():
    if not server_running():
        spawn("serve")


def top_windows(hidden=False):
    """(exe name, title, area, owned, hwnd, pid) of every visible (or, with hidden, every) titled
    top-level window, on any virtual desktop."""
    names = {pid: n for pid, (_, n) in processes().items()}
    found = []

    @WNDENUMPROC
    def visit(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if (hidden or user32.IsWindowVisible(hwnd)) and length:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append((names.get(pid.value, ""), title.value, (r.right - r.left) * (r.bottom - r.top),
                          bool(user32.GetWindow(hwnd, 4)), hwnd, pid.value))  # 4: GW_OWNER
        return True

    user32.EnumWindows(visit, 0)
    return found


def window_owners():
    """Pids that own a titled top-level window of their own, shown or hidden in the tray."""
    return {pid for _, _, area, owned, _, pid in top_windows(hidden=True) if area > 0 and not owned}


def app_window(exe, seconds=0, folder=""):
    """The program's unowned window whose title names the workspace folder (Antigravity and
    VS Code titles do), else its largest; waits up to `seconds` for one to show up."""
    end = time.time() + seconds
    while True:
        found = [(bool(folder) and folder.lower() in title.lower(), area, h)
                 for e, title, area, owned, h, _ in top_windows() if e == exe and not owned]
        if found or time.time() >= end:
            return max(found)[2] if found else None
        time.sleep(0.2)


def reveal(exe):
    """Show the program's window again when it was closed to the tray (X on Claude only hides it)."""
    found = [(area, h) for e, _, area, owned, h, _ in top_windows(hidden=True)
             if e == exe and not owned and area > 0]
    if not found:
        return None
    hwnd = max(found)[1]
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    return hwnd


def open_conversation(tool, session):
    """Have the app open the conversation; it also shows its window, even from the tray."""
    link = LINKS.get(tool)
    if not link or not link[0].fullmatch(session or ""):
        return False
    try:
        os.startfile(link[1].format(session))
    except OSError:
        return False
    return True


def cloaked(hwnd):
    """True while the window sits on another virtual desktop."""
    value = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value))  # DWMWA_CLOAKED
    return value.value != 0


def shown(hwnd, seconds=1.5):
    end = time.time() + seconds
    while time.time() < end:
        if user32.GetForegroundWindow() == hwnd and not cloaked(hwnd):
            return True
        time.sleep(0.1)
    return False


def focus(tool, via="", session="", folder="", host=""):
    """Bring the app's (or the hosting editor's) window to the front, on the conversation when
    the link names one. Activating a window makes Windows switch to the virtual desktop that
    holds it; if that does not happen, try the Alt+Tab-style switch."""
    exe = HOST_EXES.get(host) or APPS[tool]
    opened = not host and open_conversation(tool, session)
    hwnd = app_window(exe, 3 if opened else 0, folder) or reveal(exe)
    if not hwnd and opened:  # the link started the app; give it time to open its window
        hwnd = app_window(exe, 10, folder)
    if not hwnd:
        result = "no window"
    else:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Windows refuses focus changes from background processes; a synthetic Alt press
        # counts as our own input, after which the change is allowed.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
        result = "ok"
        if not shown(hwnd):
            user32.SwitchToThisWindow(hwnd, True)
            result = "ok (alt-tab)" if shown(hwnd) else ("hidden" if cloaked(hwnd) else "denied")
    log(f"FOCUS {tool} {result}" + (f" via={via}" if via else "") + (f" session={session}" if opened else "")
        + (f" host={host}" if host else ""))
    return result


# --- events ---------------------------------------------------------------------

def session_key(tool, ev):
    sid = ev.get("session_id") or ev.get("conversationId") or "unknown"
    return f"{tool}-{''.join(c for c in sid if c.isalnum() or c in '-_')}"


def folder(ev):
    paths = ev.get("workspacePaths") or [ev.get("cwd") or ""]
    return Path(paths[0]).name if paths and paths[0] else ""


# Claude Code and Codex fire start once per user prompt, and a prompt can span several
# turns, so their state lives until the next prompt. AGY start fires on every model
# call, so it keeps the first and stop ends the run.
PER_PROMPT = {"claude", "codex"}


def start(tool, ev):
    key = session_key(tool, ev)
    path = STATE / f"{key}.json"
    # Claude's desktop app also fires the prompt hook for system wake-ups such as
    # <task-notification>; those continue the user's request rather than start one.
    woke = re.match(r"\s*<[\w-]+>", ev.get("prompt") or "")
    if path.exists() and (tool not in PER_PROMPT or woke):
        return
    path.write_text(json.dumps({"ts": time.time(), "prompt": short(ev.get("prompt"), 60),
                                "folder": folder(ev)}, ensure_ascii=False), encoding="utf-8")
    (STATE / f"pending-{key}.json").unlink(missing_ok=True)  # the user answered


def stop(tool, ev, cfg):
    key = session_key(tool, ev)
    path = STATE / f"{key}.json"
    if not path.exists():
        return
    st = json.loads(path.read_text(encoding="utf-8"))
    if tool not in PER_PROMPT:
        path.unlink()
    elapsed = time.time() - st["ts"]
    error = ev.get("error")
    if elapsed < cfg["min_seconds"] and not error:
        return
    queue(tool, key, {"tool": tool, "elapsed": elapsed, "folder": st.get("folder"),
                      "prompt": st.get("prompt"), "answer": ev.get("last_assistant_message"),
                      "error": error, "transcript": ev.get("transcriptPath"),
                      "session": conversation(tool, ev)})


def agy_transcript(path):
    """Last user request and the answer to it, from an Antigravity transcript."""
    prompt = answer = ""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        step = json.loads(line)
        if step.get("source") == "USER_EXPLICIT" and step.get("type") == "USER_INPUT":
            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", step.get("content", ""), re.S)
            prompt, answer = (m.group(1) if m else step.get("content", "")), ""
        elif step.get("type") == "PLANNER_RESPONSE" and step.get("content"):
            answer = step["content"]
    return prompt, answer


def message(m):
    """Built at send time: Antigravity's hook events carry no prompt or answer, so they are
    read from its transcript once the answer has surely been written."""
    if "text" in m:
        return m["text"]
    if m.get("transcript"):
        try:
            m["prompt"], m["answer"] = agy_transcript(m["transcript"])
        except (OSError, ValueError):
            pass
    error = m.get("error")
    lines = [f"{'❌' if error else '✅'} {label(m['tool'], m.get('host', ''))} "
             f"{'작업 중단' if error else '답변 도착'} · {duration(m['elapsed'])}"]
    if m.get("folder"):
        lines.append(f"📁 {m['folder']}")
    if m.get("prompt"):
        lines.append(f"💬 {short(plain(m['prompt']), 60)}")
    if error:
        lines.append(f"오류: {short(error, 120)}")
    elif m.get("answer"):
        lines.append(f"↳ {short(plain(m['answer']), 120)}")
    return "\n".join(lines)


def queue(tool, key, msg):
    found = find_app(tool)
    if found is None:
        log(f"SKIP {tool} not from a desktop app window")
        return
    app, msg["host"] = found
    token = str(time.time_ns())
    name = f"pending-{key}.json"
    (STATE / name).write_text(json.dumps({"token": token, "app": app, "msg": msg},
                                         ensure_ascii=False), encoding="utf-8")
    spawn("wait", name, token)


def spawn(*args):
    """Run notify.py <args> in the background, detached from the hook, without a console."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    cmd = [str(pythonw if pythonw.exists() else sys.executable), __file__, *args]
    detached = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for flags in (detached | 0x01000000, detached):  # try CREATE_BREAKAWAY_FROM_JOB first
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass


def wait(name, token, cfg):
    path = STATE / name
    deadline = time.time() + cfg["unread_seconds"]
    while True:
        try:
            p = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return  # cancelled by a new request
        if p["token"] != token:
            return  # replaced by a newer answer
        if user_is_watching(p["app"]):
            path.unlink(missing_ok=True)
            log(f"READ {name[8:-5]}")
            return
        if time.time() >= deadline:
            break
        time.sleep(2)
    path.unlink(missing_ok=True)
    m = p["msg"]
    send(cfg, message(m), m.get("tool"), m.get("session", ""), m.get("folder", ""), m.get("host", ""))


def cleanup():
    old = time.time() - 86400
    for p in STATE.glob("*.json"):
        if p.stat().st_mtime < old:
            p.unlink()


# --- management: prints results, for people and agents (never called by hooks) -------

HOOK_FILES = {"Claude Code": Path.home() / ".claude" / "settings.json",
              "Codex": Path.home() / ".codex" / "hooks.json",
              "Antigravity": Path.home() / ".gemini" / "config" / "hooks.json"}
WEBHOOK = re.compile(r"https://kakaowork\.com/bots/hook/\w{16,}")
MANAGE = ("status", "set", "webhook", "test", "server", "focus", "update")
REPO = "sooobeeeen/AI-Work-Notify"  # public; each release is a vX.Y.Z tag


class Fail(Exception):
    pass


def short_path(path):
    """8.3 form of an existing path (no spaces), or the path itself if Windows has none."""
    buf = ctypes.create_unicode_buffer(1024)
    n = kernel32.GetShortPathNameW(str(path), buf, 1024)
    return buf.value if 0 < n < 1024 else str(path)


def masked(url):
    cut = url.rfind("/") + 1
    return f"{url[:cut + 3]}…({len(url) - cut}자)"


def save_config(**changes):
    path = HOME / "config.json"
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    data.update(changes)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_config(key, raw):
    raw = raw.strip()
    if key == "enabled":
        if raw.lower() not in ("true", "false"):
            raise Fail("enabled는 true 또는 false입니다.")
        value = raw.lower() == "true"
    elif key in ("unread_seconds", "min_seconds"):
        if not raw.isdigit() or (key == "unread_seconds" and int(raw) < 5):
            raise Fail(f"{key}는 초 단위 정수입니다(unread_seconds는 5 이상).")
        value = int(raw)
    elif key == "antigravity":
        value = [x.strip() for x in raw.split(",") if x.strip()]
        if not set(value) <= {"app", "ide", "cli"}:
            raise Fail("antigravity는 app, ide, cli를 쉼표로 이어 적습니다(예: app,ide).")
    elif key == "email":
        if "@" not in raw:
            raise Fail("이메일 형식이 아닙니다.")
        value = raw
    else:
        raise Fail("바꿀 수 있는 설정: enabled, unread_seconds, min_seconds, antigravity")
    save_config(**{key: value})
    print(f"{key} = {json.dumps(value, ensure_ascii=False)}")


def webhook(source=None):
    """Save the webhook URL from the clipboard (or a text file) without ever printing it."""
    if source:
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    url = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not WEBHOOK.fullmatch(url):
        raise Fail("웹훅 주소를 찾지 못했습니다. 카카오워크에서 웹훅 주소(https://kakaowork.com/bots/hook/…)를 "
                   "복사한 뒤 다시 실행하세요.")
    save_config(webhook_url=url)
    print(f"웹훅 주소를 저장했습니다: {masked(url)}")


def installed():
    """{"version", "mode"} written by install.py; mode is "full" or "runtime-only"."""
    path = HOME / "installed.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def version_key(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def github(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-work-notify"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def update():
    """Install the latest GitHub release over this one when it is newer, the same way as
    before (full, or runtime-only on the PC that keeps the source)."""
    have = installed()
    try:
        tag = json.loads(github(f"https://api.github.com/repos/{REPO}/releases/latest"))["tag_name"]
    except (OSError, ValueError, KeyError) as e:
        raise Fail(f"최신 판을 확인하지 못했습니다: {e}") from None
    if have.get("version") and version_key(tag) <= version_key(have["version"]):
        print(f"이미 최신 판입니다 (설치된 판 {have['version']}, 최신 {tag}).")
        return
    print(f"새 판을 설치합니다: {have.get('version', '알 수 없음')} -> {tag}", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            (root / "release.zip").write_bytes(github(f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip"))
        except OSError as e:
            raise Fail(f"새 판을 받지 못했습니다: {e}") from None
        with zipfile.ZipFile(root / "release.zip") as z:
            if any(not (root / "pkg" / n).resolve().is_relative_to((root / "pkg").resolve()) for n in z.namelist()):
                raise Fail("받은 압축 파일의 경로가 이상해 설치하지 않았습니다.")
            z.extractall(root / "pkg")
        installer = next((root / "pkg").glob("*/install.py"), None)
        if not installer:
            raise Fail("받은 판에서 install.py를 찾지 못했습니다.")
        args = [sys.executable, str(installer)] + (["--runtime-only"] if have.get("mode") == "runtime-only" else [])
        if subprocess.run(args).returncode != 0:
            raise Fail("설치 도구가 실패했습니다. 위 출력을 확인하세요.")


def status():
    cfg = config()
    have = installed()
    print(f"[판] {have.get('version', '알 수 없음')} ({'알림 장치만' if have.get('mode') == 'runtime-only' else '전체 설치'})")
    print("[보내는 곳]")
    if cfg["webhook_url"]:
        print(f"  웹훅 {masked(cfg['webhook_url'])}")
    elif cfg["app_key"] and cfg["email"]:
        print(f"  봇 (키 있음) -> {cfg['email']}")
    else:
        print("  없음: 웹훅 주소도 봇 키도 없어 기록 파일에만 남깁니다 (webhook으로 주소 저장)")
    print("[설정]")
    for key in ("enabled", "unread_seconds", "min_seconds", "antigravity"):
        print(f"  {key}: {json.dumps(cfg[key], ensure_ascii=False)}")
    print("[훅]")
    me = {str(HOME / "notify.py").replace("\\", "/"), short_path(HOME / "notify.py").replace("\\", "/")}
    for name, path in HOOK_FILES.items():
        hooked = path.exists() and any(m in path.read_text(encoding="utf-8-sig") for m in me)
        print(f"  {name}: {'연결됨' if hooked else '없음'} ({path})")
        if name == "Codex" and hooked:
            toml = Path.home() / ".codex" / "config.toml"
            text = toml.read_text(encoding="utf-8") if toml.exists() else ""
            trusted = all(f".codex\\hooks.json:{ev}:0:0" in text for ev in ("user_prompt_submit", "stop"))
            print(f"  Codex 훅 승인 기록: {'있음' if trusted else '없음 (Codex에서 /hooks로 승인해야 동작)'}")
    print(f"  앱 이동 단추 서버(127.0.0.1:{PORT}): {'켜짐' if server_running() else '꺼짐 (server로 켬)'}")
    pending = sorted(p.name[8:-5] for p in STATE.glob("pending-*.json"))
    print(f"[대기 중인 알림] {len(pending)}건" + (": " + ", ".join(pending) if pending else ""))
    print("[최근 기록]")
    lines = LOG.read_text(encoding="utf-8").splitlines()[-10:] if LOG.exists() else []
    for line in lines or ["(없음)"]:
        print("  " + line[:200])


def test():
    try:
        send(config(), "🔔 카카오워크 알림 봇 연결 확인")
    except Exception as e:  # urllib raises on HTTP errors; show it instead of a traceback
        raise Fail(f"보내지 못했습니다: {e}") from None
    print(LOG.read_text(encoding="utf-8").splitlines()[-1] if LOG.exists() else "(기록 없음)")


def server():
    ensure_server()
    for _ in range(20):
        if server_running():
            print(f"앱 이동 단추 서버가 켜져 있습니다 (127.0.0.1:{PORT}).")
            return
        time.sleep(0.1)
    raise Fail("앱 이동 단추 서버를 켜지 못했습니다.")


def manage(args):
    sys.stdout.reconfigure(errors="replace")
    try:
        cmd, rest = args[0], args[1:]
        if cmd == "set" and len(rest) == 2:
            set_config(*rest)
        elif cmd == "webhook":
            webhook(rest[0] if rest else None)
        elif cmd == "focus" and rest and rest[0] in APPS:
            print(focus(rest[0], session=rest[1] if len(rest) > 1 else ""))
        elif cmd in ("status", "test", "server", "update"):
            {"status": status, "test": test, "server": server, "update": update}[cmd]()
        else:
            raise Fail("사용법: notify.py status | set <설정> <값> | webhook [파일] | test | server | update"
                       " | focus <앱> [대화 ID]")
        return 0
    except Fail as e:
        print(f"실패: {e}")
        return 1


def main():
    args = sys.argv[1:]
    cfg = config()
    if args[:1] == ["ping"]:
        return
    if args[:1] == ["wait"]:
        wait(args[1], args[2], cfg)
        return
    if args[:1] == ["serve"]:
        serve()
        return
    tool, event = args[0], args[1]
    raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace") if not sys.stdin.isatty() else ""
    ev = json.loads(raw) if raw.strip() else {}
    if tool == "agy":
        tool = agy_client(ev)
        if tool not in cfg["antigravity"]:
            return
        if event == "stop" and ev.get("fullyIdle") is False:  # still running
            return
    STATE.mkdir(exist_ok=True)
    cleanup()
    if event == "start":
        start(tool, ev)
        ensure_server()  # so buttons of earlier notifications work again after a reboot
    elif event == "stop":
        stop(tool, ev, cfg)
    elif event == "permission" and ev.get("notification_type", "permission_prompt") == "permission_prompt":
        queue(tool, session_key(tool, ev), {"tool": tool, "text": f"⏸ {NAMES[tool]} 승인 기다림\n{short(ev.get('message'), 120)}",
                                            "folder": folder(ev), "session": conversation(tool, ev)})


if __name__ == "__main__":
    if sys.argv[1:2] and sys.argv[1] in MANAGE:
        sys.exit(manage(sys.argv[1:]))
    try:
        main()
    except Exception as e:  # a hook must never break the agent
        try:
            log(f"ERROR {sys.argv[1:]} {type(e).__name__}: {e}")
        except Exception:
            pass
    sys.exit(0)
