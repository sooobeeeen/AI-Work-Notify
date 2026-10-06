# AI 작업 알림 (카카오워크)

Claude Code·Codex·Antigravity에 일을 맡겨 두고 다른 일을 하다가, 답변이 끝났는데 30초 안에 보지 않으면 카카오워크로 알려 줍니다. 알림의 "○○로 이동" 단추를 누르면 그 앱 창으로 바로 넘어갑니다. 앱이 다른 가상 데스크톱에 있어도 그 데스크톱으로 넘어갑니다.

## 알림 모양

```
✅ Claude Code 답변 도착 · 2분 13초
📁 작업 폴더 이름
💬 보낸 질문의 앞부분
↳ 답변의 앞부분
[ Claude Code로 이동 ]
```

- 그 앱 창을 보고 있으면 보내지 않습니다. 창이 맨 앞에 있고 최근 30초 안에 키보드나 마우스를 썼으면 본 것으로 칩니다.
- 같은 대화에 다음 요청을 보내면 기다리던 알림은 취소됩니다.
- Claude Code가 승인을 기다릴 때도 알려 줍니다.
- 이동 단추는 Claude Code와 Codex 데스크톱 앱에서는 그 질문을 한 대화를 열어 줍니다. VS Code와 Antigravity는 대화를 여는 링크가 없어서, 그 작업 폴더가 열린 창을 앞으로 띄웁니다. 창을 X로 닫아 트레이에 들어가 있어도 다시 띄웁니다(VS Code는 X로 닫으면 종료되므로 예외).
- 시간은 요청을 보낸 때부터 답변이 끝날 때까지 걸린 시간입니다.
- 이동 단추는 이 PC의 카카오워크에서 눌러야 합니다. 휴대폰에서는 동작하지 않습니다.

## 설치

> **창이 있는 앱에서만 동작합니다.** Claude 데스크톱 앱, Codex 데스크톱 앱(Windows에서는 ChatGPT 앱과 같은 프로그램), VS Code의 Claude Code·Codex 확장, Antigravity(2.0 앱 또는 Antigravity IDE)에서 한 작업을 알려 줍니다. 터미널에서 쓰는 Claude Code·Codex는 알림이 오지 않습니다.

