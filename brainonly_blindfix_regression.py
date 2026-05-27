"""Brain-only blind-fix regression for the readpack -> patchfitroom loop.

This module is intentionally small and dependency-free.  It exercises a real
low-risk seam used by hand-authored repairs: the plain-text NOTE/WRITE block
format must remain easy to identify without relying on external tooling.
"""

from __future__ import annotations

import importlib
import re
from typing import List, Tuple


_WRITE_BLOCK_RE = re.compile(
    r"<<<WRITE path=([^>\n]+)>>>\n(.*?)\n<<<END>>>",
    re.DOTALL,
)


def extract_write_blocks(patch_text: str) -> List[Tuple[str, str]]:
    """Return ``(path, body)`` pairs from hand-authored WRITE blocks.

    The parser is deliberately conservative: it only accepts complete WRITE
    blocks and preserves the file body exactly between the block markers.
    """

    return [(match.group(1), match.group(2)) for match in _WRITE_BLOCK_RE.finditer(patch_text)]


def test_readpack_and_patchfitroom_importable() -> None:
    """The brain-only repair path depends on both modules being importable."""

    importlib.import_module("readpack")
    importlib.import_module("patchfitroom")


def test_plain_text_write_block_extraction_preserves_body() -> None:
    """Guard the plain-text patch contract used during blind repairs."""

    patch_text = (
        "NOTE: regression sample\n"
        "<<<WRITE path=sample_regression.py>>>\n"
        "VALUE = '<<<not-a-marker-inside-content>>>'\n"
        "def ok():\n"
        "    return VALUE\n"
        "<<<END>>>\n"
    )

    blocks = extract_write_blocks(patch_text)

    assert blocks == [
        (
            "sample_regression.py",
            "VALUE = '<<<not-a-marker-inside-content>>>'\n"
            "def ok():\n"
            "    return VALUE",
        )
    ]


def run_regression() -> bool:
    """Run this regression without requiring pytest."""

    test_readpack_and_patchfitroom_importable()
    test_plain_text_write_block_extraction_preserves_body()
    return True


if __name__ == "__main__":
    run_regression()
    print("brainonly_blindfix_regression: ok")
