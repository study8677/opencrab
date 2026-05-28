"""End-to-end verification: ensure showcase stays fresh."""
import sys
from showcase_refresher import update_showcase


def main() -> int:
    try:
        update_showcase()
        print("showcase_refresher ran successfully – docs updated.")
        return 0
    except Exception as exc:
        print(f"showcase_refresher failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
