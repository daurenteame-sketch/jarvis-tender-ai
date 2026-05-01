"""
pytest config — adds backend/ to sys.path so test files can `import modules.foo`
without each one repeating the boilerplate.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
