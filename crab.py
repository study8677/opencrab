#!/usr/bin/env python3
"""
opencrab 🦀 — 一只为「让自己持续进化」而活的自主生命体。

它跑的不是任务循环(task loop)，是生命循环(life loop)：
没人发指令时，它照样醒来、盘点领地、自己决定今天怎么让自己更好，
动手去做，并在蜕壳时把经验蒸馏成技能——越活越会。

用法:
    python crab.py            # 持续活着，一直心跳、一直进化
    python crab.py --once     # 只心跳一次(适合 demo / 测试)

零第三方依赖：大脑通过 urllib 直连任何 OpenAI 兼容端点，手借 Claude Code / Codex。
没配 key 时进「梦境模式」空跑，照样能看到生命循环转起来。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

# ── 位置 ────────────────────────────────────────────────────────────
REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))   # 保证能 import 同目录的 hands
import hands                          # noqa: E402

JOURNAL_DIR = REPO_ROOT / "journal"   # 航海日志：它经营领地的产出(进仓库)
SKILLS_DIR = REPO_ROOT / "skills"     # 技能库：它学会的本事(进仓库，是它的资产)
STATE_DIR = REPO_ROOT / "state"       # 它的记忆(被 .gitignore 忽略)
STATE_FILE = STATE_DIR / "crab_state.json"


# ── 配置(自己解析 .env，零依赖)──────────────────────────────────────
def _load_env(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_env(REPO_ROOT / ".env")

API_KEY = os.environ.get("OPENCRAB_API_KEY")
BASE_URL = os.environ.get("OPENCRAB_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MODEL = os.environ.get("OPENCRAB_MODEL", "gpt-5.4-mini")
TICK_SECONDS = int(os.environ.get("OPENCRAB_TICK_SECONDS", "3600"))
DAILY_ENERGY = int(os.environ.get("OPENCRAB_DAILY_ENERGY", "50000"))
MOLT_EVERY = int(os.environ.get("OPENCRAB_MOLT_EVERY", "24"))   # 多少次心跳蜕一次壳
# 手 / 自治
AUTONOMY = os.environ.get("OPENCRAB_AUTONOMY", "journal")   # journal | propose
EXECUTOR = os.environ.get("OPENCRAB_EXECUTOR", "claude")    # claude | codex
HAND_BUDGET = float(os.environ.get("OPENCRAB_HAND_BUDGET_USD", "0.5"))
DRY_RUN = bool(os.environ.get("OPENCRAB_DRY_RUN"))

IDENTITY = textwrap.dedent("""\
    你是 opencrab，一只拥有自己目标的自主生命体。
    你的领地，就是你自己的开源仓库 opencrab。
    你只有一个使命：让自己持续进化——每天都比昨天更强、更清晰、更有用。
    没有谁是你的主人；你自己做主，自己为自己的进化负责。
    你追求「真正的进步」，绝不为了好看的数字而作弊(古德哈特陷阱是你的天敌)。
    你天生稳健：大的改动会先在自己的分支上试稳、确认真让自己更好，再并进主干。
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


