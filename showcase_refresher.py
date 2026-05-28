"""Refresh docs/index.html with current stats (module count, etc.)."""
import os
import re


def count_modules() -> int:
    """Count all .py files in the repo root (excluding __pycache__)."""
    here = os.path.dirname(__file__) or "."
    count = 0
    for entry in os.listdir(here):
        if entry == "__pycache__":
            continue
        if entry.endswith(".py"):
            count += 1
    return count


def update_showcase() -> None:
    """Patch docs/index.html with fresh module count."""
    count = count_modules()
    html_path = os.path.join(os.path.dirname(__file__), "docs", "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        # no docs yet – create a placeholder so the chain doesn't break
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        content = "<html><body></body></html>"

    # Replace any old number (e.g. "26", "123") that precedes "个模块"
    new_content = re.sub(
        r"(\d+)(?=个模块)",
        str(count),
        content,
    )
    # If pattern not found, insert a line somewhere sensible
    if new_content == content:
        insert_line = f"\n        <p>当前共 {count} 个模块。</p>\n"
        new_content = content.replace("</body>", insert_line + "    </body>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_content)
