"""Boot sanity test: proves the uv-managed interpreter matches the TESP v1.1 \u00a71.1 stack pin (Python 3.12) and that pytest runs green in the target repo."""

import sys


def test_interpreter_is_python_312() -> None:
    """The workshop targets Python 3.12 per TESP v1.1 \u00a71.1; fail loudly under any other interpreter."""
    assert sys.version_info[:2] == (3, 12), (
        f"expected Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
    )
