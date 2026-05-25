#!/usr/bin/env python3
"""提交前的密钥/隐私哨卡 🔑🚧 —— 在 `git commit` 落地前最后一道门。

为什么要有它：opencrab 每天自改、自提交、自推送到**公开仓库**。supplychain 已经
做全树静态扫描，回答「整个仓库现在干不干净」；但自我进化真正会出事的瞬间，是**这一次
蜕壳新带进来的那几行**——一把刚粘进代码的 key、一段调试时贴的真实邮箱/IP。等它被
push 出去再发现，凭据已经泄了。secretscan 只盯一件事，且只盯**增量**：

  **本次 `git add` 进暂存区的改动里，有没有新引入密钥或隐私？有就别让它进 commit。**

和 supplychain 的分工：
  · supplychain = 全树体检，关心「边界整体守不守得住」(密钥+许可证+脚本+依赖)。
  · secretscan  = 提交闸门，只看 `git diff --cached` 的**新增行**，且对每一处给出
    「脱敏补丁」(把那行改成什么) 与「验证证据」(改完再扫确实干净)。

三件交付物，缺一不可：
  · 命中     —— 哪个文件第几行、哪类泄漏、脱敏后的证据(报隐患时绝不二次泄密)。
  · 脱敏补丁 —— 这一行应该改成什么(原样 → 建议)，可直接照抄。
  · 验证证据 —— 把补丁应用到内存中的暂存内容后重扫，确认归零，并打印前后对照。

用法:
    python secretscan.py                # 扫暂存区(git diff --cached)的新增行
    python secretscan.py --all          # 退而扫工作区全部跟踪文件(无暂存内容时)
    python secretscan.py --patch        # 命中时额外打印逐行脱敏补丁
    python secretscan.py --verify       # 模拟应用补丁并重扫，打印验证证据
    python secretscan.py --json         # 导出纯数据(给 health / 钩子消费)

退出码：0 = 暂存区干净，可以放行；1 = 发现泄漏，先脱敏再提交。零第三方依赖。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── 泄漏类型：密钥(凭据)与隐私(PII)分两档，密钥一律高危 ──────────────────
KIND_SECRET = "密钥"
KIND_PII = "隐私"

SEV_HIGH = "high"   # 计入退出码：真会把领地卖了
SEV_LOW = "low"     # 提醒：值得脱敏但未必阻断


@dataclasses.dataclass(frozen=True)
class Leak:
    """一处泄漏：哪类、多严重、文件第几行、脱敏证据、原始命中片段、一句修复建议。"""
    kind: str
    severity: str
    path: str
    line: int           # 暂存内容里的新行号(尽力而为)
    evidence: str       # 已脱敏，可安全打印
    raw_match: str      # 命中的原始子串(仅在内存里用于生成补丁，不落盘/不打印)
    hint: str

    def to_meta(self) -> dict:
        # 注意：raw_match 含真凭据，刻意不导出。
        return {"kind": self.kind, "severity": self.severity, "path": self.path,
                "line": self.line, "evidence": self.evidence, "hint": self.hint}


# ── 密钥：已知前缀 / 高熵明文凭据。收紧以压低误报。──────────────────────
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI/类前缀密钥", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Anthropic 密钥", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("私钥 PEM 块", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("硬编码凭据赋值", re.compile(
        r"""(?ix)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"""
        r"""['"]([^'"\s]{16,})['"]""")),
]

# ── 隐私：能定位到个人的明文。默认低危(脱敏即可)，但宁可多提醒。──────────
_PII_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (SEV_LOW, "邮箱地址", re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (SEV_LOW, "IPv4 地址", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    (SEV_HIGH, "中国大陆身份证号", re.compile(
        r"\b\d{17}[\dXx]\b")),
    (SEV_LOW, "中国大陆手机号", re.compile(
        r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    (SEV_HIGH, "疑似银行卡号", re.compile(
        r"\b(?:\d[ -]?){13,19}\b")),
]

# 占位符 / 示例值：命中即放过，别对 .env.example、文档示例误报。
_PLACEHOLDER_RE = re.compile(
    r"(?i)(your|example|placeholder|changeme|xxx+|\.\.\.|<[^>]+>|sk-\.\.\.|"
    r"dummy|fake|test|sample|here|todo|redacted|noreply|localhost|\$\{|"
    r"0\.0\.0\.0|127\.0\.0\.1|255\.255)")

# 文档/示例邮箱域名：example.com 等保留域不算泄漏。
_SAFE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "test.com")

# 只扫会被人读到内容的文本文件。
_TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
                  ".cfg", ".ini", ".sh", ".env", ".example", ".html", ".js"}


def _looks_like_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


def _redact(secret: str) -> str:
    """脱敏证据：只留头尾各 4 字符。报隐患不能自己再泄一次。"""
    s = secret.strip()
    if len(s) <= 12:
        return s[:2] + "…" + s[-2:] if len(s) > 4 else "…"
    return f"{s[:4]}…{s[-4:]}（共 {len(s)} 字符）"


def _luhn_ok(digits: str) -> bool:
    """Luhn 校验：银行卡/部分卡号才过，避免把普通长数字串误判成卡号。"""
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total, parity = 0, len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ── 逐行扫描：一行可能同时命中密钥与多种 PII ──────────────────────────
def _scan_line(path: str, lineno: int, raw: str) -> list[Leak]:
    leaks: list[Leak] = []
    for label, pat in _SECRET_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        captured = m.group(1) if m.groups() else m.group(0)
        if _looks_like_placeholder(captured) or _looks_like_placeholder(raw):
            continue
        leaks.append(Leak(
            KIND_SECRET, SEV_HIGH, path, lineno, f"{label}：{_redact(captured)}",
            captured,
            "立刻吊销该凭据并从历史清除，改读环境变量(.env 已被 .gitignore 拦在门外)"))

    for sev, label, pat in _PII_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        hit = m.group(0)
        if _looks_like_placeholder(hit) or _looks_like_placeholder(raw):
            continue
        if label == "邮箱地址" and any(hit.lower().endswith(d) for d in _SAFE_EMAIL_DOMAINS):
            continue
        if label == "疑似银行卡号" and not _luhn_ok(hit):
            continue   # 没过 Luhn 的长数字串不当卡号，否则误报版本号/时间戳
        leaks.append(Leak(
            KIND_PII, sev, path, lineno, f"{label}：{_redact(hit)}", hit,
            "改用占位符 / 脱敏样例，真实个人信息不该进公开仓"))
    return leaks


# ── 取材：默认只看暂存区的新增行(git diff --cached) ──────────────────
def _staged_added_lines() -> dict[str, list[tuple[int, str]]]:
    """解析 `git diff --cached -U0`，按文件收集**新增行**及其新行号。

    只看 `+` 行(真正被引入的内容)，从 `@@ ... +start,count @@` 头推算行号。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "diff", "--cached", "-U0",
             "--no-color", "--diff-filter=ACM"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return {}
    if out.returncode != 0:
        return {}

    files: dict[str, list[tuple[int, str]]] = {}
    cur: str | None = None
    new_lineno = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in out.stdout.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        m = hunk_re.match(line)
        if m:
            new_lineno = int(m.group(1))
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            files.setdefault(cur, []).append((new_lineno, line[1:]))
            new_lineno += 1
        elif not line.startswith("-"):
            new_lineno += 1
    return files


