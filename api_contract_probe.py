"""API entry contract probe.

This module builds a JSON-serialisable stability map for selected public Python
entry points.  It is intentionally conservative: by default it only imports
modules and inspects public functions; optional execution is limited to callables
with no required arguments.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTRACT_VERSION = "api-contract-probe/v1"

DEFAULT_ORGANS: Tuple[str, ...] = (
    "contracts",
    "compat",
    "budget",
    "evidence",
    "health",
    "intent",
    "policy",
    "privacy",
    "releasegate",
    "trustscore",
    "uncertainty",
    "value",
)

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


def _jsonable(value: Any) -> bool:
    """Return True when value can be represented as strict JSON data."""

    if isinstance(value, _JSON_SCALAR_TYPES):
        return True
    if isinstance(value, (list, tuple)):
        return all(_jsonable(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _jsonable(item) for key, item in value.items())
    return False


def _stable_json(value: Any) -> str:
    """Render value as deterministic JSON for external diffing."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect.Signature.empty:
        return "unannotated"
    if getattr(annotation, "__name__", None):
        return annotation.__name__
    return str(annotation)


def _parameter_contract(parameter: inspect.Parameter) -> Dict[str, Any]:
    return {
        "name": parameter.name,
        "kind": str(parameter.kind).replace("Parameter.", ""),
        "required": parameter.default is inspect.Parameter.empty,
        "annotation": _annotation_name(parameter.annotation),
        "has_default": parameter.default is not inspect.Parameter.empty,
    }


def _callable_contract(func: Any) -> Dict[str, Any]:
    signature = inspect.signature(func)
    parameters = [_parameter_contract(param) for param in signature.parameters.values()]
    required = [
        param["name"]
        for param in parameters
        if param["required"]
        and param["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")
    ]
    return {
        "name": getattr(func, "__name__", "<unknown>"),
        "qualname": getattr(func, "__qualname__", getattr(func, "__name__", "<unknown>")),
        "signature": str(signature),
        "parameters": parameters,
        "required_parameter_count": len(required),
        "return_annotation": _annotation_name(signature.return_annotation),
        "doc_present": bool(inspect.getdoc(func)),
    }


def _public_functions(module: Any) -> List[Any]:
    functions: List[Any] = []
    for name, obj in sorted(vars(module).items()):
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj) and getattr(obj, "__module__", None) == module.__name__:
            functions.append(obj)
    return functions


def _execute_zero_arg(func: Any) -> Dict[str, Any]:
    try:
        value = func()
    except Exception as exc:  # pragma: no cover - intentionally diagnostic
        return {
            "executed": True,
            "ok": False,
            "breach": "execution_error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    jsonable = _jsonable(value)
    result: Dict[str, Any] = {
        "executed": True,
        "ok": jsonable,
        "return_type": type(value).__name__,
        "jsonable": jsonable,
    }
    if jsonable:
        rendered = _stable_json(value)
        result["json_size"] = len(rendered)
        result["json_preview"] = rendered[:240]
    else:
        result["breach"] = "non_json_return"
    return result


def probe_module(module_name: str, execute: bool = False) -> Dict[str, Any]:
    """Inspect one module and return a JSON-safe API contract report."""

    report: Dict[str, Any] = {
        "module": module_name,
        "import_ok": False,
        "functions": [],
        "breaches": [],
    }

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - diagnostic path
        report["breaches"].append(
            {
                "module": module_name,
                "kind": "import_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return report

    report["import_ok"] = True

    for func in _public_functions(module):
        item = _callable_contract(func)
        item["stability_flags"] = []

        if item["required_parameter_count"]:
            item["stability_flags"].append("requires_input")
        else:
            item["stability_flags"].append("zero_arg_candidate")

        if item["return_annotation"] == "unannotated":
            item["stability_flags"].append("return_unannotated")

        if execute and item["required_parameter_count"] == 0:
            execution = _execute_zero_arg(func)
            item["sample_execution"] = execution
            if not execution.get("ok"):
                report["breaches"].append(
                    {
                        "module": module_name,
                        "function": item["name"],
                        "kind": execution.get("breach", "execution_not_ok"),
                        "error_type": execution.get("error_type"),
                        "error": execution.get("error"),
                    }
                )
        elif execute:
            item["sample_execution"] = {
                "executed": False,
                "reason": "required_parameters_present",
            }

        report["functions"].append(item)

    return report


def build_stability_map(
    modules: Optional[Iterable[str]] = None,
    execute: bool = False,
) -> Dict[str, Any]:
    """Build a JSON-serialisable external API stability map."""

    module_names = tuple(modules or DEFAULT_ORGANS)
    module_reports = [probe_module(name, execute=execute) for name in module_names]

    breaches: List[Dict[str, Any]] = []
    public_function_count = 0
    zero_arg_candidates = 0

    for module_report in module_reports:
        breaches.extend(module_report.get("breaches", []))
        functions = module_report.get("functions", [])
        public_function_count += len(functions)
        zero_arg_candidates += sum(
            1
            for item in functions
            if item.get("required_parameter_count") == 0
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "execute_samples": bool(execute),
        "modules_requested": list(module_names),
        "summary": {
            "module_count": len(module_reports),
            "import_ok_count": sum(1 for item in module_reports if item.get("import_ok")),
            "public_function_count": public_function_count,
            "zero_arg_candidate_count": zero_arg_candidates,
            "breach_count": len(breaches),
        },
        "modules": module_reports,
        "breaches": breaches,
    }


def stability_map_json(
    modules: Optional[Iterable[str]] = None,
    execute: bool = False,
    indent: Optional[int] = 2,
) -> str:
    """Return the stability map as deterministic JSON text."""

    return json.dumps(
        build_stability_map(modules=modules, execute=execute),
        ensure_ascii=False,
        sort_keys=True,
        indent=indent,
    )


def write_stability_map(
    path: str,
    modules: Optional[Iterable[str]] = None,
    execute: bool = False,
) -> Dict[str, Any]:
    """Write the stability map to path and return the same data."""

    data = build_stability_map(modules=modules, execute=execute)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return data


def _parse_modules(raw: Optional[Sequence[str]]) -> Optional[List[str]]:
    if not raw:
        return None
    modules: List[str] = []
    for chunk in raw:
        for item in chunk.split(","):
            name = item.strip()
            if name:
                modules.append(name)
    return modules or None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Python API entry contracts.")
    parser.add_argument(
        "modules",
        nargs="*",
        help="Module names to probe. Comma-separated groups are accepted.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute only zero-required-argument functions and classify JSON output.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write JSON report to this path instead of stdout.",
    )
    args = parser.parse_args(argv)

    modules = _parse_modules(args.modules)
    if args.output:
        write_stability_map(args.output, modules=modules, execute=args.execute)
    else:
        print(stability_map_json(modules=modules, execute=args.execute))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
