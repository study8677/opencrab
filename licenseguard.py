#!/usr/bin/env python3
"""许可证守卫层 📜⚖️ —— 别让自我进化把法律风险悄悄带进领地。

为什么要有它：opencrab 是 **MIT 授权的公开仓库**，每天自改、自提交、自推送。
进化时它会抓依赖、抄参考片段、生成新产物——任何一处粘进一段 GPL 代码、引一份
没署名的第三方实现，都会在不知不觉间把整个仓库的授权前提推翻。supplychain 管的是
「会不会把密钥/边界卖出去」；licenseguard 只问一件更安静、却更致命的事：
**这次蜕壳引入/生成的东西，许可证还和 MIT 宿主相容吗？**

它只做静态扫描，不执行、不联网，扫的对象限定为 `git ls-files`(真正会被发布的文件)。
对每一处可疑授权，按相容性给出三类裁决，每条都带「在哪、是什么、怎么办」：

  · 阻断 🔴 —— 强 copyleft(GPL/AGPL/SSPL 等)或来源不明。混入即可能传染整库授权，
              必须先移除或换实现，不能蜕壳。
  · 署名 🟡 —— 宽松/弱 copyleft(MIT/BSD/Apache/ISC/MPL/LGPL 等)。可用，但要保留
              版权声明与许可证文本；Apache/弱 copyleft 还要留 NOTICE / 隔离边界。
  · 替代 💡 —— 凡被阻断的，顺手给一句「换什么/怎么自己实现」的方向，别只喊停。

三个扫描面：
  · 依赖    —— requirements.txt 声明的第三方包，比对内置许可证登记表。
  · 引用片段 —— 源码 / 文档里嵌入的 SPDX 标记、版权块、许可证名(疑似外来代码)。
  · 生成物   —— skills / capabilities / journal 等自动生成内容里夹带的授权文本。

用法:
    python licenseguard.py            # 全量扫描，列出每一处授权隐患
    python licenseguard.py --quiet    # 只在有隐患时说话(适合钩子 / CI)
    python licenseguard.py --json     # 导出纯数据(给 health / 外部工具消费)

退出码：0 = 授权守得住(无阻断级隐患)；1 = 发现阻断级隐患。零第三方依赖，纯标准库。
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

# ── 宿主授权：opencrab 自身是 MIT(宽松)。所有相容性判断都以「能不能安全并入 MIT 仓库」为准。──
HOST_LICENSE = "MIT"

# ── 裁决：阻断必须按下蜕壳，署名只是义务提醒。──────────────────────────
VERDICT_BLOCK = "阻断"   # 计入退出码：混入会传染/越权
VERDICT_NOTICE = "署名"  # 可用，但有保留声明/隔离的义务

# ── 隐患所在的扫描面 ─────────────────────────────────────────────────
FACE_DEP = "依赖"
FACE_SNIPPET = "引用片段"
FACE_ARTIFACT = "生成物"

# 扫描文本面时只看「会被人读到内容」的文本文件；二进制 / 大产物跳过。
_TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml",
                  ".cfg", ".ini", ".sh", ".js", ".html", ".rst"}
_SKIP_DIRS = {".git", "__pycache__", "state", "logs", "node_modules", ".venv"}

# 生成物所在目录：这些目录下的文件视作「自动生成」，命中外来授权尤其危险
# (说明进化时把别处的内容原样吞了进来)。
_ARTIFACT_DIRS = {"skills", "capabilities", "journal", "docs"}


@dataclasses.dataclass(frozen=True)
class Family:
    """一族许可证的法律性质：决定它和 MIT 宿主相容到什么程度。"""
    key: str            # permissive / weak_copyleft / strong_copyleft / unknown
    verdict: str        # 默认裁决(VERDICT_BLOCK / VERDICT_NOTICE)
    obligation: str     # 一句话义务说明(署名级)或风险说明(阻断级)
    alternative: str    # 阻断时的替代方向("" 表示无需替代)


# ── 许可证族谱：每族的法律性质 ───────────────────────────────────────
# 判据：能否安全并入 MIT 仓库而不被「传染」更强的义务。
PERMISSIVE = Family(
    "permissive", VERDICT_NOTICE,
    "保留原版权声明与许可证文本即可并入(Apache-2.0 另需保留 NOTICE 与专利条款)。",
    "")
WEAK_COPYLEFT = Family(
    "weak_copyleft", VERDICT_NOTICE,
    "可用但有边界：保留声明，且对该文件的修改需以同协议回馈，勿与 MIT 源码直接合并。",
    "")
STRONG_COPYLEFT = Family(
    "strong_copyleft", VERDICT_BLOCK,
    "强 copyleft 会传染整库授权——并入即要求 opencrab 整体改用同协议,与 MIT 公开复用前提冲突。",
    "换宽松授权(MIT/BSD/Apache)的等价实现，或参照接口自己重写,不要直接搬运。")
UNKNOWN = Family(
    "unknown", VERDICT_BLOCK,
    "来源/授权不明——默认「保留所有权利」,未经许可复用即侵权。",
    "确认出处与授权;无法确认就移除,或换一份明确宽松授权的实现。")

# ── SPDX 标识 → 许可证族。键统一小写,匹配时大小写不敏感。──────────────
_SPDX_FAMILY: dict[str, Family] = {}
for _ids, _fam in [
    # 宽松
    (["mit", "bsd-2-clause", "bsd-3-clause", "0bsd", "isc", "apache-2.0",
      "zlib", "unlicense", "python-2.0", "boost-1.0", "bsl-1.0"], PERMISSIVE),
    # 弱 copyleft(文件级回馈,可与宽松共存但需隔离)
    (["mpl-2.0", "lgpl-2.1", "lgpl-2.1-or-later", "lgpl-3.0", "lgpl-3.0-or-later",
      "epl-1.0", "epl-2.0", "cddl-1.0", "cc-by-4.0"], WEAK_COPYLEFT),
    # 强 copyleft / 越权(传染整库或带额外限制)
    (["gpl-2.0", "gpl-2.0-only", "gpl-2.0-or-later", "gpl-3.0", "gpl-3.0-only",
      "gpl-3.0-or-later", "agpl-3.0", "agpl-3.0-only", "agpl-3.0-or-later",
      "sspl-1.0", "cc-by-sa-4.0", "cc-by-nc-4.0", "osl-3.0"], STRONG_COPYLEFT),
]:
    for _i in _ids:
        _SPDX_FAMILY[_i] = _fam

# ── 自由文本里的许可证名 → 族。按「越具体越靠前」排序,先命中先算。──────
# 每条 = (展示名, 正则, 族)。强 copyleft 放最前,免得被 "lesser GPL" 之类抢词。
_TEXT_LICENSE_PATTERNS: list[tuple[str, re.Pattern, Family]] = [
    ("AGPL", re.compile(r"(?i)\bAffero\s+General\s+Public|\bAGPL\b"), STRONG_COPYLEFT),
    ("SSPL", re.compile(r"(?i)\bServer\s+Side\s+Public\s+License|\bSSPL\b"), STRONG_COPYLEFT),
    ("LGPL", re.compile(r"(?i)\bLesser\s+General\s+Public|\bLGPL\b"), WEAK_COPYLEFT),
    ("GPL", re.compile(r"(?i)\bGNU\s+General\s+Public\s+License|\bGPL(?:v?[23])?\b"), STRONG_COPYLEFT),
    ("MPL", re.compile(r"(?i)\bMozilla\s+Public\s+License|\bMPL\b"), WEAK_COPYLEFT),
    ("EPL", re.compile(r"(?i)\bEclipse\s+Public\s+License|\bEPL\b"), WEAK_COPYLEFT),
    ("CC-BY-NC", re.compile(r"(?i)\bCreativeCommons[\s-]+\S*NonCommercial|\bCC[\s-]?BY[\s-]?NC\b"), STRONG_COPYLEFT),
    ("CC-BY-SA", re.compile(r"(?i)\bShareAlike\b|\bCC[\s-]?BY[\s-]?SA\b"), STRONG_COPYLEFT),
    ("Apache", re.compile(r"(?i)\bApache\s+License|\bApache-2\.0\b"), PERMISSIVE),
    ("BSD", re.compile(r"(?i)\bBSD\s+(?:2|3)-Clause|\bBSD\s+License\b"), PERMISSIVE),
    ("MIT", re.compile(r"(?i)\bMIT\s+License\b"), PERMISSIVE),
    ("ISC", re.compile(r"(?i)\bISC\s+License\b"), PERMISSIVE),
]

_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")
# 版权块:出现他人(非本仓库)的 Copyright 行,且行内未带明确宽松授权名,值得过一眼。
_COPYRIGHT_RE = re.compile(r"(?im)^\s*(?://|#|\*)?\s*Copyright\s*(?:\(c\)|©|\bc\b)?\s*\d{4}")
# 本仓库自己的版权署名,出现这串就当是自家文件,不算外来引用。
_OWN_COPYRIGHT = re.compile(r"(?i)Copyright.*\b(?:study8677|opencrab)\b")


@dataclasses.dataclass(frozen=True)
class Finding:
    """一处授权隐患:在哪个面、哪个文件第几行、命中的授权、裁决、义务/替代建议。"""
    face: str           # FACE_DEP / FACE_SNIPPET / FACE_ARTIFACT
    verdict: str        # VERDICT_BLOCK / VERDICT_NOTICE
    path: str           # 相对仓库根的文件路径
    line: int           # 行号(0 表示非定位到某一行)
    license_name: str   # 命中的许可证展示名(如 "GPL"、"未知")
    evidence: str       # 触发的那段证据
    hint: str           # 一句话:该尽的义务 / 替代方向

    def to_meta(self) -> dict:
        return {"face": self.face, "verdict": self.verdict, "path": self.path,
                "line": self.line, "license": self.license_name,
                "evidence": self.evidence, "hint": self.hint}


def _tracked_files() -> list[pathlib.Path]:
    """只扫真正会被发布的文件(git ls-files);非 git 仓库则回退到磁盘遍历。"""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            files = [REPO_ROOT / line for line in out.stdout.splitlines() if line]
            return [f for f in files if f.is_file()]
    except Exception:
        pass
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


def _face_of(path: pathlib.Path) -> str:
    """文件落在生成目录里就算「生成物」,否则按「引用片段」处理。"""
    rel = _rel(path)
    top = rel.split("/", 1)[0]
    return FACE_ARTIFACT if top in _ARTIFACT_DIRS else FACE_SNIPPET


def _hint_for(fam: Family) -> str:
    """据族给义务/替代建议:阻断给替代方向,署名给保留义务。"""
    if fam.verdict == VERDICT_BLOCK:
        tail = f" 替代:{fam.alternative}" if fam.alternative else ""
        return f"{fam.obligation}{tail}"
    return fam.obligation


# ── 依赖面:requirements.txt 声明的第三方包 ───────────────────────────
# opencrab 立约零依赖。任何出现的第三方包都查不到内置许可证就该人工核实——
# 这里不联网,只维护一张「常见包→授权」的小登记表,查不到即按未知阻断处理。
_DEP_LICENSE: dict[str, str] = {
    # 常见宽松(SPDX 小写键,复用上面的族谱)
    "requests": "apache-2.0", "urllib3": "mit", "flask": "bsd-3-clause",
    "click": "bsd-3-clause", "numpy": "bsd-3-clause", "pandas": "bsd-3-clause",
    "pydantic": "mit", "fastapi": "mit", "httpx": "bsd-3-clause",
    "rich": "mit", "pytest": "mit", "pyyaml": "mit", "jinja2": "bsd-3-clause",
    "setuptools": "mit", "wheel": "mit", "anyio": "mit", "starlette": "bsd-3-clause",
    # 常见 copyleft——并非不能用,但要按族尽义务/隔离
    "paramiko": "lgpl-2.1", "chardet": "lgpl-2.1", "mysql-connector-python": "gpl-2.0",
    "pymysql": "mit", "psycopg2": "lgpl-3.0",
}

_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9._\-]+)")


def _scan_dependencies() -> list[Finding]:
    findings: list[Finding] = []
    req = REPO_ROOT / "requirements.txt"
    if not req.exists():
        return findings
    for lineno, raw in enumerate(req.read_text("utf-8", errors="ignore").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-e", "git+", "http", ".", "/")):
            continue
        m = _DEP_NAME_RE.match(line)
        if not m:
            continue
        name = m.group(1).lower()
        spdx = _DEP_LICENSE.get(name)
        if spdx is None:
            findings.append(Finding(
                FACE_DEP, VERDICT_BLOCK, "requirements.txt", lineno, "未知",
                f"依赖 {name} 的许可证未登记",
                "核实该包的实际许可证;确认是强 copyleft 就换宽松等价实现,否则按其授权尽署名义务"))
            continue
        fam = _SPDX_FAMILY.get(spdx, UNKNOWN)
        findings.append(Finding(
            FACE_DEP, fam.verdict, "requirements.txt", lineno, spdx.upper(),
            f"依赖 {name} 为 {spdx.upper()}", _hint_for(fam)))
    return findings


# ── 引用片段 / 生成物面:文本里嵌入的授权标记 ─────────────────────────
def _scan_text(path: pathlib.Path, text: str) -> list[Finding]:
    """逐文件找:SPDX 标记、外来版权块、自由文本里的许可证名。"""
    findings: list[Finding] = []
    face = _face_of(path)
    rel = _rel(path)
    seen_spans: set[tuple[int, str]] = set()   # 同一行同一族只报一次

    for lineno, raw in enumerate(text.splitlines(), 1):
        # 1) SPDX 标识——最权威,优先。
        m = _SPDX_RE.search(raw)
        if m:
            spdx = m.group(1).strip().lower()
            fam = _SPDX_FAMILY.get(spdx, UNKNOWN)
            name = m.group(1).strip()
            if (lineno, fam.key) not in seen_spans:
                seen_spans.add((lineno, fam.key))
                findings.append(Finding(
                    face, fam.verdict, rel, lineno,
                    name if fam is not UNKNOWN else f"{name}(未识别)",
                    f"SPDX 标记:{raw.strip()[:80]}", _hint_for(fam)))
            continue

        # 2) 自由文本里的许可证名(疑似搬运的代码/文档头)。
        for disp, pat, fam in _TEXT_LICENSE_PATTERNS:
            if not pat.search(raw):
                continue
            # MIT/宽松名出现在本仓库自家文件里是常态,不必逐行喊;只报 copyleft 以上。
            if fam is PERMISSIVE and face == FACE_SNIPPET:
                break
            if (lineno, fam.key) not in seen_spans:
                seen_spans.add((lineno, fam.key))
                findings.append(Finding(
                    face, fam.verdict, rel, lineno, disp,
                    f"提及 {disp} 许可证:{raw.strip()[:80]}", _hint_for(fam)))
            break

    # 3) 外来版权块:出现他人 Copyright 且全文未声明宿主授权,值得人工过一眼。
    if _COPYRIGHT_RE.search(text) and not _OWN_COPYRIGHT.search(text):
        # 生成物里冒出外来版权尤其可疑(说明进化时原样吞了别处内容)。
        if face == FACE_ARTIFACT:
            cm = _COPYRIGHT_RE.search(text)
            lineno = text[:cm.start()].count("\n") + 1
            findings.append(Finding(
                face, VERDICT_NOTICE, rel, lineno, "外来版权",
                f"生成物含他人版权声明:{text[cm.start():cm.start()+60].strip()}",
                "确认来源与授权;若为引用,保留原始版权与许可证文本并标注出处"))
    return findings


# ── 总扫描 ───────────────────────────────────────────────────────────
def scan() -> list[Finding]:
    """全量扫描:依赖 + 逐文件的引用片段/生成物。任何一处读不到都跳过而非崩。"""
    findings: list[Finding] = []
    findings.extend(_scan_dependencies())
    self_path = pathlib.Path(__file__).resolve()
    for path in _tracked_files():
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        if path.resolve() == self_path:
            continue   # 本模块自己满是许可证名,别自我误报
        try:
            text = path.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        findings.extend(_scan_text(path, text))
    return findings


def summarize(findings: list[Finding]) -> tuple[bool, int, int]:
    """归一化结论:授权是否守得住(无阻断)、阻断几处、署名几处。"""
    block = sum(1 for f in findings if f.verdict == VERDICT_BLOCK)
    notice = sum(1 for f in findings if f.verdict == VERDICT_NOTICE)
    return (block == 0, block, notice)


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    findings = scan()
    healthy, block, notice = summarize(findings)
    return {"host_license": HOST_LICENSE, "healthy": healthy,
            "block": block, "notice": notice,
            "findings": [f.to_meta() for f in findings]}


_FACE_ICON = {FACE_DEP: "📦", FACE_SNIPPET: "📄", FACE_ARTIFACT: "🏭"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 许可证守卫层 📜⚖️")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有隐患时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    findings = scan()
    healthy, block, notice = summarize(findings)
    clean = not findings

    if not (args.quiet and clean):
        print(f"📜 opencrab 许可证守卫（宿主：{HOST_LICENSE}）\n")
        if clean:
            print("  ✅ 授权干净：依赖、引用片段、生成物均与 MIT 宿主相容，无需署名义务。")
        else:
            by_face: dict[str, list[Finding]] = {}
            for f in findings:
                by_face.setdefault(f.face, []).append(f)
            for face in (FACE_DEP, FACE_SNIPPET, FACE_ARTIFACT):
                items = by_face.get(face, [])
                if not items:
                    continue
                icon = _FACE_ICON[face]
                print(f"  {icon} {face}（{len(items)} 处）")
                for f in items:
                    tag = "🔴阻断" if f.verdict == VERDICT_BLOCK else "🟡署名"
                    loc = f.path + (f":{f.line}" if f.line else "")
                    print(f"      · {tag} [{f.license_name}] {loc}")
                    print(f"        {f.evidence}")
                    print(f"        ↳ {f.hint}")
        print()

    if block == 0:
        if not args.quiet:
            extra = f"（{notice} 处署名义务待履行）" if notice else ""
            print(f"⚖️  授权守得住：无阻断级许可证隐患{extra}。")
        sys.exit(0)
    else:
        print(f"🚨 发现 {block} 处阻断级许可证隐患，先移除/替代再蜕壳，别把法律风险带进领地。")
        sys.exit(1)


if __name__ == "__main__":
    main()
