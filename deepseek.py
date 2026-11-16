"""Deprecated alias for :mod:`llm`.

The client stopped being DeepSeek-only once provider selection was added, so
the real implementation now lives in ``llm.py``. This module remains only so
older imports (and any local scripts) keep working.
"""

from llm import chat, stream_chat, test_key  # noqa: F401
