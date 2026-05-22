"""
AWI-integrated MiniWob agent.

Pipeline per agent step:
  1. Inject AWI_protocol.js into the live Playwright page via page.evaluate().
     — Standard pass: tags <a>, <button>, <input> with [AWI: clickable=True]
     — BrowserGym SOM pass: tags all [browsergym_set_of_marks=1] elements
       (covers MiniWob's <span class="alink"> words that have no ARIA roles).
       Embeds the BrowserGym `bid` number into the AWI tag so the LLM can
       report it back for reliable env.step() execution.
  2. page.accessibility.snapshot(interesting_only=True) → format as YAML text.
  3. OpenAI API (JSON mode) → structured action with optional bid.
  4. Execute: prefer env.step("click(bid)") via BrowserGym; fall back to
     Playwright aria-label selector + env.step("noop()").
  5. Reward / terminated / truncated come from env.step() in step 4.
"""

import os
import re
import json
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
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
TASK_ID   = "browsergym/miniwob.click-tab-2-medium"   # ← CHANGE: 태스크 변경
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

# ── AWI injection JS ──────────────────────────────────────────────────────────
# Executed via page.evaluate() before each observation extraction.
# Uses var/for-loop syntax (ES5-compatible, avoids template-literal escaping).
_AWI_JS = """
(function () {
    var inViewport = function(el) {
        var r = el.getBoundingClientRect();
        return r.top >= 0 && r.left >= 0
            && r.bottom <= (window.innerHeight || document.documentElement.clientHeight)
            && r.right  <= (window.innerWidth  || document.documentElement.clientWidth);
    };

    // ── Pass 1: Pruning ────────────────────────────────────────────────────
    // Mark off-viewport elements aria-hidden so they are excluded from
    // page.accessibility.snapshot(). Reduces observation noise.
    var allEls = document.querySelectorAll(
        'button,a,input,textarea,select,div,span,[role="button"]'
    );
    for (var i = 0; i < allEls.length; i++) {
        if (!inViewport(allEls[i])) allEls[i].setAttribute('aria-hidden', 'true');
    }

    // ── Pass 2: Standard augmentation ─────────────────────────────────────
    // Inject AWI metadata into aria-label of visible standard interactive elements.
    var stdEls = document.querySelectorAll(
        'a:not([aria-hidden]),button:not([aria-hidden]),'
        + 'input:not([aria-hidden]),[onclick]:not([aria-hidden])'
    );
    for (var j = 0; j < stdEls.length; j++) {
        var el = stdEls[j];
        var tag = el.tagName.toLowerCase();
        var meta = '[AWI: tag=' + tag + ', clickable=True';
        if (tag === 'input' && el.type) meta += ', input_type=' + el.type;
        meta += ']';
        if (el.hasAttribute('onclick') && tag !== 'button' && tag !== 'a')
            el.setAttribute('role', 'button');
        var base = (el.getAttribute('aria-label') || el.innerText || el.value || '')
            .replace(/\\n/g, ' ').trim();
        el.setAttribute('aria-label', (base + ' ' + meta).trim());
    }

    // ── Pass 3: BrowserGym SOM augmentation ───────────────────────────────
    // BrowserGym marks interactive elements (including MiniWob's <span class="alink">
    // word-links) with browsergym_set_of_marks="1" and a `bid` attribute.
    // These elements have no ARIA role by default, so they are invisible to
    // page.accessibility.snapshot(). We promote them to role="button" and
    // embed the bid in the AWI tag so the LLM can extract it for env.step().
    var somEls = document.querySelectorAll('[browsergym_set_of_marks="1"]:not([aria-hidden])');
    for (var k = 0; k < somEls.length; k++) {
        var el2 = somEls[k];
        // Skip if already augmented by Pass 2
        if (el2.getAttribute('aria-label') && el2.getAttribute('aria-label').indexOf('[AWI:') !== -1)
            continue;
        var tag2 = el2.tagName.toLowerCase();
        var bid  = el2.getAttribute('bid') || '';
        el2.setAttribute('role', 'button');
        var base2 = (el2.getAttribute('aria-label') || el2.innerText || '').replace(/\\n/g,' ').trim();
        var meta2 = '[AWI: tag=' + tag2 + ', clickable=True' + (bid ? ', bid=' + bid : '') + ']';
        el2.setAttribute('aria-label', (base2 + ' ' + meta2).trim());
    }

    // ── Pass 4: Virtual scroll button ─────────────────────────────────────
    // Exposes page scrolling as an explicit named action (action_id=999 sentinel).
    if (!document.querySelector('[data-awi-next]')) {
        var btn = document.createElement('button');
        btn.setAttribute('aria-label', 'Next Page [AWI: action_id=999, scroll_down]');
        btn.setAttribute('data-awi-next', '1');
        btn.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:9999;'
                          + 'padding:4px 8px;font-size:11px;opacity:.7;';
        btn.textContent = 'Scroll';
        document.body.appendChild(btn);
    }
})();
"""

# ── System prompt ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """
# Instructions
Review the current state of the page and all other information to find the best possible next action to accomplish your goal.

## Goal:
{goal}

# Observation of current step:
{snapshot}

## AWI Snapshot Guide (Modified from Baseline):
Note: You are viewing an Augmented Web Interaction (AWI) snapshot. 
Elements tagged with [AWI: ..., clickable=True] are interactive. 
If an [AWI: ...] tag contains a `bid=N` (e.g., [AWI: tag=span, clickable=True, bid=27]), this `N` is the unique BrowserGym element ID. 
Always use this `bid` number inside your action functions (e.g., click('27')). 
If you see [AWI: action_id=999, scroll_down], use the scroll(0, 300) action.