1. Claude Code나 Codex에게 이렇게 말합니다.
   > **https://github.com/sooobeeeen/AI-Work-Notify 에서 AI 작업 알림 설치해줘**

   에이전트가 아래 [에이전트용: 받는 방법](#에이전트용-받는-방법)대로 최신 판을 받고, `AGENTS.md`를 따라 설치합니다. Python이 없으면 에이전트가 먼저 설치합니다. Codex는 설치 중에 "샌드박스 밖에서 실행" 승인을 요청하는데, 승인해야 설치됩니다.
2. 카카오워크 웹훅을 만듭니다.
   - 카카오워크 PC 앱에서 **바로가기 > 확장 서비스 > Incoming Webhook > Bot 만들기**로 들어갑니다.
   - 이름을 정합니다(예: "AI 작업 알림"). 이 이름이 알림을 보낸 사람으로 보입니다.
   - 채팅방은 **1:1 채팅방**을 고릅니다.
   - 만든 뒤 나오는 웹훅 주소를 **복사**합니다.
3. 에이전트에게 **"웹훅 주소 넣어줘"** 라고 말합니다. 주소를 대화창에 붙이지 않아도 됩니다. 에이전트가 복사해 둔 주소를 바로 읽어 저장합니다.
4. 에이전트가 보낸 시험 메시지가 카카오워크 1:1 방에 왔는지 확인합니다.
5. Codex를 쓰면 Codex에서 `/hooks`를 열어 알림 훅 2개를 **승인**합니다. 승인하지 않으면 Codex 알림만 오지 않습니다.
6. Claude Code, Codex, VS Code, Antigravity를 다시 시작합니다. 새 대화부터 알림이 옵니다.

## 쓰는 법

설치하면 `ai-work-notify` 스킬도 함께 깔립니다. 이렇게 말하면 됩니다.

| 이렇게 말하면 | 하는 일 |
|---|---|
| "알림 꺼줘" / "알림 켜줘" | 알림 전체를 끄거나 켭니다 |
| "알림 대기 시간 1분으로" | 답변이 끝난 뒤 기다리는 시간을 바꿉니다(기본 30초) |
| "웹훅 주소 바꿔줘" | 새로 복사한 웹훅 주소로 바꿉니다 |
| "알림 시험해 줘" | 시험 메시지를 보냅니다 |
| "알림이 안 와" | 상태와 기록을 보고 원인을 찾습니다 |
| **"AI 작업 알림 업데이트해줘"** | GitHub에 새 판이 있으면 받아서 설치합니다. 설정과 웹훅 주소는 그대로 남습니다 |

## 업데이트

새 판은 이 저장소의 [Releases](https://github.com/sooobeeeen/AI-Work-Notify/releases)에 올라옵니다. 에이전트에게 "AI 작업 알림 업데이트해줘"라고 하면 됩니다. 에이전트는 `notify.py update`를 실행해, 설치된 판보다 새 판이 있을 때만 받아서 설치합니다. 훅 설정은 바뀌지 않으므로 Codex에서 다시 승인할 필요가 없습니다(바뀌는 판이면 릴리즈 노트에 적습니다).

1.2.0보다 전 판(1.0.0, 1.1.x)에는 `update` 명령이 없습니다. 그때는 처음 설치할 때처럼 "https://github.com/sooobeeeen/AI-Work-Notify 에서 AI 작업 알림 설치해줘"라고 하면 최신 판으로 올라갑니다.

## 에이전트용: 받는 방법

사용자가 이 저장소 주소를 주며 설치나 업데이트를 부탁하면, 최신 릴리즈를 임시 폴더에 받아 풀고 그 안의 `AGENTS.md`를 따른다(PowerShell).

```powershell
$tag = (Invoke-RestMethod https://api.github.com/repos/sooobeeeen/AI-Work-Notify/releases/latest).tag_name
$dir = Join-Path $env:TEMP "AI-Work-Notify-$tag"
Invoke-WebRequest "https://github.com/sooobeeeen/AI-Work-Notify/archive/refs/tags/$tag.zip" -OutFile "$dir.zip"
Expand-Archive "$dir.zip" $dir -Force
Get-ChildItem $dir -Directory | Select-Object -First 1 -ExpandProperty FullName   # 이 폴더의 AGENTS.md를 따른다
```

이미 설치된 PC(1.2.0 이상)에서 업데이트만 하려면 `python %USERPROFILE%\.kakaowork-notify\notify.py update`를 실행한다.

## 주의

- **웹훅 주소는 그 1:1 방에 글을 올릴 수 있는 열쇠입니다.** 남에게 주거나 대화창·공유 폴더에 두지 마세요. 새어 나갔으면 카카오워크에서 그 웹훅을 지우고 새로 만든 뒤 "웹훅 주소 바꿔줘"라고 하세요.
- 알림 장치는 `%USERPROFILE%\.kakaowork-notify`에 설치됩니다(알림 장치, 설정, 기록). 이 폴더를 옮기거나 지우면 알림이 끊깁니다.
- 설치 도구는 각 앱의 훅 설정 파일을 처음 고칠 때 원래 파일을 `이름.before-ai-work-notify`로 백업해 둡니다.
- 이동 단추용 작은 서버는 이 PC 안(127.0.0.1)에서만 접속됩니다. 다른 웹 페이지가 이 주소를 부르면 거절합니다.

## 문제가 생기면

에이전트에게 "알림이 안 와"라고 하면 됩니다. 직접 보려면 아래 명령의 결과를 확인하세요.

```
python %USERPROFILE%\.kakaowork-notify\notify.py status
```
