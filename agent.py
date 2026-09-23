#!/usr/bin/env python3
"""Skeleton for the Python -> Rust translation agent.

    python agent.py                  # run with defaults
    python agent.py --budget 40      # cap on model calls (graded: do not raise)

WHAT IS GIVEN
  * the loop
  * six working tools
  * trajectory logging

WHAT YOU FILL IN   (search for "TODO")
  1. call_model()      - talk to whichever model you have access to
  2. system_prompt()   - what the agent is told about its job
  3. build_context()   - CONTEXT MANAGEMENT. The hard one.
  4. should_stop()     - TERMINATION. The one everyone forgets.
  5. the tool set      - add, remove, or reshape tools. This matters more
                         than you expect; see README.

The skeleton runs as given and accomplishes nothing. That is intentional.
"""
from __future__ import annotations
import argparse, json, pathlib, subprocess, time, sys

HERE   = pathlib.Path(__file__).parent
RUST   = HERE / "rust"
LIB    = RUST / "src" / "lib.rs"
PYSRC  = HERE / "reference" / "version.py"
LOGS   = HERE / "logs"

# ============================================================== TODO 1
def call_model(messages: list[dict], tools: list[dict]) -> dict:
    """Send `messages` + `tools` to a model; return its reply.

    Return shape expected by the loop below:
        {"text": str | None,
         "tool_calls": [{"name": str, "arguments": dict}, ...]}

    Any provider works. Keep the return shape and the loop needs no changes.
    Read your key from the environment - do not hard-code it, you will be
    committing this file.
    """
    raise NotImplementedError("TODO 1: implement call_model()")

# ============================================================== TODO 2
def system_prompt() -> str:
    """What the agent is told about its job.

    Worth deciding deliberately: how much of the semver spec do you put in
    here versus letting the agent read reference/version.py itself? Baking
    knowledge into the prompt is cheap and brittle; making the agent read
    the source costs tokens but generalises. Try both and measure.
    """
    return "TODO 2: write the system prompt."

# ============================================================== TODO 3
def build_context(history: list[dict], step: int) -> list[dict]:
    """Turn the full history into the messages you actually send.

    The naive version - return history unchanged - will fill the context
    window somewhere around step 15 once compiler errors start accumulating,
    and the agent will begin repeating work it has already done.

    You have four levers (agentweb deck, part IV):
        WRITE     put state in a file instead of the context
        SELECT    retrieve only what this step needs
        COMPRESS  summarise old turns
        ISOLATE   give a sub-agent its own window

    Constraint for this assignment: you may not raise the model's context
    limit to solve this. Solve it by managing what you send.
    """
    return history                      # TODO 3: replace this

# ============================================================== TODO 4
def should_stop(history: list[dict], step: int, budget: int, last_score: float | None) -> tuple[bool, str]:
    """Return (stop?, why).

    The budget check below is given. Everything else is yours:
      - stop when the score stops improving? after how many flat steps?
      - stop when the agent repeats an identical action?
      - stop when it claims to be done - and do you believe it?
      - what if the score goes DOWN? do you roll back?

    An agent that never decides to stop is not finished, it is just out
    of budget. That distinction is graded.
    """
    if step >= budget:
        return True, f"budget exhausted ({budget} model calls)"
    return False, ""                    # TODO 4: add real stopping conditions

# ================================================================== tools
def _run(cmd, cwd=None, timeout=180):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"

def t_read_python(_args):
    """The source to translate."""
    return PYSRC.read_text() if PYSRC.exists() else "reference/version.py missing - run fetch_source.py"

def t_read_rust(_args):
    return LIB.read_text()

def t_write_rust(args):
    """Overwrite rust/src/lib.rs. `content` must be the WHOLE file."""
    LIB.write_text(args["content"])
    return f"wrote {len(args['content'])} bytes to rust/src/lib.rs"

def t_cargo_build(_args):
    return _run(["cargo", "build", "--release"], cwd=RUST)

def t_cargo_test(_args):
    return _run(["cargo", "test", "--release"], cwd=RUST)

def t_evaluate(_args):
    """Practice seed only. The grading seed is different - do not tune to this."""
    return _run([sys.executable, str(HERE / "evaluate.py"), "--n", "60"], cwd=HERE)

# TODO 5: this action space is deliberately coarse. `write_rust` rewriting
# the whole file every time is expensive and loses work on partial edits.
# Consider: a patch/replace-function tool, a "run one differential case"
# tool, a tool that greps the Python source. Measure before and after.
TOOLS = [
    dict(name="read_python", description="Read reference/version.py, the source to translate.",
         parameters={"type": "object", "properties": {}}, fn=t_read_python),
    dict(name="read_rust", description="Read the current rust/src/lib.rs.",
         parameters={"type": "object", "properties": {}}, fn=t_read_rust),
    dict(name="write_rust", description="Overwrite rust/src/lib.rs with the complete file contents.",
         parameters={"type": "object", "required": ["content"],
                     "properties": {"content": {"type": "string"}}}, fn=t_write_rust),
    dict(name="cargo_build", description="Compile the crate. Returns compiler errors.",
         parameters={"type": "object", "properties": {}}, fn=t_cargo_build),
    dict(name="cargo_test", description="Run the crate's own tests.",
         parameters={"type": "object", "properties": {}}, fn=t_cargo_test),
    dict(name="evaluate", description="Run the differential evaluation (practice seed).",
         parameters={"type": "object", "properties": {}}, fn=t_evaluate),
]
BY_NAME = {t["name"]: t for t in TOOLS}
SCHEMAS = [{k: t[k] for k in ("name", "description", "parameters")} for t in TOOLS]

# =================================================================== loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=40, help="max model calls (graded cap: 40)")
    ap.add_argument("--task", default="Translate reference/version.py into rust/src/lib.rs.")
    a = ap.parse_args()

    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"run-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    def rec(**kw):
        with log.open("a") as f:
            f.write(json.dumps({"t": time.time(), **kw}) + "\n")

    history = [{"role": "system", "content": system_prompt()},
               {"role": "user",   "content": a.task}]
    rec(event="start", budget=a.budget, task=a.task)

    step, last_score = 0, None
    while True:
        stop, why = should_stop(history, step, a.budget, last_score)
        if stop:
            print(f"\n[stop] {why}")
            rec(event="stop", reason=why, steps=step)
            break

        step += 1
        reply = call_model(build_context(history, step), SCHEMAS)
        rec(event="model", step=step, reply=reply)

        if reply.get("text"):
            print(f"[{step}] {reply['text'][:200]}")
        history.append({"role": "assistant", "content": reply.get("text") or "",
                        "tool_calls": reply.get("tool_calls", [])})

        calls = reply.get("tool_calls") or []
        if not calls:
            # TODO: no tool call. Is the agent done, stuck, or just chatting?
            # Deciding this is part of TODO 4.
            continue

        for c in calls:
            tool = BY_NAME.get(c["name"])
            out = (f"unknown tool {c['name']!r}" if tool
                   else tool["fn"](c.get("arguments") or {}))
            print(f"      -> {c['name']}: {str(out).splitlines()[0][:120] if out else ''}")
            rec(event="tool", step=step, name=c["name"], output=str(out)[:4000])
            history.append({"role": "tool", "name": c["name"], "content": str(out)})

    print(f"\ntrajectory: {log}")
    print("final score:")
    subprocess.run([sys.executable, str(HERE / "evaluate.py")], cwd=HERE)

if __name__ == "__main__":
    main()
