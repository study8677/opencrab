#!/usr/bin/env python3
"""结构化错误码与失败分流 🚑 —— 把常见失败统一映射成可识别的错误类型。

为什么要有它：心跳里散落的失败各说各话——HTTP 401、URLError、py_compile
报错、合并冲突……同是「出错」，定位方式、修复手段天差地别。最怕的不是失败，
是「看起来失败了，却不知道为什么、也不知道下一步该怎么办」的盲区。

这里把启动、自检、进化、回放、大脑这几处常见失败，归成一张稳定的**错误码目录**：
每个错误码带「人话标题 + 它意味着什么 + 一条固定的修复建议」。再给一个分流器
`classify(...)`：吃一份失败现场(异常 / HTTP 码 / stderr / 退出码)，匹配出最贴切
的错误码。于是审计里留下的不再是一句模糊的 `error=...`，而是
`code=E-BRAIN-AUTH · 大脑拒绝：密钥无效或无权限 · 修复：检查 OPENCRAB_API_KEY`。

错误码命名：`E-<域>-<具体>`，域取自失败发生的环节(BRAIN/HANDS/EVOLVE/REPLAY/
STARTUP/CONFIG)。目录是单一真相源，CLI 与 `cap_errors` 能力都从这里读。

零第三方依赖，纯标准库。

用法:
    python errors.py            # 列出全部错误码目录(按域分组)
    python errors.py <文本>     # 把一段失败信息分流成错误码，看它属于哪类、怎么修
"""
from __future__ import annotations

import dataclasses
import re
import sys
from typing import Callable


@dataclasses.dataclass(frozen=True)
class ErrorSpec:
    """一种可识别的失败类型。"""
    code: str                  # 稳定标识，形如 E-BRAIN-AUTH
    domain: str                # 失败发生的环节(给目录分组)
    title: str                 # 一句人话：这到底是什么错
    hint: str                  # 固定的修复建议：下一步该做什么
    # 匹配谓词：吃一份失败现场 ctx，命中返回 True。None 表示仅作兜底，不参与匹配。
    match: Callable[[dict], bool] | None = None

    def to_meta(self) -> dict:
        """导出纯数据(供清单 / 目录 / 外部工具消费)。"""
        return {"code": self.code, "domain": self.domain,
                "title": self.title, "hint": self.hint}


# ── 取现场字段的小工具 ──────────────────────────────────────────────
def _text(ctx: dict) -> str:
    """把现场里所有文本线索拼成一段，供正则扫描(小写化便于匹配)。"""
    parts = [str(ctx.get(k, "")) for k in
             ("exc", "stderr", "note", "self_test", "message", "raw")]
    return "  ".join(parts).lower()


def _has(ctx: dict, *needles: str) -> bool:
    blob = _text(ctx)
    return any(n.lower() in blob for n in needles)


# ── 错误码目录(单一真相源)──────────────────────────────────────────
# 顺序即优先级：越靠前越具体，分流时取第一个命中的。
CATALOG: list[ErrorSpec] = [
    # 大脑(brain)：调用 OpenAI 兼容端点时的失败
    ErrorSpec("E-BRAIN-AUTH", "大脑",
              "大脑拒绝：密钥无效或无权限",
              "检查 .env 里的 OPENCRAB_API_KEY 是否正确、是否还有余额/权限。",
              lambda c: c.get("http_status") in (401, 403)),
    ErrorSpec("E-BRAIN-RATELIMIT", "大脑",
              "大脑被限流：请求太频繁",
              "调大 OPENCRAB_TICK_SECONDS 放慢心跳，或稍后再试。",
              lambda c: c.get("http_status") == 429
              or _has(c, "rate limit", "too many requests")),
    ErrorSpec("E-BRAIN-NETWORK", "大脑",
              "够不到大脑：网络不通或超时",
              "检查网络连通性与 OPENCRAB_BASE_URL 是否可达(端点拼写、代理、防火墙)。",
              lambda c: _has(c, "urlerror", "timed out", "timeout",
                             "connection", "getaddrinfo", "name or service")),
    ErrorSpec("E-BRAIN-HTTP", "大脑",
              "大脑返回异常状态码",
              "看返回码与响应体确认 OPENCRAB_BASE_URL / OPENCRAB_MODEL 配置是否匹配端点。",
              lambda c: isinstance(c.get("http_status"), int)
              or _has(c, "httperror")),

    # 手(hands)：雇佣爪子改文件这一步的失败
    ErrorSpec("E-HANDS-MISSING", "手",
              "找不到执行器 CLI：没有爪子可用",
              "安装对应 CLI(claude / codex)，或改 OPENCRAB_EXECUTOR 指向已装的那个。",
              lambda c: _has(c, "未找到", "not found", "no hands", "cli")),
    ErrorSpec("E-HANDS-BRANCH", "手",
              "开分支失败：分支可能已存在",
              "删除同名分支(git branch -D)，或换一个意图让分支名不同。",
              lambda c: _has(c, "开分支失败", "checkout -b", "already exists")),
    ErrorSpec("E-HANDS-NOCHANGE", "手",
              "爪子没做出任何改动(空跑)",
              "这不一定是故障：把意图写得更具体、可落地，给爪子明确的下手点。",
              lambda c: _has(c, "没做出任何改动", "no change", "空跑")),

    # 进化(evolve)：自测 / 合并 / 推送这些「把改动并进自己」的失败
    ErrorSpec("E-EVOLVE-SELFTEST", "进化",
              "自测没过：改完自己起不来了",
              "改动已自动回滚保命；看 self_test 里的语法/导入报错定位问题，修好再来。",
              lambda c: _has(c, "自测", "self_test", "py_compile",
                             "语法错误", "导入失败", "self-test")),
    ErrorSpec("E-EVOLVE-MERGE", "进化",
              "合并冲突：改动并不进主干",
              "改动留在分支了；手动 checkout 分支解决冲突后再合并。",
              lambda c: _has(c, "合并冲突", "merge conflict", "conflict")),
    ErrorSpec("E-EVOLVE-PUSH", "进化",
              "已合并到本地，但 push 到公开仓失败",
              "检查 origin 远端是否配置、是否有推送凭据与网络;改动已安全在本地主干。",
              lambda c: _has(c, "push 失败", "push failed", "rejected",
                             "remote")),

    # 回放 / 启动 / 配置
    ErrorSpec("E-REPLAY-BADDAY", "回放",
              "回放日期格式不对",
              "用 YYYY-MM-DD 格式，例如 2026-05-25。",
              lambda c: _has(c, "yyyy-mm-dd", "isoformat", "--day")),
    ErrorSpec("E-REPLAY-EMPTY", "回放",
              "这一天没有审计记录可回放",
              "先让 opencrab 心跳一次(python crab.py once)产生审计，再回放。",
              lambda c: _has(c, "没有审计记录", "no records", "为空")),
    ErrorSpec("E-STARTUP-IMPORT", "启动",
              "启动失败：模块导入或语法出错",
              "在仓库根跑 python -m py_compile *.py 找出坏文件;近期改动可先回退。",
              lambda c: _has(c, "importerror", "modulenotfound",
                             "syntaxerror", "no module named")),
    ErrorSpec("E-CONFIG-VALUE", "配置",
              "配置值非法：环境变量解析失败",
              "检查 .env 里数值型变量(TICK_SECONDS / DAILY_ENERGY 等)是否为合法整数。",
              lambda c: _has(c, "valueerror", "invalid literal", "int(")),
]