def _all_tracked_lines() -> dict[str, list[tuple[int, str]]]:
    """退路：没有暂存内容时(--all)，扫工作区全部跟踪的文本文件。"""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"],
                             capture_output=True, text=True, timeout=10)
        names = out.stdout.splitlines() if out.returncode == 0 else []
    except Exception:
        names = []
    files: dict[str, list[tuple[int, str]]] = {}
    for name in names:
        p = REPO_ROOT / name
        if pathlib.Path(name).suffix not in _TEXT_SUFFIXES:
            continue
        if p.resolve() == pathlib.Path(__file__).resolve():
            continue   # 别把本模块的密钥正则当成密钥
        try:
            text = p.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        files[name] = list(enumerate(text.splitlines(), 1))
    return files


def _is_scannable(path: str) -> bool:
    if pathlib.Path(path).suffix not in _TEXT_SUFFIXES:
        return False
    return pathlib.Path(path).name != pathlib.Path(__file__).name


def scan(source: dict[str, list[tuple[int, str]]]) -> list[Leak]:
    """对取材结果逐行扫描，汇总所有泄漏。"""
    leaks: list[Leak] = []
    for path, lines in source.items():
        if not _is_scannable(path):
            continue
        for lineno, raw in lines:
            leaks.extend(_scan_line(path, lineno, raw))
    return leaks


