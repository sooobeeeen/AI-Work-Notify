"""Install or update the AI work notifier (KakaoWork) on this PC.

    python install.py                 notify.py, hooks for the apps found here, and the ai-work-notify skill
    python install.py --runtime-only  update notify.py only (hooks, settings and skills untouched)
    python install.py --dry-run       show what would change and change nothing

notify.py goes to %USERPROFILE%\\.kakaowork-notify, which the hooks run. Hook commands carry no
quotes because Antigravity passes quotes through literally, so the Python and notify.py paths
must have no spaces; their 8.3 short form is used when they do. Our hooks are added once,
other hooks are kept, and a file that would not change is not rewritten (Codex asks to approve
hooks again whenever its hooks change).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent
sys.path.insert(0, str(PKG))
import notify  # noqa: E402  (the package copy, for short_path)

HOME = Path.home()
DATA = HOME / ".kakaowork-notify"
SKILL = "ai-work-notify"
NEW_CONFIG = {"webhook_url": "", "enabled": True, "unread_seconds": 30, "min_seconds": 0,
              "antigravity": ["app", "ide"]}
OURS = re.compile(r"notify\.py (claude|codex|agy) (start|stop|permission)$")


def say(msg):
    print(msg, flush=True)


def no_space(path):
    text = str(path)
    if " " in text and Path(path).exists():
        text = notify.short_path(path)
    if " " in text:
        sys.exit(f"설치 중단: 경로에 띄어쓰기가 있어 훅 명령을 만들 수 없습니다: {path}\n"
                 "띄어쓰기 없는 경로에 Python을 설치하거나, 이 PC에서 8.3 짧은 이름을 켜야 합니다.")
    return text.replace("\\", "/")


# --- notify.py ---------------------------------------------------------------------

def install_runtime(dry):
    src, dst = PKG / "notify.py", DATA / "notify.py"
    if dst.exists() and dst.read_bytes() == src.read_bytes():
        say(f"notify.py: 최신 ({dst})")
        return
    say(f"notify.py: {'바꿀 예정' if dry else '복사함'} -> {dst}")
    if dry:
        return
    (DATA / "state").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    restart_server()


def restart_server():
    """The button's page keeps running old code, so restart it (only our own server)."""
    names = {str(DATA / "notify.py"), notify.short_path(DATA / "notify.py")}
    like = " -or ".join(f"$_.CommandLine -like '*{n}* serve'" for n in names)
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
          f"Where-Object {{ {like} }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    subprocess.run([sys.executable, str(DATA / "notify.py"), "server"], capture_output=True)


# --- hooks -------------------------------------------------------------------------

def merge_grouped(data, wanted):
    """Claude Code and Codex: {"hooks": {event: [{"matcher"?, "hooks": [{type, command, timeout}]}]}}."""
    hooks = data.setdefault("hooks", {})
    changed = False
    for event, (matcher, command) in wanted.items():
        groups = hooks.setdefault(event, [])
        for group in list(groups):
            entries = group.get("hooks", [])
            keep = [h for h in entries if not (OURS.search(h.get("command", "")) and h.get("command") != command)]
            if len(keep) != len(entries):  # an older install of ours with another path
                changed = True
                if keep:
                    group["hooks"] = keep
                else:
                    groups.remove(group)
        if not any(h.get("command") == command for g in groups for h in g.get("hooks", [])):
            group = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
            groups.append({"matcher": matcher, **group} if matcher else group)
            changed = True
    return changed


def merge_named(data, base):
    """Antigravity: {name: {event: [{type, command, timeout}]}}."""
    want = {"PreInvocation": [{"type": "command", "command": f"{base} agy start", "timeout": 10}],
            "Stop": [{"type": "command", "command": f"{base} agy stop", "timeout": 10}]}
    if data.get("kakaowork-notify") == want:
        return False
    data["kakaowork-notify"] = want
    return True


