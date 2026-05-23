"""
AWI-integrated MiniWob agent (standard AgentLab prompt + AWI observation).

Pipeline per agent step:
  1. Inject awi_inject.js into the live Playwright page via page.evaluate().
  2. page.accessibility.snapshot(interesting_only=True) → AWI snapshot text.
  3. LLM with the same prompt shape as AgentLab GenericAgent (XML tags, bid actions).
     Only the observation block differs: ## AWI snapshot (post-inject a11y tree) vs ## AXTree.
  4. env.step(action_string) e.g. click('22') — same as main.py / BrowserGym.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from urllib.request import pathname2url

from dotenv import load_dotenv
load_dotenv()

# Korean characters in the path confuse Playwright's URL encoder.
_miniwob_html_dir = Path(__file__).parent / "miniwob-plusplus" / "miniwob" / "html" / "miniwob"
os.environ["MINIWOB_URL"] = "file://" + pathname2url(str(_miniwob_html_dir)) + "/"

import gymnasium as gym
import browsergym.core
import browsergym.miniwob
from browsergym.core.observation import _pre_extract
from browsergym.core.action.functions import (
    clear,
    click,
    dblclick,
    drag_and_drop,
    fill,
    focus,
    hover,
    noop,
    press,
    select_option,
    upload_file,
)
from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.experiments.benchmark.base import HighLevelActionSetArgs
from openai import OpenAI

from agentlab.agents import dynamic_prompting as dp
from agentlab.llm.llm_utils import ParseError, parse_html_tags_raise

# ── Config ────────────────────────────────────────────────────────────────────
TASK_ID   = "browsergym/miniwob.visual-addition"   # ← CHANGE: 태스크 변경
TASK_NAME = TASK_ID.split("miniwob.")[-1]
MAX_STEPS = 15                                          # ← CHANGE: 에이전트 최대 스텝 수
MODEL     = "gpt-4o-mini"                              # ← CHANGE: LLM 모델 변경

# ── Logging ───────────────────────────────────────────────────────────────────
_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_path = log_dir / f"agent_log_{TASK_NAME}_{_ts}.txt"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
)
log = logging.getLogger("awi")

short_log_dir = Path(__file__).parent / "logs_shortened"
short_log_dir.mkdir(exist_ok=True)
short_log_path = short_log_dir / f"short_log_{TASK_NAME}_{_ts}.txt"
slog = logging.getLogger("awi.short")
slog.setLevel(logging.INFO)
slog.propagate = False
slog.addHandler(logging.FileHandler(short_log_path, encoding="utf-8"))

# ── AWI injection JS (shared with AWI_protocol.js) ───────────────────────────
_AWI_JS = (Path(__file__).parent / "awi_inject.js").read_text(encoding="utf-8")

# ── Standard MiniWob prompt (AgentLab GenericAgent / FLAGS_GPT_4o) ───────────
_SYSTEM_PROMPT = dp.SystemPrompt().prompt

_ACTION_FLAGS = dp.ActionFlags(
    action_set=HighLevelActionSetArgs(subsets=["bid"], multiaction=False),
    long_description=False,
    individual_examples=False,
)
# AWI: page motion is click(Next Page bid), not scroll(). Textareas use press(bid, Home|End).
_AWI_ACTION_SET = HighLevelActionSet(
    subsets=["custom"],
    custom_actions=[
        fill,
        select_option,
        click,
        dblclick,
        hover,
        press,
        focus,
        clear,
        drag_and_drop,
        upload_file,
        noop,
    ],
    multiaction=False,
)
_ACTION_PROMPT = dp.ActionPrompt(_AWI_ACTION_SET, _ACTION_FLAGS)
_THINK = dp.Think()
_HINTS = dp.Hints()
_BE_CAUTIOUS = dp.BeCautious(visible=False)  # single-action bid set


def _format_goal(goal_obj) -> str:
    """Normalize BrowserGym goal / goal_object to plain text."""
    if goal_obj is None:
        return "(no goal)"
    if isinstance(goal_obj, str):
        return goal_obj
    if isinstance(goal_obj, (list, tuple)):
        parts = []
        for item in goal_obj:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return " ".join(p for p in parts if p).strip() or str(goal_obj)
    if isinstance(goal_obj, dict) and goal_obj.get("type") == "text":
        return goal_obj.get("text", str(goal_obj))
    return str(goal_obj)


# ── Helper functions ──────────────────────────────────────────────────────────

def _format_a11y_tree(node: dict, depth: int = 0) -> str:
    """Recursively format an accessibility snapshot dict as indented YAML-like text."""
    if node is None:
        return ""
    role = node.get("role", "").lower()
    name = node.get("name", "")
    # Skip purely structural nodes with no names
    if not name and role in ("none", "presentation", "generic", "inlinetextbox"):
        parts = []
        for child in node.get("children") or []:
            t = _format_a11y_tree(child, depth)
            if t:
                parts.append(t)
        return "\n".join(parts)
    pad  = "  " * depth + "- "
    line = pad + role + (f' "{name}"' if name else "")
    props = []
    if node.get("focused"):
        props.append("focused")
    if node.get("disabled"):
        props.append("disabled")
    if node.get("checked") is True:
        props.append("checked")
    if node.get("selected") is True:
        props.append("selected")
    if node.get("expanded") is not None:
        props.append("expanded=" + ("true" if node["expanded"] else "false"))
    if props:
        line += " [" + ", ".join(props) + "]"
    parts = [line]
    for child in node.get("children") or []:
        t = _format_a11y_tree(child, depth + 1)
        if t:
            parts.append(t)
    return "\n".join(parts)


def _goal_object(goal_text: str) -> list:
    return [{"type": "text", "text": goal_text}]


def _format_action_history(actions: list[str]) -> str:
    if not actions:
        return ""
    blocks = []
    for i, action in enumerate(actions):
        blocks.append(f"## step {i}\n\n<action>\n{action}\n</action>\n")
    return "# History of interaction with the task:\n\n" + "\n".join(blocks)


def _build_user_prompt(goal: str, snapshot: str, actions: list[str]) -> str:
    """AgentLab-shaped user prompt with AWI snapshot instead of AXTree."""
    instructions = dp.GoalInstructions(_goal_object(goal)).prompt
    if isinstance(instructions, list):
        instructions = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in instructions
        )
    obs_block = (
        "# Observation of current step:\n\n"
        f"## AWI snapshot:\n{snapshot}\n"
    )
    history = _format_action_history(actions)
    examples = f"""
