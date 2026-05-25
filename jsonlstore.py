#!/usr/bin/env python3
"""JSONL 落地层 🗄️ —— 记录系统(audit/trace/memory)共用的「读一批 / 追一条」单一真相源。

为什么要有它：审计(audit)、轨迹(trace)、情境记忆(memory)都把数据写成
一行一条 JSON 的 JSONL，于是各自抄了同一段代码：
  · 读：逐行 strip、空行跳过、坏行 `json.loads` 失败也跳过、文件缺失返回空；
  · 写：建目录、追加一行、**任何异常都吞掉**——记录是观测者，绝不成为新的故障源。
这两段逻辑一字不差地散在三处，改一处忘两处就会埋下不一致的雷。把它收敛到这里，
让「怎么安全地存取一行行 JSON」只有一个定义。

零第三方依赖，纯标准库。
"""
from __future__ import annotations

import json
import pathlib


def read_jsonl(path: pathlib.Path) -> list[dict]:
    """读出一个 JSONL 文件的全部记录(时间正序/原始顺序)。

    文件缺失 → 返回空列表；空行与无法解析的坏行 → 直接跳过。
    读取本身永不抛错(以 errors="ignore" 容忍编码脏数据)。
    """
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def append_jsonl(path: pathlib.Path, obj: dict) -> bool:
    """把一条记录追加成 JSONL 的一行；建目录失败/写失败都被吞掉。

    返回是否真的落盘成功——调用方可忽略。记录是观测者，写盘出错绝不反噬生命。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False   # 记录是观测者，不能成为新的故障源
