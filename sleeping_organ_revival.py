"""Revive low-heat/high-trust organs by wiring them through route/navigator.

This module is intentionally defensive: it performs real imports and real
call attempts against three quiet but trusted organs, while recording any
unusable path as an explicit degradation instead of failing the whole plan.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib
import inspect
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


LOW_HEAT_HIGH_TRUST_ORGANS: Tuple[str, ...] = (
    "checklist",
    "compass",
    "trustscore",
)

ROUTE_NAVIGATOR_MODULES: Tuple[str, ...] = (
    "route",
    "navigator",
)


@dataclass
class RevivalStep:
    module: str
    status: str
    detail: str
    callable: Optional[str] = None
    result_preview: Optional[str] = None


def _preview(value: Any, limit: int = 220) -> str:
    text = repr(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _import_module(name: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return importlib.import_module(name), None
    except Exception as exc:  # pragma: no cover - exact organ inventory varies
        return None, f"{type(exc).__name__}: {exc}"


def _safe_signature(callable_obj: Callable[..., Any]) -> Optional[inspect.Signature]:
    try:
        return inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return None


def _candidate_calls(callable_obj: Callable[..., Any], intent: str) -> Iterable[Tuple[Tuple[Any, ...], Dict[str, Any]]]:
    """Yield conservative call shapes likely to be accepted by pure helpers."""

    signature = _safe_signature(callable_obj)
    context = {
        "intent": intent,
        "organs": list(LOW_HEAT_HIGH_TRUST_ORGANS),
        "source": "sleeping_organ_revival",
    }

    if signature is None:
        yield (), {}
        return

    params = list(signature.parameters.values())
    required = [
        p
        for p in params
        if p.default is inspect._empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]

    if not required:
        yield (), {}
        return

    if len(required) == 1:
        name = required[0].name.lower()
        if any(token in name for token in ("intent", "text", "query", "goal", "task", "prompt")):
            yield (intent,), {}
        if any(token in name for token in ("ctx", "context", "state", "plan", "data", "record")):
            yield (context,), {}
        yield (), {"intent": intent}
        yield (), {"context": context}


def _preferred_callables(module: Any) -> List[Tuple[str, Callable[..., Any]]]:
    preferred_names = (
        "plan",
        "navigate",
        "route",
        "check",
        "run",
        "score",
        "evaluate",
        "calibrate",
        "summarize",
        "build",
        "main",
    )
    found: List[Tuple[str, Callable[..., Any]]] = []

    for name in preferred_names:
        obj = getattr(module, name, None)
        if callable(obj):
            found.append((name, obj))

    if found:
        return found

    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        obj = getattr(module, name, None)
        if inspect.isfunction(obj) and getattr(obj, "__module__", None) == module.__name__:
            found.append((name, obj))
            if len(found) >= 4:
                break

    return found


def _try_real_call(module_name: str, intent: str) -> RevivalStep:
    module, error = _import_module(module_name)
    if module is None:
        return RevivalStep(module_name, "degraded", f"import unavailable: {error}")

    callables = _preferred_callables(module)
    if not callables:
        return RevivalStep(module_name, "degraded", "no suitable public callable discovered")

    last_error = "not attempted"
    for callable_name, callable_obj in callables:
        for args, kwargs in _candidate_calls(callable_obj, intent):
            try:
                result = callable_obj(*args, **kwargs)
                return RevivalStep(
                    module=module_name,
                    status="used",
                    detail="real callable executed",
                    callable=callable_name,
                    result_preview=_preview(result),
                )
            except Exception as exc:  # pragma: no cover - module APIs vary
                last_error = f"{callable_name}: {type(exc).__name__}: {exc}"

    return RevivalStep(module_name, "degraded", last_error)


def _touch_route_navigator(intent: str) -> List[RevivalStep]:
    steps: List[RevivalStep] = []

    for module_name in ROUTE_NAVIGATOR_MODULES:
        module, error = _import_module(module_name)
        if module is None:
            steps.append(RevivalStep(module_name, "degraded", f"import unavailable: {error}"))
            continue

        callables = [
            item
            for item in _preferred_callables(module)
            if item[0] in {"plan", "navigate", "route", "choose", "select", "build", "run"}
        ]
        if not callables:
            steps.append(RevivalStep(module_name, "observed", "imported; no conservative callable used"))
            continue

        last_error = "not attempted"
        for callable_name, callable_obj in callables:
            for args, kwargs in _candidate_calls(callable_obj, intent):
                try:
                    result = callable_obj(*args, **kwargs)
                    steps.append(
                        RevivalStep(
                            module=module_name,
                            status="used",
                            detail="route/navigator callable executed",
                            callable=callable_name,
                            result_preview=_preview(result),
                        )
                    )
                    last_error = ""
                    break
                except Exception as exc:  # pragma: no cover - module APIs vary
                    last_error = f"{callable_name}: {type(exc).__name__}: {exc}"
            if not last_error:
                break

        if last_error:
            steps.append(RevivalStep(module_name, "degraded", last_error))

    return steps


def run_real_plan(intent: str = "revive sleeping organs through route/navigator") -> Dict[str, Any]:
    """Run the revival plan and return used/degraded evidence.

    The plan deliberately chooses exactly three low-heat/high-trust organs and
    attempts real execution. Organs that cannot be safely called are listed in
    ``degraded`` so future work can target them explicitly.
    """

    route_navigator_steps = _touch_route_navigator(intent)
    organ_steps = [_try_real_call(module_name, intent) for module_name in LOW_HEAT_HIGH_TRUST_ORGANS]
    all_steps = route_navigator_steps + organ_steps

    return {
        "intent": intent,
        "selected_organs": list(LOW_HEAT_HIGH_TRUST_ORGANS),
        "route_navigator": [asdict(step) for step in route_navigator_steps],
        "organs": [asdict(step) for step in organ_steps],
        "used": [asdict(step) for step in all_steps if step.status == "used"],
        "degraded": [asdict(step) for step in all_steps if step.status == "degraded"],
    }


def main() -> Dict[str, Any]:
    return run_real_plan()


if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(main(), ensure_ascii=False, indent=2, sort_keys=True))
