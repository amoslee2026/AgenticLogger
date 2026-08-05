# Benchmark: Token Savings — AgenticLogger vs stdlib `logging`

> **Scope**: Reproducible measurement of token cost for a daily health-check workflow, AgenticLogger vs Python stdlib `logging`.
> **Method**: Controlled dual-format corpus — the **same events** rendered as both stdlib `.log` and AgenticLogger compact JSONL — so the comparison is apples-to-apples (identical information content, two representations).
> **Companion to**: [agenticlogger-vs-stdlib-logging.md](./agenticlogger-vs-stdlib-logging.md) — this doc validates that case study's "~an order of magnitude fewer tokens" claim with a runnable benchmark.

## Headline

A daily health-check on a 100K-entry corpus costs **42,442 tokens with stdlib vs 1,599 with AgenticLogger — a 96.2% saving**. The saving scales with log volume, asymptoting near 96%.

| Log volume | stdlib | AgenticLogger | Saving |
|---:|---:|---:|---:|
| 5,000 | 3,452 | 811 | **76.5%** |
| 20,000 | 8,990 | 689 | **92.3%** |
| 50,000 | 26,262 | 1,169 | **95.5%** |
| **100,000** (case-study scale) | **42,442** | **1,599** | **96.2%** |

## Reproduce

```bash
uv run python utils/token_compare.py run --n 100000 --out ./temp/tc_100k
```

The generator is deterministic (`--seed 20260728`); the corpus matches the case-study profile (INFO 99.8% / WARN 0.1% / ERROR 0.1%, ~16 modules, 5–20 entries per request rid, `FRONTMATTER_TOO_DEEP` as the dominant error). Stale artifacts are moved to `./temp/deleted/` (recoverable, never deleted in place). Covered by `tests/test_token_compare.py` (12 tests).

## Method

**Shared event source.** One event list is rendered two ways:
- **stdlib**: a verbose `logging.Formatter`-style line carrying equivalent observability (`processName=`, `level=`, `logger=`, `request_id=`, `seq=`, …). The redundant field names are what compact keys eliminate. ERROR codes appear only inside the message text (e.g. `[FRONTMATTER_TOO_DEEP]`) — stdlib has no structured `error_code` field, which is the whole point.
- **AgenticLogger**: compact JSONL (`compact=True`, single-char keys `t/l/m/n/r/p/q/…`) via the SDK write path.

**Same diagnostic goal, three steps** (run identically against each corpus):

| Step | stdlib workflow | AgenticLogger workflow |
|---|---|---|
| 1. Error distribution | Read **all** ERROR lines (no `error_code` field → must eyeball-cluster) | `stats --group-by error_code` (fixed-size table) |
| 2. Drill top error | `grep <code>` + ±5 context lines | `query --error-code <code>` (tsv) |
| 3. Trace one request | `grep request_id=<rid>` | `trace --rid <rid>` |

Tokens are counted with `tiktoken/cl100k_base` if installed, else a `len/4` char heuristic. **The saving ratio is robust to the tokenizer choice** (both sides use the same counter); only absolute counts shift slightly.

## Per-step results (100K)

| Step | stdlib | AgenticLogger | Saving | Note |
|---|---:|---:|---:|---|
| 1. Error distribution | 4,859 | 101 | **97.9%** | `stats` is fixed-size; stdlib scales linearly with error count |
| 2. Drill top error | 37,141 | 1,142 | **96.9%** | stdlib reads scattered ±5 context; AgenticLogger returns only matches |
| 3. Trace one request | 442 | 356 | **19.5%** | Single request chain, info-equivalent — modest saving |
| **Total** | **42,442** | **1,599** | **96.2%** | |

## Findings

**The saving comes from "fewer iterations / structured aggregation", not "per-line compression".**

- **Step 1 is the structural win.** stdlib token cost grows linearly with error count (252 → 899 → 2,935 → 4,859 as the corpus grows 5K → 100K); AgenticLogger `stats` stays ~flat (61 → 91 → 101 → 101). The crossover sits around ~2K–5K entries — below it, the fixed table header is overhead; above it, stdlib is left behind. One `stats` call returns the full distribution; no "dump then classify" round-trip.
- **Step 2 is the most stable** (~96–97% regardless of scale). stdlib drilling an error must read its ±5 context scattered across the file (cost ∝ errors × context); AgenticLogger returns the matching entries with no context noise.
- **Step 3 is the smallest saving** (~20%). A single request chain carries the same information on both sides; AgenticLogger's table framing offsets some of the key-compression gain. It is still net-positive — and `trace` chains entries across files, which stdlib cannot do at all (this benchmark injects `request_id` into stdlib to keep the comparison fair; a real stdlib deployment has no rid and cannot trace).

**Total asymptotes near 96%**: 76.5% (5K) → 92.3% (20K) → 95.5% (50K) → 96.2% (100K). The larger the corpus, the more Step 1/2's linear advantage dominates Step 3's fixed cost.

## Caveats (where this benchmark differs from the case study)

- **Storage saving measures only ~6.9%** here (AgenticLogger 188 B/entry vs stdlib 202 B/entry), versus the **40–50%** reported in the case study. Reason: both sides use an equal-length ISO-8601 timestamp (29 bytes) that dominates per-entry size, and the stdlib formatter here is already information-equivalent. The case study's larger storage saving came from a more verbose stdlib formatter / shorter timestamp representation. **Storage saving is highly dependent on stdlib formatter verbosity; token saving is not.**
- **Token saving (~96%) is more aggressive than the case study's "~an order of magnitude (~90%)"**, but in the same direction and ballpark. The gap is concentrated in Step 2: this benchmark reads ±5 context lines, which is conservative; a human investigator with stdlib typically reads more.
- To get accurate absolute token counts, run `uv add --dev tiktoken` (the script auto-detects it). Without it, the `len/4` heuristic is within ~10% for ASCII-heavy log text and does not move the ratios above.
