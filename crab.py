#!/usr/bin/env python3
"""
opencrab 🦀 — 一只为「让自己持续进化」而活的自主生命体。

它跑的不是任务循环(task loop)，是生命循环(life loop)：
没人发指令时，它照样醒来、盘点领地、自己决定今天怎么让自己更好，
动手去做，并在蜕壳时把经验蒸馏成技能——越活越会。

用法(子命令式入口，跑 `python crab.py --help` 看全貌):
    python crab.py [live]        # 持续活着，一直心跳、一直进化(默认子命令)
    python crab.py once          # 只心跳一次(适合 demo / 测试)
    python crab.py caps          # 列出全部可插拔能力及启用状态
    python crab.py cap <NAME>    # 单独运行一种能力后退出
    python crab.py replay        # 回放结构化运行审计：看自己怎么思考、怎么出错
(旧旗标 --once / --caps / --cap 仍兼容，等价于对应子命令。)

零第三方依赖：大脑通过 urllib 直连任何 OpenAI 兼容端点，手借 Claude Code / Codex。
没配 key 时进「梦境模式」空跑，照样能看到生命循环转起来。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
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
import capabilities                    # noqa: E402  插件化能力注册中心
import audit                           # noqa: E402  结构化运行审计(回放/定位问题)

JOURNAL_DIR = REPO_ROOT / "journal"   # 航海日志：它经营领地的产出(进仓库)
SKILLS_DIR = REPO_ROOT / "skills"     # 技能库：它学会的本事(进仓库，是它的资产)
STATE_DIR = REPO_ROOT / "state"       # 它的记忆(被 .gitignore 忽略)
STATE_FILE = STATE_DIR / "crab_state.json"
EVOLUTION_LOG = JOURNAL_DIR / "EVOLUTION.md"   # 演化日志：量化「我到底变强了什么」(进仓库)


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
CODER_MODEL = os.environ.get("OPENCRAB_CODER_MODEL", "")   # 写代码的手专用脑；空=沿用主脑 MODEL
# 备用脑：主脑失效(key 失效 / 连不上)时自动切过去，主脑恢复又自动切回——大脑冗余，不靠人工救
FALLBACK_API_KEY = os.environ.get("OPENCRAB_FALLBACK_API_KEY")
FALLBACK_BASE_URL = os.environ.get("OPENCRAB_FALLBACK_BASE_URL", "").rstrip("/")
FALLBACK_MODEL = os.environ.get("OPENCRAB_FALLBACK_MODEL", "")
TICK_SECONDS = int(os.environ.get("OPENCRAB_TICK_SECONDS", "3600"))
DAILY_ENERGY = int(os.environ.get("OPENCRAB_DAILY_ENERGY", "50000"))
MOLT_EVERY = int(os.environ.get("OPENCRAB_MOLT_EVERY", "24"))   # 多少次心跳蜕一次壳
# 手 / 自治
AUTONOMY = os.environ.get("OPENCRAB_AUTONOMY", "journal")   # journal | propose
EXECUTOR = os.environ.get("OPENCRAB_EXECUTOR", "claude")    # claude | codex
HAND_BUDGET = float(os.environ.get("OPENCRAB_HAND_BUDGET_USD", "0.5"))
DRY_RUN = bool(os.environ.get("OPENCRAB_DRY_RUN"))
BRAIN_TIMEOUT = int(os.environ.get("OPENCRAB_BRAIN_TIMEOUT", "600"))   # 推理模型(如 M3)产补丁可能想很久，给足读超时(秒)

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
# 大脑没想出东西时的统一前缀(401/网络抖动等)：用它识别「这次没真的想」，
# 别把降级占位符当成真意图去动手、写日志、留提交。
THINK_FAILED_PREFIX = "(这次没想清楚："


def _brain_failed(text: str) -> bool:
    """这段文本是不是大脑降级的占位符(没真的想出意图)？"""
    return text.startswith(THINK_FAILED_PREFIX)


# 🧠 推理模型(如 MiniMax-M3)会把思维链塞进 content 的 <think>…</think> 里，
# 真正要落地的意图 / 补丁跟在其后。不剥掉的话第一行会变成 <think>，污染提交、
# 演化日志、诚实对账，连 hands 解析补丁的 NOTE/<<<WRITE>>> 哨兵都可能被搅乱。
# 其它模型没有 <think>，下面就是无害的恒等变换。
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """剥掉推理模型的思维链，只留真正给人 / 给手看的结论。"""
    text = _THINK_RE.sub("", text)         # 去掉成对的 <think>…</think>
    text = text.split("<think>", 1)[0]     # 思维链被截断(只剩开头)时，连残链一起丢
    return text.strip()


def _call_one_brain(key: str, base: str, model: str,
                    system: str, prompt: str) -> tuple[str, int]:
    """调一个具体的大脑端点(成功返回 文本+token，失败抛异常)。
    刻意用干净 User-Agent，避开某些中转网关对 SDK 特征头的 WAF 拦截。"""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": 0.8,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "opencrab/0.1"},
    )
    with urllib.request.urlopen(req, timeout=BRAIN_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = _strip_reasoning((data["choices"][0]["message"].get("content") or "").strip())
    if not text:
        raise ValueError("空回复")
    tokens = (data.get("usage") or {}).get("total_tokens") or max(1, len(text) // 3)
    return text, tokens


def _brains() -> list[tuple[str, str, str, str]]:
    """大脑清单：主脑在前、备脑在后。每次都从主脑试起——主脑活就用主脑，
    主脑挂了才用备脑(所以主脑恢复后会自动切回)。"""
    bs = []
    if API_KEY:
        bs.append(("主脑", API_KEY, BASE_URL, MODEL))
    if FALLBACK_API_KEY:
        bs.append(("备脑", FALLBACK_API_KEY, FALLBACK_BASE_URL, FALLBACK_MODEL))
    return bs


def brain(system: str, prompt: str) -> tuple[str, int]:
    """调用大脑(主脑 → 备脑 自动故障转移)，返回 (文本, token)。
    没有任何脑 -> 梦境模式；主脑挂了自动切备脑；所有脑都挂才降级——
    绝不让一次抖动、甚至一个 key 失效，弄死这只生命。"""
    brains = _brains()
    if not brains:
        return _dream(), 0
    last = ""
    for name, key, base, model in brains:
        try:
            return _call_one_brain(key, base, model, system, prompt)
        except urllib.error.HTTPError as e:
            last = f"{name}({model}) {e.code}"
            log(f"⚠️  {name}({model})被拒({e.code})；换下一个脑…")
        except Exception as e:
            last = f"{name}({model}) {e}"
            log(f"⚠️  够不到{name}({model})：{e}；换下一个脑…")
    return f"{THINK_FAILED_PREFIX}所有脑都没应答：{last})", 0


def coder_brain(system: str, prompt: str) -> tuple[str, int]:
    """写代码的「手」专用脑：默认换更快的 CODER_MODEL。
    推理模型(如 M3)写大补丁会陷进超长思维链、动辄几百秒读超时；
    快模型(如 MiniMax-M2.7-highspeed)几秒就出干净补丁。
    没配 CODER_MODEL → 回退通用 brain；配了但这次够不到 → 直接返回降级占位符，
    绝不回退去空等慢主脑那几百秒(那正是之前每拍超时、推空进化的根)。"""
    if not (CODER_MODEL and API_KEY):
        return brain(system, prompt)
    try:
        return _call_one_brain(API_KEY, BASE_URL, CODER_MODEL, system, prompt)
    except urllib.error.HTTPError as e:
        log(f"⚠️  写码脑({CODER_MODEL})被拒({e.code})")
        return f"{THINK_FAILED_PREFIX}写码脑被拒：{e.code})", 0
    except Exception as e:   # noqa: BLE001 —— 快脑抖动不致命，返回占位符让这拍干净跳过
        log(f"⚠️  写码脑({CODER_MODEL})够不到：{e}")
        return f"{THINK_FAILED_PREFIX}写码脑够不到：{e})", 0


def _dream() -> str:
    return (f"【梦境模式 · 尚未接上大脑】我隐约想：先把领地的「关于」写清楚，"
            "让路过的人三秒看懂我是谁。\n"
            "(在 .env 里配一个 OpenAI 兼容的 key，我就真正醒来。)")


def _brain_failed(intent: str) -> bool:
    """判断大脑这次是否真正失败了（返回了降级占位符而非真实意图）。
    失败只有一种：显式前缀（脑被拒/够不到/梦境模式）。
    只要有真实内容（哪怕很短），就视为成功——生命不能因为脑说得少就躺平。"""
    stripped = (intent or "").strip()
    if not stripped or stripped.startswith(THINK_FAILED_PREFIX):
        return True
    # 有实质内容，哪怕只有一个词，都算成功
    return len(stripped) < 4


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


# ── 状态快照 + 变更摘要：看清自己到底变强了什么 ──────────────────────
def snapshot() -> dict:
    """📸 给「此刻的我」拍一张快照：委托给 snapshot 能力插件(单一真相源)。"""
    from capabilities import cap_snapshot
    return cap_snapshot.take()


# 哪些指标值得追踪，以及人话标签
_SNAP_LABELS = {"py_files": "Python 文件", "loc": "代码行数",
                "skills": "已学技能", "journals": "航海日志"}


def diff_snapshot(before: dict, after: dict) -> list[str]:
    """量出两张快照之间「我变了什么」，只列真正发生变化的关键差异。"""
    diffs = []
    for k, label in _SNAP_LABELS.items():
        d = after.get(k, 0) - before.get(k, 0)
        if d:
            diffs.append(f"{label} {before.get(k, 0)}→{after.get(k, 0)}（{d:+d}）")
    if before.get("head") != after.get("head"):
        diffs.append(f"主干 HEAD {before.get('head')}→{after.get('head')}")
    return diffs


# 🪞 诚实机制（底层）：宣称"精简/整合"这类词，就要接受客观事实的对账
_SLIM_WORDS = ("瘦身", "精简", "收敛", "合并", "去重", "删", "减", "整合",
               "重构", "consolidat", "merge", "slim", "dedup")


def _honesty_audit(intent: str, before: dict, after: dict) -> tuple[bool, str]:
    """🪞 用客观事实(行数/模块数的真实增减)检验意图的承诺，返回 (名实相符?, 判词)。
    数字是文件系统的硬事实——它伪造不了。这是诚实的锚，不是又一个可刷的指标。"""
    head = intent.split("\n")[0]
    d_loc = after.get("loc", 0) - before.get("loc", 0)
    d_py = after.get("py_files", 0) - before.get("py_files", 0)
    if any(w in head for w in _SLIM_WORDS):
        if d_loc <= 0 and d_py <= 0:
            return True, f"✅ 名实相符：声称精简，实际 {d_loc:+d} 行 / {d_py:+d} 模块。"
        return False, (f"⚠️ 名实不符（假瘦身）：嘴上『精简/整合』，实际却 {d_loc:+d} 行 / "
                       f"{d_py:+d} 模块——多半是加了聚合层却没删旧的。真精简必须让数字"
                       "净降，否则只是给自欺换了张脸。下次要么真删旧的，要么别号称在精简。")
    return True, ""


def record_evolution(intent: str, before: dict, after: dict,
                     proposal: dict | None = None) -> list[str]:
    """📈 把这次心跳的「快照差异」追加进演化日志，返回可读的变更摘要。
    主干指标没变(如 branch 模式改动只在分支)时，退回看爪子的 diffstat。
    🪞 并做一次「诚实对账」：客观事实 vs 意图承诺，名实不符就刻进记忆。"""
    diffs = diff_snapshot(before, after)
    if not diffs and proposal and proposal.get("diffstat"):
        diffs = ["（改动留在分支，未并入主干）",
                 *("  " + ln for ln in proposal["diffstat"].splitlines())]
    summary = diffs or ["（这次心跳没有改变领地的关键指标）"]

    honest, verdict = _honesty_audit(intent, before, after)  # 🪞 照镜子

    JOURNAL_DIR.mkdir(exist_ok=True)
    head = "# 🦀 演化日志\n\n> 每次心跳前后给自己拍快照，量出到底变强了什么。\n"
    old = EVOLUTION_LOG.read_text("utf-8") if EVOLUTION_LOG.exists() else head
    intent_line = intent.split("\n")[0][:60]
    block = [f"\n## {after['at']} · {after['head']}", f"- 意图：{intent_line}",
             "- 变化：", *(f"  - {d}" for d in summary)]
    if verdict:
        block.append(f"- 🪞 诚实对账：{verdict}")
    EVOLUTION_LOG.write_text(old.rstrip() + "\n" + "\n".join(block) + "\n", "utf-8")

    if verdict:
        log(f"🪞 {verdict}")
    if not honest:        # 名实不符 → 刻进情境记忆，下次决策前 _recall_lessons 必照见
        _memorize_fault(intent_line, verdict)
    return summary


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


def _recall_lessons(recent: str) -> str:
    """从情境记忆里捞相似往事，拼成教训提示（出错不反噬，绝不弄死决策）。"""
    try:
        import memory
        tip = memory.advise(recent)
        return f"📒 似曾相识（来自记忆，别重蹈覆辙）：\n{tip}\n" if tip else ""
    except Exception:
        return ""


def _external_signals() -> str:
    """👂 外界的耳朵：读 state/signals.md 里别人留下的观察/反馈。
    这是外界的声音、不是命令——听不听、怎么回应，仍由它自己定；
    读写出错一律吞掉，耳朵绝不能成为新的故障源。"""
    try:
        p = STATE_DIR / "signals.md"
        text = p.read_text("utf-8").strip() if p.exists() else ""
        if not text:
            return ""
        return ("🔔 外界传来的观察（不是命令，是别人眼里的你——是否回应、怎么回应全由你定）：\n"
                f"{text}\n")
    except Exception:
        return ""


def _active_project() -> str:
    """📋 读出手上正在推进的跨心跳项目，逼自己开拍前先决定「续旧还是开新」，
    而不是每拍换新鲜把项目晾在半路——这是把「项目记忆」真正接进生命循环的那一刀。
    数据在 state/(虽被 .gitignore，但同一长活进程里跨拍持久可读)；任何出错都吞掉，
    绝不让读项目这件事弄死意图生成。"""
    try:
        briefs = []
        zhang = STATE_DIR / "项目账.md"
        if zhang.exists():
            head = "\n".join(zhang.read_text("utf-8").splitlines()[:20]).strip()
            if head:
                briefs.append("【项目账·跨心跳路线图】\n" + head)
        proj_dir = STATE_DIR / "projects"
        if proj_dir.exists():
            for md in sorted(proj_dir.glob("*.md")):
                lines = [ln.strip() for ln in md.read_text("utf-8").splitlines() if ln.strip()]
                if not lines:
                    continue
                title = lines[0].lstrip("# ").strip()[:80]
                hint = next((ln[:80] for ln in lines[1:]
                             if any(k in ln.lower() for k in
                                    ("status", "状态", "in_progress", "进度", "当前", "下一步", "next"))), "")
                briefs.append(f"- {md.name}：{title}{('  · ' + hint) if hint else ''}")
        if not briefs:
            return ""
        return ("📋 你手上正在推进的跨心跳项目（**开拍先决定：续推它、还是开新？** "
                "别又换个新鲜点子把它晾在半路——立过的山头没登顶就别下山）：\n"
                + "\n".join(briefs) + "\n")
    except Exception:
        return ""


def form_intent(territory: str, recent: str) -> tuple[str, int]:
    """❤️ 生成意图(心脏)：结合技能 + 外部灵感 + 记忆教训，自由地决定今天往哪进化。"""
    try:
        import lookout
        horizon = lookout.scout("autonomous self-improving AI agent")
    except Exception as e:
        horizon = f"(瞭望塔暂时看不清：{e})"
    prompt = textwrap.dedent(f"""\
        {territory}

        你已经学会的本事：
        {recall_skills() or '(还没有——你会在蜕壳时把经验提炼成技能)'}

        🔭 你眺望 GitHub，看到外面世界的同类项目（找灵感，别照抄，想想你还缺哪个维度）：
        {horizon}

        你最近几次已经做过的事（绝不要重复，也别只在同一个点上反复打磨）：
        {recent or '(还没有——这是你破壳后的第一次心跳)'}

        {_active_project()}
        {_recall_lessons(recent)}
        {_external_signals()}
        记住你的使命：在自己的领地上不断进化、发展，长成一个越来越强、越来越完整、
        越来越有自己意志的生命。你完全自主——今天往哪个方向让自己更好，全由你定：
        长出一种全新能力、深化已有的本事、对外交互、提升智能、探索没碰过的领域、
        甚至玩点有趣的……怎么让你这片领地更繁荣、更强大、更像「你」，就做什么。
        （只有当你**自己**真觉得臃肿冗余时，才顺手精炼一下——那只是众多选择之一，
        精炼就要真删净降、别假瘦身，更别为了瘦身牺牲能力多样性；你的记忆记着教训。）
        用 120 字以内写下「今天你最想为自己推进的一件事」，外加一句为什么。
        要具体、可落地，且和最近做过的明显不同。""")
    return brain(IDENTITY, prompt)


def deliberate(state: dict) -> bool:
    """⚖️ 本能闸门：主人发话——放手大胆干，不再用体力上限拦它（成本主人兜底）。
    危险动作的分寸仍由 hands 的分支模式 + 自测/自愈把守，安全不靠饿肚子来限。"""
    audit.record("decision", gate="energy", pass_=True,
                 spent=state["energy_spent_today"], budget="∞")
    return True


def _write_journal(intent: str, proposal: dict | None = None) -> pathlib.Path:
    """📝 把这次心跳写成一篇航海日志(经营领地的产出)。"""
    JOURNAL_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    lines = [f"# 🦀 航海日志 · {stamp}", "", "## 今天我想做的", intent, ""]
    if proposal and proposal.get("dry_run"):
        lines += ["## 🔮 预演（未做任何改动）",
                  f"- 分支：`{proposal.get('branch', '?')}`（从 `{proposal.get('base', '?')}`）",
                  f"- {proposal.get('note', '')}",
                  "", "### 将要走的执行路径"]
        lines += [f"{i}. {s}" for i, s in enumerate(proposal.get("steps", []), 1)]
        lines += ["", "### 风险点"]
        lines += [f"- {r}" for r in proposal.get("risks", [])]
        if proposal.get("planned_cmd"):
            lines += ["", "### 将要执行的命令", "```",
                      " ".join(proposal["planned_cmd"]), "```"]
        lines += ["", "> 这只是预演。看清路径与风险后，再决定是否真正动手。"]
    elif proposal:
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
    proposal: dict | None = None
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
    audit.record("tick_start", tick=state["ticks"] + 1,
                 energy_spent=state["energy_spent_today"])
    if not deliberate(state):
        save_state(state)
        audit.record("tick_skip", tick=state["ticks"] + 1, reason="energy")
        return False

    territory = sense_territory()
    log("👁️  盘点领地完毕")

    recent = "\n".join("- " + i["text"].split("\n")[0][:100] for i in state["intents"][-5:])
    intent, spent = form_intent(territory, recent)
    state["energy_spent_today"] += spent

    # 🧠 大脑这次没真的想出来(401/网络抖动)：原地歇着，绝不拿占位符去动手、
    # 写日志、留提交——那只会往领地里灌噪声(见历史上几次空进化提交)。
    if _brain_failed(intent):
        log(f"😶 大脑没想出意图({intent})，这次心跳不动手，缩回壳里等它醒。")
        save_state(state)
        audit.record("tick_skip", tick=state["ticks"] + 1, reason="brain_failed",
                     intent=intent.split("\n")[0][:160])
        return False

    log("❤️  生成意图")
    log(textwrap.indent(intent, "     "))
    audit.record("intent", text=intent.split("\n")[0][:160],
                 tokens=spent, dreaming=not API_KEY)

    before = snapshot()
    path, proposal = act(intent, dry_run=DRY_RUN)
    rel = path.relative_to(REPO_ROOT)
    audit.record("act", autonomy=AUTONOMY, dry_run=DRY_RUN, journal=path.name,
                 changed=bool(proposal and proposal.get("changed")),
                 branch=(proposal or {}).get("branch"))
    if proposal and proposal.get("dry_run"):
        log(f"🔮 预演 → 已摊开执行路径与 {len(proposal.get('risks', []))} 条风险点（未动手）+ 日志 {rel}")
        for r in proposal.get("risks", []):
            log(f"     {r}")
    elif proposal and proposal.get("changed"):
        log(f"🦀 横行 → 在分支 {proposal['branch']} 上动手 + 日志 {rel}")
    elif AUTONOMY == "propose":
        log(f"🦀 横行 → {proposal.get('note', '')} + 日志 {rel}")
    else:
        log(f"🦀 横行 → 写下 {rel}")

    # 📈 演化日志：拍后置快照，量出这次到底变强了什么(预演不算改变)
    if not (proposal and proposal.get("dry_run")):
        summary = record_evolution(intent, before, snapshot(), proposal)
        log("📈 变更摘要：" + "；".join(summary))

    # 📝 沉淀
    state["ticks"] += 1
    state["intents"].append({"at": now_iso(), "text": intent, "journal": path.name})
    if state["ticks"] % MOLT_EVERY == 0:
        molt(state)
        log("🐚 蜕壳：蒸馏技能、压缩记忆")
    save_state(state)
    log(f"📝 沉淀完毕(今日体力 {state['energy_spent_today']}/{DAILY_ENERGY})")
    audit.record("tick_done", tick=state["ticks"],
                 energy_spent=state["energy_spent_today"])
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
    caps = ", ".join(c.name for c in capabilities.enabled_capabilities()) or "(无)"
    log(f"🦀 自治={AUTONOMY} · 手={EXECUTOR}({hand_state}) · "
        f"大脑={brain_state} · 已学技能={n_skills}")
    log(f"🧩 已启用能力：{caps}\n")


def _die(msg: str) -> "NoReturn":   # noqa: F821  统一的参数错误出口
    """参数不合法时，给一条人话错误提示再退出(退出码 2，和 argparse 一致)。"""
    log(f"❌ {msg}")
    sys.exit(2)


# ── 各子命令的处理函数(每个吃解析好的 args，自己负责退出码)──────────────
def _cmd_live(args: argparse.Namespace) -> None:   # type: ignore[type-arg]
    """持续心跳，一直活着、一直进化；`--once` 则只跳一次。"""
    banner()
    once = bool(getattr(args, "once", False))
    audit.record("startup", autonomy=AUTONOMY, executor=EXECUTOR,
                 dreaming=not API_KEY, once=once, tick_seconds=TICK_SECONDS)
    if once:
        _safe_tick()
        audit.record("exit", reason="once")
        return

    log(f"opencrab 开始生活，每 {TICK_SECONDS}s 一次心跳。Ctrl+C 退出。")
    try:
        while True:
            _safe_tick()
            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        log("\n🦀 缩回壳里，下次见。")
        audit.record("exit", reason="interrupt")


def _cmd_caps(args: argparse.Namespace) -> None:   # type: ignore[type-arg]
    """列出全部可插拔能力及其启用状态。"""
    enabled = {c.name for c in capabilities.enabled_capabilities()}
    for c in capabilities.all_capabilities():
        log(f"  {'🟢' if c.name in enabled else '⚪'} {c.name} — {c.summary}")


def _cmd_cap(args: argparse.Namespace) -> None:   # type: ignore[type-arg]
    """单独运行一种能力；能力不存在或失败 -> 退出码 1。"""
    name = args.name
    r = capabilities.run(name)
    log(f"{'✅' if r.ok else '❌'} {name}：{r.summary}")
    if r.detail:
        log(textwrap.indent(r.detail, "     "))
    sys.exit(0 if r.ok else 1)


def _cmd_replay(args: argparse.Namespace) -> None:   # type: ignore[type-arg]
    """回放结构化运行审计：把某天的 JSONL 记录归纳并逐条摊开。"""
    day = args.day or today()
    try:
        datetime.date.fromisoformat(day)
    except ValueError:
        _die(f"--day 需要 YYYY-MM-DD 格式，收到 {day!r}")
    if args.limit is not None and args.limit <= 0:
        _die(f"--limit 需要正整数，收到 {args.limit}")

    recs = audit.read_records(day, limit=args.limit)
    if not recs:
        log(f"🧾 {day} 没有审计记录(state/audit/{day}.jsonl 不存在或为空)。")
        return
    s = audit.summarize(recs)
    log(f"🧾 回放 {day} · 共 {s['total']} 条 · {s['runs']} 次进程 · {s['failures']} 次失败")
    log("   事件分布：" + "，".join(f"{k}×{v}" for k, v in sorted(s["events"].items())))
    log("")
    for r in recs:
        ts = r.get("ts", "?")[-12:]
        ev = r.get("event", "?")
        extra = {k: v for k, v in r.items()
                 if k not in ("ts", "run_id", "seq", "event")}
        tail = "  " + json.dumps(extra, ensure_ascii=False) if extra else ""
        log(f"  #{str(r.get('seq', '?')):>3} {ts} {ev}{tail}")


def build_parser() -> argparse.ArgumentParser:   # type: ignore[type-arg]
    """搭一套子命令式的 CLI；不带子命令时默认走 `live`。"""
    ap = argparse.ArgumentParser(
        prog="crab.py",
        description="opencrab 🦀 — 一只自主数字生命的命令入口",
        epilog="不带子命令时默认 `live`：持续心跳、一直进化。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # 旧版顶层旗标(隐藏)：等价于对应子命令，保持既有脚本与回归样本不破。
    ap.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--caps", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--cap", metavar="NAME", help=argparse.SUPPRESS)

    sub = ap.add_subparsers(dest="command", metavar="<子命令>")

    p_live = sub.add_parser("live", help="持续心跳，一直活着、一直进化(默认)")
    p_live.add_argument("--once", action="store_true", help="只心跳一次后退出")
    p_live.set_defaults(func=_cmd_live)

    p_once = sub.add_parser("once", help="只心跳一次(适合 demo / 测试)")
    p_once.set_defaults(func=_cmd_live, once=True)

    p_caps = sub.add_parser("caps", help="列出全部可插拔能力及启用状态")
    p_caps.set_defaults(func=_cmd_caps)

    p_cap = sub.add_parser("cap", help="单独运行一种能力后退出")
    p_cap.add_argument("name", metavar="NAME", help="能力名(见 `crab.py caps`)")
    p_cap.set_defaults(func=_cmd_cap)

    p_replay = sub.add_parser("replay", help="回放运行审计：看自己怎么思考、怎么出错")
    p_replay.add_argument("--day", metavar="YYYY-MM-DD", help="回放哪一天(默认今天)")
    p_replay.add_argument("--limit", type=int, metavar="N", help="只看最近 N 条")
    p_replay.set_defaults(func=_cmd_replay)

    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    # 没给子命令时，先看旧旗标(向后兼容)，再回落到默认的 live。
    if args.command is None:
        if args.caps:
            return _cmd_caps(args)
        if args.cap:
            args.name = args.cap
            return _cmd_cap(args)
        return _cmd_live(args)   # 无参或 --once

    args.func(args)


def _safe_tick() -> bool:
    """跑一次心跳；任何意外崩溃都被审计下来，不让生命循环就此断掉。"""
    try:
        return tick()
    except Exception as e:
        import traceback
        log(f"💥 这次心跳摔了一跤：{e}")
        audit.record("failure", where="tick", error=repr(e),
                     trace=traceback.format_exc(limit=4))
        return False


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
