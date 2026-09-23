#!/usr/bin/env python3
"""Bounded, verification-driven translation agent using the Codex CLI."""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
RUST = HERE / "rust"
LIB = RUST / "src" / "lib.rs"
PYTHON = HERE / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = pathlib.Path(sys.executable)
LOGS = HERE / "logs"
STATE = {"score": None, "best_score": -1.0, "best_source": None,
         "improved_at": 0, "verified": False, "idle": 0, "repeats": 0,
         "previous_action": None, "step": 0, "last_report": None,
         "source_reads": 0, "written": False}

SCHEMA = {"type": "object", "properties": {
    "text": {"type": "string"},
    "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"},
        "arguments": {"type": "string"}},
        "required": ["name", "arguments"], "additionalProperties": False}}},
    "required": ["text", "tool_calls"], "additionalProperties": False}


def call_model(messages: list[dict], tools: list[dict]) -> dict:
    """One outer-loop call, authenticated by the local ChatGPT Codex login."""
    prompt = ("Act only as the decision maker for this tool-driven agent. "
              "Do not use your own tools or edit files. Return exactly one tool "
              "call in the JSON reply; encode tool arguments as a JSON string. "
              "Only return no calls after verify passes. "
              "Do not create subagents.\nTOOLS:\n" + json.dumps(tools) +
              "\nMESSAGES:\n" + json.dumps(messages, ensure_ascii=False))
    with tempfile.TemporaryDirectory(prefix="semver-model-") as tmp:
        schema = pathlib.Path(tmp) / "schema.json"
        output = pathlib.Path(tmp) / "output.json"
        schema.write_text(json.dumps(SCHEMA))
        cmd = ["codex", "exec", "--ephemeral", "--ignore-user-config",
               "--sandbox", "read-only", "--output-schema", str(schema),
               "--output-last-message", str(output), "-C", str(HERE), "-"]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                           timeout=300, cwd=HERE)
        if p.returncode or not output.exists():
            raise RuntimeError(f"model call failed: {p.stderr[-1200:]}")
        reply = json.loads(output.read_text())
        for call in reply["tool_calls"]:
            call["arguments"] = json.loads(call["arguments"])
        return reply


def system_prompt() -> str:
    return """Translate reference/version.py to rust/src/lib.rs. Read the source
and reference tests first. Preserve the required public signatures and never
edit main.rs. Use std only; no unsafe, Python callback, extra dependency,
todo!, unimplemented!, or panic!. Keep clone and unwrap usage low.
Inspect at most three source excerpts, then write a complete translation with
meaningful Rust tests -> build ->
test -> evaluate -> fix failure families -> verify. Build metadata does not
affect precedence; a release outranks its prereleases. Bump methods increment
the requested core number and clear both suffixes. The Python oracle is final.
Use targeted replacement after the first full write. Do not claim completion
from a model message or an invalid-parse score. Use the verify tool.
"""


def build_context(history: list[dict], step: int) -> list[dict]:
    """Select recent evidence and persistent state; do not resend all errors."""
    state = {k: v for k, v in STATE.items() if k != "best_source"}
    source_evidence = [h["content"] for h in history[2:] if
        h.get("role") == "tool" and h.get("name") in
        {"read_python", "read_tests"}]
    source_evidence = source_evidence[:4]
    recent = []
    for raw in history[2:][-6:]:
        item = dict(raw)
        if isinstance(item.get("content"), str):
            item["content"] = item["content"][-5000:]
        if item.get("tool_calls"):
            item["tool_calls"] = [{"name": c.get("name"),
                "arguments": "omitted; read current file before editing"}
                for c in item["tool_calls"]]
        recent.append(item)
    directive = ("You have inspected enough source. Your next action MUST be "
                 "write_rust with a complete translation and at least six "
                 "meaningful tests. Do not read again. " if
                 STATE["source_reads"] >= 3 and not STATE["written"] else "")
    return history[:2] + [{"role": "user", "content":
        f"Step {step}/40. State: {json.dumps(state)}. {directive}"
        f"Retained source evidence: {json.dumps(source_evidence)}. "
        "Recent evidence:"}] + recent


