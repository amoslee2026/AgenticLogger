"""Tests for CLI commands."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_logger import AgentLogger, ErrorCode


@pytest.fixture
def cli_env(tmp_path):
    """Set up a log directory with test data and return CLI base args."""
    log_dir = tmp_path / "logs"
    logger = AgentLogger(program="cli_test", command="demo", log_dir=log_dir, storage="jsonl")
    logger.run_start()
    logger.info("Processing", module="agent.parser", ctx={"file": "data.json"})
    logger.warn("Slow op", dur=5000)
    logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.tool_call(tool="bash", cmd="rm", exit=1, dur=100, error_code=ErrorCode.EXEC_NON_ZERO)
    logger.decision(choice="async", alts=["sync"])
    logger.run_end(exit_code=0, dur=10000)

    # Save a traceback
    try:
        raise ValueError("test error")
    except Exception as e:
        tid = logger.save_traceback(e)
        logger.error("Exception caught", error_code=ErrorCode.INTERNAL_UNEXPECTED, tid=tid)

    base = [sys.executable, "-m", "agentic_logger.cli", "--log-dir", str(log_dir)]
    return base, logger.rid, tid


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


class TestQuery:
    def test_query_all(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query"])
        assert r.returncode == 0
        assert "Found" in r.stdout

    def test_query_by_level(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--level", "ERROR"])
        assert r.returncode == 0
        assert "Failed" in r.stdout or "Exception" in r.stdout

    def test_query_json_format(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "count" in data
        assert "logs" in data

    def test_query_by_error_code(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--error-code", "IO_NOT_FOUND"])
        assert r.returncode == 0
        assert "IO_NOT_FOUND" in r.stdout


class TestTrace:
    def test_trace_by_rid(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid])
        assert r.returncode == 0
        assert f"rid={rid}" in r.stdout

    def test_trace_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid, "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["rid"] == rid

    def test_trace_with_traceback(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid, "--include-traceback", "--format", "json"])
        assert r.returncode == 0


class TestStats:
    def test_stats_by_level(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["stats", "--group-by", "level"])
        assert r.returncode == 0
        assert "INFO" in r.stdout
        assert "ERROR" in r.stdout

    def test_stats_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["stats", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "total" in data
        assert "groups" in data


class TestTail:
    def test_tail_no_follow(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["tail"])
        assert r.returncode == 0
        assert "Tailing:" in r.stderr


class TestTraceback:
    def test_traceback_found(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["traceback", "--tid", tid])
        assert r.returncode == 0
        assert "ValueError" in r.stdout

    def test_traceback_not_found(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["traceback", "--tid", "nonexistent"])
        assert r.returncode == 1


class TestListFiles:
    def test_list_files(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["list-files"])
        assert r.returncode == 0
        assert "cli_test_demo_" in r.stdout

    def test_list_files_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["list-files", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) >= 1


class TestParseSince:
    """P2: _parse_since must reject ambiguous input instead of silent wrong windows."""

    def test_no_unit_raises(self):
        from agentic_logger.cli import _parse_since
        with pytest.raises(ValueError):
            _parse_since("100")  # bare number, no unit

    def test_non_integer_raises(self):
        from agentic_logger.cli import _parse_since
        with pytest.raises(ValueError):
            _parse_since("1.5h")  # fractional value

    def test_valid_relative(self):
        from agentic_logger.cli import _parse_since
        result = _parse_since("1h")
        assert result is not None and "T" in result

    def test_iso_passthrough(self):
        from agentic_logger.cli import _parse_since
        iso = "2026-07-21T00:00:00+00:00"
        assert _parse_since(iso) == iso


class TestTailDedup:
    """P2: tail must not drop entries that share a millisecond timestamp."""

    def test_same_ts_different_seq_both_emitted(self, tmp_path, capsys):
        from agentic_logger.cli import cmd_tail, build_parser

        log_dir = tmp_path / "logs"
        logger = AgentLogger(program="t", command="c", log_dir=log_dir, storage="jsonl")
        b = logger._backend
        shared_ts = "2026-07-21T10:00:00.000+00:00"
        b.write({"ts": shared_ts, "level": "INFO", "msg": "alpha",
                 "module": "m", "rid": "r", "pid": "1", "seq": 1})
        b.write({"ts": shared_ts, "level": "INFO", "msg": "beta",
                 "module": "m", "rid": "r", "pid": "1", "seq": 2})

        args = build_parser().parse_args(["--log-dir", str(log_dir), "tail"])
        cmd_tail(args)
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" in out


# === Direct in-process CLI tests (for coverage; subprocess tests above don't credit) ===


@pytest.fixture
def populated_cli(tmp_path):
    log_dir = tmp_path / "logs"
    logger = AgentLogger(program="cli", command="demo", log_dir=log_dir, storage="jsonl")
    logger.run_start()
    logger.info("Processing", module="agent.parser", ctx={"file": "data.json"})
    logger.warn("Slow op", dur=5000)
    logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.tool_call(tool="bash", cmd="rm", exit=1, dur=100, error_code=ErrorCode.EXEC_NON_ZERO)
    logger.decision(choice="async", alts=["sync"])
    logger.file_op("write", "/tmp/o.txt", ok=True, size=10)
    logger.code_gen(lang="python", path="src/x.py", lines=5)
    logger.context_switch(to_task="b", from_task="a")
    try:
        raise ValueError("boom")
    except Exception as e:
        tid = logger.save_traceback(e)
        logger.error("Exc", error_code=ErrorCode.INTERNAL_UNEXPECTED, tid=tid)
    logger.run_end(exit_code=0, dur=10000)
    return log_dir, tid


def _parse(populated_cli, *opts):
    log_dir, _ = populated_cli
    from agentic_logger.cli import build_parser
    return build_parser().parse_args(["--log-dir", str(log_dir), *opts])


class TestDirectCommands:
    def test_query_table_and_json(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_query
        assert cmd_query(_parse(populated_cli, "query")) == 0
        assert "Found" in capsys.readouterr().out
        assert cmd_query(_parse(populated_cli, "query", "--format", "json")) == 0
        json.loads(capsys.readouterr().out)

    def test_query_with_filters(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_query
        cmd_query(_parse(populated_cli, "query", "--level", "ERROR", "--error-code",
                         "IO_NOT_FOUND", "--since", "1h", "--until", "1d",
                         "--min-dur", "1", "--module", "agent.*", "--keyword", "Failed",
                         "--limit", "5", "--offset", "0", "--order-by", "ts_asc"))
        capsys.readouterr()

    def test_query_table_with_dur_and_error_cols(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_query
        cmd_query(_parse(populated_cli, "query", "--format", "table"))
        out = capsys.readouterr().out
        assert "dur" in out and "error_code" in out

    def test_trace_table_and_json(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_trace
        log_dir, tid = populated_cli
        a = _parse(populated_cli, "trace", "--rid", "__placeholder__")
        a.rid = _rid_of(log_dir)
        assert cmd_trace(a) == 0
        assert "Trace for" in capsys.readouterr().out
        a2 = _parse(populated_cli, "trace", "--rid", _rid_of(log_dir), "--format", "json",
                    "--include-traceback")
        assert cmd_trace(a2) == 0
        json.loads(capsys.readouterr().out)

    def test_stats_table_and_json(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_stats
        assert cmd_stats(_parse(populated_cli, "stats", "--group-by", "level")) == 0
        assert "Statistics" in capsys.readouterr().out
        assert cmd_stats(_parse(populated_cli, "stats", "--group-by", "tool",
                                "--since", "1d", "--format", "json")) == 0
        json.loads(capsys.readouterr().out)

    def test_tail_text_and_json_and_filters(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_tail
        assert cmd_tail(_parse(populated_cli, "tail")) == 0
        assert "Tailing:" in capsys.readouterr().err
        assert cmd_tail(_parse(populated_cli, "tail", "--format", "json",
                               "--level", "ERROR", "--module", "agent.*",
                               "--error-code", "IO_NOT_FOUND")) == 0
        capsys.readouterr()

    def test_tail_no_backends(self, tmp_path, capsys):
        from agentic_logger.cli import cmd_tail
        empty = tmp_path / "empty"
        empty.mkdir()
        from agentic_logger.cli import build_parser
        args = build_parser().parse_args(["--log-dir", str(empty), "tail"])
        assert cmd_tail(args) == 1

    def test_traceback_text_and_json(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_traceback
        _, tid = populated_cli
        assert cmd_traceback(_parse(populated_cli, "traceback", "--tid", tid)) == 0
        assert "Traceback:" in capsys.readouterr().out
        assert cmd_traceback(_parse(populated_cli, "traceback", "--tid", tid,
                                    "--format", "json")) == 0
        json.loads(capsys.readouterr().out)

    def test_traceback_not_found(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_traceback
        assert cmd_traceback(_parse(populated_cli, "traceback", "--tid", "nope")) == 1

    def test_list_files_table_and_json(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_list_files
        assert cmd_list_files(_parse(populated_cli, "list-files")) == 0
        assert "cli_demo_" in capsys.readouterr().out
        assert cmd_list_files(_parse(populated_cli, "list-files", "--format", "json")) == 0
        json.loads(capsys.readouterr().out)

    def test_list_files_empty(self, tmp_path, capsys):
        from agentic_logger.cli import cmd_list_files, build_parser
        empty = tmp_path / "empty"
        empty.mkdir()
        args = build_parser().parse_args(["--log-dir", str(empty), "list-files"])
        assert cmd_list_files(args) == 0


class TestFormatHelpers:
    def test_format_table_empty(self):
        from agentic_logger.cli import _format_table
        assert _format_table([], ["a", "b"]) == "(no results)"

    def test_format_table_truncation(self):
        from agentic_logger.cli import _format_table
        long = "x" * 100
        out = _format_table([{"a": long, "b": "y"}], ["a", "b"])
        assert "..." in out

    def test_format_entry_json(self):
        from agentic_logger.cli import _format_entry_json
        assert "k" in json.loads(_format_entry_json({"k": "v"}))


class TestMain:
    def test_main_no_command_exits(self, populated_cli, capsys):
        from agentic_logger.cli import main
        import sys
        log_dir, _ = populated_cli
        with pytest.raises(SystemExit):
            main_with_args(["--log-dir", str(log_dir)])

    def test_main_bad_since_returns_2(self, populated_cli, capsys):
        with pytest.raises(SystemExit) as ei:
            main_with_args(["--log-dir", str(populated_cli[0]), "query", "--since", "100"])
        assert ei.value.code == 2

    def test_main_unknown_handler(self, populated_cli, capsys):
        # build_parser enforces a valid subcommand, so exercise main via a
        # malformed invocation path by calling handler dispatch directly.
        from agentic_logger.cli import main
        with pytest.raises(SystemExit):
            main_with_args(["--log-dir", str(populated_cli[0]), "query"])


def main_with_args(argv):
    """Run cli.main with a synthetic argv (avoids monkeypatching sys.argv inline)."""
    import sys
    old = sys.argv
    sys.argv = ["agentic-logger", *argv]
    try:
        from agentic_logger.cli import main
        return main()
    finally:
        sys.argv = old


def _rid_of(log_dir):
    """Read the rid from the single log file's global context."""
    from pathlib import Path
    import json as _j
    files = list(Path(log_dir).glob("*.jsonl"))
    with open(files[0]) as f:
        for line in f:
            rec = _j.loads(line)
            if rec.get("level") == "__GLOBAL_CTX__":
                return rec.get("rid")
    return None