# 兜底：任何没被认领的失败都归到这里，绝不留「不知道为什么」的盲区。
UNKNOWN = ErrorSpec("E-UNKNOWN", "未知",
                    "未能归类的失败",
                    "把这段失败现场贴进 `python errors.py <文本>` 看线索;"
                    "若反复出现，考虑给 errors.py 的目录补一条新错误码。")

_BY_CODE = {spec.code: spec for spec in CATALOG}
_BY_CODE[UNKNOWN.code] = UNKNOWN


# ── 分流 ────────────────────────────────────────────────────────────
def classify(**ctx) -> ErrorSpec:
    """把一份失败现场分流成一个错误码。

    现场字段(都可选)：
        http_status : int      —— 大脑返回的 HTTP 状态码
        exc         : str|Exception —— 异常对象或其 repr
        stderr/note/self_test/message/raw : str —— 任何文本线索
    取第一个命中的错误码；都不中则归到 E-UNKNOWN，绝不抛错。
    """
    if "exc" in ctx and isinstance(ctx["exc"], BaseException):
        ctx["exc"] = repr(ctx["exc"])
    for spec in CATALOG:
        try:
            if spec.match and spec.match(ctx):
                return spec
        except Exception:
            continue   # 分流器自身绝不能成为新的故障源
    return UNKNOWN


def get(code: str) -> ErrorSpec | None:
    return _BY_CODE.get(code)


def triage(**ctx) -> dict:
    """分流并返回一条结构化结果(供审计 record / 打印复用)。"""
    spec = classify(**ctx)
    return {"code": spec.code, "domain": spec.domain,
            "title": spec.title, "hint": spec.hint}


def explain(spec: ErrorSpec) -> str:
    """把一个错误码渲染成一行人话(给日志 / CLI 用)。"""
    return f"{spec.code} · {spec.title} · 修复：{spec.hint}"


def by_domain() -> dict[str, list[ErrorSpec]]:
    """把目录按域分组(给清单 / 帮助自动生成用)。"""
    grouped: dict[str, list[ErrorSpec]] = {}
    for spec in CATALOG:
        grouped.setdefault(spec.domain, []).append(spec)
    return grouped


def manifest() -> dict:
    """🚑 错误码清单：全部错误码的可发现目录(纯数据)。"""
    return {"total": len(CATALOG),
            "domains": list(by_domain()),
            "errors": [s.to_meta() for s in CATALOG]}


# ── CLI ─────────────────────────────────────────────────────────────
def _print_catalog() -> None:
    print("🚑 opencrab 错误码目录\n")
    for domain, specs in by_domain().items():
        print(f"【{domain}】")
        for s in specs:
            print(f"  {s.code:<18} {s.title}")
            print(f"  {'':<18} 修复：{s.hint}")
        print()
    print(f"共 {len(CATALOG)} 个错误码;兜底 {UNKNOWN.code}。")


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        _print_catalog()
        return
    blob = " ".join(argv)
    spec = classify(message=blob)
    print(f"🚑 分流结果：{spec.code}（{spec.domain}）")
    print(f"   {spec.title}")
    print(f"   修复：{spec.hint}")


if __name__ == "__main__":
    main()
