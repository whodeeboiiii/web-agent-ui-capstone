# BrowserGym + AgentLab 환경 설정 가이드

> Notion 붙여넣기용 가이드입니다.  
> AgentLab은 **Python 3.12**에서만 정상 동작합니다.

---

## 1. 가상환경 생성

### 방법 A — Conda (권장)

```bash
conda create -n browser_agent python=3.12
conda activate browser_agent
```

### 방법 B — venv

```bash
python3.12 -m venv browser_agent
source browser_agent/bin/activate   # macOS / Linux
# browser_agent\Scripts\activate   # Windows
```

---

## 2. 패키지 설치

```bash
# BrowserGym 코어 및 AgentLab 설치
pip install browsergym agentlab

# Playwright 브라우저 드라이버 설치 (Chromium)
playwright install chromium

# .env 파일 로딩용 라이브러리
pip install python-dotenv
```

---

## 3. OpenAI API 키 설정

프로젝트 폴더 안에 `.env` 파일을 생성하고 아래 내용을 입력합니다.

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **주의**: `.env` 파일은 절대 GitHub에 커밋하지 마세요. `.gitignore`에 추가하세요.

---

## 4. 에이전트 코드 작성 (`main.py`)

```python
import os
from dotenv import load_dotenv
from copy import deepcopy

load_dotenv()  # .env에서 OPENAI_API_KEY 로드

import gymnasium as gym
import browsergym.core
from agentlab.agents.generic_agent.agent_configs import AGENT_4o  # 또는 AGENT_4o_MINI

# ── 에이전트 설정 ───────────────────────────────────────────────
agent_args = deepcopy(AGENT_4o)
agent_args.flags.enable_chat = True  # goal 모드 경고 방지
agent = agent_args.make_agent()

# ── 환경 생성 ────────────────────────────────────────────────────
env = gym.make(
    "browsergym/openended",
    disable_env_checker=True,  # gymnasium의 render_mode 자동 주입 방지
    headless=False,            # True로 바꾸면 창 없이 백그라운드 실행
    task_kwargs={
        "start_url": "https://www.amazon.com/",
        "goal": "가장 저렴한 녹색 티셔츠를 찾아 장바구니에 담아줘.",
    }
)

# ── 실행 루프 ─────────────────────────────────────────────────────
obs, info = env.reset()
step = 0

while True:
    step += 1
    print(f"\n{'='*50}\n  STEP {step}  |  URL: {obs.get('url', '?')}\n{'='*50}")

    if hasattr(agent, 'obs_preprocessor'):
        obs = agent.obs_preprocessor(obs)

    action, agent_info = agent.get_action(obs)

    if agent_info.think:
        print(f"🧠 Think:\n{agent_info.think}")
    print(f"🤖 Action:\n{action}")
    print(f"📊 Stats: {agent_info.stats}")

    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        print(f"\n✅ 완료! reward={reward}")
        break

env.close()
```

---

## 5. 실행

```bash
conda activate browser_agent   # 또는 source browser_agent/bin/activate
python main.py
```

실행하면 **Chromium 브라우저 창**이 열리고, 에이전트가 자동으로 웹을 탐색합니다.  
터미널에서는 각 스텝마다 에이전트의 생각(Think), 액션, 토큰 사용량이 출력됩니다.

---

## 6. 주요 에러 해결

| 에러 메시지 | 원인 | 해결 방법 |
|---|---|---|
| `ModuleNotFoundError: No module named 'agentlab'` | 가상환경이 활성화되지 않음 | `conda activate browser_agent` 실행 |
| `OpenAIError: The api_key client option must be set` | API 키 미설정 | `.env` 파일에 `OPENAI_API_KEY` 추가 |
| `BrowserEnv.__init__() got an unexpected keyword argument 'render_mode'` | Gymnasium 버전 문제 | `gym.make()`에 `disable_env_checker=True` 추가 |
| `OpenEndedTask.__init__() got an unexpected keyword argument 'headless'` | `headless`를 `task_kwargs` 안에 넣음 | `headless=False`를 `gym.make()`의 최상위 인자로 이동 |
| `AttributeError: 'ChatModel' object has no attribute 'make_model'` | `ChatModel`을 직접 `GenericAgent`에 전달 | `AGENT_4o.make_agent()`처럼 미리 정의된 설정 사용 |
| `429 Too Many Requests` | API 요금제 한도 초과 | 잠시 대기하거나 `AGENT_4o_MINI`로 교체하여 비용 절감 |

---

## 7. 사용 가능한 에이전트 모델

`agent_configs.py`에 미리 정의된 설정 목록:

| 변수명 | 모델 | 비고 |
|---|---|---|
| `AGENT_4o_MINI` | `gpt-4o-mini` | 빠르고 저렴 (권장) |
| `AGENT_4o` | `gpt-4o` | 고성능 |
| `AGENT_4o_VISION` | `gpt-4o` + 스크린샷 | 화면을 직접 보는 멀티모달 모드 |
| `AGENT_CLAUDE_SONNET_35` | Claude 3.5 Sonnet | Anthropic 키 필요 |

모델을 바꾸려면 import 줄과 `deepcopy()` 인자만 교체하면 됩니다:

```python
from agentlab.agents.generic_agent.agent_configs import AGENT_4o_MINI
agent_args = deepcopy(AGENT_4o_MINI)
```