# ── 脱敏补丁：把命中那行改成什么 ──────────────────────────────────────
def _redacted_line(raw: str, leaks_on_line: list[Leak]) -> str:
    """把这一行里所有命中片段替换成占位符，得到可直接照抄的脱敏后行。"""
    patched = raw
    for lk in leaks_on_line:
        if lk.kind == KIND_SECRET:
            replacement = 'os.environ["SECRET_FROM_ENV"]'  # 提示走环境变量
            # 仅替换被引号包裹的字面值时更稳妥，这里做朴素整段替换。
            patched = patched.replace(lk.raw_match, "***REDACTED***")
        else:
            patched = patched.replace(lk.raw_match, "<REDACTED>")
    return patched


def build_patches(source: dict[str, list[tuple[int, str]]],
                  leaks: list[Leak]) -> list[dict]:
    """逐行脱敏补丁：[{path, line, before, after, kinds}]。before/after 均已脱敏可打印。"""
    raw_by_loc: dict[tuple[str, int], str] = {}
    for path, lines in source.items():
        for lineno, raw in lines:
            raw_by_loc[(path, lineno)] = raw

    by_loc: dict[tuple[str, int], list[Leak]] = {}
    for lk in leaks:
        by_loc.setdefault((lk.path, lk.line), []).append(lk)

    patches: list[dict] = []
    for (path, line), lks in sorted(by_loc.items()):
        raw = raw_by_loc.get((path, line), "")
        after = _redacted_line(raw, lks)
        # before 也要脱敏：把原始命中替换成证据展示，避免补丁里又泄一遍。
        before_safe = raw
        for lk in lks:
            before_safe = before_safe.replace(lk.raw_match, _redact(lk.raw_match))
        patches.append({
            "path": path, "line": line,
            "before": before_safe.strip()[:120],
            "after": after.strip()[:120],
            "kinds": sorted({lk.kind for lk in lks}),
        })
    return patches


# ── 验证证据：内存中应用补丁后重扫，确认归零 ──────────────────────────
def verify(source: dict[str, list[tuple[int, str]]],
           leaks: list[Leak]) -> dict:
    """把补丁应用到内存副本后重扫，返回 {before, after, cleared, residual}。"""
    by_loc: dict[tuple[str, int], list[Leak]] = {}
    for lk in leaks:
        by_loc.setdefault((lk.path, lk.line), []).append(lk)

    patched_source: dict[str, list[tuple[int, str]]] = {}
    for path, lines in source.items():
        new_lines = []
        for lineno, raw in lines:
            lks = by_loc.get((path, lineno))
            new_lines.append((lineno, _redacted_line(raw, lks) if lks else raw))
        patched_source[path] = new_lines

    residual = scan(patched_source)
    return {
        "before": len(leaks),
        "after": len(residual),
        "cleared": len(leaks) - len(residual),
        "residual": [r.to_meta() for r in residual],
    }


