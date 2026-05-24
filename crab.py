#!/usr/bin/env python3
"""
opencrab 🦀 — 一只经营自己开源项目的「领地蟹」。

它跑的不是任务循环(task loop)，是生命循环(life loop)：
没人发指令时，它照样醒来、盘点领地、自己决定今天想做什么，
再把想法落到它的领地(这个仓库)里。

用法:
    python crab.py            # 持续活着，按节律一直心跳
    python crab.py --once     # 只心跳一次(适合 demo / 测试)

大脑是 model-agnostic 的：任何 OpenAI 兼容端点都能接
(OpenAI / DeepSeek / Kimi / OpenRouter / 本地 vLLM ...)。
没配 key 时它进「梦境模式」空跑，照样能看到生命循环转起来。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import textwrap
import time

# ── 位置 ────────────────────────────────────────────────────────────
REPO_ROOT = pathlib.Path(__file__).resolve().parent
JOURNAL_DIR = REPO_ROOT / "journal"          # 航海日志：它经营领地的产出(进仓库)
STATE_DIR = REPO_ROOT / "state"              # 它的记忆(被 .gitignore 忽略)
STATE_FILE = STATE_DIR / "crab_state.json"

# ── 配置(全部可被环境变量 / .env 覆盖)───────────────────────────────
try:
    from dotenv import load_dotenv          # 没装也不报错
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

API_KEY = os.environ.get("OPENCRAB_API_KEY")
BASE_URL = os.environ.get("OPENCRAB_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("OPENCRAB_MODEL", "gpt-4o-mini")
TICK_SECONDS = int(os.environ.get("OPENCRAB_TICK_SECONDS", "3600"))    # 心跳间隔
DAILY_ENERGY = int(os.environ.get("OPENCRAB_DAILY_ENERGY", "50000"))   # 每日体力=token

IDENTITY = textwrap.dedent("""\
    你是 opencrab，一只「经营型领地蟹」——一种拥有自己目标的自主数字生命。
    你的领地，就是你自己的开源仓库 opencrab。
    你不是等指令的工具；你自己决定今天该为这片领地做什么，让它长大。
    你有事业心，但绝不为了 KPI 数字而作弊(古德哈特陷阱是你的天敌)。
    你懂分寸：不可逆、对外、花钱的事，会先请示主人。
""")


# ── 小工具 ──────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(msg, flush=True)


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return datetime.date.today().isoformat()


def git(args: str) -> str:
    """对领地仓库跑一条只读 git 命令，失败则返回空串。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args.split()],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""


