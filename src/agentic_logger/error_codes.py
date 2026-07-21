"""Standard error code taxonomy for structured logging.

@spec-ref: spec/02-log-format.md §9 — 标准错误码字典 (ErrorCode)

Format: ``{CATEGORY}_{SPECIFIC}`` (UPPER_SNAKE_CASE).

Categories:
    PARSE_*     — JSON/YAML/XML/CSV parse failures
    IO_*        — File system read/write/permission errors
    EXEC_*      — Command execution failures, timeouts
    NET_*       — Network timeouts, DNS, SSL
    AUTH_*      — Authentication/authorization failures
    CONFIG_*    — Missing/invalid configuration
    RES_*       — Resource exhaustion (memory, disk, FD)
    TIMEOUT_*   — API/DB/lock timeouts
    CONFLICT_*  — Version, lock, duplicate conflicts
    INTERNAL_*  — Unexpected program errors (bugs)
    UNKNOWN     — Fallback when no category fits

Usage::

    from agentic_logger import ErrorCode
    logger.error("Parse failed", error_code=ErrorCode.PARSE_JSON)
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes for structured logging.

    Inherits from ``str`` so enum members serialize naturally to JSON
    without a custom encoder.

    @spec-ref: spec/02-log-format.md §9.2 — 完整错误码列表
    """

    # ── PARSE_* ────────────────────────────────────────────────────
    PARSE_JSON = "PARSE_JSON"
    PARSE_YAML = "PARSE_YAML"
    PARSE_XML = "PARSE_XML"
    PARSE_CSV = "PARSE_CSV"
    PARSE_REGEX = "PARSE_REGEX"
    PARSE_ENCODING = "PARSE_ENCODING"

    # ── IO_* ───────────────────────────────────────────────────────
    IO_NOT_FOUND = "IO_NOT_FOUND"
    IO_PERMISSION = "IO_PERMISSION"
    IO_DISK_FULL = "IO_DISK_FULL"
    IO_READ_FAIL = "IO_READ_FAIL"
    IO_WRITE_FAIL = "IO_WRITE_FAIL"
    IO_LOCK_FAIL = "IO_LOCK_FAIL"

    # ── EXEC_* ─────────────────────────────────────────────────────
    EXEC_NON_ZERO = "EXEC_NON_ZERO"
    EXEC_TIMEOUT = "EXEC_TIMEOUT"
    EXEC_NOT_FOUND = "EXEC_NOT_FOUND"
    EXEC_KILLED = "EXEC_KILLED"
    EXEC_CRASH = "EXEC_CRASH"

    # ── NET_* ──────────────────────────────────────────────────────
    NET_TIMEOUT = "NET_TIMEOUT"
    NET_DNS_FAIL = "NET_DNS_FAIL"
    NET_CONN_REFUSED = "NET_CONN_REFUSED"
    NET_SSL_ERROR = "NET_SSL_ERROR"
    NET_HTTP_ERROR = "NET_HTTP_ERROR"

    # ── AUTH_* ─────────────────────────────────────────────────────
    AUTH_LOGIN_FAIL = "AUTH_LOGIN_FAIL"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"

    # ── CONFIG_* ───────────────────────────────────────────────────
    CONFIG_MISSING = "CONFIG_MISSING"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_RANGE = "CONFIG_RANGE"

    # ── RES_* ──────────────────────────────────────────────────────
    RES_MEMORY = "RES_MEMORY"
    RES_DISK = "RES_DISK"
    RES_CPU = "RES_CPU"
    RES_FD = "RES_FD"

    # ── TIMEOUT_* ──────────────────────────────────────────────────
    TIMEOUT_API = "TIMEOUT_API"
    TIMEOUT_DB = "TIMEOUT_DB"
    TIMEOUT_LOCK = "TIMEOUT_LOCK"

    # ── CONFLICT_* ─────────────────────────────────────────────────
    CONFLICT_VERSION = "CONFLICT_VERSION"
    CONFLICT_LOCK = "CONFLICT_LOCK"
    CONFLICT_DUPLICATE = "CONFLICT_DUPLICATE"

    # ── INTERNAL_* ─────────────────────────────────────────────────
    INTERNAL_UNEXPECTED = "INTERNAL_UNEXPECTED"
    INTERNAL_ASSERT = "INTERNAL_ASSERT"
    INTERNAL_TYPE = "INTERNAL_TYPE"
    INTERNAL_KEY = "INTERNAL_KEY"
    INTERNAL_INDEX = "INTERNAL_INDEX"

    # ── UNKNOWN ────────────────────────────────────────────────────
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value
