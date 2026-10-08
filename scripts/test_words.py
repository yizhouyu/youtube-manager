"""Unit test for src.editor.words.find (no ASR needed)."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.editor.words import find  # noqa: E402

W = [{"t0": 0.0, "t1": 0.2, "w": "你"}, {"t0": 0.2, "t1": 0.4, "w": "再"}, {"t0": 0.4, "t1": 0.6, "w": "一"},
     {"t0": 0.6, "t1": 0.8, "w": "震"}, {"t0": 1.0, "t1": 1.3, "w": "八秒"}, {"t0": 1.3, "t1": 1.5, "w": "钟"},
     {"t0": 2.0, "t1": 2.2, "w": "Stock"}, {"t0": 2.2, "t1": 2.5, "w": "yards"}]
assert find(W, "八秒钟") == [(1.0, 1.5)], find(W, "八秒钟")
assert find(W, "一震") == [(0.4, 0.8)]
assert find(W, "Stockyards") == [(2.0, 2.5)]
assert find(W, "秒钟") == [(1.0, 1.5)]
assert find(W, "不存在") == []
print("ok")
