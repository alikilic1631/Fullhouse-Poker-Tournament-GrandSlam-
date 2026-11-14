"""Build bot.py from bot_src.py by injecting the preflop equity blob."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
shared = os.path.join(HERE, "..", "..", "shared", "preflop_data.py")
blob = re.search(r'_PF_BLOB = "([^"]+)"', open(shared).read()).group(1)
src = open(os.path.join(HERE, "bot_src.py")).read()
assert "@@BLOB@@" in src
out = src.replace("@@BLOB@@", blob)
open(os.path.join(HERE, "bot.py"), "w").write(out)
print("bot.py written, %d bytes" % len(out))
