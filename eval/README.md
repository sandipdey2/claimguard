# eval/

| File | Written by | What |
|---|---|---|
| `logs/live_*.json` | `scripts/live_run.py` | real gpt-4o-mini runs made after the first commit, each carrying its git sha in the receipt; includes the draft, the 12 check statuses, gate inputs, spans, cost, and the published outcome (held out from the agents) |
| `logs/dev/` | pre-commit development runs | 5 runs made before any commit (`git_sha: unknown`), kept for the gardener; their receipts used an ephemeral key |
| `model_report.json` | `scripts/train_models.py` | P3 overturn model: time split, validation comparison, 2025 test metrics, baselines, calibration |
| `text_model_report.json` | same | P4 text model + Findings leakage upper bound |
| `stats_results.json` | same | P2 tests with effect sizes |
| `summary.json` | `scripts/run_eval.py` | retrieval recall@k / MRR, gate mutation test, live-run quality, injection block / false-positive rate |
| `garden_report.json` | `scripts/garden.py` | recurring failure patterns (propose-only) |
| `verify_mcp.log` | `scripts/verify_mcp.py` | MCP stdio + streamable-HTTP check |

Two evaluation fixes were made after a first pass; both first-pass results are recorded in `summary.json`:

- **Injection patterns.** The first pass blocked 12 of 16 prompts and patterns were added afterwards, so 16/16 is in-sample.
- **Number grounding.** The first pass caught 39 of 40 mutations, and grounding became rounding-aware.

The receipts in `logs/` were signed with a local `CG_RECEIPT_KEY` that is not in the repo, so they verify only on the machine that made them. `receipt_verifies: true` was recorded at run time.