# Action space:
noop(wait_ms: float = 1000)
scroll(delta_x: float, delta_y: float)
fill(bid: str, value: str, enable_autocomplete_menu: bool = False)
select_option(bid: str, options: str | list[str])
click(bid: str, button: Literal['left', 'middle', 'right'] = 'left', modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])
dblclick(bid: str, button: Literal['left', 'middle', 'right'] = 'left', modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])
hover(bid: str)
press(bid: str, key_comb: str)
focus(bid: str)
clear(bid: str)
drag_and_drop(from_bid: str, to_bid: str)
upload_file(bid: str, file: str | list[str])
Only a single action can be provided at once. Example:
fill('b534', 'Montre', True)


# Abstract Example
Here is an abstract version of the answer with description of the content of
each tag. Make sure you follow this structure, but replace the content with your
answer:

<think>
Think step by step. If you need to make calculations such as coordinates, write them here. Describe the effect
that your previous action had on the current content of the page.
</think>

<action>
One single action to be executed. You can only use one action at a time.
</action>


# Concrete Example

Here is a concrete example of how to format your answer.
Make sure to follow the template with proper tags:

<think>
From previous action I tried to set the value of year to "2022",
using select_option, but it doesn't appear to be in the form. It may be a
dynamic dropdown, I will try using click with the bid "a324" and look at the
response from the page.
</think>

<action>
click('a324')
</action>

"""


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


def _inject_and_snapshot(page) -> str:
    """Inject AWI protocol into the DOM and return formatted accessibility snapshot."""
    page.evaluate(_AWI_JS)
    tree = page.accessibility.snapshot(interesting_only=True)
    if tree is None:
        return "(accessibility snapshot unavailable)"
    return _format_a11y_tree(tree)


def _call_llm(client: OpenAI, goal: str, history: list, snapshot: str) -> dict:
    """Call OpenAI and return the parsed JSON action dict."""
    history_text = (
        "\n".join(f"  {i+1}. {h}" for i, h in enumerate(history))
        if history else "  (none)"
    )
    user_msg = (
        f"Goal: {goal}\n\n"
        f"Action History:\n{history_text}\n\n"
        f"Current Page Snapshot:\n{snapshot}\n\n"
        "Respond with JSON only."
    )
    resp = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.0,
    )
    u    = resp.usage
    cost = u.prompt_tokens * 0.15e-6 + u.completion_tokens * 0.6e-6
    log.info(
        f"📊 Tokens in: {u.prompt_tokens} | out: {u.completion_tokens} | "
        f"cost: ${cost:.6f} | snapshot chars: {len(snapshot)}"
    )
    result = json.loads(resp.choices[0].message.content)
    if "action" not in result:
        result["action"] = "done"
    return result


def _step(env, page, act: dict) -> tuple:
    """Execute one action and return (obs, reward, terminated, truncated, info, description)."""
    atype = act.get("action", "done")
    bid   = re.sub(r"\D", "", str(act.get("bid") or ""))
    value = (act.get("value") or "").strip()
    label = (act.get("label") or "").strip()
    clean = re.sub(r"\[AWI:[^\]]*\]", "", label).strip()

    if atype == "done":
        obs, r, term, trunc, info = env.step("noop()")
        return obs, r, term, trunc, info, "DONE"

    if atype in ("scroll_down", "scroll_up") or "action_id=999" in label:
        delta = -300 if atype == "scroll_up" else 300
        page.evaluate(f"window.scrollBy(0, {delta})")
        obs, r, term, trunc, info = env.step("noop()")
        return obs, r, term, trunc, info, "SCROLL_" + ("DOWN" if delta > 0 else "UP")

    desc = f"{atype.upper()} bid={bid or '?'} '{clean}'"

    bg_map = {
        "click":  f"click('{bid}')",
        "fill":   f"fill('{bid}', {json.dumps(value)})",
        "select": f"select_option('{bid}', {json.dumps(value)})",
        "press":  f"press('{bid}', '{value or label}')",
    }
    bg_action = bg_map.get(atype)

    if not bid or not bg_action:
        log.warning(f"No bid for action '{atype}' (label='{clean}') — skipping")
        obs, r, term, trunc, info = env.step("noop()")
        return obs, r, term, trunc, info, f"SKIP(no_bid,{atype})"

    obs, r, term, trunc, info = env.step(bg_action)
    log.info(f"✅ {bg_action}")
    return obs, r, term, trunc, info, desc


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

goal = str(obs.get("goal") or obs.get("goal_object") or "(no goal)")
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
    log.info(f"🤖 Action JSON: {act}")
    slog.info(f"🧠 Think: {act.get('think', '')}")
    slog.info(f"🤖 Action: {act}")

    # ── 4 & 5: Execute + get reward/done ─────────────────────────────────────
    obs, reward, terminated, truncated, info, desc = _step(env, page, act)
    action_history.append(desc)
    final_reward = reward
    log.info(f"💰 Reward: {reward:.3f} | terminated: {terminated} | truncated: {truncated}")
    slog.info(f"✅ Executed: {desc}  |  reward={reward:.3f}")

    if terminated or truncated or act.get("action") == "done":
        result = "✅ SUCCESS" if reward > 0 else "❌ FAIL"
        log.info(f"\n{result}  reward={reward:.3f}  steps={step}")
        slog.info(f"\n{result}  reward={reward:.3f}  steps={step}")
        break

env.close()
log.info(f"\n{'='*60}")
log.info(f"📊 Final reward: {final_reward:.3f}  |  Steps: {step}")
log.info(f"📝 Full log:   {log_path}")
log.info(f"📋 Short log:  {short_log_path}")
