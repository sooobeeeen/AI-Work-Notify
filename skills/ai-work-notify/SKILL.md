---
name: ai-work-notify
description: 카카오워크 'AI 작업 알림'을 관리한다. Claude Code·Codex·Antigravity 답변이 끝났는데 보지 않으면 카카오워크 1:1 방으로 오는 알림을 켜고 끄기, 대기 시간 바꾸기, 웹훅 주소 넣기·바꾸기, 시험 메시지, "알림이 안 와" 문제 해결, 새 판으로 업데이트, 알림 지우기에 사용한다. 처음 설치는 AI-Work-Notify 저장소(github.com/sooobeeeen/AI-Work-Notify)의 AGENTS.md를 따른다.
---

# 스킬: AI 작업 알림 관리

알림 장치는 `%USERPROFILE%\.kakaowork-notify\notify.py`에 설치되어 있다. Claude Code·Codex·Antigravity의 훅이 이 파일을 부른다. 답변이 끝나고 `unread_seconds`초 안에 사용자가 그 앱 창을 보지 않으면, 카카오워크 웹훅으로 1:1 방에 알림을 보낸다. 알림에는 그 앱으로 넘어가는 단추가 붙는다. Claude Code와 Codex의 단추는 질문한 그 대화를 열고(`claude://code/continue?session=…`, `codex://threads/…`), VS Code(Claude Code·Codex 확장)와 Antigravity는 대화를 여는 링크가 없어 그 작업 폴더 이름이 제목에 있는 창을 고른다. 창을 X로 닫아 트레이에 숨어 있어도 다시 띄운다(VS Code는 X로 닫으면 종료되므로 "no window").

Codex(PowerShell)에서는 아래처럼 실행한다. `status`는 읽기만 하므로 먼저 기본 권한으로 실행한다. 설정 변경·업데이트·시험 발송처럼 사용자 폴더 쓰기나 네트워크가 필요한 명령은 샌드박스가 막으면 실행 승인을 요청한다.

```powershell
py -3.13 "$env:USERPROFILE\.kakaowork-notify\notify.py" status
```

Bash에서는 `py -3.13 ~/.kakaowork-notify/notify.py status`처럼 쓴다. Python 3.13 대신 다른 지원 버전을 설치했다면 설치 때 확인한 독립 Python의 전체 경로로 실행한다. PowerShell은 따옴표로 감싼 실행 파일 경로 앞에 `&`를 붙인다. `%USERPROFILE%`은 cmd.exe 문법이므로 PowerShell·Bash 명령에 쓰지 않는다. 관리 명령은 실패하면 `실패:`로 시작하는 이유를 출력하고 종료 코드 1을 돌려준다.

## 지킬 것

- `config.json`을 읽거나 출력하지 않는다. 웹훅 주소가 들어 있다. 상태는 `status`, 설정은 `set`으로 다룬다.
- 웹훅 주소를 대화창에 붙이라고 하지 않는다. 사용자가 주소를 복사한 뒤 `webhook`을 실행한다.
- 이 알림은 웹훅만 쓴다. 카카오워크 봇 키(App Key)를 넣지 않는다.
- 훅 명령과 설치 경로를 바꾸지 않는다. **훅 설정에 저장하는 명령**에는 따옴표를 넣지 않는다(Antigravity가 따옴표를 글자 그대로 넘긴다). PowerShell·Bash에서 직접 실행할 때는 경로를 그 셸 문법에 맞게 감싼다. Codex는 훅이 바뀌면 `/hooks`에서 다시 승인해야 한다.
- 알림 장치를 고치거나 새 판으로 바꿀 때는 AI-Work-Notify 폴더에서 `py -3.13 install.py`를 다시 실행한다. 설치된 `notify.py`를 직접 고치지 않는다.

## 사용자 요청과 명령

| 요청 | 명령 |
| --- | --- |
| 알림 꺼 줘 / 켜 줘 | `set enabled false` / `set enabled true` |
| 대기 시간 N초로 | `set unread_seconds N` (5 이상, 기본 30) |
| 오래 걸린 작업만 알려 줘 | `set min_seconds N` (N초보다 짧게 걸린 작업은 알리지 않음, 기본 0) |
| Antigravity IDE만 / 앱만 | `set antigravity ide` / `set antigravity app` (기본 `app,ide`) |
| 웹훅 주소 넣어 줘 / 바꿔 줘 | 사용자가 주소를 복사했는지 확인한 뒤 `webhook`. 클립보드를 못 읽으면 메모장 파일에 저장하게 하고 `webhook <파일>`, 그 파일은 지우게 한다 |
| 알림 시험해 줘 | `test`. 1:1 방에 왔는지 사용자에게 확인받는다 |
| 업데이트해 줘 | `update`. GitHub(sooobeeeen/AI-Work-Notify) 최신 릴리즈가 더 새로울 때만 받아 설치한다. 설정·웹훅 주소·훅은 그대로다. `update`가 없다고 나오면(1.2.0 전 판) 저장소 주소로 처음 설치하듯 다시 설치한다 |
| 새 판 있어? | `status`의 설치된 판과 GitHub 최신 릴리즈(`https://api.github.com/repos/sooobeeeen/AI-Work-Notify/releases/latest`의 `tag_name`)를 비교해 알린다. 판 확인 요청만으로 `update`를 실행하지 않는다 |
| 이동 단추가 안 돼 | `server`. 창은 뜨는데 다른 대화가 보이면: 1.1.0 전에 온 알림(단추에 대화 ID 없음)이거나, Codex에서 보관(archive)한 대화(Codex 앱이 열지 못함)다. 새 알림으로 다시 해 보게 한다. Antigravity는 원래 대화까지는 못 바꾼다 |
| 상태 보여 줘 | `status` |

