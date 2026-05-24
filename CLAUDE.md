# Project Overview: Web UI for AI Agents

이 프로젝트는 웹 에이전트(LLM)가 웹페이지를 탐색할 때 겪는 SVI(Spatial/Visual Interaction) 병목 현상(예: 스크롤, 숨겨진 요소, 복잡한 폼 입력 등)을 해결하기 위한 **AWI(Augmented Web Interaction) 프로토콜**을 검증하는 연구입니다. 
우리는 BrowserGym 환경(MiniWoB 태스크)에서 Playwright의 `page` 객체를 인터셉트하여, 에이전트에게 전달되는 관측 공간(Observation Space)을 조작하고 최적화합니다.

## 📂 Directory & Environment Context
* **`AWI_protocol.js`**: 우리가 설계한 핵심 프로토콜 로직. Playwright 환경에서 DOM을 조작하여 화면 밖 요소를 자르고(Pruning), 핵심 요소에 메타데이터(`[AWI: ...]`)를 주입하며, 스크롤을 우회하는 가상 버튼을 생성합니다.
* **`main.py` / `miniwob_tasks.py`**: 에이전트 실행 루프가 구현될 메인 파이썬 스크립트.
* **`.env`**: `OPENAI_API_KEY`가 저장되어 있습니다.
* **프레임워크**: BrowserGym (MiniWoB 벤치마크), Playwright, OpenAI API (gpt-4o-mini).

## 🎯 Core Mission for Claude Code
당신의 임무는 파이썬(Python) 환경에서 다음 4단계의 에이전트 루프를 완벽하게 구현하는 것입니다:

1. **Environment Hooking**: `browsergym`을 이용해 MiniWoB 환경을 초기화하고, 내부에서 구동되는 Playwright `page` 객체를 추출하세요.
2. **Observation Interception**: 매 스텝마다 에이전트에게 상태를 전달하기 **직전**에, `AWI_protocol.js`의 로직을 `page.evaluate()`를 통해 브라우저에 주입(Injection)하세요.
3. **State Extraction**: 조작이 완료된 상태에서 `page.ariaSnapshot()`을 호출하여, 토큰이 극도로 최적화된 YAML 형태의 관측치(Observation)를 추출하세요.
4. **LLM Execution & Action Mapping**: 추출한 스냅숏을 OpenAI API에 전달하여 다음 행동(Action)을 결정하게 하고, LLM의 텍스트 출력(예: `CLICK`, `FILL`)을 파싱하여 실제 Playwright 명령으로 웹페이지를 제어하세요.

## ⚠️ Strict Rules & Coding Guidelines (반드시 준수할 것)

### 1. Memory Management (Context Bloat 방지)
* 에이전트의 프롬프트에 과거의 `ariaSnapshot` 데이터를 계속 누적해서는 **절대 안 됩니다.** * 과거의 관측치는 과감히 삭제(State Overwriting)하고, 오직 **"현재 뷰포트의 최신 AWI 스냅숏"**과 **"과거에 수행한 행동의 짧은 텍스트 요약(Action History)"**만을 유지하여 LLM에 전달하세요.

### 2. AWI Protocol Application
* `AWI_protocol.js` 파일의 내용을 파이썬 스크립트 내에서 읽어 들여 런타임에 주입하거나, 해당 로직을 파이썬 코드로 깔끔하게 포팅하여 사용하세요. 
* 목표는 MiniWoB의 고질적 문제(링크 클릭 불가, 스크롤 실패, 라디오 버튼 조작 실패, Date Picker 오인)를 해결하는 것입니다. `aria-label`에 `[AWI: clickable=True]` 등의 태그가 정상적으로 반영되는지 반드시 확인해야 합니다.

### 3. Action Parser 설계
* LLM이 뱉어내는 자유 양식의 텍스트를 Playwright 제어 코드로 변환하는 정규표현식 또는 구조화된 파서(JSON/함수 호출 등)를 견고하게 작성하세요.
* 가상 페이지네이션 버튼(`[AWI: action_id=999]`)을 클릭한다는 명령이 들어오면, 실제 물리적 클릭 대신 `window.scrollBy`를 실행하도록 분기 처리하세요.

### 4. Logging & Evaluation
* 각 Trajectory 스텝마다 소비된 토큰 수(Prompt/Completion)와 추출된 AWI 스냅숏의 길이를 로그로 남기세요.
* 태스크 성공/실패 여부를 판단하고, 결과를 터미널에 명확히 출력하세요.