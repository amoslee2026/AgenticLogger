# Case Study: Real-World Token Savings in Claude Code Sessions

> **Scope**: Production measurement across 89 Claude Code sessions — before and after AgenticLogger adoption in a mid-size Python project (~50 modules).
> **Method**: Transcript mining of Claude Code session JSONL files — comparing session size, tool call patterns, thinking overhead, and log query efficiency across the migration boundary.
> **Companion to**: [token-savings-benchmark.md](./token-savings-benchmark.md) — that doc measures controlled synthetic corpora; this doc validates savings in actual production use.

## Headline

After AgenticLogger adoption, **average session size dropped 31%** (2.86 MB → 1.96 MB) and **thinking overhead dropped 27.5%** — while log analysis frequency increased 7x (5% → 36% of sessions). Total log data consumed stayed flat (~2.9M chars) despite far more queries, proving that cheaper per-query cost doesn't induce bloat.

| Metric | Before (< 07-22) | After (≥ 07-22) | Delta |
|---|---:|---:|---:|
| Sessions analyzed | 39 | 50 | +28% |
| **Avg session size** | **2,855,577 B** | **1,959,827 B** | **-31%** |
| Avg thinking chars | 142,916 | 103,610 | **-27.5%** |
| Avg tool calls | 105 | 106 | flat |
| Sessions doing log analysis | 2/39 (5%) | 18/50 (36%) | **7x↑** |
| Avg log result per query | 4,741 chars | 4,068 chars | -14% |
| Total log data consumed | ~2.98M chars | ~2.89M chars | flat |

## Head-to-Head: Same Query, Two Ways

For 20 entries from a typical application module:

| Approach | Command | Output |
|---|---|---:|
| Old (raw grep) | `grep "myapp.service.client" logs/agentic/*.jsonl \| head -20` | 3,395 chars |
| New (agentic-logger TSV) | `agentic-logger query --module myapp.service.client --format tsv` | 1,818 chars |
| **Single-query saving** | | **1.9x** |

The old way dumps raw JSONL (full field names, timestamps, redundant metadata). The new way emits compact TSV with only relevant columns — the agent gets the same diagnostic signal in half the characters.

## Why Session Size Dropped More Than Per-Query Size

The 31% session shrink exceeds the 14-47% per-query saving. Three compounding effects:

1. **Fewer grep iterations.** Structured `agentic-logger` output (TSV tables, `--smart` analysis, `trace --rid`) gives the agent what it needs in one call. Raw grep requires iterative refinement: grep → parse → grep again with tighter pattern → read context lines. Each iteration adds tool_result chars to the context window.

2. **Lower thinking overhead (-27.5%).** Parsing structured TSV requires less reasoning than interpreting raw JSONL. The agent spends fewer thinking tokens deciding what to grep next, which fields matter, how to correlate across lines.

3. **Progressive disclosure.** `agentic-logger query --depth summary` returns a compact table; `--depth detail` adds context only when needed. Raw grep has no such knob — you either get everything or manually pipe through `head`/`jq`.

## The Induced-Demand Non-Effect

Before migration, log analysis was expensive enough that the agent **avoided it** — only 5% of sessions attempted log queries. After migration, 36% of sessions do log analysis (7x more sessions, 23x more total log queries).

Crucially, **total log data consumed stayed flat** (~2.9M chars in both periods). Cheaper per-query cost enabled dramatically more observability without increasing the token budget. This is the correct economic outcome: the agent shifts from "don't look at logs because it's expensive" to "look at logs frequently because each look is cheap."

## Reproduce

```bash
# Analyze your own Claude Code sessions
cd ~/.claude/projects/<your-project>

python3 << 'PYEOF'
import json, os
from datetime import datetime

# Adjust to your AgenticLogger migration date
cutoff = datetime(2026, 7, 22)

for f in sorted(os.listdir('.')):
    if not f.endswith('.jsonl'): continue
    mtime = datetime.fromtimestamp(os.path.getmtime(f))
    size = os.path.getsize(f)
    period = "BEFORE" if mtime < cutoff else "AFTER"
    print(f"{period}  {mtime.strftime('%Y-%m-%d')}  {size:>12,} B  {f}")
PYEOF
```

## Data Source

- 89 Claude Code session transcripts from a single project directory
- Date range: 30 days spanning the migration boundary
- Project: mid-size Python application (~50 modules), all logging migrated to AgenticLogger in a single pass
- Model: consistent local model throughout the measurement window

## Caveats

1. **Not a controlled experiment.** Sessions before and after differ in task mix (new features, bug fixes, debugging). The 31% reduction could partly reflect task complexity shifts rather than logging alone.
2. **Diluted measurement.** The "avg log result per query" metric captures any tool_result mentioning "log" — not just log query results. True per-query saving for `agentic-logger` calls specifically is closer to 1.9x (see head-to-head table).
3. **Partial adoption.** Even post-migration, some sessions still fall back to raw grep/Read on `.jsonl` files (60 old-way calls vs 214 new-way calls). Full adoption would likely show larger savings.
4. **Model constant.** All sessions used the same model throughout the measurement window. Model changes would confound the comparison.
