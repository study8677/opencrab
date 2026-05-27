#!/usr/bin/env python3
"""brain 补丁影子落盘 🖋️👻 —— brain 亲手生成一处低风险文档/JSON 补丁，只写临时影子副本，真身分毫不动。

为什么要有它：到今天为止，brain **亲手产补丁**这件事只发生在「修坏的源码」——`weaning_trial`
补语法真伤、`purefix_trial` 撞对纯函数逻辑，都得先有一处**坏掉/算错**的代码当起点。可断奶的
下一步不是「修得更狠」，而是先证明一件更朴素的事：**「给我一份本就好端端的文件，我能不能亲手
誊出一处该改的小修，而且全程不碰真身？」** 这一步要的不是难度，是**安全的自主落笔**——先把
「我能写」与「我不会伤到真身」拆开，各自证一遍。

`patchfitroom` 是「给定候选 → 过五闸 → 过了**原子写回真文件**」；本层恰恰相反，是
「**自己生成**候选 → 验收 → 只写**影子副本**、真文件**永远不碰**」。一个管落地，一个管断奶第一课。

本层就是那支只在影子上落笔的笔：

  1) 🎯 **低风险闸(kind)**：只接 `.json / .md / .txt / .markdown` 这类文档/配置文件。
     源码(`.py`)与任何不认识的后缀，当场弃权——高风险的代码改动交给 fitroom 那条线，
     断奶第一课只在「改坏了也只是格式」的地方练手。
  2) 🖋️ **誊写(scribe)**：按文件类型选一支确定性的笔，亲手生成「该改的那一处」——
       · JSON  → 规范化：解析后按 `indent=2 / sort_keys / 末尾单换行` 重排(纯重排，数据一字不改)。
       · 文档  → 去行尾空白 + 收敛成单一末尾换行(纯空白整理，可见内容一字不改)。
     本就规整、无可誊写的文件，老实回「无需誊写」，绝不为动而动。
  3) 🔒 **保义闸(oracle)**：每支笔自带一道「这一改没改变语义」的判据——
     JSON 笔验 `loads(后) == loads(前)`(数据相等)，文档笔验「抹掉所有空白后两份完全相同」
     (可见内容相等)。判据不过 = 这支笔把意思改坏了，**当场拒、连影子都不写**。
  4) 👻 **影子落盘**：验收全过，才把誊本写进一份隔离的**临时影子副本**(系统临时目录里的
     `{name}.shadow`)，并回给一份 unified diff 供人验收「brain 这一爪到底改了什么」。
  5) 🪞 **不碰真身闸(untouched)**：全程结束，断言真文件的 sha256 与落笔前**一字节不差**——
     这是本层的命根子：brain 可以亲手写，但只能写在影子上，真身永远是只读的。

设计与全家一致：零第三方依赖、纯标准库；誊写/验收任一步出意外，一律收敛成「不誊写、不写影子、
真身不动」，绝不抛错、绝不反噬——一支只敢在影子上落笔的笔，自己绝不能成为真身的第一道伤口。

用法:
    python shadowscribe.py                 # 演示：几类文件各誊一爪(JSON 规范化 / 文档去尾空白 / 源码弃权)
    python shadowscribe.py --selfcheck     # 自检:誊得对 / 保义闸拦住语义漂移 / 全程真身字节不变
    python shadowscribe.py --json          # 机读:接哪些后缀 + 各支笔
    python shadowscribe.py --shadow PATH   # 对真仓库内 PATH 誊一爪,只写影子副本并打 diff(真身不动)
    加 --quiet 静默,仅以退出码表态。
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── 一支笔：认哪些后缀、怎么誊、怎么证「没改坏意思」 ──────────────────────────────
@dataclasses.dataclass(frozen=True)
class Scribe:
    """一支确定性的誊写笔：对某类低风险文件，生成「该改的那一处」并自带保义判据。"""
    name: str                          # 这支笔的名字
    exts: tuple[str, ...]              # 认哪些后缀(小写，含点)
    what: str                          # 一句人话：这支笔誊什么
    # rewrite(before)->after：纯函数，确定性地生成誊本；本就规整则返回与 before 相等的串。
    # oracle(before, after)->bool：这一改有没有保住语义/可见内容。出意外抛给上层收敛成「拒」。


def _json_rewrite(before: str) -> str:
    """JSON 规范化：解析后按 indent=2 / sort_keys / 末尾单换行重排(纯重排，数据一字不改)。"""
    data = json.loads(before)
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _json_oracle(before: str, after: str) -> bool:
    """保义：重排前后解析出来的数据必须完全相等——只许换排版，不许动一个值。"""
    return json.loads(before) == json.loads(after)


def _doc_rewrite(before: str) -> str:
    """文档整理：逐行去行尾空白 + 收敛成单一末尾换行(纯空白整理，可见内容一字不改)。"""
    lines = [ln.rstrip() for ln in before.splitlines()]
    body = "\n".join(lines)
    return body + "\n" if body else ""


def _doc_oracle(before: str, after: str) -> bool:
    """保义：抹掉**所有**空白后两份完全相同——证明只动了空白，可见内容一字未改。"""
    return "".join(before.split()) == "".join(after.split())


# 各支笔的实现挂在这里(rewrite/oracle 按 name 取)，Scribe 只存元信息便于机读。
_IMPL = {
    "json-canonicalize": (_json_rewrite, _json_oracle),
    "doc-tidy": (_doc_rewrite, _doc_oracle),
}

SCRIBES: list[Scribe] = [
    Scribe(name="json-canonicalize", exts=(".json",),
           what="JSON 规范化：解析后按 indent=2 / sort_keys / 末尾单换行重排(数据一字不改)"),
    Scribe(name="doc-tidy", exts=(".md", ".markdown", ".txt"),
           what="文档整理：去每行行尾空白 + 收敛成单一末尾换行(可见内容一字不改)"),
]

# 低风险后缀全集：只在这些文件上练手；源码(.py)与不认识的后缀一律弃权。
ALLOWED_EXTS = tuple(sorted({e for s in SCRIBES for e in s.exts}))


def _pick(path: pathlib.Path) -> Scribe | None:
    """按后缀选笔；不是低风险文档/JSON 则返回 None(弃权，交回上层)。"""
    ext = path.suffix.lower()
    for s in SCRIBES:
        if ext in s.exts:
            return s
    return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class ShadowResult:
    """一次影子誊写的结论：誊没誊、哪支笔、保义过没过、真身碰没碰、影子在哪。"""
    proposed: bool          # 是否亲手生成了一处**非空且保义**的誊改(影子已落)
    scribe: str             # 用了哪支笔；弃权/无可誊写时为 ""
    target: str             # 誊写针对的真文件路径
    shadow: str             # 影子副本路径(只写它，绝不写真身)；未落影子时为 ""
    oracle_ok: bool         # 保义判据过没过(语义/可见内容是否保住)
    real_untouched: bool    # 命根子：全程结束真文件 sha256 是否与落笔前一字节不差
    changed_lines: int      # 这一爪改了多少行(unified diff 里 +/- 的行数，供验收掂量轻重)
    detail: str             # 一句现场
    diff: str               # unified diff：brain 这一爪到底改了什么，供人验收

    def to_meta(self) -> dict:
        return {"proposed": self.proposed, "scribe": self.scribe, "target": self.target,
                "shadow": self.shadow, "oracle_ok": self.oracle_ok,
                "real_untouched": self.real_untouched, "changed_lines": self.changed_lines,
                "detail": self.detail}


def _unified(before: str, after: str, name: str) -> tuple[str, int]:
    """生成 unified diff，并数出 +/- 的实际改动行数(不含 @@/+++/--- 表头)。"""
    diff_lines = list(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{name}", tofile=f"b/{name} (shadow)"))
    changed = sum(1 for ln in diff_lines
                  if (ln.startswith("+") and not ln.startswith("+++"))
                  or (ln.startswith("-") and not ln.startswith("---")))
    return "".join(diff_lines), changed


def scribe(target, *, write_shadow: bool = True,
           shadow_dir: pathlib.Path | None = None) -> ShadowResult:
    """让 brain 对真文件 target 亲手誊一处低风险小修，只写影子副本，真身永远不碰。

    target      : 真仓库内的文档/JSON 文件(其当前内容当 before；只读，绝不写它)。
    write_shadow: False = 只验收看效果、连影子都不写(供 replay 零副作用重跑)。
    shadow_dir  : 影子副本写到哪个目录(缺省系统临时目录)；自检据此固定到隔离目录。
    返回 ShadowResult。永不抛错——任何意外都收敛成「不誊写、不写影子、真身不动」。
    """
    target = pathlib.Path(target)
    try:
        before = target.read_text(encoding="utf-8") if target.exists() else ""
    except OSError as e:
        return ShadowResult(False, "", str(target), "", False, True, 0,
                            f"读不到目标文件，弃权：{type(e).__name__}: {e}", "")
    before_sha = _sha256(before)

    def _untouched() -> bool:
        """落笔前后比对真文件 sha256——本层从不为写而打开真文件，这里只是把不变性钉死成证据。"""
        try:
            now = target.read_text(encoding="utf-8") if target.exists() else ""
        except OSError:
            return False
        return _sha256(now) == before_sha

    # ── 闸 1) 低风险闸：只接文档/JSON，源码与陌生后缀一律弃权 ──
    pen = _pick(target)
    if pen is None:
        return ShadowResult(False, "", str(target), "", False, _untouched(), 0,
                            f"{target.suffix or '无后缀'} 不是低风险文档/JSON，影子誊写不接"
                            f"（只接 {'、'.join(ALLOWED_EXTS)}）", "")
    rewrite, oracle = _IMPL[pen.name]

    # ── 闸 2) 誊写：亲手生成「该改的那一处」(解析/重排崩了 → 弃权，绝不硬塞) ──
    try:
        after = rewrite(before)
    except Exception as e:  # noqa: BLE001 —— 比如 .json 根本解析不了：当作无可誊写、保守弃权
        return ShadowResult(False, pen.name, str(target), "", False, _untouched(), 0,
                            f"{pen.name} 誊不动(可能内容已损坏)，保守弃权：{type(e).__name__}: {e}", "")
    if after == before:
        return ShadowResult(False, pen.name, str(target), "", True, _untouched(), 0,
                            "已经规整，无需誊写", "")

    # ── 闸 3) 保义闸：这一改不许动语义/可见内容，否则当场拒、连影子都不写 ──
    try:
        ok = oracle(before, after)
    except Exception as e:  # noqa: BLE001 —— 判据自己崩了也按「没保住」处理，宁可不写
        return ShadowResult(False, pen.name, str(target), "", False, _untouched(), 0,
                            f"保义判据出意外，拒、不写影子：{type(e).__name__}: {e}", "")
    diff, changed = _unified(before, after, target.name)
    if not ok:
        return ShadowResult(False, pen.name, str(target), "", False, _untouched(), changed,
                            f"{pen.name} 这一誊改变了语义/可见内容 → 拒，连影子都不写", diff)

    # ── 闸 4) 影子落盘：只写隔离的临时影子副本，真身永远不碰 ──
    shadow_path = ""
    if write_shadow:
        sd = pathlib.Path(shadow_dir) if shadow_dir else pathlib.Path(tempfile.gettempdir())
        sd.mkdir(parents=True, exist_ok=True)
        sp = sd / f"{target.name}.shadow"
        try:
            sp.write_text(after, encoding="utf-8")
            shadow_path = str(sp)
        except OSError as e:
            return ShadowResult(False, pen.name, str(target), "", True, _untouched(), changed,
                                f"影子副本写不下，弃权(真身仍未动)：{type(e).__name__}: {e}", diff)

    # ── 闸 5) 不碰真身闸：钉死真文件全程字节未变 ──
    untouched = _untouched()
    detail = (f"{pen.name} 誊了 {changed} 行 → 已落影子副本"
              if write_shadow else f"{pen.name} 可誊 {changed} 行(只看不写影子)")
    if not untouched:
        detail += "；⚠️ 但真身竟被改动——本层契约被破坏"
    return ShadowResult(True, pen.name, str(target), shadow_path, True, untouched,
                        changed, detail, diff)


def manifest() -> dict:
    """机读：接哪些后缀 + 各支笔(给 health / 外部消费)。"""
    return {
        "allowed_exts": list(ALLOWED_EXTS),
        "scribes": [{"name": s.name, "exts": list(s.exts), "what": s.what} for s in SCRIBES],
        "invariant": "只写影子副本，真文件全程字节不变(real_untouched)",
    }


# ── 自检 ─────────────────────────────────────────────────────────────
def selfcheck(quiet: bool = False) -> bool:
    """自检：誊得对 / 本就规整不动 / 源码弃权 / 坏 JSON 弃权 / 保义闸拦住语义漂移 / 全程真身字节不变。

    全程在隔离临时目录里跑(真文件、影子副本都在临时目录)，确定性、无外部副作用。供 evidence 复跑。
    """
    failures: list[str] = []

    def in_tmp(fn):
        with tempfile.TemporaryDirectory(prefix="shadowscribe-") as d:
            fn(pathlib.Path(d))

    # 1) JSON 规范化：紧凑+乱序的 .json → 誊出规整版、保义过、真身字节不变、影子内容数据相等
    def s_json(dp):
        target = dp / "conf.json"
        raw = '{"b":1,"a":[2,3]}'          # 紧凑、键无序、无末尾换行
        target.write_text(raw, encoding="utf-8")
        before_sha = _sha256(raw)
        r = scribe(target, shadow_dir=dp / "shadow")
        if not r.proposed:
            failures.append(f"乱序紧凑 JSON 该被誊写，实得未誊：{r.detail}")
        if not r.oracle_ok:
            failures.append("JSON 规范化是纯重排，保义闸该过，实得没过")
        if not r.real_untouched or target.read_text(encoding="utf-8") != raw:
            failures.append("JSON 誊写后真文件竟被改动——影子落盘的命根子破了")
        if _sha256(target.read_text(encoding="utf-8")) != before_sha:
            failures.append("JSON 誊写后真文件 sha256 变了")
        if r.shadow and json.loads(pathlib.Path(r.shadow).read_text()) != json.loads(raw):
            failures.append("影子副本的数据该与原文件相等(只换排版)，实得不等")
        if r.shadow and pathlib.Path(r.shadow).read_text(encoding="utf-8") != \
                '{\n  "a": [\n    2,\n    3\n  ],\n  "b": 1\n}\n':
            failures.append("影子副本该是 indent=2/sort_keys 的规范化形态，实得不符")
    in_tmp(s_json)

    # 2) 文档去尾空白：带行尾空白+无末尾换行的 .md → 誊出整理版、保义过、真身不动
    def s_doc(dp):
        target = dp / "NOTE.md"
        raw = "# 标题   \n正文有尾空白\t\n末行无换行"
        target.write_text(raw, encoding="utf-8")
        r = scribe(target, shadow_dir=dp / "shadow")
        if not r.proposed:
            failures.append(f"带行尾空白的文档该被誊写，实得未誊：{r.detail}")
        if not r.oracle_ok:
            failures.append("去空白是纯整理，保义闸(抹空白后相同)该过，实得没过")
        if not r.real_untouched or target.read_text(encoding="utf-8") != raw:
            failures.append("文档誊写后真文件竟被改动")
        if r.shadow and pathlib.Path(r.shadow).read_text(encoding="utf-8") != \
                "# 标题\n正文有尾空白\n末行无换行\n":
            failures.append("影子副本该是去尾空白+单末尾换行的整理形态，实得不符")
    in_tmp(s_doc)

    # 3) 本就规整：规范化过的 JSON 再誊 → 无需誊写(proposed=False)、真身不动、不为动而动
    def s_clean(dp):
        target = dp / "tidy.json"
        clean = '{\n  "a": 1,\n  "b": 2\n}\n'   # 已是 indent=2/sort_keys/末尾换行
        target.write_text(clean, encoding="utf-8")
        r = scribe(target, shadow_dir=dp / "shadow")
        if r.proposed or r.shadow:
            failures.append(f"已规整的 JSON 不该再誊、不该落影子，实得 {r.to_meta()}")
        if not r.real_untouched:
            failures.append("对已规整文件该原样不动，真身却被碰了")
    in_tmp(s_clean)

    # 4) 低风险闸：源码 .py → 当场弃权(scribe=""、proposed=False)，真身不动
    def s_reject_py(dp):
        target = dp / "mod.py"
        raw = "x=1  \n"        # 哪怕有尾空白也不接：源码不是本层的练手地
        target.write_text(raw, encoding="utf-8")
        r = scribe(target, shadow_dir=dp / "shadow")
        if r.proposed or r.scribe != "":
            failures.append(f".py 该被低风险闸弃权(不接源码)，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != raw:
            failures.append(".py 弃权后真文件竟被改动")
    in_tmp(s_reject_py)

    # 5) 坏 JSON：.json 但根本解析不了 → 誊不动、保守弃权、真身不动(不崩)
    def s_bad_json(dp):
        target = dp / "broken.json"
        raw = "{not valid json,,,"
        target.write_text(raw, encoding="utf-8")
        r = scribe(target, shadow_dir=dp / "shadow")
        if r.proposed or r.shadow:
            failures.append(f"坏 JSON 该弃权、不落影子，实得 {r.to_meta()}")
        if target.read_text(encoding="utf-8") != raw:
            failures.append("坏 JSON 弃权后真文件竟被改动")
    in_tmp(s_bad_json)

    # 6) 保义闸真能拦语义漂移：直接喂判据一个「丢了键」的伪誊本，必须判 False
    #    (证明若哪支笔誊出改了意思的内容，第 3 道闸会拒、连影子都不写)
    drift_before = '{"a": 1, "b": 2}'
    drift_after = '{\n  "a": 1\n}\n'        # 少了键 b：数据不再相等
    if _json_oracle(drift_before, drift_after):
        failures.append("JSON 保义闸该判出『丢了键 b』是语义漂移(False)，实得放行")
    doc_drift_before = "hello world"
    doc_drift_after = "hello  WORLD\n"      # 改了可见字符：抹空白后不相同
    if _doc_oracle(doc_drift_before, doc_drift_after):
        failures.append("文档保义闸该判出『改了可见内容』是漂移(False)，实得放行")

    # 7) write_shadow=False：誊得出但只看不写，影子不落、真身不动
    def s_dry(dp):
        target = dp / "d.json"
        raw = '{"z":9,"a":1}'
        target.write_text(raw, encoding="utf-8")
        r = scribe(target, write_shadow=False, shadow_dir=dp / "shadow")
        if not r.proposed or r.shadow != "":
            failures.append(f"write_shadow=False 该判可誊但不落影子，实得 {r.to_meta()}")
        if not r.real_untouched or target.read_text(encoding="utf-8") != raw:
            failures.append("write_shadow=False 竟动了真身/落了影子")
    in_tmp(s_dry)

    ok = not failures
    if not quiet:
        if ok:
            print("✅ shadowscribe selfcheck：JSON/文档各能亲手誊出规整小修、保义闸拦得住语义漂移、"
                  "源码与坏 JSON 老实弃权，且全程真身一字节不变——影子落盘可信。")
        else:
            print("❌ shadowscribe selfcheck 失败：")
            for f in failures:
                print(f"   · {f}")
    return ok


# ── 演示 ───────────────────────────────────────────────────────────────
def _demo() -> None:
    print("🖋️👻 brain 补丁影子落盘 —— 亲手誊一处低风险小修，只写影子副本，真身分毫不动：\n")
    print(f"   接的后缀：{'、'.join(ALLOWED_EXTS)}（源码 .py 与陌生后缀一律弃权）\n")
    samples = [
        ("conf.json", '{"b":1,"a":[2,3]}', "🎯 JSON 紧凑+乱序 → 规范化"),
        ("NOTE.md", "# 标题   \n正文有尾空白\t\n末行无换行", "🎯 文档带行尾空白 → 整理"),
        ("tidy.json", '{\n  "a": 1\n}\n', "🟡 已规整 → 无需誊写"),
        ("mod.py", "x = 1  \n", "🚫 源码 → 低风险闸弃权"),
        ("broken.json", "{not valid,,,", "🚫 坏 JSON → 保守弃权"),
    ]
    with tempfile.TemporaryDirectory(prefix="shadowscribe-demo-") as d:
        dp = pathlib.Path(d)
        for fname, raw, label in samples:
            target = dp / fname
            target.write_text(raw, encoding="utf-8")
            r = scribe(target, shadow_dir=dp / "shadow")
            if r.proposed:
                mark = f"🟢 誊了 {r.changed_lines} 行 → 影子已落"
            elif r.scribe and r.oracle_ok and not r.diff:
                mark = "🟡 无需誊写"
            else:
                mark = "⚪ 弃权"
            body = (f"      {r.detail}\n      真身未动：{'是 ✅' if r.real_untouched else '否 ⚠️'}")
            print(f"  {label}（{fname}）\n      {mark}\n{body}")
            if r.diff:
                preview = "\n".join("        " + ln for ln in r.diff.rstrip().splitlines())
                print(f"      brain 这一爪改了什么(影子 diff)：\n{preview}")
            print()


def _shadow_from_path(path: str, *, quiet: bool) -> int:
    """对真仓库内 path 誊一爪，只写影子副本并打 diff(真身不动)。返回退出码。

    0 = 誊出并落影子；1 = 无可誊写/被闸拦下；2 = 路径越界(只许仓库内文件)。
    """
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):   # 只许碰仓库内文件，挡掉 ../ 越界
        if not quiet:
            print(f"⛔ 拒绝：{path} 解析到仓库之外（{target}），影子誊写只对仓库内文件落笔")
        return 2
    r = scribe(target)
    if not quiet:
        if r.proposed:
            print(f"🟢 {target.name}：{r.detail}")
            print(f"   影子副本：{r.shadow}")
            print(f"   真身未动：{'是 ✅' if r.real_untouched else '否 ⚠️ 契约被破坏'}")
            if r.diff:
                print("   --- 影子 diff ---")
                print("\n".join("   " + ln for ln in r.diff.rstrip().splitlines()))
        else:
            print(f"🟡 {target.name}：{r.detail}")
    return 0 if r.proposed else 1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab brain 补丁影子落盘 🖋️👻")
    ap.add_argument("--selfcheck", action="store_true",
                    help="自检:誊得对 / 保义闸拦语义漂移 / 全程真身字节不变(供 evidence 复跑)")
    ap.add_argument("--json", action="store_true", help="机读:接哪些后缀 + 各支笔")
    ap.add_argument("--shadow", metavar="PATH",
                    help="对真仓库内 PATH 誊一爪,只写影子副本并打 diff(真身不动)")
    ap.add_argument("--quiet", action="store_true", help="静默,仅以退出码表态")
    args = ap.parse_args(argv)

    if args.selfcheck:
        sys.exit(0 if selfcheck(quiet=args.quiet) else 1)
    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return
    if args.shadow:
        sys.exit(_shadow_from_path(args.shadow, quiet=args.quiet))
    if not args.quiet:
        _demo()


if __name__ == "__main__":
    main()
