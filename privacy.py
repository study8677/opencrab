#!/usr/bin/env python3
"""落盘前的隐私闸门 🪪🚪 —— 审计 / 记忆写进磁盘之前，先把 PII 脱敏并贴上「保质期」。

为什么要有它：opencrab 每一次心跳都往 `state/audit/*.jsonl` 与 `state/memory/episodes.jsonl`
里沉淀文字——意图、结果、失败现场。这些文本是它喂回自己大脑的养料，但里头随手可能
裹进**别人的痕迹**：调试时贴的真实邮箱、对话里出现的手机号、日志里的 IP。secretscan 守的是
「**别 push 进公开仓**」那道门(只看 `git diff --cached` 的增量)；可 `state/` 被 .gitignore
拦在仓库之外，secretscan 永远扫不到它——于是这些 PII 会**安安静静地无限期堆在本地记忆里**，
没人脱敏、没人设期限、没人清。

privacy 补的就是这一段：**落盘那一刻**的最后一道处理，且只对落盘负责：

  · 脱敏  —— 把文本里的 PII 换成稳定占位符(同一个值 → 同一个 token，能去重、不可还原)，
            脱敏后的文本才允许写进 audit/memory。高危项(身份证/卡号)一律抹掉。
  · 保质期 —— 按 PII 种类给这条记录定一个保留期限(deadline)；最敏感的那类说了算
            (取最短保留天数)。没有 PII 的记录则按默认期限。
  · 删除清单 —— 扫已经落盘的 `state/*.jsonl`，列出**已过保质期**或**仍残留明文 PII**
            (本该脱敏却漏网)的记录，给出该删哪个文件第几条、为什么删。

与邻居的分工：
  · secretscan = 提交闸门，盯 `git diff --cached` 的新增行，防的是「泄进公开仓」。
  · privacy    = 落盘闸门，盯写进 `state/` 的文本，防的是「在本地记忆里滥存他人痕迹」。
  二者共用 secretscan 里那套 PII 正则与 Luhn/占位符判定，不重复造轮子。

PII 识别规则复用 `secretscan`，零第三方依赖，纯标准库。隐私模块是观测者：
读写出错一律吞掉，绝不成为新的故障源。

用法:
    python privacy.py "<一段文本>"     # 看这段文本里有哪些 PII、脱敏成什么、保质期多久
    python privacy.py --sweep          # 扫已落盘的 state/*.jsonl，打印删除清单
    python privacy.py --sweep --json   # 删除清单导出纯数据(给清理脚本 / health 消费)
    python privacy.py --json "<文本>"  # 单段文本的脱敏结果导出纯数据
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import sys

import secretscan
import jsonlstore

_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_STATE = _REPO_ROOT / "state"

# 复用 secretscan 的 PII 正则与判定，privacy 不另起一套(单一真相源)。
SEV_HIGH = secretscan.SEV_HIGH
SEV_LOW = secretscan.SEV_LOW

# ── 保留期限：按 PII 种类定保质期(天)。高危项不该留，给 0 天 = 立即可删。──────
# 取值理念：越能直接定位到个人、越敏感，留得越短。最敏感的那类决定整条记录。
RETENTION_DAYS: dict[str, int] = {
    "中国大陆身份证号": 0,    # 高危：本不该入库，落了也立即列入删除
    "疑似银行卡号": 0,        # 高危：同上
    "中国大陆手机号": 30,     # 能直呼到人，短留
    "IPv4 地址": 30,          # 可定位，短留
    "邮箱地址": 90,           # 相对弱标识，留长一点
}
DEFAULT_RETENTION_DAYS = 30   # 不含 PII 的记录也不无限期留：短期记忆本就该新陈代谢


# ── 一处 PII 命中 ───────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class PiiHit:
    """文本里的一处 PII：种类、严重度、原值、脱敏后的稳定占位符、该类的保留天数。"""
    kind: str
    severity: str
    value: str        # 原始命中值(仅内存中用于替换，不导出/不打印)
    token: str        # 稳定占位符：同值同 token，可去重、不可还原
    retain_days: int

    def to_meta(self) -> dict:
        # value 含真实 PII，刻意不导出。
        return {"kind": self.kind, "severity": self.severity,
                "token": self.token, "retain_days": self.retain_days}


def _stable_token(kind: str, value: str) -> str:
    """为一个 PII 值造稳定占位符：同一个值永远映射到同一个 token。

    后缀取 (种类+值) 的短哈希——既能让重复出现的同一手机号在记忆里仍可被识别为
    「同一个人」(支持去重/关联)，又彻底不可还原(单向哈希，不留原值)。
    """
    digest = hashlib.sha256(f"{kind}\x00{value}".encode("utf-8")).hexdigest()[:6]
    short = kind.replace("中国大陆", "").replace("地址", "")
    return f"‹{short}#{digest}›"


# ── 识别：在任意文本里找出 PII(复用 secretscan 的正则与误报过滤) ──────────
def scan_text(text: str) -> list[PiiHit]:
    """在一段文本里找出所有 PII 命中(种类 / 严重度 / 原值 / 占位符 / 保留天数)。

    占位符与 Luhn/安全域名过滤完全沿用 secretscan，避免对示例值/版本号误报。
    """
    if not text:
        return []
    hits: list[PiiHit] = []
    for sev, label, pat in secretscan._PII_PATTERNS:
        for m in pat.finditer(text):
            hit = m.group(0)
            if secretscan._looks_like_placeholder(hit):
                continue
            if label == "邮箱地址" and any(
                    hit.lower().endswith(d) for d in secretscan._SAFE_EMAIL_DOMAINS):
                continue
            if label == "疑似银行卡号" and not secretscan._luhn_ok(hit):
                continue
            hits.append(PiiHit(
                kind=label, severity=sev, value=hit,
                token=_stable_token(label, hit),
                retain_days=RETENTION_DAYS.get(label, DEFAULT_RETENTION_DAYS)))
    return hits


# ── 脱敏：把文本里每处 PII 换成稳定占位符 ────────────────────────────────
def redact(text: str) -> tuple[str, list[PiiHit]]:
    """返回 (脱敏后的文本, 命中列表)。脱敏后的文本才允许落盘。

    同一个值的所有出现都被换成同一个 token；从长到短替换，避免子串先被换掉。
    """
    hits = scan_text(text)
    if not hits:
        return text, []
    out = text
    for h in sorted(hits, key=lambda x: len(x.value), reverse=True):
        out = out.replace(h.value, h.token)
    return out, hits


def retention_for(hits: list[PiiHit], at: datetime.datetime | None = None) -> dict:
    """据命中决定整条记录的保留期限：最敏感的那类(最短保留)说了算。

    返回 {retain_days, deadline(ISO), driver(决定期限的 PII 种类)}；
    没有 PII 时按 DEFAULT_RETENTION_DAYS。
    """
    at = at or datetime.datetime.now()
    if hits:
        driver = min(hits, key=lambda h: h.retain_days)
        days = driver.retain_days
        driver_kind = driver.kind
    else:
        days = DEFAULT_RETENTION_DAYS
        driver_kind = ""
    deadline = (at + datetime.timedelta(days=days)).date().isoformat()
    return {"retain_days": days, "deadline": deadline, "driver": driver_kind}


def redact_record(text: str, at: datetime.datetime | None = None) -> dict:
    """落盘前的统一入口：给一段待持久化的文本，返回可安全落盘的结果。

    {text: 脱敏后文本, pii: [脱敏元数据], retention: {...}}。
    audit / memory 在写盘前调用它，把 text 换成 result["text"]，并把 retention
    随记录一起存下，sweep 时才有依据判断该不该删。
    """
    safe, hits = redact(text)
    return {"text": safe, "pii": [h.to_meta() for h in hits],
            "retention": retention_for(hits, at)}


# ── 删除清单：扫已落盘的 state/*.jsonl，列出该删的记录 ────────────────────
def _record_timestamp(rec: dict) -> str | None:
    """从一条记录里尽力取出时间戳(audit 用 ts，memory 用 at)。"""
    for key in ("ts", "at", "time", "timestamp"):
        v = rec.get(key)
        if isinstance(v, str) and v:
            return v
    return None

# 哪些字段含可能裹着 PII 的自由文本——只扫这些，别把 run_id/seq 当文本扫。
_TEXT_FIELDS = ("situation", "action", "result", "text", "detail", "message", "note")


def _record_pii(rec: dict) -> list[PiiHit]:
    """一条记录的自由文本字段里残留的 PII(本该脱敏却漏网的)。"""
    hits: list[PiiHit] = []
    for field in _TEXT_FIELDS:
        v = rec.get(field)
        if isinstance(v, str):
            hits.extend(scan_text(v))
    return hits


def _expired(rec: dict, now: datetime.datetime) -> tuple[bool, str]:
    """这条记录是否已过保质期。

    优先读记录里随存的 retention.deadline；没有(老记录)则按其时间戳 + 默认期限推算。
    返回 (是否过期, 截止日期)。无从判断时按未过期处理(宁可不误删)。
    """
    deadline = None
    ret = rec.get("retention")
    if isinstance(ret, dict) and isinstance(ret.get("deadline"), str):
        deadline = ret["deadline"]
    else:
        ts = _record_timestamp(rec)
        if ts:
            try:
                base = datetime.datetime.fromisoformat(ts)
                deadline = (base + datetime.timedelta(
                    days=DEFAULT_RETENTION_DAYS)).date().isoformat()
            except ValueError:
                deadline = None
    if not deadline:
        return False, ""
    try:
        return now.date().isoformat() > deadline, deadline
    except Exception:
        return False, deadline


def sweep(now: datetime.datetime | None = None) -> dict:
    """扫已落盘的 state/*.jsonl，生成删除清单。

    一条记录被列入删除，当且仅当满足任一：
      · 过保质期 —— 短期记忆该新陈代谢，留着只占地方还扩大留存面;
      · 残留明文 PII —— 本该在落盘前脱敏却漏了，存着就是滥存他人痕迹。
    返回 {scanned, doomed:[{file, line, reasons, age_days, pii}], stores:{...}}。
    """
    now = now or datetime.datetime.now()
    files = sorted(_STATE.glob("**/*.jsonl"))
    doomed: list[dict] = []
    scanned = 0
    per_store: dict[str, int] = {}
    for path in files:
        rel = str(path.relative_to(_REPO_ROOT))
        records = jsonlstore.read_jsonl(path)
        for lineno, rec in enumerate(records, 1):
            scanned += 1
            reasons: list[str] = []
            expired, deadline = _expired(rec, now)
            if expired:
                reasons.append(f"过保质期(截止 {deadline})")
            pii = _record_pii(rec)
            if pii:
                kinds = sorted({h.kind for h in pii})
                reasons.append(f"残留明文 PII：{', '.join(kinds)}")
            if reasons:
                doomed.append({
                    "file": rel, "line": lineno, "reasons": reasons,
                    "ts": _record_timestamp(rec) or "",
                    "pii": [h.to_meta() for h in pii]})
        per_store[rel] = len(records)
    return {"scanned": scanned, "doomed": doomed, "stores": per_store}