def summarize(leaks: list[Leak]) -> tuple[bool, int, int]:
    high = sum(1 for f in leaks if f.severity == SEV_HIGH)
    low = sum(1 for f in leaks if f.severity == SEV_LOW)
    return (high == 0, high, low)


def manifest(use_all: bool = False) -> dict:
    source = _all_tracked_lines() if use_all else _staged_added_lines()
    scope = "all-tracked" if use_all else "staged"
    if not use_all and not source:
        source = {}   # 暂存区为空 = 没东西要提交，干净放行
    leaks = scan(source)
    healthy, high, low = summarize(leaks)
    return {"scope": scope, "healthy": healthy, "high": high, "low": low,
            "leaks": [f.to_meta() for f in leaks],
            "patches": build_patches(source, leaks),
            "verification": verify(source, leaks) if leaks else None}


_KIND_ICON = {KIND_SECRET: "🔑", KIND_PII: "🕵️"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 提交前密钥/隐私哨卡 🔑🚧")
    ap.add_argument("--all", action="store_true",
                    help="扫工作区全部跟踪文件(默认只扫暂存区新增行)")
    ap.add_argument("--patch", action="store_true", help="命中时打印逐行脱敏补丁")
    ap.add_argument("--verify", action="store_true",
                    help="模拟应用补丁并重扫，打印验证证据")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(use_all=args.all), ensure_ascii=False, indent=2))
        return

    source = _all_tracked_lines() if args.all else _staged_added_lines()
    leaks = scan(source)
    healthy, high, low = summarize(leaks)
    scope_label = "工作区全部跟踪文件" if args.all else "暂存区新增行"

    print(f"🔑 opencrab 提交前哨卡 · 扫描范围：{scope_label}\n")
    if not source and not args.all:
        print("  ℹ️  暂存区为空——没有待提交的改动，放行。\n")
        sys.exit(0)
    if not leaks:
        print("  ✅ 干净：本次改动未引入密钥或隐私明文。\n")
        sys.exit(0)

    by_kind: dict[str, list[Leak]] = {}
    for lk in leaks:
        by_kind.setdefault(lk.kind, []).append(lk)
    for kind in (KIND_SECRET, KIND_PII):
        items = by_kind.get(kind, [])
        if not items:
            continue
        print(f"  {_KIND_ICON[kind]} {kind}（{len(items)} 处）")
        for lk in items:
            sev = "🔴高危" if lk.severity == SEV_HIGH else "🟡提醒"
            print(f"      · {sev} [{lk.path}:{lk.line}] {lk.evidence}")
            print(f"        ↳ {lk.hint}")
    print()

    if args.patch:
        print("  🩹 脱敏补丁（原样 → 建议，可直接照抄）：")
        for p in build_patches(source, leaks):
            print(f"      [{p['path']}:{p['line']}]")
            print(f"        - {p['before']}")
            print(f"        + {p['after']}")
        print()

    if args.verify:
        v = verify(source, leaks)
        print("  🧪 验证证据（内存中应用补丁后重扫）：")
        print(f"      补丁前 {v['before']} 处 → 补丁后 {v['after']} 处"
              f"（清除 {v['cleared']} 处）")
        if v["after"] == 0:
            print("      ✅ 重扫归零：补丁确实堵住了全部泄漏。")
        else:
            print("      ⚠️  仍有残留，需人工再核：")
            for r in v["residual"]:
                print(f"        · [{r['path']}:{r['line']}] {r['evidence']}")
        print()

    if high == 0:
        extra = f"（{low} 处隐私提醒，建议脱敏）" if low else ""
        print(f"🟡 无高危密钥泄漏{extra}。可提交，但请先处理上述提醒。")
        sys.exit(0)
    print(f"🚨 发现 {high} 处高危泄漏，先脱敏再 commit——别把领地秘密推上公开仓。")
    sys.exit(1)


if __name__ == "__main__":
    main()
