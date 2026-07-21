"""JSONL storage backend.

spec 05-storage.md §3: JSONL 后端
- 流式追加写入
- 循环写入安全轮转 (先改名→创建新文件→删除旧文件)
- 堆栈跟踪分离存储 (.tracebacks)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path


class JSONLBackend:
    """JSONL (JSON Lines) storage backend.

    Each log entry is one line of JSON. Supports:
    - Streaming append writes
    - Circular rotation with safe ordering
    - Separate traceback storage

    Args:
        file_path: Path to the JSONL log file.
        max_files: Max number of log files to keep (circular).
        max_size_mb: Max file size in MB before rotation.
        circular: Enable circular write mode.
        global_ctx: Global context dict written to file header.
    """

    def __init__(
        self,
        file_path: Path | str,
        max_files: int = 10,
        max_size_mb: int = 500,
        circular: bool = False,
        global_ctx: dict | None = None,
    ):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.circular = circular
        self._global_ctx = global_ctx or {}
        self._write_count = 0

        # Recover from interrupted rotation
        self._recover_from_interrupted_rotation()
        # Write global context to new file header
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            self._write_global_context()

    # --- Write API ---

    def write(self, entry: dict) -> None:
        """Write a single log entry."""
        if self.circular and self._should_rotate():
            self._safe_rotate()

        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._write_count += 1

    def write_batch(self, entries: list[dict]) -> None:
        """Write multiple log entries in one IO operation."""
        lines = [json.dumps(e, ensure_ascii=False, default=str) for e in entries]
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._write_count += len(entries)

    def save_traceback(self, tid: str, traceback_text: str, exc_type: str, exc_msg: str) -> None:
        """Save traceback to separate file, keyed by tid.

        Uses file locking (fcntl) for multi-process safety.
        spec 05-storage.md §6: 堆栈跟踪分离存储
        """
        tb_path = self._traceback_path()
        tb_path.parent.mkdir(parents=True, exist_ok=True)
        # Sanitize: replace newlines in traceback to keep one-line-per-record
        safe_tb = traceback_text.replace("\n", "\\n")
        line = f"{tid}|{exc_type}|{exc_msg}|{safe_tb}\n"

        with open(tb_path, "a", encoding="utf-8") as f:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line)
                f.flush()
            finally:
                try:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def get_traceback(self, tid: str) -> dict | None:
        """Retrieve traceback by tid."""
        tb_path = self._traceback_path()
        if not tb_path.exists():
            return None
        with open(tb_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|", 3)
                if len(parts) == 4 and parts[0] == tid:
                    return {
                        "tid": parts[0],
                        "exception_type": parts[1],
                        "exception_msg": parts[2],
                        "traceback": parts[3].replace("\\n", "\n"),
                    }
        return None

    # --- Query API ---

    def query(self, **filters) -> list[dict]:
        """Query logs with filters.

        Supported filters: level, module, error_code, tool, rid, pid, tid,
                          min_dur, max_dur, since, until, limit, offset.
        """
        limit = filters.pop("limit", 1000)
        offset = filters.pop("offset", 0)
        order_by = filters.pop("order_by", "ts_desc")

        if not self.file_path.exists():
            return []

        results = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self._match(entry, filters):
                    results.append(entry)

        # Sort
        reverse = order_by != "ts_asc"
        if order_by == "dur_desc":
            results.sort(key=lambda x: x.get("dur") or 0, reverse=True)
        else:
            results.sort(key=lambda x: x.get("ts", ""), reverse=reverse)

        # Paginate
        return results[offset : offset + limit]

    def get_time_range(self) -> dict | None:
        """Get min/max timestamps for this file (used by query engine)."""
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return None
        min_ts = None
        max_ts = None
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("ts")
                    if ts:
                        if min_ts is None or ts < min_ts:
                            min_ts = ts
                        if max_ts is None or ts > max_ts:
                            max_ts = ts
                except json.JSONDecodeError:
                    continue
        return {"min_ts": min_ts, "max_ts": max_ts} if min_ts else None

    # --- Internal ---

    def _should_rotate(self) -> bool:
        return self.file_path.exists() and self.file_path.stat().st_size > self.max_size_bytes

    def _safe_rotate(self) -> None:
        """Safe rotation: rename → create new → delete oldest.

        spec 05-storage.md §5.1: 评审修复 AGG-001
        """
        rotating_path = self.file_path.with_suffix(".jsonl.rotating")

        # Step 1: Rename current file (mark as rotating)
        try:
            self.file_path.rename(rotating_path)
        except FileNotFoundError:
            return  # File already gone

        try:
            # Step 2: Create new file
            new_path = self._generate_next_filename()
            new_path.touch()
            self.file_path = new_path
            self._write_global_context()

            # Step 3: Delete oldest completed files
            files = sorted(self._get_completed_files())
            while len(files) >= self.max_files:
                oldest = files[0]
                oldest.unlink(missing_ok=True)
                # Clean up corresponding traceback file
                tb_file = oldest.with_suffix(".tracebacks")
                if tb_file.exists():
                    tb_file.unlink()
                files = sorted(self._get_completed_files())

            # Step 4: Remove .rotating suffix (rotation complete)
            final_path = rotating_path.with_suffix(".jsonl")
            rotating_path.rename(final_path)

        except OSError as e:
            # Rollback: restore original filename
            if rotating_path.exists():
                rotating_path.rename(self.file_path)
            raise RuntimeError(f"Rotation failed, original file restored: {e}") from e

    def _recover_from_interrupted_rotation(self) -> None:
        """Recover from a rotation that was interrupted mid-way."""
        parent = self.file_path.parent
        for f in parent.glob("*.rotating"):
            original = f.with_suffix(".jsonl")
            if not original.exists():
                f.rename(original)
            else:
                f.unlink(missing_ok=True)

    def _generate_next_filename(self) -> Path:
        """Generate next filename for rotation."""
        base = self.file_path.stem
        # Extract the base pattern (without timestamp)
        match = re.match(r"(.+?)_\d{8}_\d+$", base)
        if match:
            base_pattern = match.group(1)
        else:
            base_pattern = base

        now = datetime.now()
        time_str = now.strftime("%H%M%S") + f"{now.microsecond:06d}"
        date_str = now.strftime("%Y%m%d")
        name = f"{base_pattern}_{date_str}_{time_str}.jsonl"
        return self.file_path.parent / name

    def _get_completed_files(self) -> list[Path]:
        """Get all completed log files (not .rotating)."""
        # Find files matching the same base pattern
        pattern = self.file_path.stem
        match = re.match(r"(.+?)_\d{8}_\d+$", pattern)
        if match:
            base_pattern = match.group(1)
        else:
            base_pattern = pattern

        return sorted(
            f
            for f in self.file_path.parent.glob(f"{base_pattern}_*.jsonl")
            if not f.name.endswith(".rotating")
        )

    def _write_global_context(self) -> None:
        """Write global context as first line of the file."""
        if not self._global_ctx:
            return
        ctx_entry = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": "__GLOBAL_CTX__",
            "msg": "Global context",
            "module": "__system__",
            "tid": None,
            "rid": self._global_ctx.get("rid", ""),
            "pid": str(os.getpid()),
            "seq": 0,
            "dur": None,
            "error_code": None,
            **self._global_ctx,
        }
        line = json.dumps(ctx_entry, ensure_ascii=False, default=str)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _traceback_path(self) -> Path:
        return self.file_path.with_suffix(".tracebacks")

    @staticmethod
    def _match(entry: dict, filters: dict) -> bool:
        """Check if entry matches all filters."""
        for key, value in filters.items():
            if value is None:
                continue
            if key == "min_dur":
                if (entry.get("dur") or 0) < value:
                    return False
            elif key == "max_dur":
                if (entry.get("dur") or 0) > value:
                    return False
            elif key == "module" and "*" in str(value):
                import fnmatch
                if not fnmatch.fnmatch(entry.get("module", ""), value):
                    return False
            elif key == "keyword":
                text = json.dumps(entry, ensure_ascii=False).lower()
                if str(value).lower() not in text:
                    return False
            elif key in entry and str(entry[key]) != str(value):
                return False
        return True