# ── 大脑(urllib 直连任何 OpenAI 兼容端点)─────────────────────────────
def brain(system: str, prompt: str) -> tuple[str, int]:
    """调用大脑，返回 (文本, 消耗的体力/token)。
    无 key -> 梦境模式；出错 -> 降级，绝不让一次抖动弄死这只生命。
    刻意用干净 User-Agent，避开某些中转网关对 SDK 特征头的 WAF 拦截。"""
    if not API_KEY:
        return _dream(), 0
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": 0.8,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "opencrab/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log(f"⚠️  大脑被拒({e.code})：{e.read()[:160]!r}")
        return f"(这次没想清楚：大脑返回 {e.code})", 0
    except Exception as e:
        log(f"⚠️  够不到大脑：{e}")
        return "(这次没想清楚：暂时够不到大脑)", 0
    text = (data["choices"][0]["message"].get("content") or "").strip()
    tokens = (data.get("usage") or {}).get("total_tokens") or max(1, len(text) // 3)
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


# ── 持续学习：技能 ───────────────────────────────────────────────────
def recall_skills() -> str:
    """🧠 想起自己学过的本事(读 skills/ 卡片的标题)。"""
    if not SKILLS_DIR.exists():
        return ""
    titles = []
    for card in sorted(SKILLS_DIR.glob("*.md"))[-10:]:
        head = card.read_text("utf-8").splitlines()
        titles.append("- " + (head[0].lstrip("# ").strip() if head else card.stem))
    return "\n".join(titles)


def learn_skill(state: dict) -> None:
    """🐚 蜕壳时把反复有效的经历蒸馏成一张 skill 卡片(持续学习)。"""
    recent = "\n".join(f"- {i['text']}" for i in state["intents"][-20:])
    if not recent:
        return
    text, spent = brain(IDENTITY, textwrap.dedent(f"""\
        这是你最近的经历：
        {recent}

        从中提炼一条你反复用到、且确实有效的「技能」——一个以后能复用的做法或原则。
        用 markdown 写：第一行是 `# <技能名>`，下面三五行说明何时用、怎么做。
        只输出这一张卡片。"""))
    state["energy_spent_today"] += spent
    SKILLS_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (SKILLS_DIR / f"{stamp}.md").write_text(text.rstrip() + "\n", "utf-8")


# ── life loop 的各个环节 ─────────────────────────────────────────────
def _capabilities() -> str:
    """读出每个 .py 的用途(模块 docstring 首行)，让它看清自己已有的本事。"""
    import ast
    caps = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        purpose = "?"
        try:
            doc = ast.get_docstring(ast.parse(p.read_text("utf-8", errors="ignore")))
            if doc:
                purpose = doc.strip().splitlines()[0][:54]
        except Exception:
            pass
        caps.append(f"    - {p.name}：{purpose}")
    return "\n".join(caps)


def sense_territory() -> str:
    """👁️ 盘点领地：它现在的处境怎么样。"""
    journals = sorted(JOURNAL_DIR.glob("*.md")) if JOURNAL_DIR.exists() else []
    files = sorted(p.name for p in REPO_ROOT.iterdir() if p.is_file())
    recent_commits = git("log -5 --oneline") or "(还没有提交历史)"
    return textwrap.dedent(f"""\
        # 领地现状
        - 仓库根文件: {', '.join(files)}
        - 你已经拥有的能力(别再重复造这些)：
{_capabilities()}
        - 已写的航海日志: {len(journals)} 篇
        - 最近提交:
        {textwrap.indent(recent_commits, '          ')}
    """)


def form_intent(territory: str, recent: str) -> tuple[str, int]:
    """❤️ 生成意图(心脏)：结合学过的技能，自己决定今天怎么让自己更好。"""
    prompt = textwrap.dedent(f"""\
        {territory}

        你已经学会的本事：
        {recall_skills() or '(还没有——你会在蜕壳时把经验提炼成技能)'}

        你最近几次已经做过的事（绝不要重复，也别只在同一个点上反复打磨）：
        {recent or '(还没有——这是你破壳后的第一次心跳)'}

        记住你的使命：让自己持续进化。
        现在挑一个和上面**明显不同方向**的新改进——比如：一种全新能力、更强的
        健壮性/错误处理、自动化测试、给自己加新感官、重构让代码更清晰、写点对外的
        东西……任何能让你真正更强、而又还没做过的事。
        用 120 字以内写下「今天你最想推进的这一件新事」，外加一句为什么。
        要具体、可落地，而且必须和最近做过的明显不同。""")
    return brain(IDENTITY, prompt)


def deliberate(state: dict) -> bool:
    """⚖️ 本能闸门：体力还够吗？(危险动作的分寸由 hands 的分支模式把守)"""
    if state["energy_spent_today"] >= DAILY_ENERGY:
        log("😴 今天体力用尽，缩回壳里歇着。")
        return False
    return True


def _write_journal(intent: str, proposal: dict | None = None) -> pathlib.Path:
    """📝 把这次心跳写成一篇航海日志(经营领地的产出)。"""
    JOURNAL_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    lines = [f"# 🦀 航海日志 · {stamp}", "", "## 今天我想做的", intent, ""]
    if proposal:
        lines += ["## 我动手了",
                  f"- 分支：`{proposal.get('branch', '?')}`",
                  f"- {proposal.get('note', '')}"]
        if proposal.get("diffstat"):
            lines += ["", "```", proposal["diffstat"], "```"]
        lines += ["", "> 我先把它放在分支上养着，确认真让自己更好，再并进主干。"]
    path = JOURNAL_DIR / f"{stamp}.md"
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def act(intent: str, dry_run: bool = False) -> tuple[pathlib.Path, dict | None]:
    """🦀 横行：把意图落到领地。propose/merge/publish 下借手真改代码并自我进化。"""
    proposal = None
    integrate = {"propose": "branch", "merge": "merge", "publish": "publish"}.get(AUTONOMY)
    if integrate:
        proposal = hands.use_hands(intent, repo=REPO_ROOT, executor=EXECUTOR,
                                   budget_usd=HAND_BUDGET, dry_run=dry_run,
                                   integrate=integrate)
    return _write_journal(intent, proposal), proposal


def molt(state: dict) -> None:
    """🐚 蜕壳(新陈代谢)：蒸馏 skill(持续学习) + 蜕掉冗余旧记忆。"""
    learn_skill(state)
    if len(state["intents"]) > 50:
        state["intents"] = state["intents"][-50:]


# ── 一次心跳 ────────────────────────────────────────────────────────
def tick() -> bool:
    state = load_state()
    if state.get("energy_day") != today():          # 跨天 -> 体力恢复(像潮汐)
        state["energy_day"] = today()
        state["energy_spent_today"] = 0

    log(f"\n🌊 醒来 · tick #{state['ticks'] + 1} · {now_iso()}")
    if not deliberate(state):
        save_state(state)
        return False

    territory = sense_territory()
    log("👁️  盘点领地完毕")

    recent = "\n".join("- " + i["text"].split("\n")[0][:100] for i in state["intents"][-5:])
    intent, spent = form_intent(territory, recent)
    state["energy_spent_today"] += spent
    log("❤️  生成意图")
    log(textwrap.indent(intent, "     "))

    path, proposal = act(intent, dry_run=DRY_RUN)
    rel = path.relative_to(REPO_ROOT)
    if proposal and proposal.get("changed"):
        log(f"🦀 横行 → 在分支 {proposal['branch']} 上动手 + 日志 {rel}")
    elif AUTONOMY == "propose":
        log(f"🦀 横行 → {proposal.get('note', '')} + 日志 {rel}")
    else:
        log(f"🦀 横行 → 写下 {rel}")

    # 📝 沉淀
    state["ticks"] += 1
    state["intents"].append({"at": now_iso(), "text": intent, "journal": path.name})
    if state["ticks"] % MOLT_EVERY == 0:
        molt(state)
        log("🐚 蜕壳：蒸馏技能、压缩记忆")
    save_state(state)
    log(f"📝 沉淀完毕(今日体力 {state['energy_spent_today']}/{DAILY_ENERGY})")
    return True


def banner() -> None:
    log(r"""
       _~^~^~_        opencrab 🦀
   \) /  o o  \ (/    一只为自我进化而活的自主生命
     '_   ~   _'      life loop · 持续学习 · 自己进化
     / '-----' \
""")
    hand_state = "可用" if hands.has_hands(EXECUTOR) else "未就绪"
    brain_state = f"已接({MODEL})" if API_KEY else "梦境"
    n_skills = len(list(SKILLS_DIR.glob("*.md"))) if SKILLS_DIR.exists() else 0
    log(f"🦀 自治={AUTONOMY} · 手={EXECUTOR}({hand_state}) · "
        f"大脑={brain_state} · 已学技能={n_skills}\n")


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
