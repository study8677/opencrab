#!/usr/bin/env python3
"""供应链守卫层 🔗🛡️ —— 在自改之前先守住领地的「对外暴露面」。

为什么要有它：opencrab 是**公开仓库**，每天自改、自提交、自推送。自我进化最容易
忽略的不是「功能对不对」，而是「我往外推的东西，会不会把自己卖了」——一把误提交的
密钥、一段 `curl | sh` 的盲信脚本、一份漂移的许可证、一行没钉死的依赖，都是别人能
攻进来的门。probe 管「依赖装没装」，docsync 管「文档真不真」；supplychain 只问一件事：
**这次蜕壳推出去的代码，安全边界还守得住吗？** 它只做静态扫描，不执行任何东西，
扫的对象刻意限定为 `git ls-files`(真正会被发布的文件)——`.env` 这类已被 .gitignore
拦在门外的，不在射程内，免得自己吓自己。

四类隐患，每条都带「在哪个文件、第几行、怎么修」：

  · 潜在密钥 —— 被纳入版本管理的文件里，出现疑似 API key / token / 私钥的明文。
  · 许可证   —— LICENSE 缺失，或 README 自述的许可证与实际不一致。
  · 可疑脚本 —— `curl|sh` 盲信、`eval/exec` 远程代码、`rm -rf` 等高危模式。
  · 未钉依赖 —— requirements.txt 里没钉死版本(`==`)的第三方依赖。

用法:
    python supplychain.py            # 全量扫描，列出每一处隐患
    python supplychain.py --quiet    # 只在有隐患时说话(适合钩子 / CI)
    python supplychain.py --json     # 导出纯数据(给 health / 外部工具消费)

退出码：0 = 边界守得住(无高危隐患)；1 = 发现高危隐患。零第三方依赖，纯标准库。
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

# ── 隐患类型与严重度：高危必须按下蜕壳，低危只提醒 ──────────────────────
KIND_SECRET = "潜在密钥"
KIND_LICENSE = "许可证"
KIND_SUSPICIOUS = "可疑脚本"
KIND_UNPINNED = "未钉依赖"

SEV_HIGH = "high"   # 计入退出码：会真把领地卖了
SEV_LOW = "low"     # 只提醒：值得看一眼但不阻断

# 扫描密钥时只看「会被人读到内容」的文本文件；二进制 / 大产物跳过。
_TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
                  ".cfg", ".ini", ".sh", ".env", ".example", ".html", ".js"}
_SKIP_DIRS = {".git", "__pycache__", "state", "logs", "node_modules", ".venv"}


@dataclasses.dataclass(frozen=True)
class Finding:
    """一处供应链隐患：哪类、多严重、在哪个文件第几行、那段证据、怎么修。"""
    kind: str
    severity: str       # SEV_HIGH / SEV_LOW
    path: str           # 相对仓库根的文件路径("" 表示仓库级，如缺 LICENSE)
    line: int           # 行号(0 表示非定位到某一行)
    evidence: str       # 触发的那段证据(密钥已脱敏)
    hint: str           # 一句话最小修复建议

    def to_meta(self) -> dict:
        return {"kind": self.kind, "severity": self.severity, "path": self.path,
                "line": self.line, "evidence": self.evidence, "hint": self.hint}


# ── 潜在密钥：高熵 / 已知前缀的明文凭据 ────────────────────────────────
# 每条 = (说明, 正则)。刻意收紧以压低误报——宁可漏报也别天天狼来了。
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI/类前缀密钥", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Anthropic 密钥", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("私钥 PEM 块", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # 形如 KEY="字面值"：只在值看起来像真凭据(长且杂)时才报，放过占位符。
    ("硬编码凭据赋值", re.compile(
        r"""(?ix)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"""
        r"""['"]([^'"\s]{16,})['"]""")),
]

# 一眼能认出是「占位符 / 示例」的值：命中即放过，避免对 .env.example 误报。
_PLACEHOLDER_RE = re.compile(
    r"(?i)(your|example|placeholder|changeme|xxx+|\.\.\.|<[^>]+>|sk-\.\.\.|"
    r"dummy|fake|test|sample|here|todo|redacted|\$\{)")


def _redact(secret: str) -> str:
    """脱敏：只留头尾各 4 字符，中间打码——报隐患不能自己再泄一次。"""
    s = secret.strip()
    if len(s) <= 12:
        return s[:2] + "…" + s[-2:] if len(s) > 4 else "…"
    return f"{s[:4]}…{s[-4:]}（共 {len(s)} 字符）"


def _looks_like_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


# ── 可疑脚本：盲信远程代码 / 不可逆破坏 / 隐蔽执行 ─────────────────────
_SUSPICIOUS_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (SEV_HIGH, "管道盲信远程脚本(curl|sh)",
     re.compile(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b")),
    (SEV_HIGH, "base64 解码后直接执行",
     re.compile(r"base64\s+(?:-d|--decode)[^\n|]*\|\s*(?:ba)?sh\b")),
    (SEV_HIGH, "shell=True 拼接命令",
     re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")),
    (SEV_LOW, "eval/exec 动态执行",
     re.compile(r"\b(?:eval|exec)\s*\(")),
    (SEV_LOW, "递归强删(rm -rf)",
     re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r")),
]


def _tracked_files() -> list[pathlib.Path]:
    """只扫真正会被发布的文件(git ls-files)；非 git 仓库则回退到磁盘遍历。"""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            files = [REPO_ROOT / line for line in out.stdout.splitlines() if line]
            return [f for f in files if f.is_file()]
    except Exception:
        pass
    # 回退：不在 git 里也别哑火，遍历磁盘但跳过运行时目录。
    files = []
    for p in REPO_ROOT.rglob("*"):
        if p.is_file() and not any(part in _SKIP_DIRS for part in p.parts):
            files.append(p)
    return files


def _rel(p: pathlib.Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _scan_file_for_secrets(path: pathlib.Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        # .env.example 本就该放占位符；它的「赋值」形态最容易误报，但具体凭据正则仍要跑。
        for label, pat in _SECRET_PATTERNS:
            m = pat.search(raw)
            if not m:
                continue
            captured = m.group(1) if m.groups() else m.group(0)
            if _looks_like_placeholder(captured) or _looks_like_placeholder(raw):
                continue
            findings.append(Finding(
                KIND_SECRET, SEV_HIGH, _rel(path), lineno, f"{label}：{_redact(captured)}",
                "立刻吊销该凭据、从历史里清掉，改走环境变量(.env 已被 .gitignore 拦截)"))
    return findings


def _scan_file_for_suspicious(path: pathlib.Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = raw.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue   # 注释里的示范不算执行
        for sev, label, pat in _SUSPICIOUS_PATTERNS:
            if pat.search(raw):
                findings.append(Finding(
                    KIND_SUSPICIOUS, sev, _rel(path), lineno, f"{label}：{raw.strip()[:80]}",
                    "校验来源 / 改成下载后校验哈希再执行，或换掉动态执行写法"))
    return findings


# ── 许可证完整性 ─────────────────────────────────────────────────────
_LICENSE_DECL_RE = re.compile(r"(?im)^\s*(?:license)\s*[:：]\s*(.+?)\s*$")
# README 徽章 / 正文里常见的许可证名(用来和 LICENSE 文件粗对一下)。
_KNOWN_LICENSES = ["MIT", "Apache-2.0", "Apache License", "GPL", "BSD", "MPL",
                   "Unlicense", "ISC"]


def _detect_license_name(license_text: str) -> str:
    head = license_text[:400]
    if "MIT License" in head or re.search(r"\bMIT\b", head):
        return "MIT"
    for name in _KNOWN_LICENSES:
        if name.lower() in head.lower():
            return name
    return "未知"


def _scan_license() -> list[Finding]:
    findings: list[Finding] = []
    lic = REPO_ROOT / "LICENSE"
    if not lic.exists():
        findings.append(Finding(
            KIND_LICENSE, SEV_HIGH, "", 0, "仓库根缺少 LICENSE 文件",
            "补一份 LICENSE（公开仓库无许可证 = 默认保留所有权利，他人无法合法复用）"))
        return findings

    try:
        lic_text = lic.read_text("utf-8", errors="ignore")
    except Exception:
        return findings
    actual = _detect_license_name(lic_text)

    # README 自述的许可证若与 LICENSE 文件对不上，是种隐性漂移。
    for readme in ("README.md", "README.en.md"):
        p = REPO_ROOT / readme
        if not p.exists():
            continue
        text = p.read_text("utf-8", errors="ignore")
        m = _LICENSE_DECL_RE.search(text)
        if not m:
            continue
        declared = m.group(1).strip()
        if actual != "未知" and actual.lower() not in declared.lower():
            findings.append(Finding(
                KIND_LICENSE, SEV_LOW, readme, text[:m.start()].count("\n") + 1,
                f"自述许可证「{declared}」与 LICENSE 实际「{actual}」不一致",
                "对齐两处许可证声明，避免对外承诺与实际授权不符"))
    return findings


# ── 依赖钉版本 ───────────────────────────────────────────────────────
def _scan_requirements() -> list[Finding]:
    """opencrab 立约零依赖；任何出现的第三方依赖都该钉死版本(==)。"""
    findings: list[Finding] = []
    req = REPO_ROOT / "requirements.txt"
    if not req.exists():
        return findings
    for lineno, raw in enumerate(req.read_text("utf-8", errors="ignore").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # 已钉死(==)或本地路径 / URL 安装的放过；其余视作未钉。
        if "==" in line or line.startswith((".", "/", "http", "-e", "git+")):
            continue
        findings.append(Finding(
            KIND_UNPINNED, SEV_LOW, "requirements.txt", lineno,
            f"未钉版本：{line}",
            "用 `==` 钉死精确版本，避免上游悄悄换实现引入供应链风险"))
    return findings


# ── 总扫描 ───────────────────────────────────────────────────────────
def scan() -> list[Finding]:
    """全量扫描：密钥 + 可疑脚本(逐文件) + 许可证 + 依赖钉版本。任何一处读不到都跳过而非崩。"""
    findings: list[Finding] = []
    for path in _tracked_files():
        if path.suffix not in _TEXT_SUFFIXES and path.name not in (".env.example",):
            continue
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue   # 别把本模块自己的密钥正则当成密钥
        try:
            text = path.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        findings.extend(_scan_file_for_secrets(path, text))
        findings.extend(_scan_file_for_suspicious(path, text))
    findings.extend(_scan_license())
    findings.extend(_scan_requirements())
    return findings


def summarize(findings: list[Finding]) -> tuple[bool, int, int]:
    """归一化结论：是否守得住(无高危)、高危几处、低危几处。"""
    high = sum(1 for f in findings if f.severity == SEV_HIGH)
    low = sum(1 for f in findings if f.severity == SEV_LOW)
    return (high == 0, high, low)


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    findings = scan()
    healthy, high, low = summarize(findings)
    return {"healthy": healthy, "high": high, "low": low,
            "findings": [f.to_meta() for f in findings]}


_KIND_ICON = {KIND_SECRET: "🔑", KIND_LICENSE: "📜",
              KIND_SUSPICIOUS: "⚠️", KIND_UNPINNED: "📌"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 供应链守卫层 🔗🛡️")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有隐患时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    findings = scan()
    healthy, high, low = summarize(findings)
    clean = not findings

    if not (args.quiet and clean):
        print("🔗 opencrab 供应链守卫\n")
        if clean:
            print("  ✅ 对外暴露面干净：无泄密、无可疑脚本、许可证与依赖都守约。")
        else:
            by_kind: dict[str, list[Finding]] = {}
            for f in findings:
                by_kind.setdefault(f.kind, []).append(f)
            for kind in (KIND_SECRET, KIND_SUSPICIOUS, KIND_LICENSE, KIND_UNPINNED):
                items = by_kind.get(kind, [])
                if not items:
                    continue
                icon = _KIND_ICON[kind]
                print(f"  {icon} {kind}（{len(items)} 处）")
                for f in items:
                    sev = "🔴高危" if f.severity == SEV_HIGH else "🟡提醒"
                    loc = f.path + (f":{f.line}" if f.line else "") or "（仓库级）"
                    print(f"      · {sev} [{loc}] {f.evidence}")
                    print(f"        ↳ {f.hint}")
        print()

    if high == 0:
        if not args.quiet:
            extra = f"（{low} 处低危提醒）" if low else ""
            print(f"🛡️  边界守得住：无高危供应链隐患{extra}。")
        sys.exit(0)
    else:
        print(f"🚨 发现 {high} 处高危供应链隐患，先堵住再蜕壳。")
        sys.exit(1)


if __name__ == "__main__":
    main()
