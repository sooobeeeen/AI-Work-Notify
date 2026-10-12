"""Windows regression checks; all writes and install targets are isolated."""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import notify
import install


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(tempfile.gettempdir()).resolve()
        self.root = self.temp_root / ("ai-work-notify-test-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(self.remove_fixture)
        self.state = self.root / "state"
        self.state.mkdir()
        for name, value in (("HOME", self.root), ("STATE", self.state),
                            ("LOG", self.root / "log.txt")):
            p = patch.object(notify, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.event = {"session_id": "00000000-0000-0000-0000-000000000001",
                      "cwd": str(self.root), "prompt": "first request"}

    def remove_fixture(self):
        target = self.root.resolve()
        if target.parent != self.temp_root or not target.name.startswith("ai-work-notify-test-"):
            raise AssertionError("Refusing to remove a path outside the isolated test folder")

        def writable(func, path, _):  # read-only folders copied from a synced checkout
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(target, **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))

    def pending_for(self, tool):
        key = notify.session_key(tool, self.event)
        return self.state / ("pending-" + key + ".json")

    def test_tagged_codex_prompt_replaces_state_and_cancels_pending(self):
        with patch.object(notify.time, "time", return_value=100):
            notify.start("codex", self.event)
        pending = self.pending_for("codex")
        pending.write_text('{"token":"old"}', encoding="utf-8")
        event = {**self.event, "prompt": "<request>second request</request>"}
        with patch.object(notify.time, "time", return_value=200):
            notify.start("codex", event)
        stored = json.loads((self.state / (notify.session_key("codex", event) + ".json")).read_text())
        self.assertEqual(stored["ts"], 200)
        self.assertEqual(stored["prompt"], event["prompt"])
        self.assertFalse(pending.exists())

    def test_claude_system_wakeup_keeps_original_request(self):
        notify.start("claude", self.event)
        stored = self.state / (notify.session_key("claude", self.event) + ".json")
        before = stored.read_bytes()
        pending = self.pending_for("claude")
        pending.write_text('{"token":"old"}', encoding="utf-8")
        notify.start("claude", {**self.event, "prompt": "<task-notification>done</task-notification>"})
        self.assertEqual(stored.read_bytes(), before)
        self.assertTrue(pending.exists())

    def test_claude_subagent_and_ci_wakeups_keep_original_request(self):
        notify.start("claude", self.event)
        stored = self.state / (notify.session_key("claude", self.event) + ".json")
        before = stored.read_bytes()
        for prompt in ('<agent-message from="a3082f9692f641e94"> [Subagent hand-back] report',
                       'Another Claude session sent a message:\n<agent-message from="a1"> [Subagent hand-back]',
                       "<ci-monitor-event>checks passed</ci-monitor-event>"):
            notify.start("claude", {**self.event, "prompt": prompt})
            self.assertEqual(stored.read_bytes(), before, prompt)

    def test_claude_prompt_starting_with_other_tag_is_a_new_request(self):
        with patch.object(notify.time, "time", return_value=100):
            notify.start("claude", self.event)
        event = {**self.event, "prompt": "<command-name>/review</command-name> 검토해줘"}
        with patch.object(notify.time, "time", return_value=200):
            notify.start("claude", event)
        stored = json.loads((self.state / (notify.session_key("claude", event) + ".json")).read_text())
        self.assertEqual(stored["ts"], 200)

    def test_claude_stop_waits_until_background_tasks_end(self):
        notify.start("claude", self.event)
        queued, logged = [], []
        running = [{"id": "bv90a2sxn", "type": "shell", "status": "running"},
                   {"id": "abaa9f0a6c1bf0f44", "type": "subagent", "status": "running"}]
        cfg = {**notify.config(), "min_seconds": 0}
        with patch.object(notify, "queue", side_effect=lambda *a: queued.append(a)), \
                patch.object(notify, "log", side_effect=logged.append):
            notify.stop("claude", {**self.event, "background_tasks": running}, cfg)
            self.assertEqual(queued, [])
            self.assertEqual(logged, ["WAIT claude 2 background task(s) still running"])
            notify.stop("claude", {**self.event, "background_tasks": running[:1]}, cfg)
            self.assertEqual(queued, [])
            done = [{**running[0], "status": "completed"}]
            notify.stop("claude", {**self.event, "background_tasks": done}, cfg)
            self.assertEqual(len(queued), 1)
            notify.stop("claude", {**self.event, "background_tasks": []}, cfg)
            self.assertEqual(len(queued), 2)
        self.assertEqual(queued[0][2]["prompt"], "first request")

    def test_codex_app_generated_request_is_not_tracked(self):
        event = {**self.event, "prompt": "This is an app-generated request for a suggested next user "
                                         "message. The user did not write this message."}
        notify.start("codex", event)
        self.assertFalse((self.state / (notify.session_key("codex", event) + ".json")).exists())
        with patch.object(notify, "queue", side_effect=AssertionError("No notification allowed")):
            notify.stop("codex", event, {**notify.config(), "min_seconds": 0})

    def test_codex_thread_without_rollout_is_not_sent(self):
        codex_home = self.root / "codex-home"
        session = "01a12da6-2542-7703-a95e-c7e3774e627e"
        pending = self.pending_for("codex")
        sent, logged = [], []

        def run():
            pending.write_text(json.dumps({"token": "t", "app": 123, "msg": {
                "tool": "codex", "elapsed": 9, "prompt": "q", "answer": "a", "session": session}}))
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}), \
                    patch.object(notify.time, "time", side_effect=[0, 31]), \
                    patch.object(notify, "user_is_watching", return_value=False), \
                    patch.object(notify, "send", side_effect=lambda *a: sent.append(a)), \
                    patch.object(notify, "log", side_effect=logged.append):
                notify.wait(pending.name, "t", notify.config())

        run()
        self.assertEqual(sent, [])
        self.assertIn("is not a saved conversation", logged[-1])
        rollout = codex_home / "sessions" / "2026" / "10" / "12" / f"rollout-2026-10-12T10-03-49-{session}.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text("{}\n")
        run()
        self.assertEqual(len(sent), 1)

    def run_wait(self, change):
        pending = self.pending_for("codex")
        pending.write_text(json.dumps({"token": "t", "app": 123,
                                       "msg": {"tool": "codex", "text": "synthetic message"}}))
        notify.save_config(enabled=True)
        sent = []
        with patch.object(notify.time, "time", side_effect=[0, 0, 31]), \
                patch.object(notify.time, "sleep", side_effect=lambda _: change()), \
                patch.object(notify, "user_is_watching", return_value=False), \
                patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("No network allowed")), \
                patch.object(notify, "log", side_effect=sent.append):
            notify.wait(pending.name, "t", notify.config())
        self.assertFalse(pending.exists())
        return sent

    def test_disabling_notifications_stops_an_existing_waiter(self):
        sent = self.run_wait(lambda: notify.save_config(enabled=False))
        self.assertEqual(sent, [])

    def test_enabled_waiter_still_sends_a_dry_message(self):
        sent = self.run_wait(lambda: None)
        self.assertEqual(sent, ["DRY synthetic message"])

    def test_replaced_waiter_does_not_send_or_delete_new_pending(self):
        pending = self.pending_for("codex")
        pending.write_text('{"token":"new"}')
        with patch.object(notify, "send", side_effect=AssertionError("No send allowed")):
            notify.wait(pending.name, "old", notify.config())
        self.assertTrue(pending.exists())

    def test_codex_status_leaves_current_trust_check_to_codex(self):
        hooks = self.root / ".codex" / "hooks.json"
        hooks.parent.mkdir()
        hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{
            "command": str(self.root / "notify.py").replace("\\", "/") + " codex stop"
        }]}]}}, ensure_ascii=False), encoding="utf-8")
        # An obsolete hash is not proof that the current hook is trusted.
        config_path = hooks.parent / "config.toml"
        config_path.write_text("[hooks.state.'" + str(hooks) + ":stop:0:0']\ntrusted_hash='sha256:old'\n")
        out = io.StringIO()
        with patch.object(notify, "HOOK_FILES", {"Codex": hooks}), \
                patch.object(notify, "server_running", return_value=False), \
                patch.object(Path, "home", return_value=self.root), \
                contextlib.redirect_stdout(out):
            notify.status()
        self.assertIn("/hooks", out.getvalue())
        self.assertNotIn("Codex 훅 승인 기록: 있음", out.getvalue())
        self.assertNotIn("Codex 훅 승인 기록: 없음", out.getvalue())

    def test_powershell_management_command_expands_userprofile(self):
        data = self.root / ".kakaowork-notify"
        data.mkdir()
        shutil.copy2(ROOT / "notify.py", data / "notify.py")
        env = {**os.environ, "USERPROFILE": str(self.root),
               "AI_WORK_NOTIFY_TEST_PYTHON": sys.executable}
        result = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 '& $env:AI_WORK_NOTIFY_TEST_PYTHON "$env:USERPROFILE\\.kakaowork-notify\\notify.py" status'],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_install_twice_preserves_hooks_and_configuration(self):
        data = self.root / ".kakaowork-notify"
        data.mkdir()
        cfg = {"enabled": False, "unread_seconds": 45, "webhook_url": "synthetic-only"}
        (data / "config.json").write_text(json.dumps(cfg))
        codex = self.root / ".codex"
        codex.mkdir()
        hooks = codex / "hooks.json"
        unrelated = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other-hook.exe"}]}]}}
        hooks.write_text(json.dumps(unrelated))
        with patch.object(install, "HOME", self.root), patch.object(install, "DATA", data), \
                patch.object(install, "restart_server"), patch.object(sys, "argv", ["install.py"]), \
                contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")):
            install.main()
            before = hooks.read_bytes()
            install.main()
        self.assertEqual(hooks.read_bytes(), before)
        self.assertEqual(json.loads((data / "config.json").read_text()), cfg)
        self.assertEqual(json.loads(hooks.read_text())["hooks"]["Stop"][0]["hooks"][0]["command"], "other-hook.exe")
        self.assertTrue((codex / "skills" / "ai-work-notify" / "SKILL.md").exists())
        for path in [codex / "skills" / "ai-work-notify", *(codex / "skills" / "ai-work-notify").rglob("*")]:
            self.assertFalse(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY, f"{path} left read-only")
        self.assertEqual(json.loads((data / "installed.json").read_text())["mode"], "full")

    def test_runtime_only_install_does_not_create_hooks_or_skills(self):
        data = self.root / ".kakaowork-notify"
        with patch.object(install, "HOME", self.root), patch.object(install, "DATA", data), \
                patch.object(install, "restart_server"), \
                patch.object(sys, "argv", ["install.py", "--runtime-only"]), \
                contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")):
            install.main()
        self.assertFalse((self.root / ".codex").exists())
        self.assertEqual(json.loads((data / "installed.json").read_text())["mode"], "runtime-only")

    def test_update_of_current_release_does_not_download_or_install(self):
        version = (ROOT / "VERSION").read_text().strip()
        with patch.object(notify, "installed", return_value={"version": version}), \
                patch.object(notify, "github", return_value=json.dumps({"tag_name": "v" + version}).encode()) as github, \
                patch.object(notify.subprocess, "run", side_effect=AssertionError("No install allowed")), \
                contextlib.redirect_stdout(io.StringIO()):
            notify.update()
        self.assertEqual(github.call_count, 1)

    def test_update_keeps_runtime_only_mode(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("release/install.py", "# isolated installer fixture\n")
        update_root = self.root / "update"
        update_root.mkdir()
        with patch.object(notify, "installed", return_value={"version": "1.0.0", "mode": "runtime-only"}), \
                patch.object(notify, "github", side_effect=[b'{"tag_name":"v1.2.1"}', archive.getvalue()]), \
                patch.object(notify.tempfile, "TemporaryDirectory", return_value=contextlib.nullcontext(str(update_root))), \
                patch.object(notify.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            notify.update()
        self.assertEqual(run.call_args.args[0][-1], "--runtime-only")

    def write_installed(self, version):
        (self.root / "installed.json").write_text(json.dumps({"version": version, "mode": "full"}))

    def latest(self, tag, body=""):
        return patch.object(notify, "github", return_value=json.dumps({"tag_name": tag, "body": body}).encode())

    def test_newer_release_is_announced_once(self):
        self.write_installed("1.3.0")
        body = "새 판이 나오면 알려 줍니다.\r\n\r\n## 바뀐 것\r\n- 자세한 내용"
        later = notify.time.time() + 2 * 86400
        sent = []
        with self.latest("v1.3.1", body) as github, \
                patch.object(notify, "send", side_effect=lambda cfg, text: sent.append(text)):
            notify.release_notice()
            notify.release_notice()  # already checked today
            self.assertEqual(github.call_count, 1)
            with patch.object(notify.time, "time", return_value=later):
                notify.release_notice()  # checks again; this release was already announced
            self.assertEqual(github.call_count, 2)
        self.assertEqual(sent, ["🆕 AI 작업 알림 새 판 v1.3.1\n새 판이 나오면 알려 줍니다.\n"
                                'Claude Code나 Codex에게 "AI 작업 알림 업데이트해줘"라고 하면 받을 수 있습니다.'])

    def test_no_release_message_when_current_offline_or_disabled(self):
        self.write_installed("1.3.0")
        cache = self.root / "release.json"
        logged = []
        with patch.object(notify, "send", side_effect=AssertionError("No message allowed")), \
                patch.object(notify, "log", side_effect=logged.append):
            with self.latest("v1.3.0"):
                notify.release_notice()
            checked = json.loads(cache.read_text(encoding="utf-8"))["checked"]
            with patch.object(notify, "github", side_effect=OSError("offline")) as github, \
                    patch.object(notify.time, "time", return_value=checked + 2 * 86400):
                notify.release_notice()
                notify.release_notice()  # an unreachable GitHub is tried again the next day
            self.assertEqual(github.call_count, 1)
            self.assertEqual(logged, ["RELEASE check failed: OSError: offline"])
            self.assertEqual(json.loads(cache.read_text(encoding="utf-8"))["checked"], checked)  # status's date
            cache.unlink()
            notify.save_config(enabled=False)
            with self.latest("v1.3.1"):
                notify.release_notice()
        notify.save_config(enabled=True)
        sent = []
        with self.latest("v1.3.1"), patch.object(notify, "send", side_effect=lambda cfg, text: sent.append(text)), \
                patch.object(notify.time, "time", return_value=notify.time.time() + 2 * 86400):
            notify.release_notice()  # turned on again: the next check announces it
        self.assertEqual(len(sent), 1)

    def test_release_summary_is_the_first_line_that_is_not_a_heading(self):
        self.assertEqual(notify.release_summary("## 고친 것\n- **Codex 알림을 고쳤습니다.** 자세히"),
                         "Codex 알림을 고쳤습니다. 자세히")
        self.assertEqual(notify.release_summary(None), "")

    def test_management_commands_show_a_newer_release(self):
        def run():
            out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")  # manage() needs reconfigure()
            with patch.object(notify, "HOOK_FILES", {}), patch.object(notify, "server_running", return_value=False), \
                    contextlib.redirect_stdout(out):
                notify.status()
                notify.manage(["set", "unread_seconds", "40"])
            out.flush()
            return out.buffer.getvalue().decode("utf-8")

        self.write_installed("1.3.0")
        (self.root / "release.json").write_text(json.dumps(
            {"tag": "v1.3.1", "summary": "요약 한 줄", "checked": 0}, ensure_ascii=False), encoding="utf-8")
        shown = run()
        self.assertIn("[판] 1.3.0 (전체 설치) · 새 판 v1.3.1 있음: 요약 한 줄\n", shown)
        self.assertIn('새 판 v1.3.1 있음: 요약 한 줄 ("AI 작업 알림 업데이트해줘"로 받습니다)\n', shown)
        self.write_installed("1.3.1")
        shown = run()
        self.assertNotIn("새 판", shown)
        self.assertIn("[판] 1.3.1 (전체 설치) · 최신 (", shown)

    def test_waiter_checks_for_a_release_after_the_answer(self):
        calls = []
        with patch.object(notify, "wait", side_effect=lambda *a: calls.append("wait")), \
                patch.object(notify, "release_notice", side_effect=lambda: calls.append("release")), \
                patch.object(sys, "argv", ["notify.py", "wait", "pending-x.json", "t"]):
            notify.main()
        self.assertEqual(calls, ["wait", "release"])


if __name__ == "__main__":
    unittest.main()