설정 변경은 다음 알림부터 적용된다. 알림을 끄면 이미 대기 중인 알림도 발송하지 않는다. 앱을 다시 시작할 필요는 없다.

## 알림이 안 올 때

`status`를 실행한다. 보내는 곳(가린 웹훅 주소), 설정, 세 앱의 훅 연결, Codex 훅 승인 확인 방법, 이동 단추 서버, 최근 기록 10줄이 나온다. 연결됨 표시는 훅 설정이 있다는 뜻이다. 현재 훅 정의가 승인됐는지는 Codex의 `/hooks`에서 확인한다.

| 최근 기록 | 뜻과 할 일 |
| --- | --- |
| `SENT` | 보냈다. 못 받았으면 웹훅을 연결한 방과 카카오워크 알림 설정을 확인하게 한다. |
| `READ` | 앱 창을 보고 있어서 보내지 않았다. 정상이다. |
| `SKIP … not from a desktop app window` | 창이 있는 앱 밖에서 돌린 실행이라 건너뛰었다. 터미널에서 돌린 `claude`, `claude -p`, `codex exec`, `agy -p`, SDK 스크립트면 정상이다. 이 알림은 Claude·Codex 데스크톱 앱, VS Code의 Claude Code·Codex 확장, Antigravity(2.0 앱·IDE)에서만 동작한다고 사용자에게 알린다. |
| `FAIL` | 카카오워크가 거절했다. 웹훅이 지워졌으면 새로 만들고 `webhook`을 다시 한다. |
| `ERROR … HTTPError: HTTP Error 404` | 웹훅이 없어졌다. 새로 만들고 `webhook`을 다시 한다. |
| `ERROR` (그 밖) | 알림 장치 오류다. 메시지를 사용자에게 알린다. |
| `DRY` | 웹훅 주소가 없어 기록만 했다. `webhook`으로 넣는다. |
| `FOCUS <앱> ok` / `hidden` / `denied` / `no window` | 이동 단추 결과: 성공 / 다른 데스크톱으로 못 넘어감 / Windows가 막음 / 그 앱 창이 없음(앱이 꺼져 있음). 뒤에 `session=…`이 붙으면 Claude Code나 Codex에 그 대화를 열라고 전달한 것이고, `host=vscode`면 VS Code 창을 띄운 것이다. |
| `BLOCKED … request from a web page` | 카카오워크가 아닌 웹 페이지가 이동 단추 주소를 불러서 거절했다. 정상이다. 카카오워크 단추를 눌렀는데 이 줄이 나오면 카카오워크 작은 창의 제목이 바뀌었을 수 있으니 사용자에게 알린다. |
| `REQUEST … from KakaoWork's window` | 카카오워크 작은 창이 연 요청이라 받아들였다. 정상이다. |
| `POPUP not found` / `POPUP still open` | 이동 단추를 누르면 뜨는 카카오워크 작은 창을 못 찾았거나 못 닫았다. 사용자가 닫으면 된다. |
| 아무 줄도 없음 | 훅이 돌지 않았다. `status`의 [훅]이 "연결됨"인지 보고, Codex의 `/hooks`에서 현재 알림 훅 2개가 승인됐는지 확인하게 한다. 앱을 다시 시작하게 한다. 연결이 없으면 AI-Work-Notify 폴더에서 `py -3.13 install.py`를 다시 실행한다. |

## 알림을 아예 지우려면

먼저 `set enabled false`로 끄고, 사용자에게 완전히 지울지 확인한다. 지운다면 아래 순서로 한다.

1. 세 훅 설정 파일에서 명령이 `notify.py claude …`, `notify.py codex …`, `notify.py agy …`로 끝나는 항목만 지운다. 파일은 `~/.claude/settings.json`, `~/.codex/hooks.json`, `~/.gemini/config/hooks.json`이고, Antigravity 쪽은 `kakaowork-notify` 항목이다.
2. 명령줄에 `notify.py serve`가 있는 `pythonw.exe` 프로세스 하나만 끈다.
3. `%USERPROFILE%\.kakaowork-notify` 폴더를 지운다.
4. Codex를 쓰면 `/hooks`에서 확인하게 하고, 앱을 다시 시작하게 한다.
5. 카카오워크의 웹훅은 사용자가 확장 서비스에서 지운다.