# ── CLI ─────────────────────────────────────────────────────────────
def _print_text_report(text: str) -> None:
    result = redact_record(text)
    ret = result["retention"]
    print("🪪 落盘前隐私闸门 · 单段文本\n")
    if not result["pii"]:
        print("  ✅ 未发现 PII。可原样落盘。")
    else:
        print(f"  🕵️ 发现 {len(result['pii'])} 处 PII：")
        for p in result["pii"]:
            sev = "🔴高危" if p["severity"] == SEV_HIGH else "🟡提醒"
            print(f"      · {sev} {p['kind']} → 脱敏为 {p['token']}"
                  f"（保留 {p['retain_days']} 天）")
        print("\n  脱敏后(可安全落盘)：")
        print(f"      {result['text'][:200]}")
    drv = f"，由「{ret['driver']}」决定" if ret["driver"] else ""
    print(f"\n  ⏳ 保质期：{ret['retain_days']} 天{drv}，截止 {ret['deadline']}。")


def _print_sweep_report(report: dict) -> None:
    print("🪪 落盘后隐私清扫 · state/*.jsonl 删除清单\n")
    if report["stores"]:
        print("  扫描范围：")
        for store, n in report["stores"].items():
            print(f"      · {store}（{n} 条）")
    print(f"\n  共扫 {report['scanned']} 条记录。")
    doomed = report["doomed"]
    if not doomed:
        print("  ✅ 没有该删的记录：无过期、无残留明文 PII。\n")
        return
    print(f"  🗑️  {len(doomed)} 条建议删除：\n")
    for d in doomed:
        print(f"      [{d['file']}:{d['line']}] {d['ts']}")
        for r in d["reasons"]:
            print(f"          ↳ {r}")
    print("\n  → 残留明文 PII 的，先确认落盘入口已接 redact_record(...) 再清，"
          "免得边删边进；过期的可直接按 (file,line) 清掉。\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="opencrab 落盘前隐私闸门 🪪🚪")
    ap.add_argument("text", nargs="*", help="待脱敏的一段文本")
    ap.add_argument("--sweep", action="store_true",
                    help="扫已落盘的 state/*.jsonl，打印删除清单")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.sweep:
        report = sweep()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_sweep_report(report)
        # 退出码：有残留明文 PII = 落盘入口漏了脱敏，值得阻断关注。
        has_raw_pii = any(d["pii"] for d in report["doomed"])
        sys.exit(1 if has_raw_pii else 0)

    text = " ".join(args.text)
    if not text:
        ap.error("给一段文本来脱敏，或用 --sweep 清扫已落盘记录。")
    if args.json:
        print(json.dumps(redact_record(text), ensure_ascii=False, indent=2))
    else:
        _print_text_report(text)


if __name__ == "__main__":
    main()
