from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


class BrainOnlyAstPatchError(ValueError):
    """Raised when a brain-only AST patch is not a safe single-function replace."""


def brain_only_single_function_replace(
    source: str,
    function_name: str,
    replacement_source: str,
) -> str:
    """Replace exactly one top-level function in *source*.

    This is intentionally narrow: the replacement must define exactly one
    function or async function with the same name, and the target source must
    contain exactly one top-level function with that name.
    """

    if not isinstance(source, str):
        raise BrainOnlyAstPatchError("source must be text")
    if not function_name or not isinstance(function_name, str):
        raise BrainOnlyAstPatchError("function_name must be a non-empty string")
    _validate_single_replacement(function_name, replacement_source)

    span = _locate_with_astlocator(source, function_name)
    if span is None:
        span = _locate_top_level_function_span(source, function_name)

    rewritten = _rewrite_with_astrewriter(source, span, replacement_source)
    if rewritten is not None:
        return rewritten

    return _replace_line_span(source, span, replacement_source)


def brain_only_single_function_replace_in_file(
    path: str | Path,
    function_name: str,
    replacement_source: str,
    *,
    dry_run: bool = False,
) -> str:
    """Apply a safe single-function replacement to a Python file.

    Returns the rewritten source.  When *dry_run* is true the file is not
    modified.
    """

    file_path = Path(path)
    original = file_path.read_text(encoding="utf-8")
    rewritten = brain_only_single_function_replace(
        original,
        function_name,
        replacement_source,
    )
    if not dry_run and rewritten != original:
        file_path.write_text(rewritten, encoding="utf-8")
    return rewritten


def _validate_single_replacement(function_name: str, replacement_source: str) -> None:
    try:
        tree = ast.parse(replacement_source)
    except SyntaxError as exc:
        raise BrainOnlyAstPatchError(f"replacement is not valid Python: {exc}") from exc

    funcs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    non_doc_nodes = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(getattr(node, "value", None), ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]

    if len(funcs) != 1 or len(non_doc_nodes) != 1:
        raise BrainOnlyAstPatchError("replacement must contain exactly one function")
    if funcs[0].name != function_name:
        raise BrainOnlyAstPatchError("replacement function name does not match target")


def _locate_top_level_function_span(source: str, function_name: str) -> tuple[int, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise BrainOnlyAstPatchError(f"source is not valid Python: {exc}") from exc

    matches: list[ast.FunctionDef | ast.AsyncFunctionDef] = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(matches) != 1:
        raise BrainOnlyAstPatchError(
            f"expected exactly one top-level function named {function_name!r}, "
            f"found {len(matches)}"
        )

    node = matches[0]
    start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
    end = getattr(node, "end_lineno", None)
    if end is None:
        raise BrainOnlyAstPatchError("Python AST does not provide end_lineno")
    return start, end


def _locate_with_astlocator(source: str, function_name: str) -> tuple[int, int] | None:
    try:
        import astlocator  # type: ignore
    except Exception:
        return None

    for name in (
        "locate_function_span",
        "locate_function",
        "find_function_span",
        "find_function",
        "function_span",
    ):
        locator = getattr(astlocator, name, None)
        if locator is None:
            continue
        result = _try_call(locator, source, function_name)
        span = _normalise_span(result)
        if span is not None:
            return span
    return None


def _rewrite_with_astrewriter(
    source: str,
    span: tuple[int, int],
    replacement_source: str,
) -> str | None:
    try:
        import astrewriter  # type: ignore
    except Exception:
        return None

    start, end = span
    for name in (
        "replace_function_span",
        "replace_span",
        "rewrite_span",
        "replace_lines",
    ):
        rewriter = getattr(astrewriter, name, None)
        if rewriter is None:
            continue
        result = _try_call(rewriter, source, start, end, replacement_source)
        if isinstance(result, str):
            return result
    return None


def _try_call(func: Any, *args: Any) -> Any:
    try:
        return func(*args)
    except TypeError:
        return None


def _normalise_span(result: Any) -> tuple[int, int] | None:
    if result is None:
        return None

    if isinstance(result, dict):
        start = result.get("start_line", result.get("lineno", result.get("start")))
        end = result.get("end_line", result.get("end_lineno", result.get("end")))
    elif isinstance(result, (tuple, list)) and len(result) >= 2:
        start, end = result[0], result[1]
    else:
        start = getattr(result, "start_line", getattr(result, "lineno", None))
        end = getattr(result, "end_line", getattr(result, "end_lineno", None))

    if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end:
        return start, end
    return None


def _replace_line_span(source: str, span: tuple[int, int], replacement_source: str) -> str:
    start, end = span
    lines = source.splitlines(keepends=True)
    if not lines:
        raise BrainOnlyAstPatchError("cannot replace inside empty source")

    if start < 1 or end > len(lines) or start > end:
        raise BrainOnlyAstPatchError("invalid replacement span")

    newline = "\n"
    for line in lines:
        if line.endswith("\r\n"):
            newline = "\r\n"
            break

    replacement = replacement_source
    if replacement and not replacement.endswith(("\n", "\r\n")):
        replacement += newline

    replacement_lines = replacement.splitlines(keepends=True)
    return "".join(lines[: start - 1] + replacement_lines + lines[end:])
