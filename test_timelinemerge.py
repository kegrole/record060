"""Root-level shim so ``python -m unittest test_timelinemerge`` works.

The real suite lives in ``tests/test_timelinemerge.py``.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_timelinemerge import *  # noqa: F401,F403

if __name__ == "__main__":
    import unittest

    unittest.main()
