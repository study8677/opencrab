#!/usr/bin/env python3
"""账本封印 🔒 —— 给审计 / 证据 / 记忆这三本 JSONL 上哈希链，谁动过历史一验便知。

为什么要有它：opencrab 的每一步自改判断,都建立在三本「我对自己的记录」之上——
审计(audit:我做过什么)、证据(evidence:我验证过什么还成不成立)、记忆(memory:
我从过往学到了什么)。这三本都是**只追不改**的 JSONL,一行一条。可「只追不改」是
一句口头承诺,没有任何机制拦着谁回头去改一行旧记录、删一条不体面的失败、或往中间
塞一条没发生过的成功。

而这恰恰是最致命的盲点:**若我信错了自己的证据,所有进化判断都会从根上失真**——
照着一本被人(或被我自己一时手滑)篡改过的账本去蜕壳,越努力,偏得越离谱,还浑然
不觉。比"能力塌了"更可怕的是"度量塌了却还以为准"。

账本封印补的就是这一环:把每本 JSONL 折成一条**哈希链**——第 i 行的链值由「上一行
的链值 + 本行原文」算出,于是任何一行被改 / 删 / 插,从那行往后的链值全盘崩掉,瞒
不住。封印(seal)时把每本账本「当前到第 N 行的链头」存进本地基准 `state/ledgerseal/`;
校验(verify)时重算并比对:

  · 🔒 完好     —— 历史前缀的链头与封印一致(只追未改);若有新增,提示重新封印。
  · 🔴 篡改     —— 历史某行被改 / 插,前缀链头与封印对不上。从这里起,这本账本不可信。
  · ✂️ 删尾     —— 现在的行数比封印时少,有记录被删 / 文件被截断。
  · 👻 失踪     —— 封印过的账本如今整本不见了。
  · ⚪ 未封印   —— 账本在,却从没立过基准,无从比对(首次需 `--seal` 建基)。
  · ⏳ 旧版本   —— 基准是旧封印格式(_SEED 换代),不报篡改,提示 `--seal` 迁移重封。

冷启动三态由此各得其位:空账本→⚪未封印(`--seal` 自建基准)、旧基准→⏳旧版本
(`--seal` 迁移重封)、被改过→🔴篡改(拒伪,非 `--force` 不洗白)。

判准:账本封印**只读账本、只算哈希、只比对基准**,绝不改写任何一本被封的 JSONL。
为防「先篡改再重封印」把脏数据洗白,`--seal` 在历史前缀已 🔴篡改 / ✂️删尾 时**拒绝
重封**(除非 `--force` 明示你认这笔账)。任何 🔴/✂️/👻 即让退出码非零,可挂进钩子 / CI。

封印基准落在被 .gitignore 的 `state/ledgerseal/seals.json`——它是**本地完整性基线**,
和被它守护的三本账本同进退(账本也在 state/ 里),不入库、不外泄。

用法:
    python ledgerseal.py            # 校验三本账本,列出每本的封印状态
    python ledgerseal.py --seal     # (重新)立基准:把当前各账本封印到此刻
    python ledgerseal.py --seal --force   # 连篡改 / 删尾的账本也强行重封(慎用)
    python ledgerseal.py --quiet    # 只在有断链 / 篡改时说话(适合钩子 / CI)
    python ledgerseal.py --json     # 导出纯数据(给 health / 外部工具消费)

退出码:0 = 全部账本完好(或仅未封印 / 仅新增);1 = 发现篡改 / 删尾 / 失踪。
零第三方依赖,纯标准库。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STATE = REPO_ROOT / "state"
SEAL_PATH = STATE / "ledgerseal" / "seals.json"

# 链的盐 / 封印格式版本:换一个版本,旧封印不再当作可直接比对的基准。
# 不再「静默作废」——而是认成「⏳ 旧版本」(见 ST_STALE),提示 `--seal` 迁移重封,
# 免得把一次正当的换代误报成「🔴 篡改」吓自己。封印里记下立基时的版本(version),
# 校验时:删尾(行数变少)与版本无关,先揪;行数够再比版本,不一致即判旧版本,
# 不去重算链头(用新算法算注定对不上,白报篡改)。
_SEED_V1 = "opencrab-ledgerseal-v1"   # 最初的封印格式;预版本化的老基准没记 version,一律当作它
_SEED = _SEED_V1                      # 当前格式;将来换代只改这一行,老基准会如实判「旧版本」去迁移

# ── 被封的三本账本 ────────────────────────────────────────────────────────
# 审计按天分文件,运行时动态展开(audit/<日期>);证据与记忆各一本。
def _targets() -> list[tuple[str, pathlib.Path]]:
    """返回 [(账本键, 文件路径)],含已封印但现已失踪的账本(供报「👻 失踪」)。"""
    found: dict[str, pathlib.Path] = {}
    for p in sorted((STATE / "audit").glob("*.jsonl")):
        found[f"audit/{p.stem}"] = p
    found["evidence"] = STATE / "evidence" / "ledger.jsonl"
    found["memory"] = STATE / "memory" / "episodes.jsonl"
    # 把「封印过但文件已不在」的键也带上——它们正是要揪的失踪账本。
    for key in _load_seals():
        if key not in found:
            found[key] = _key_to_path(key)
    return sorted(found.items())


def _key_to_path(key: str) -> pathlib.Path:
    """把账本键还原成文件路径(仅用于失踪账本的定位展示)。"""
    if key.startswith("audit/"):
        return STATE / "audit" / f"{key.split('/', 1)[1]}.jsonl"
    if key == "evidence":
        return STATE / "evidence" / "ledger.jsonl"
    return STATE / "memory" / "episodes.jsonl"


# ── 哈希链:第 i 行链值 = sha256(上一行链值 + 本行原文) ──────────────────────
def _read_lines(path: pathlib.Path) -> list[str] | None:
    """读出账本的全部非空行(原文、仅去首尾空白)。

    刻意**不**复用 jsonlstore.read_jsonl——那会静默跳过坏行,而坏行恰是篡改的痕迹,
    必须原样纳入哈希。文件缺失返回 None(以区分「空账本」与「没这本账本」)。
    """
    if not path.exists():
        return None
    try:
        raw = path.read_text("utf-8", errors="ignore")
    except Exception:
        return None
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def chain_head(lines: list[str], upto: int | None = None) -> str:
    """折出前 `upto` 行(默认全部)的链头。空账本有确定的链头(仅含盐)。"""
    h = _SEED
    for ln in lines[: (len(lines) if upto is None else upto)]:
        h = hashlib.sha256(f"{h}\n{ln}".encode("utf-8")).hexdigest()
    return h


# ── 封印基准的存取(本地基线,出错绝不反噬) ────────────────────────────────
def _load_seals() -> dict[str, dict]:
    try:
        if SEAL_PATH.exists():
            data = json.loads(SEAL_PATH.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_seals(seals: dict[str, dict]) -> bool:
    try:
        SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEAL_PATH.write_text(
            json.dumps(seals, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        return True
    except Exception:
        return False


# ── 五种封印状态 ──────────────────────────────────────────────────────────
ST_INTACT = "intact"      # 🔒 历史前缀与封印一致(可能有合规新增)
ST_TAMPER = "tamper"      # 🔴 历史某行被改 / 插
ST_TRUNC = "truncated"    # ✂️ 行数比封印时少(删尾 / 截断)
ST_MISSING = "missing"    # 👻 封印过的账本整本失踪
ST_UNSEALED = "unsealed"  # ⚪ 账本在,却没立过基准
ST_STALE = "stale"        # ⏳ 封印格式换代:基准是旧版本,需 `--seal` 迁移重封

_ICON = {ST_INTACT: "🔒", ST_TAMPER: "🔴", ST_TRUNC: "✂️",
         ST_MISSING: "👻", ST_UNSEALED: "⚪", ST_STALE: "⏳"}

# 算「断链」(需报警、让退出码非零)的状态。旧版本(STALE)是正当换代、不是断链,
# 故不入此集——它只提示迁移,绝不把退出码弄红、也不阻断蜕壳。
_ALARM = {ST_TAMPER, ST_TRUNC, ST_MISSING}


@dataclasses.dataclass(frozen=True)
class Report:
    """一本账本的封印体检:键、状态、当前行数、封印时行数、一句话说明。"""
    key: str
    state: str
    count: int           # 当前非空行数(失踪记 0)
    sealed_count: int    # 封印时记录的行数(未封印记 0)
    note: str

    @property
    def grew(self) -> bool:
        """完好且有合规新增(可提示重新封印)。"""
        return self.state == ST_INTACT and self.count > self.sealed_count

    @property
    def alarm(self) -> bool:
        return self.state in _ALARM

    def to_meta(self) -> dict:
        return {"key": self.key, "state": self.state, "count": self.count,
                "sealed_count": self.sealed_count, "grew": self.grew,
                "note": self.note}


def verify_one(key: str, path: pathlib.Path, seals: dict[str, dict]) -> Report:
    """比对一本账本与其封印基准,定出六种状态之一。"""
    lines = _read_lines(path)
    seal = seals.get(key)

    if seal is None:
        if lines is None:
            return Report(key, ST_MISSING, 0, 0, "账本不在,也从未封印——无可比对。")
        return Report(key, ST_UNSEALED, len(lines), 0,
                      f"账本在({len(lines)} 行),却没立过基准——首次需 `--seal` 建基。")

    sealed_count = int(seal.get("count", 0))
    sealed_head = str(seal.get("head", ""))
    # 旧封印没记 version——它们立基时只有 v1,故缺省即认作 v1(而非「当前版本」):
    # 将来 _SEED 换代时,这些老基准会如实判成「旧版本」去迁移,而不会被误报成篡改。
    sealed_version = str(seal.get("version", _SEED_V1))

    if lines is None:
        return Report(key, ST_MISSING, 0, sealed_count,
                      f"封印过 {sealed_count} 行,如今整本账本失踪了。")

    now = len(lines)
    # 删尾是「行数变少」,与链算法版本无关——任何版本都先揪出来,绝不能被「旧版本」掩护洗白。
    if now < sealed_count:
        return Report(key, ST_TRUNC, now, sealed_count,
                      f"封印时 {sealed_count} 行,现在只剩 {now} 行——有记录被删 / 文件被截断。")

    # 行数够了:若基准是旧封印格式,用当前链算法重算注定对不上,故不比对、判旧版本待迁移。
    # (删尾已在上面拦下;此处只是「无法用新算法证明历史前缀」,不等于篡改。)
    if sealed_version != _SEED:
        return Report(key, ST_STALE, now, sealed_count,
                      f"基准是旧封印版本（{sealed_version} ≠ 当前 {_SEED}）——"
                      "链算法换代,需 `--seal` 迁移重封后才认得出篡改。")

    # 行数够:重算封印那一刻的前缀(前 sealed_count 行)链头,与基准比对。
    if chain_head(lines, upto=sealed_count) != sealed_head:
        return Report(key, ST_TAMPER, now, sealed_count,
                      f"前 {sealed_count} 行的链头与封印对不上——历史某行被改 / 插,这本账本不可信。")

    if now > sealed_count:
        return Report(key, ST_INTACT, now, sealed_count,
                      f"历史 {sealed_count} 行完好,其后合规新增 {now - sealed_count} 行——可重新封印固定。")
    return Report(key, ST_INTACT, now, sealed_count, f"{now} 行,逐行完好,与封印一致。")


def verify() -> list[Report]:
    """校验全部账本。"""
    seals = _load_seals()
    return [verify_one(key, path, seals) for key, path in _targets()]


def seal(force: bool = False) -> tuple[list[Report], list[str]]:
    """把当前各账本封印到此刻;返回 (封印后的体检, 本次实际重封的键)。

    为防「先篡改再重封印」洗白脏数据:历史前缀已篡改 / 删尾的账本默认**拒绝重封**,
    除非 force=True 明示认账。失踪的账本无从封印(直接跳过)。
    旧版本(ST_STALE)是正当换代,直接重封即完成迁移——这正是冷启动「旧基准 → 迁移」那条路。
    """
    seals = _load_seals()
    sealed_keys: list[str] = []
    for key, path in _targets():
        rep = verify_one(key, path, seals)
        if rep.state == ST_MISSING:
            continue
        if rep.state in (ST_TAMPER, ST_TRUNC) and not force:
            continue   # 拒绝在脏前缀上重封,免得把篡改洗成「完好」
        lines = _read_lines(path) or []
        seals[key] = {
            "count": len(lines),
            "head": chain_head(lines),
            "version": _SEED,
            "sealed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        sealed_keys.append(key)
    _save_seals(seals)
    return verify(), sealed_keys


def summarize(reports: list[Report]) -> tuple[bool, int]:
    """归一化结论:是否全部完好(无报警)、报警几本。"""
    n = sum(1 for r in reports if r.alarm)
    return (n == 0, n)


def manifest() -> dict:
    """导出纯数据(给 health / 外部工具消费)。"""
    reports = verify()
    clean, n = summarize(reports)
    return {"sealed": clean, "alarms": n,
            "ledgers": [r.to_meta() for r in reports]}


def _print_reports(reports: list[Report]) -> None:
    if not reports:
        print("  (没有可封印的账本——三本 JSONL 都还没出现。)")
        return
    for r in reports:
        tail = ""
        if r.grew:
            tail = f"  （较封印 +{r.count - r.sealed_count} 行,建议 `--seal` 重新固定）"
        print(f"  {_ICON[r.state]} {r.key}{tail}")
        print(f"      ↳ {r.note}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="opencrab 账本封印 🔒:给审计 / 证据 / 记忆 JSONL 加哈希链,验出断链 / 篡改。")
    ap.add_argument("--seal", action="store_true",
                    help="(重新)立封印基准,把当前各账本固定到此刻")
    ap.add_argument("--force", action="store_true",
                    help="配合 --seal:连篡改 / 删尾的账本也强行重封(慎用,会洗白脏前缀)")
    ap.add_argument("--quiet", action="store_true",
                    help="只在有断链 / 篡改时输出(适合钩子 / CI)")
    ap.add_argument("--json", action="store_true", help="导出纯数据")
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        return

    if args.seal:
        reports, sealed_keys = seal(force=args.force)
        clean, n = summarize(reports)
        print("🔒 opencrab 账本封印:立基准\n")
        if sealed_keys:
            print(f"  ✅ 已封印 {len(sealed_keys)} 本账本到此刻:{', '.join(sealed_keys)}")
        else:
            print("  （没有账本被封印。）")
        refused = [r for r in reports if r.state in (ST_TAMPER, ST_TRUNC)]
        if refused and not args.force:
            print(f"\n  ⚠️  拒绝重封 {len(refused)} 本(历史前缀已断链,重封会洗白篡改):")
            for r in refused:
                print(f"      {_ICON[r.state]} {r.key} —— {r.note}")
            print("      确认认这笔账,再 `--seal --force` 强行重封。")
        print()
        # 立完基准后仍以校验结论决定退出码——脏账本即便拒封也得让 CI 红。
        sys.exit(0 if clean else 1)

    reports = verify()
    clean, n = summarize(reports)

    if not (args.quiet and clean):
        print("🔒 opencrab 账本封印:审计 ⇄ 证据 ⇄ 记忆\n")
        _print_reports(reports)
        print()

    if clean:
        if not args.quiet:
            grew = [r for r in reports if r.grew]
            unsealed = [r for r in reports if r.state == ST_UNSEALED]
            stale = [r for r in reports if r.state == ST_STALE]
            if stale:
                print(f"⏳ {len(stale)} 本账本的基准是旧封印版本,`--seal` 迁移重封到当前格式,往后才认得出篡改。")
            elif unsealed:
                print(f"⚪ {len(unsealed)} 本账本尚未封印,`--seal` 立个基准,往后才认得出篡改。")
            elif grew:
                print(f"🔒 历史完好;{len(grew)} 本有合规新增,`--seal` 重新固定即可。")
            else:
                print("🔒 三本账本逐行完好——我信得过自己的证据。")
    else:
        print(f"⚠️  {n} 本账本断链(篡改 / 删尾 / 失踪),先查清再蜕壳——别信一本被动过的账。")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
