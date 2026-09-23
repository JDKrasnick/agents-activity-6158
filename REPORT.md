# Translation agent report

The submitted nine-call trajectory produced a compiling Rust translation and
stopped after its verification tool passed. `cargo test --release` passed all
7 tests. The full evaluator scored **100.00%** on practice seed 0 and seed 17,
and **99.63%** on seed 91. The semver precedence chain passed on each seed.
The quality scan found zero `unsafe` blocks, `.clone()` calls, `.unwrap()`
calls, forbidden macros, or extra dependencies.

The seed 91 losses come from generated strings such as
`29.19.14-06.201.r`: the evaluator puts them in its “valid” set, but its own
Python oracle rejects the leading-zero numeric prerelease. The same issue
causes downstream checker errors in comparison and bump cases. I stopped at
this baseline rather than teach the translation to accept an invalid SemVer
string to improve a faulty test score.

I estimate **70% agent / 30% scaffold** for the result. The agent read source
and tests, wrote the Rust implementation and its tests, and chose to build,
test, evaluate, and verify. I supplied the model adapter, bounded context,
targeted editing tools, score tracking, rollback, and stopping criteria.

An early pilot run repeatedly requested source excerpts after older excerpts
fell out of its context. That was unintended and made no implementation
progress. I changed context construction to retain selected source evidence
and direct the agent to write after a short inspection phase. The submitted
run then wrote the translation on call 5, verified it on call 9, and stopped
with 31 calls unused. The main challenge was making test feedback useful
without filling the model context or chasing discrepancies in the evaluator.