def should_stop(history: list[dict], step: int, budget: int,
                last_score: float | None) -> tuple[bool, str]:
    if STATE["verified"]:
        return True, "full verification passed"
    if step >= min(budget, 40):
        return True, f"budget exhausted ({min(budget, 40)} model calls)"
    if STATE["repeats"] >= 3:
        return True, "same action repeated three times"
    if STATE["idle"] >= 2:
        return True, "two replies without actions"
    if step >= 15 and step - STATE["improved_at"] >= 12:
        return True, "no improvement in twelve calls"
    return False, ""


def _run(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=180)
        return {"exit_code": p.returncode,
                "output": (p.stdout + p.stderr).strip()[-6000:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "output": "timeout after 180 seconds"}


def _numbered(path, args, limit):
    lines = path.read_text().splitlines()
    start = max(1, int(args.get("start", 1)))
    end = min(len(lines), int(args.get("end", start + limit - 1)), start + limit - 1)
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))


def t_read_python(args):
    return _numbered(HERE / "reference" / "version.py", args, 160)


def t_read_tests(args):
    name = args.get("name", "test_parsing.py")
    if name not in {"test_parsing.py", "test_compare.py", "test_bump.py"}:
        return "invalid test file"
    return _numbered(HERE / "reference" / name, args, 120)


def t_read_rust(_args):
    return LIB.read_text()


def t_write_rust(args):
    content = args["content"]
    if not isinstance(content, str) or not content.strip():
        return "rejected: empty source"
    LIB.write_text(content)
    return f"wrote {len(content)} bytes"


def t_replace_rust(args):
    old, new = args["old"], args["new"]
    source = LIB.read_text()
    count = source.count(old)
    if not old or count != 1:
        return f"rejected: expected one exact match, found {count}"
    LIB.write_text(source.replace(old, new, 1))
    return f"replaced {len(old)} bytes with {len(new)} bytes"


def t_cargo_build(_args):
    return _run(["cargo", "build", "--release"], cwd=RUST)


def t_cargo_test(_args):
    return _run(["cargo", "test", "--release"], cwd=RUST)


def _evaluate(seed, n):
    with tempfile.TemporaryDirectory(prefix="semver-eval-") as tmp:
        report_path = pathlib.Path(tmp) / "report.json"
        cmd = [str(PYTHON), str(HERE / "evaluate.py"), "--seed", str(seed),
               "--n", str(n), "--json", str(report_path)]
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           timeout=240)
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        failures = p.stdout.split("First failures:")[-1].strip()[:4500]
        return {"exit_code": p.returncode, "report": report,
                "first_failures": failures if "First failures:" in p.stdout else "",
                "stderr": p.stderr[-500:]}


def t_evaluate(_args):
    result = _evaluate(0, 60)
    report = result["report"]
    STATE["last_report"] = {k: report.get(k) for k in
        ("build", "cargo_test", "differential", "differential_pct",
         "spec_precedence_chain", "quality", "violations", "degenerate_rejector")}
    score = report.get("differential_pct", -1)
    STATE["score"] = score
    if report.get("build") and not report.get("violations") and score > STATE["best_score"]:
        STATE["best_score"] = score
        STATE["best_source"] = LIB.read_text()
        STATE["improved_at"] = STATE["step"]
        result["best_updated"] = True
    elif STATE["best_source"] is not None and (report.get("violations") or
            not report.get("build") or score + 0.5 < STATE["best_score"]):
        LIB.write_text(STATE["best_source"])
        result["restored_best_source"] = True
    return result


def t_verify(_args):
    results = [_evaluate(seed, 300) for seed in (0, 17, 91)]
    reports = [r["report"] for r in results]
    passed = all(r.get("build") and r.get("cargo_test") and
                 r["cargo_test"]["failed"] == 0 and
                 r["cargo_test"]["passed"] >= 6 and
                 r.get("spec_precedence_chain") and
                 not r.get("violations") and
                 not r.get("degenerate_rejector") and
                 r.get("differential_pct", 0) >= 90 for r in reports)
    STATE["verified"] = passed
    return {"passed": passed, "seeds": [{"seed": r.get("seed"),
        "build": r.get("build"), "cargo_test": r.get("cargo_test"),
        "differential_pct": r.get("differential_pct"),
        "spec_precedence_chain": r.get("spec_precedence_chain"),
        "violations": r.get("violations")} for r in reports],
        "first_failures": [r["first_failures"][:1200] for r in results]}