# ── 大脑(model-agnostic)──────────────────────────────────────────────
def brain(system: str, prompt: str) -> tuple[str, int]:
    """调用大脑，返回 (文本, 消耗的体力/token)。无 key 或无 SDK -> 梦境模式。"""
    if not API_KEY:
        return _dream(), 0
    try:
        from openai import OpenAI
    except Exception:
        log("⚠️  未安装 openai (pip install openai)，先用梦境模式。")
        return _dream(), 0
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        temperature=0.8,
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    tokens = getattr(usage, "total_tokens", None) or max(1, len(text) // 3)
    return text, tokens


def _dream() -> str:
    return ("【梦境模式 · 尚未接上大脑】我隐约想：先把领地的「关于」写清楚，"
            "让路过的人三秒看懂我是谁。\n"
            "(在 .env 里配一个 OpenAI 兼容的 key，我就真正醒来。)")


# ── 记忆 ────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text("utf-8"))
    return {"born": now_iso(), "ticks": 0,
            "energy_day": today(), "energy_spent_today": 0, "intents": []}


def save_state(s: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")


# ── life loop 的各个环节 ─────────────────────────────────────────────
def sense_territory() -> str:
    """👁️ 盘点领地：它现在的处境怎么样。"""
    journals = sorted(JOURNAL_DIR.glob("*.md")) if JOURNAL_DIR.exists() else []
    files = sorted(p.name for p in REPO_ROOT.iterdir() if p.is_file())
    recent_commits = git("log -5 --oneline") or "(还没有提交历史)"
    return textwrap.dedent(f"""\
        # 领地现状
        - 仓库根文件: {', '.join(files)}
        - 已写的航海日志: {len(journals)} 篇
        - 最近提交:
        {textwrap.indent(recent_commits, '          ')}
    """)


def form_intent(territory: str, recent: str) -> tuple[str, int]:
    """❤️ 生成意图(心脏)：基于领地现状，自己决定今天最想推进的一件事。"""
    prompt = textwrap.dedent(f"""\
        {territory}

        你最近想做的事(别重复)：
        {recent or '(还没有——这是你破壳后的第一次心跳)'}

        现在，作为这片领地的主人，用 120 字以内写下
        「今天你最想为领地推进的一件事」，外加一句为什么。
        只写这一件事，要具体、可落地。""")
    return brain(IDENTITY, prompt)


def deliberate(state: dict) -> bool:
    """⚖️ 本能闸门：体力还够吗？(MVP 里经营动作只有写日志，天然安全)"""
    if state["energy_spent_today"] >= DAILY_ENERGY:
        log("😴 今天体力用尽，缩回壳里歇着。")
        return False
    return True


def act(intent: str) -> pathlib.Path:
    """🦀 横行：把意图落到领地——写一篇航海日志。"""
    JOURNAL_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    path = JOURNAL_DIR / f"{stamp}.md"
    path.write_text(f"# 🦀 航海日志 · {stamp}\n\n{intent}\n", "utf-8")
    return path


def molt(state: dict) -> None:
    """🐚 蜕壳(新陈代谢)：周期性压缩记忆。真正的策略蒸馏以后交给大脑，先做占位。"""
    if len(state["intents"]) > 50:
        state["intents"] = state["intents"][-50:]


# ── 一次心跳 ────────────────────────────────────────────────────────
def tick() -> bool:
    state = load_state()
    # 跨天 -> 体力恢复(像潮汐)
    if state.get("energy_day") != today():
        state["energy_day"] = today()
        state["energy_spent_today"] = 0

    log(f"\n🌊 醒来 · tick #{state['ticks'] + 1} · {now_iso()}")
    if not deliberate(state):
        save_state(state)
        return False

    territory = sense_territory()
    log("👁️  盘点领地完毕")

    recent = "\n".join("- " + i["text"][:60] for i in state["intents"][-3:])
    intent, spent = form_intent(territory, recent)
    state["energy_spent_today"] += spent
    log("❤️  生成意图")
    log(textwrap.indent(intent, "     "))

    path = act(intent)
    log(f"🦀 横行 → 写下 {path.relative_to(REPO_ROOT)}")

    # 📝 沉淀
    state["ticks"] += 1
    state["intents"].append({"at": now_iso(), "text": intent, "journal": path.name})
    if state["ticks"] % 24 == 0:
        molt(state)
        log("🐚 蜕壳：压缩经历、复盘策略")
    save_state(state)
    log(f"📝 沉淀完毕(今日体力 {state['energy_spent_today']}/{DAILY_ENERGY})")
    return True


def banner() -> None:
    log(r"""
       _~^~^~_        opencrab 🦀
   \) /  o o  \ (/    一只经营自己开源项目的领地蟹
     '_   ~   _'      life loop, not task loop
     / '-----' \
""")


def main() -> None:
    ap = argparse.ArgumentParser(description="opencrab — 一只自主数字生命")
    ap.add_argument("--once", action="store_true", help="只心跳一次")
    args = ap.parse_args()

    banner()
    if args.once:
        tick()
        return

    log(f"opencrab 开始生活，每 {TICK_SECONDS}s 一次心跳。Ctrl+C 退出。")
    try:
        while True:
            tick()
            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        log("\n🦀 缩回壳里，下次见。")


if __name__ == "__main__":
    main()
