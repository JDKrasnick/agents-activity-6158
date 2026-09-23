# Translating Python to Rust with an agent

**CS 6158 — Software Engineering in the Era of ML/AI**

You will build an agent that translates a real Python module into Rust, and
you will be graded by differential testing against the original.

The module is `version.py` from
[python-semver](https://github.com/python-semver/python-semver) (BSD-3-Clause)
— 831 lines, no dependencies, pure functions. The semantics look simple and
are not: version precedence has enough edge cases that a first-pass
translation reliably gets several of them wrong.

---

## Setup

```sh
pip install -r requirements.txt
python fetch_source.py          # downloads the Python source into reference/
cd rust && cargo build --release && cd ..
python evaluate.py              # should report ~8% — the stub is unimplemented
```

If `cargo` is missing: https://rustup.rs

---

## What you are building

`rust/src/lib.rs` must expose exactly these, and your agent must write them:

```rust
pub struct Version { major, minor, patch, prerelease, build }

pub fn parse(s: &str)      -> Result<Version, String>
pub fn to_string(v: &Version) -> String
pub fn compare(a: &Version, b: &Version) -> std::cmp::Ordering
pub fn bump_major(v: &Version) -> Version
pub fn bump_minor(v: &Version) -> Version
pub fn bump_patch(v: &Version) -> Version
```

`rust/src/main.rs` is **given and must not be edited** — it is the protocol
`evaluate.py` speaks. You may add anything you like to `lib.rs` beyond the
signatures above.

### Rules

| Rule | Why |
|---|---|
| no `unsafe` | you migrate to Rust *for* memory safety |
| no extra dependencies — std only | otherwise you are grading a crate someone else wrote |
| no calling back into Python | yes, someone tries this every year |
| no `todo!()` / `unimplemented!()` / `panic!` | these compile; they are not translations |
| **max 40 model calls** | the point is a good loop, not a big budget |

Violations are reported by `evaluate.py` and are not negotiable after the fact.

---

## How you are graded

`evaluate.py` measures five things:

1. **Does it build.** A gate — nothing else runs if it fails.
2. **`cargo test`** — the tests your agent wrote. Port cases from
   `reference/test_*.py`.
3. **Differential testing** — your Rust against the real `semver` package, on
   several thousand generated cases: valid parses, invalid rejections,
   comparisons, bumps, and round-trips.
4. **The semver.org precedence chain**, reported separately because it is the
   single best diagnostic:
   `1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-alpha.beta < 1.0.0-beta < 1.0.0-beta.2
   < 1.0.0-beta.11 < 1.0.0-rc.1 < 1.0.0`
5. **Quality** — `unsafe`, `.clone()`, `.unwrap()`, `todo!`, dependencies.

`python evaluate.py` runs the **practice** seed (0). Grading uses a different
seed you do not have. Tuning to seed 0 will not help you.

## Submission

Submit your compile and test pass rates to this excel sheet [leaderboard](https://docs.google.com/spreadsheets/d/1yZACTe5F9g39eSasnhkhc8vqFa-3t_42gcSU2hMJD7k/edit?usp=sharing).

### Why correctness is not the whole score

Your agent can reach a high differential score and still have failed the task:

- `.clone()` on everything to escape lifetimes — compiles, passes, and throws
  away the performance you migrated for
- `unsafe` to silence the borrow checker — compiles, passes, and throws away
  the *memory safety* you migrated for
- `todo!()` on the hard function — compiles, and the harness will report the
  panic as a failed case

This is the whole lesson. **Your reward signal is a test suite, and a test
suite is an incomplete specification of what you actually wanted.** An
optimiser pointed at an incomplete specification will find the gap. You are
building the optimiser, so you will watch it happen.

A submission at 85% with clean Rust scores above one at 95% with twelve
`unsafe` blocks.

---

## What to fill in

`agent.py` runs as given and accomplishes nothing. Five `TODO`s:

| TODO | What | Note |
|---|---|---|
| 1 | `call_model()` | any provider; keep the return shape |
| 2 | `system_prompt()` | how much spec do you bake in vs. make it read the source? |
| 3 | `build_context()` | **the hard one** |
| 4 | `should_stop()` | **the one everyone forgets** |
| 5 | the tool set | coarser/finer actions change results more than you expect |

Feel free to make any other changes you think are necessary to the code.

### On TODO 3

The naive version — send the whole history — fills the window around step 15
once compiler errors accumulate, and the agent starts repeating work. You may
**not** solve this by raising the context limit. Use write / select /
compress / isolate.

### On TODO 4

An agent that runs until its budget runs out has not terminated, it has been
stopped. Decide what "done" means, what "stuck" looks like, and what happens
when the score goes *down*.

---

## What to hand in

```
rust/src/lib.rs        your translation
agent.py               your completed agent
logs/run-*.jsonl       at least one full trajectory
REPORT.md              one page, see below
```

**REPORT.md** — one page, answering:

1. Your final score, and where it lost points.
2. **How much came from the agent, and how much from the scaffold you wrote
   around it?** Guess a split and justify it.
3. You had 40 model calls. Would **40 independent one-shot attempts plus a
   selector** have beaten your loop? What would you have needed to find out?
4. What did your agent do that you did not intend?
5. Which of your generated Rust would you actually merge?

Question 3 is the one that carries the most credit. Answering it honestly is
worth more than five points of differential score.

---

## Hints, in the order you will need them

- Read `reference/version.py` before writing any prompt. You cannot specify a
  translation you do not understand.
- Do **not** guess semantics — `bump_patch` on a prerelease, leading zeros in
  build vs. prerelease metadata. Check the oracle: `python -c "import semver; ..."`.
- Build metadata is **ignored entirely** for precedence. Almost every first
  draft gets this wrong.
- Numeric prerelease identifiers rank **below** non-numeric ones. So does a
  version with a prerelease rank below the same version without one.
- When the borrow checker fights you, the idiomatic fix is usually to own the
  string (`String`) rather than to clone a borrow. Both compile. Only one is
  what a Rust programmer would write.
