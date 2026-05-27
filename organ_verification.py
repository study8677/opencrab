"""Minimal capability verification for formerly-unknown organs.

This module makes three small, reproducible checks for modules that were
previously treated as "?" organs: importability, public surface discovery, and
a conservative CLI help probe.  It avoids assuming private APIs, so the result
is useful even while an organ is still being mapped.
"""

from __future__ import annotations

import importlib
import inspect
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class OrganClaim:
    """Human-readable capability statement for a verified organ."""

    module: str
    former_mark: str
    capability: str
    evidence_goal: str


@dataclass(frozen=True)
class OrganEvidence:
    """Machine-readable evidence gathered by the minimal verifier."""

    module: str
    import_ok: bool
    module_file: Optional[str]
    public_symbols: List[str]
    cli_checked: bool
    cli_returncode: Optional[int]
    cli_excerpt: str
    capability: str
    verdict: str


CLAIMS: Dict[str, OrganClaim] = {
    "astlocator": OrganClaim(
        module="astlocator",
        former_mark="?",
        capability=(
            "AST定位器：提供源码结构定位相关能力，可被其它补丁/读包流程用于"
            "把文本级变更锚定到 Python 语法节点附近。"
        ),
        evidence_goal="import module, enumerate public API, run a --help CLI probe if file-backed",
    ),
    "budget": OrganClaim(
        module="budget",
        former_mark="?",
        capability=(
            "预算约束器：承载资源/步数/额度类约束的计算或表达，帮助流程在有限"
            "预算内做取舍。"
        ),
        evidence_goal="import module, enumerate public API, run a --help CLI probe if file-backed",
    ),
    "trustscore": OrganClaim(
        module="trustscore",
        former_mark="?",
        capability=(
            "信任评分器：汇总证据或信号形成可信度判断，供门禁、排序或复核流程"
            "降低盲信风险。"
        ),
        evidence_goal="import module, enumerate public API, run a --help CLI probe if file-backed",
    ),
}


def _public_symbols(module: object, limit: int = 16) -> List[str]:
    names: List[str] = []
    for name, value in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if inspect.ismodule(value):
            continue
        names.append(name)
    return names[:limit]


def _cli_probe(module_file: Optional[str], timeout: float = 3.0) -> tuple[bool, Optional[int], str]:
    if not module_file:
        return False, None, "no module file available"
    path = Path(module_file)
    if not path.exists() or path.suffix != ".py":
        return False, None, "module is not a direct Python source file"

    try:
        proc = subprocess.run(
            [sys.executable, str(path), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True, None, "timeout while probing --help"
    except OSError as exc:
        return True, None, f"os error while probing --help: {exc}"

    excerpt = " ".join(proc.stdout.strip().split())[:240]
    return True, proc.returncode, excerpt


def verify_one(module_name: str) -> OrganEvidence:
    """Verify one organ without relying on its private implementation details."""

    claim = CLAIMS[module_name]
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - kept for diagnostic output
        return OrganEvidence(
            module=module_name,
            import_ok=False,
            module_file=None,
            public_symbols=[],
            cli_checked=False,
            cli_returncode=None,
            cli_excerpt=f"import failed: {type(exc).__name__}: {exc}",
            capability=claim.capability,
            verdict="blocked",
        )

    module_file = getattr(module, "__file__", None)
    symbols = _public_symbols(module)
    cli_checked, cli_returncode, cli_excerpt = _cli_probe(module_file)
    verdict = "verified" if symbols else "imported-no-public-surface"

    return OrganEvidence(
        module=module_name,
        import_ok=True,
        module_file=module_file,
        public_symbols=symbols,
        cli_checked=cli_checked,
        cli_returncode=cli_returncode,
        cli_excerpt=cli_excerpt,
        capability=claim.capability,
        verdict=verdict,
    )


def verify_all(modules: Iterable[str] = tuple(CLAIMS)) -> List[OrganEvidence]:
    """Return capability evidence for the selected formerly-unknown organs."""

    return [verify_one(name) for name in modules]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint that prints reproducible JSON evidence."""

    args = list(argv if argv is not None else sys.argv[1:])
    selected = args or list(CLAIMS)
    unknown = [name for name in selected if name not in CLAIMS]
    if unknown:
        print(f"unknown organ(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    payload = {
        "purpose": "formerly-unknown organ verification",
        "claims": {name: asdict(claim) for name, claim in CLAIMS.items() if name in selected},
        "evidence": [asdict(item) for item in verify_all(selected)],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