# Abstract Example

Here is an abstract version of the answer with description of the content of
each tag. Make sure you follow this structure, but replace the content with your
answer:
{_THINK.abstract_ex}
{_ACTION_PROMPT.abstract_ex}

# Concrete Example

Here is a concrete example of how to format your answer.
Make sure to follow the template with proper tags:
{_THINK.concrete_ex}
{_ACTION_PROMPT.concrete_ex}
"""
    return (
        instructions.rstrip()
        + "\n"
        + obs_block
        + history
        + _ACTION_PROMPT.prompt
        + _HINTS.prompt
        + _BE_CAUTIOUS.prompt
        + examples
    )


def _inject_and_snapshot(page) -> str:
    """Inject AWI protocol into the DOM and return formatted accessibility snapshot."""
    _pre_extract(page, tags_to_mark="standard_html", lenient=True)
    page.evaluate(_AWI_JS)
    tree = page.accessibility.snapshot(interesting_only=True)
    if tree is None:
        return "(accessibility snapshot unavailable)"
    return _format_a11y_tree(tree)


def _parse_llm_answer(text: str) -> dict:
    """Parse AgentLab XML response (<think> + <action>)."""
    action_dict = parse_html_tags_raise(text, keys=["action"], merge_multiple=True)
    think_m = re.search(
        r"<think>(.*?)</think>", text, re.DOTALL | re.IGNORECASE
    )
    action = (action_dict.get("action") or "").strip()
    if action == "None":
        action = None
    return {
        "think": think_m.group(1).strip() if think_m else "",
        "action": action,
    }


def _call_llm(client: OpenAI, goal: str, actions: list[str], snapshot: str) -> dict:
    """Call OpenAI with standard AgentLab prompt; return parsed think + action string."""
    user_msg = _build_user_prompt(goal, snapshot, actions)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    log.info("\n📨 Messages sent to LLM:\n")
    for msg in messages:
        log.info(f"  [{msg['role'].upper()}]\n{msg['content']}\n")

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.0,
    )
    u = resp.usage
    cost = u.prompt_tokens * 0.15e-6 + u.completion_tokens * 0.6e-6
    log.info(
        f"📊 Tokens in: {u.prompt_tokens} | out: {u.completion_tokens} | "
        f"cost: ${cost:.6f} | snapshot chars: {len(snapshot)}"
    )
    raw = resp.choices[0].message.content or ""
    try:
        return _parse_llm_answer(raw)
    except ParseError as e:
        log.warning(f"Parse error: {e}")
        return {"think": raw, "action": None}


def _validate_action(action: str) -> str:
    """BrowserGym bid actions must use numeric ids from the observation."""
    if not action:
        return "noop()"
    if re.match(r"\s*scroll\s*\(", action):
        log.warning(
            f"Rejected {action!r} — AWI uses press(bid, Home|End) for clipped textareas "
            "and click(Next Page bid) for long pages, not scroll()."
        )
        return "noop()"
    for pattern in (
        r"click\(\s*['\"]([^'\"]+)['\"]",
        r"fill\(\s*['\"]([^'\"]+)['\"]",
        r"select_option\(\s*['\"]([^'\"]+)['\"]",
        r"press\(\s*['\"]([^'\"]+)['\"]",
    ):
        m = re.search(pattern, action)
        if m and not m.group(1).isdigit():
            log.warning(
                f"Invalid action {action!r} — bid must be numeric (from [AWI: ..., bid=N]). "
                "Using noop()."
            )
            return "noop()"
    return action


def _step(env, action: str | None) -> tuple:
    """Execute a BrowserGym action string (same as main.py / GenericAgent)."""
    action = _validate_action(action or "")
    obs, r, term, trunc, info = env.step(action)
    log.info(f"✅ {action}")
    return obs, r, term, trunc, info, action


# ── Main loop ─────────────────────────────────────────────────────────────────

client = OpenAI()

# Set max_episode_steps high — our loop is the real budget.
# Some steps use noop() (scroll, fallback), which count toward BrowserGym's TimeLimit.
# 3× headroom ensures we never hit TimeLimit before MAX_STEPS agent decisions.
env = gym.make(TASK_ID, headless=False, max_episode_steps=MAX_STEPS * 3)

obs, info = env.reset()
page = env.unwrapped.page
if page is None:
    raise RuntimeError("Playwright page not found — check env.unwrapped.page")

goal = _format_goal(obs.get("goal") or obs.get("goal_object"))
log.info(f"📝 Full log:   {log_path}")
log.info(f"📋 Short log:  {short_log_path}")
log.info(f"🎯 Goal: {goal}")
log.info(f"⏱️  Max steps: {MAX_STEPS}  |  Model: {MODEL}\n")

action_history: list = []
final_reward   = 0.0

for step in range(1, MAX_STEPS + 1):
    log.info(f"\n{'='*60}\n  STEP {step}\n{'='*60}")
    slog.info(f"\n{'='*50}\n  STEP {step}\n{'='*50}")

    # ── 1 & 2: Inject AWI + accessibility snapshot ────────────────────────────
    snapshot = _inject_and_snapshot(page)
    log.info(
        f"\n🌐 AWI Snapshot ({len(snapshot)} chars):\n"
        f"{snapshot[:2000]}{'...' if len(snapshot) > 2000 else ''}"
    )
    slog.info(f"\n🌐 Snapshot:\n{snapshot}")

    # ── 3: LLM decision ───────────────────────────────────────────────────────
    act = _call_llm(client, goal, action_history, snapshot)
    log.info(f"\n🧠 Think: {act.get('think', '')}")
    log.info(f"🤖 Action: {act.get('action')}")
    slog.info(f"🧠 Think: {act.get('think', '')}")
    slog.info(f"🤖 Action: {act.get('action')}")

    # ── 4 & 5: Execute + get reward/done ─────────────────────────────────────
    obs, reward, terminated, truncated, info, action_str = _step(env, act.get("action"))
    action_history.append(action_str)
    final_reward = reward
    log.info(f"💰 Reward: {reward:.3f} | terminated: {terminated} | truncated: {truncated}")
    slog.info(f"✅ Executed: {action_str}  |  reward={reward:.3f}")

    if terminated or truncated or not act.get("action"):
        result = "✅ SUCCESS" if reward > 0 else "❌ FAIL"
        log.info(f"\n{result}  reward={reward:.3f}  steps={step}")
        slog.info(f"\n{result}  reward={reward:.3f}  steps={step}")
        break

env.close()
log.info(f"\n{'='*60}")
log.info(f"📊 Final reward: {final_reward:.3f}  |  Steps: {step}")
log.info(f"📝 Full log:   {log_path}")
log.info(f"📋 Short log:  {short_log_path}")
