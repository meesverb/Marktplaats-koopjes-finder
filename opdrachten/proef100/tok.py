"""python tok.py naam=tokens,tools,ms ...  (subagent_tokens per Claude-batch bijhouden)"""
import json, sys
from pathlib import Path
p = Path(__file__).resolve().parent / "claude_tokens.json"
d = json.loads(p.read_text())
for arg in sys.argv[1:]:
    name, vals = arg.split("=")
    t, tools, ms = vals.split(",")
    d[name] = {"tokens": int(t), "tool_uses": int(tools), "ms": int(ms)}
p.write_text(json.dumps(d, indent=1))
print(len(d), "batches geregistreerd")
