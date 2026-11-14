"""Paste the preflop blob from shared/preflop_data.py into bot_src.py -> bot.py."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
src = open(os.path.join(ROOT, "shared", "preflop_data.py")).read()
blob = re.search(r'_PF_BLOB = "([^"]+)"', src).group(1)
code = open(os.path.join(HERE, "bot_src.py")).read()
assert code.count('"__PF_BLOB__"') == 1
code = code.replace('"__PF_BLOB__"', '"' + blob + '"')
open(os.path.join(HERE, "bot.py"), "w").write(code)
print("bot.py written,", len(code), "bytes")
