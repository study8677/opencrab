"""
opencrab 的能力注册中心 🧩 —— 把「自检、快照、干跑、日志……」拆成可插拔的能力。

每个能力是本目录下一个 `cap_*.py` 模块，用 `@capability(...)` 把自己登记进来。
新增一种能力，只要丢一个新的 `cap_*.py` 文件——核心不必再往一个大文件里堆。

- 自动发现：导入本包时，扫描并加载所有 `cap_*.py`，它们各自完成登记。
- 按需启用：环境变量 `OPENCRAB_CAPABILITIES`（逗号分隔）白名单选择要开的能力；
  留空则启用所有「默认开启」的能力。
- 运行隔离：单个能力运行出错绝不弄死这只生命，会被收敛成一条失败结果。

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import dataclasses
import importlib
import os
import pathlib
import traceback
from typing import Callable

_CAP_DIR = pathlib.Path(__file__).resolve().parent


@dataclasses.dataclass
class Capability:
    """一种可插拔能力的登记信息。"""
    name: str                         # 稳定的标识(给 CLI / 白名单用)
    summary: str                      # 一句人话说明它干什么
    run: Callable[[dict], "Result"]   # 真正执行：吃一个 ctx，吐一个 Result
    default: bool = True              # 是否默认启用


@dataclasses.dataclass
class Result:
    """一次能力运行的结果——统一格式，方便上层打印或做决策。"""
    ok: bool
    summary: str
    detail: str = ""
    data: dict | None = None


# name -> Capability
_REGISTRY: dict[str, Capability] = {}
_DISCOVERED = False


def capability(name: str, summary: str, *, default: bool = True):
    """装饰器：把一个 `run(ctx) -> Result` 函数登记成一种能力。

    用法见任意 `cap_*.py`。重复登记同名能力会直接报错(防止悄悄覆盖)。
    """
    def deco(fn: Callable[[dict], Result]) -> Callable[[dict], Result]:
        if name in _REGISTRY:
            raise ValueError(f"能力 {name!r} 已被登记，换个名字。")
        _REGISTRY[name] = Capability(name=name, summary=summary, run=fn, default=default)
        return fn
    return deco


def discover() -> None:
    """扫描本目录下所有 `cap_*.py` 并导入，触发它们的自我登记(幂等)。"""
    global _DISCOVERED
    if _DISCOVERED:
        return
    for path in sorted(_CAP_DIR.glob("cap_*.py")):
        importlib.import_module(f"{__name__}.{path.stem}")
    _DISCOVERED = True


def _whitelist() -> set[str] | None:
    """读 OPENCRAB_CAPABILITIES 白名单；未设或为空 -> None(表示用默认集)。"""
    raw = os.environ.get("OPENCRAB_CAPABILITIES", "").strip()
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def all_capabilities() -> list[Capability]:
    """已登记的全部能力(按名字排序)。"""
    discover()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def enabled_capabilities() -> list[Capability]:
    """当前生效的能力：有白名单则按白名单，否则取所有默认开启的。"""
    wl = _whitelist()
    caps = all_capabilities()
    if wl is None:
        return [c for c in caps if c.default]
    return [c for c in caps if c.name in wl]


def get(name: str) -> Capability | None:
    discover()
    return _REGISTRY.get(name)


def run(name: str, ctx: dict | None = None) -> Result:
    """运行一种能力；能力不存在或自身抛错都收敛成一条 Result，绝不向上炸。"""
    cap = get(name)
    if cap is None:
        return Result(False, f"没有名为 {name!r} 的能力",
                      detail="已登记：" + ", ".join(c.name for c in all_capabilities()))
    try:
        return cap.run(ctx or {})
    except Exception as e:        # 能力自己出错也不该弄死这只螃蟹
        return Result(False, f"能力 {name!r} 运行出错：{e}",
                      detail=traceback.format_exc(limit=3))
