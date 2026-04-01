import os
import logging
from datetime import datetime
from pathlib import Path
from urllib.request import pathname2url
from dotenv import load_dotenv

load_dotenv()  # .env에서 OPENAI_API_KEY 등 로드

# Korean characters in the path confuse Playwright's URL encoder.
_miniwob_html_dir = Path(__file__).parent / "miniwob-plusplus" / "miniwob" / "html" / "miniwob"
os.environ["MINIWOB_URL"] = "file://" + pathname2url(str(_miniwob_html_dir)) + "/"

import gymnasium as gym
import browsergym.core
import browsergym.miniwob
from agentlab.agents.generic_agent.agent_configs import AGENT_4o_MINI
from copy import deepcopy

# ── 태스크 설정 (로그 파일명에 사용) ──────────────────────────────
TASK_ID   = "browsergym/miniwob.form-sequence"   # ← CHANGE: 태스크를 바꾸려면 이 줄만 변경
TASK_NAME = TASK_ID.split("miniwob.")[-1]      # e.g. "copy-paste"
_ts = datetime.now().strftime('%Y%m%d_%H%M%S')

# ── 로깅 설정 ──────────────────────────────────────────────────
# 1) 전체 로그: logs/ 폴더
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_path = log_dir / f"agent_log_{TASK_NAME}_{_ts}.txt"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path, encoding="utf-8"),
    ],
)
log = logging.getLogger("agent")
log.info(f"📝 Logging to: {log_path}\n")

# 2) 요약 로그: logs_shortened/ 폴더 (스텝·생각·액션만 기록)
short_log_dir = Path(__file__).parent / "logs_shortened"
short_log_dir.mkdir(exist_ok=True)
short_log_path = short_log_dir / f"short_log_{TASK_NAME}_{_ts}.txt"
slog = logging.getLogger("agent.short")
slog.setLevel(logging.INFO)
slog.propagate = False   # 전체 로그로 전파하지 않음
slog.addHandler(logging.FileHandler(short_log_path, encoding="utf-8"))
log.info(f"📋 Shortened log: {short_log_path}\n")
# ───────────────────────────────────────────────────────────────

# 1. 모델 및 에이전트 설정
agent_args = deepcopy(AGENT_4o_MINI)     # gpt-4o-mini 사용 (CHANGE: 모델 변경하려면 이 줄 변경)
agent_args.flags.obs.use_html = True
agent_args.flags.obs.use_ax_tree = True      # HTML 대신 접근성 트리만 사용
agent_args.flags.max_ax_tree_depth = 10
agent_args.flags.add_clickable_area_to_ax_tree = True
agent_args.flags.obs.extract_visible_only = True
agent_args.flags.obs.use_screenshot = True
agent_args.flags.obs.use_som = True
agent = agent_args.make_agent()

# 2. MiniWoB 환경 생성
# max_episode_steps: Gymnasium의 TimeLimit 래퍼를 자동으로 적용합니다.
# N 스텝을 초과하면 env.step()이 truncated=True를 반환 → 루프 종료.
MAX_STEPS = 100  # ← CHANGE: 이 값을 조정하세요

env = gym.make(
    TASK_ID,
    headless=False,           # 에이전트가 움직이는 걸 눈으로 확인하세요!
    max_episode_steps=MAX_STEPS,  # TimeLimit 래퍼 적용
)

obs, info = env.reset()
log.info(f"🎯 Task Goal: {obs.get('goal_object', obs.get('goal', '(no goal)'))}\n")
log.info(f"⏱️  Max steps: {MAX_STEPS}\n")

step = 0
while True:
    step += 1
    # 안전장치: TimeLimit 래퍼가 누락되더라도 루프를 강제로 종료합니다.
    if step > MAX_STEPS:
        log.info(f"\n🛑 MAX_STEPS ({MAX_STEPS}) reached — forcing stop.")
        break
    log.info(f"\n{'='*60}")
    log.info(f"  STEP {step}")
    log.info(f"{'='*60}")

    # 현재 URL
    log.info(f"📍 URL: {obs.get('url', 'unknown')}")

    # 접근성 트리(AX Tree) — 에이전트가 실제로 보는 페이지 구조
    ax_tree = obs.get("axtree_txt", "")
    if ax_tree:
        preview = ax_tree[:1500]
        log.info(f"\n🌐 AX Tree (first 1500 chars):\n{preview}{'...' if len(ax_tree) > 1500 else ''}")

    # 관측값 전처리
    if hasattr(agent, 'obs_preprocessor'):
        obs = agent.obs_preprocessor(obs)

    # 에이전트 행동 결정
    action, agent_info = agent.get_action(obs)

    # ── THINK LOGGING ──────────────────────────────────────────
    log.info(f"\n{'─'*60}")

    # ── 요약 로그에 스텝·URL 기록
    slog.info(f"\n{'='*50}")
    slog.info(f"  STEP {step}")
    slog.info(f"{'='*50}")

    # 1) LLM에 보낸 메시지 전체 (system prompt + user prompt)
    if hasattr(agent_info, 'chat_messages') and agent_info.chat_messages:
        log.info("📨 Messages sent to LLM:")
        for msg in agent_info.chat_messages:
            role = msg.get('role', '?').upper()
            content = msg.get('content', '')
            if isinstance(content, list):   # multimodal → 텍스트만 추출
                content = "\n".join(
                    part.get('text', '')
                    for part in content
                    if isinstance(part, dict) and part.get('type') == 'text'
                )
            log.info(f"\n  [{role}]\n{content}")
        log.info(f"\n{'─'*60}")

    # 3) LLM 재시도 횟수 (파싱 실패 등으로 재요청한 경우)
    n_retry = agent_info.stats.get('n_retry_llm', 0)
    if n_retry:
        log.info(f"🧠⚠️  LLM retries this step: {n_retry}🧠")

    # ── 요약 로그: think + action만 저장
    think_text = agent_info.think or "(없음)"
    slog.info(f"🧠 Think:\n{think_text}")
    slog.info(f"\n🤖 Action:\n{action}")

    # 5) 토큰 & 비용
    stats = agent_info.stats
    log.info(
        f"\n📊 Stats — tokens in: {stats.get('input_tokens', '?')} | "
        f"out: {stats.get('output_tokens', '?')} | "
        f"cost: ${stats.get('cost', 0):.6f}"
    )
    log.info(f"{'─'*60}")
    # ── END THINK LOGGING ──────────────────────────────────────

    # 환경에 행동 전달
    obs, reward, terminated, truncated, info = env.step(action)

    if terminated or truncated:
        log.info(f"\n✅ Task finished! reward={reward}")
        log.info(f"📝 Full log saved to: {log_path}")
        break

env.close()