def update_hooks(name, path, merge, dry):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except ValueError:
        say(f"{name}: {path}를 읽지 못해 건너뜀 (JSON 형식 오류). 직접 확인이 필요합니다.")
        return
    if not merge(data):
        say(f"{name}: 훅 이미 연결됨")
        return
    say(f"{name}: 훅 {'연결 예정' if dry else '연결함'} ({path})")
    if dry:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".before-ai-work-notify")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install_hooks(dry):
    notify_path = DATA / "notify.py"
    target = no_space(notify_path) if notify_path.exists() else str(notify_path).replace("\\", "/")
    base = f"{no_space(sys.executable)} {target}"
    if not dry:
        # Run it the way Antigravity runs hooks (cmd.exe): a broken command must never be hooked,
        # since a failing prompt hook can block prompts in Claude Code.
        if subprocess.run(f"{base} ping", shell=True, capture_output=True).returncode != 0:
            sys.exit(f"설치 중단: 훅 명령이 실행되지 않습니다: {base} ping")
    found = False
    if (HOME / ".claude").is_dir():
        found = True
        update_hooks("Claude Code", HOME / ".claude" / "settings.json", lambda d: merge_grouped(d, {
            "UserPromptSubmit": (None, f"{base} claude start"),
            "Stop": (None, f"{base} claude stop"),
            "Notification": ("permission_prompt", f"{base} claude permission")}), dry)
    if (HOME / ".codex").is_dir():
        found = True
        update_hooks("Codex", HOME / ".codex" / "hooks.json", lambda d: merge_grouped(d, {
            "UserPromptSubmit": (None, f"{base} codex start"),
            "Stop": (None, f"{base} codex stop")}), dry)
    if (HOME / ".gemini").is_dir():
        found = True
        update_hooks("Antigravity", HOME / ".gemini" / "config" / "hooks.json", lambda d: merge_named(d, base), dry)
    if not found:
        say("Claude Code, Codex, Antigravity 중 설치된 것을 찾지 못했습니다 (~/.claude, ~/.codex, ~/.gemini 없음).")


# --- config and skill --------------------------------------------------------------

def install_config(dry):
    path = DATA / "config.json"
    if path.exists():
        say("config.json: 있음 (그대로 둠)")
        return
    say(f"config.json: {'만들 예정' if dry else '만듦'} (웹훅 주소는 비어 있음)")
    if not dry:
        path.write_text(json.dumps(NEW_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def install_skill(dry):
    src = PKG / "skills" / SKILL
    for runtime in (HOME / ".claude", HOME / ".codex"):
        if not runtime.is_dir():
            continue
        dst = runtime / "skills" / SKILL
        if dst.is_symlink() or getattr(dst, "is_junction", lambda: False)():
            say(f"스킬: {dst}는 링크라 건드리지 않음")
            continue
        say(f"스킬: {'설치 예정' if dry else '설치함'} -> {dst}")
        if not dry:
            shutil.copytree(src, dst, dirs_exist_ok=True)


NEXT = """
다음은 사람이 할 일입니다.
1. 카카오워크 PC 앱 > 바로가기 > 확장 서비스 > Incoming Webhook > Bot 만들기
   이름(예: AI 작업 알림, 알림 보낸 사람으로 보임)을 정하고 채팅방은 1:1 채팅방을 고릅니다.
2. 만든 웹훅 주소를 복사한 뒤 에이전트에게 "웹훅 주소 넣어줘"라고 합니다 (주소를 대화창에 붙이지 않습니다).
3. 에이전트가 시험 메시지를 보내면 카카오워크 1:1 방에 왔는지 확인합니다.
4. Codex를 쓰면 Codex에서 /hooks를 열어 알림 훅 2개를 승인합니다. 안 하면 Codex 알림만 오지 않습니다.
5. Claude Code, Codex, VS Code, Antigravity를 다시 시작합니다. 훅은 새 대화부터 적용됩니다.
"""


def main():
    p = argparse.ArgumentParser(description="AI 작업 알림(카카오워크) 설치")
    p.add_argument("--runtime-only", action="store_true", help="notify.py만 갱신")
    p.add_argument("--dry-run", action="store_true", help="바뀔 것만 보여 주고 아무것도 바꾸지 않음")
    a = p.parse_args()
    sys.stdout.reconfigure(errors="replace")
    install_runtime(a.dry_run)
    if a.runtime_only:
        return
    install_config(a.dry_run)
    install_hooks(a.dry_run)
    install_skill(a.dry_run)
    if not a.dry_run:
        say(NEXT)


if __name__ == "__main__":
    main()