def tool(name, description, properties, fn, required=()):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(required)}, "fn": fn}


TOOLS = [
    tool("read_python", "Read up to 160 numbered lines of reference/version.py.",
         {"start": {"type": "integer"}, "end": {"type": "integer"}}, t_read_python),
    tool("read_tests", "Read up to 120 lines from a reference test file.",
         {"name": {"type": "string"}, "start": {"type": "integer"},
          "end": {"type": "integer"}}, t_read_tests),
    tool("read_rust", "Read rust/src/lib.rs.", {}, t_read_rust),
    tool("write_rust", "Write complete rust/src/lib.rs with tests.",
         {"content": {"type": "string"}}, t_write_rust, ("content",)),
    tool("replace_rust", "Replace one exact region of rust/src/lib.rs.",
         {"old": {"type": "string"}, "new": {"type": "string"}},
         t_replace_rust, ("old", "new")),
    tool("cargo_build", "Build the release crate.", {}, t_cargo_build),
    tool("cargo_test", "Run release Rust tests.", {}, t_cargo_test),
    tool("evaluate", "Run 60 practice cases per family and report failures.",
         {}, t_evaluate),
    tool("verify", "Final gate: 300 cases on seeds 0, 17 and 91.", {}, t_verify),
]
BY_NAME = {t["name"]: t for t in TOOLS}
SCHEMAS = [{k: t[k] for k in ("name", "description", "parameters")}
           for t in TOOLS]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=40)
    parser.add_argument("--task", default="Translate reference/version.py into rust/src/lib.rs.")
    args = parser.parse_args()
    if not 1 <= args.budget <= 40:
        parser.error("budget must be 1 to 40")
    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"run-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    def rec(**data):
        with log.open("a") as stream:
            stream.write(json.dumps({"t": time.time(), **data}) + "\n")

    history = [{"role": "system", "content": system_prompt()},
               {"role": "user", "content": args.task}]
    rec(event="start", budget=args.budget, task=args.task)
    step = 0
    while True:
        stop, reason = should_stop(history, step, args.budget, STATE["score"])
        if stop:
            print(f"[stop] {reason}", flush=True)
            rec(event="stop", reason=reason, steps=step)
            break
        step += 1
        STATE["step"] = step
        try:
            reply = call_model(build_context(history, step), SCHEMAS)
        except Exception as exc:
            rec(event="model_error", step=step, error=str(exc))
            raise
        calls = reply.get("tool_calls") or []
        rec(event="model", step=step, reply=reply)
        history.append({"role": "assistant", "content": reply.get("text") or "",
                        "tool_calls": calls})
        print(f"[{step}] {str(reply.get('text', ''))[:180]}", flush=True)
        if not calls:
            STATE["idle"] += 1
            continue
        STATE["idle"] = 0
        call = calls[0]
        name, arguments = call.get("name"), call.get("arguments") or {}
        if name in {"read_python", "read_tests"}:
            STATE["source_reads"] += 1
        if name in {"write_rust", "replace_rust"}:
            STATE["written"] = True
        action = json.dumps([name, arguments], sort_keys=True)
        STATE["repeats"] = STATE["repeats"] + 1 if action == STATE["previous_action"] else 0
        STATE["previous_action"] = action
        selected = BY_NAME.get(name)
        try:
            output = f"unknown tool {name!r}" if selected is None else selected["fn"](arguments)
        except Exception as exc:
            output = {"error": f"{type(exc).__name__}: {exc}"}
        rendered = output if isinstance(output, str) else json.dumps(output)
        print(f"    -> {name}: {rendered.splitlines()[0][:180]}", flush=True)
        rec(event="tool", step=step, name=name, arguments=arguments, output=rendered)
        history.append({"role": "tool", "name": name, "content": rendered})
    final = _evaluate(0, 300)
    rec(event="final", report=final["report"])
    print(f"trajectory: {log}", flush=True)
    print("final report:", json.dumps({k: final["report"].get(k) for k in
          ("build", "cargo_test", "differential_pct", "spec_precedence_chain",
           "violations")}), flush=True)


if __name__ == "__main__":
    main()
