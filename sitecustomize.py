"""Process-wide safety hooks for opencrab local runs."""

from __future__ import annotations

try:
    from hands_external_circuitbreaker import install as _install_external_circuitbreaker

    _install_external_circuitbreaker()
except Exception:
    # Startup must remain import-safe; explicit calls still can import the module
    # and surface detailed failures.
    pass