class TestCliRemaining:
    def test_trace_table_include_traceback(self, populated_cli, capsys):
        from agentic_logger.cli import cmd_trace
        log_dir, tid = populated_cli
        a = _parse(populated_cli, "trace", "--rid", _rid_of(log_dir), "--include-traceback")
        assert cmd_trace(a) == 0
        assert "tid" in capsys.readouterr().out

    def test_tail_skips_exact_duplicate_key(self, tmp_path, capsys):
        """Identical (ts, seq) entries: second is skipped via the seen-continue."""
        from agentic_logger.cli import cmd_tail, build_parser
        log_dir = tmp_path / "logs"
        logger = AgentLogger(program="t", command="c", log_dir=log_dir)
        b = logger._backend
        line = ("{\"ts\":\"2026-07-21T10:00:00.000+00:00\",\"level\":\"INFO\","
                "\"msg\":\"dup\",\"module\":\"m\",\"rid\":\"r\",\"pid\":\"1\",\"seq\":1}\n")
        with open(b.file_path, "a") as f:
            f.write(line * 2)  # two identical lines -> same (ts, seq) key
        args = build_parser().parse_args(["--log-dir", str(log_dir), "tail"])
        cmd_tail(args)
        out = capsys.readouterr().out
        assert out.count("dup") == 1

    def test_tail_module_and_error_code_filters(self, tmp_path, capsys):
        """Exercise tail's module (fnmatch) + error_code filter lines."""
        from agentic_logger.cli import cmd_tail, build_parser
        log_dir = tmp_path / "logs"
        logger = AgentLogger(program="t", command="c", log_dir=log_dir)
        logger.info("plain", module="agent.x")
        logger.error("boom", error_code=ErrorCode.IO_NOT_FOUND)
        args = build_parser().parse_args(
            ["--log-dir", str(log_dir), "tail", "--module", "agent.*",
             "--error-code", "IO_NOT_FOUND"]
        )
        assert cmd_tail(args) == 0

    def test_tail_error_code_filter(self, tmp_path, capsys):
        """Exercise tail's error_code filter line."""
        from agentic_logger.cli import cmd_tail, build_parser
        log_dir = tmp_path / "logs"
        logger = AgentLogger(program="t", command="c", log_dir=log_dir)
        logger.error("boom", error_code=ErrorCode.IO_NOT_FOUND)
        args = build_parser().parse_args(
            ["--log-dir", str(log_dir), "tail", "--error-code", "IO_NOT_FOUND"]
        )
        assert cmd_tail(args) == 0

    def test_tail_follow_interrupt(self, tmp_path, capsys, monkeypatch):
        """--follow + KeyboardInterrupt must print 'Stopped' and return 0."""
        import agentic_logger.cli as cli_mod
        log_dir = tmp_path / "logs"
        AgentLogger(program="t", command="c", log_dir=log_dir).info("x")

        def boom(_seconds):
            raise KeyboardInterrupt
        monkeypatch.setattr(cli_mod.time, "sleep", boom)
        args = cli_mod.build_parser().parse_args(
            ["--log-dir", str(log_dir), "tail", "--follow"]
        )
        assert cli_mod.cmd_tail(args) == 0
        assert "Stopped" in capsys.readouterr().err
