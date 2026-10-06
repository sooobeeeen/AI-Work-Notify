# AI-Work-Notify 에이전트 지침

이 폴더는 카카오워크 "AI 작업 알림" 설치 묶음이다. 사용자가 이 폴더에서 "설치해줘"라고 하면 아래 순서대로 설치한다. 설치 뒤 관리("알림 꺼줘", "알림이 안 와" 등)는 함께 설치되는 `ai-work-notify` 스킬을 따른다.

## 설치 순서

0. **쓰는 앱 확인.** 이 알림은 Claude 데스크톱 앱, Codex 데스크톱 앱(Windows에서는 ChatGPT 앱과 같은 프로그램), VS Code의 Claude Code·Codex 확장, Antigravity(2.0 앱·IDE)에서 한 작업만 알린다. 터미널에서 쓰는 Claude Code·Codex는 알리지 않는다. 사용자에게 무엇을 쓰는지 묻고, 이 중 하나도 쓰지 않으면 그렇게 알리고 설치하지 않는다.
1. **Python 확인.** `python --version`이 3.10 이상인지 본다. 없거나 낮으면 사용자 범위로 설치한다.
   `winget install -e --id Python.Python.3.13 --scope user`
   설치 뒤 새 터미널에서 다시 확인한다. Microsoft Store 판 Python(경로에 `WindowsApps`)은 쓰지 않는다.
   `python`이 다른 프로그램에 딸린 Python(경로가 `Program Files\Inkscape`, `Blender` 등)을 가리키면 그것도 쓰지 않는다. 그 프로그램을 지우거나 올리면 알림이 끊긴다. `py -0p`로 따로 설치된 Python을 찾아 그 전체 경로로 아래 명령을 실행하고, 없으면 위처럼 설치한다. 훅에는 이때 쓴 Python 경로가 들어가므로 설치 뒤 사용자에게 그 Python을 지우지 말라고 알린다.
2. **미리 보기.** 이 폴더에서 `python install.py --dry-run`을 실행하고, 무엇이 바뀌는지 사용자에게 짧게 알린다.
3. **설치.** `python install.py`를 실행한다.
   - Codex에서는 사용자 폴더(`~/.claude`, `~/.codex`, `~/.gemini`, `~/.kakaowork-notify`)에 써야 하므로 샌드박스 밖 실행 승인을 요청한다.
   - "설치 중단: 경로에 띄어쓰기…"가 나오면 Python을 띄어쓰기 없는 경로에 다시 설치한다(1번의 사용자 범위 설치는 보통 띄어쓰기가 없다). 사용자 이름에 띄어쓰기가 있으면 사용자에게 알리고 멈춘다.
   - "설치 중단: 훅 명령이 실행되지 않습니다"가 나오면 그 명령을 직접 실행해 원인을 찾는다. 원인을 고치기 전에는 훅을 직접 만들지 않는다.
4. **웹훅 만들기 안내.** 사용자에게 아래를 그대로 안내하고, 주소를 복사했다는 답을 기다린다.
   - 카카오워크 PC 앱 > 바로가기 > 확장 서비스 > Incoming Webhook > Bot 만들기
   - 이름을 정한다(예: "AI 작업 알림"). 이 이름이 알림을 보낸 사람으로 보인다.
   - 채팅방은 1:1 채팅방을 고른다.
   - 만든 뒤 나오는 웹훅 주소를 복사한다.
5. **웹훅 주소 저장.** `python %USERPROFILE%\.kakaowork-notify\notify.py webhook`을 실행한다. 클립보드에서 주소를 읽어 저장하고, 가린 주소만 보여 준다.
   - 사용자에게 주소를 대화창에 붙이라고 하지 않는다. 사용자가 붙여 넣었다면 그대로 쓰지 말고, 카카오워크에서 웹훅을 새로 만들라고 권한다.
   - 클립보드를 못 읽으면, 사용자에게 메모장으로 텍스트 파일에 주소 한 줄을 저장하게 한다. 그다음 `notify.py webhook <그 파일>`을 실행하고, 그 파일은 지우게 한다.
6. **시험.** `python %USERPROFILE%\.kakaowork-notify\notify.py test`를 실행하고, 카카오워크 1:1 방에 시험 메시지가 왔는지 사용자에게 확인받는다. 결과 줄이 `SENT`여도 방에 왔는지는 사용자만 볼 수 있다.
7. **마무리 안내.**
   - Codex를 쓰면 Codex에서 `/hooks`를 열어 알림 훅 2개를 승인해야 한다. 안 하면 Codex 알림만 오지 않는다.
   - Claude Code, Codex, VS Code, Antigravity를 다시 시작해야 새 대화부터 알림이 온다.
8. **보고.** `notify.py status` 결과를 요약해 알린다. 연결된 앱, 보내는 곳(가린 주소), 설정을 포함한다.

## 지킬 것

- `%USERPROFILE%\.kakaowork-notify\config.json`을 읽거나 출력하지 않는다. 웹훅 주소가 들어 있다. 상태는 `notify.py status`로 보고, 설정은 `notify.py set`으로 바꾼다.
- 이 묶음은 웹훅만 쓴다. 카카오워크 봇 키(App Key)를 넣거나 받지 않는다.
- 훅 명령에 따옴표를 넣지 않고, 설치된 경로를 바꾸지 않는다. Antigravity는 따옴표를 글자 그대로 넘겨 명령이 깨진다. 그래서 설치 도구는 띄어쓰기 없는 경로(필요하면 8.3 짧은 이름)를 쓴다.
- 훅 설정 파일은 설치 도구로만 고친다. 다른 훅은 건드리지 않는다.
- 알림 장치를 고칠 일이 있으면 이 묶음의 `notify.py`를 고치고 `python install.py --runtime-only`로 반영한다. `%USERPROFILE%\.kakaowork-notify\notify.py`를 직접 고치면 다음 설치 때 덮어써진다.
