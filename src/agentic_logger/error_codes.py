"""Standard error code taxonomy.

spec 02-log-format.md §9: 标准错误码字典 (ErrorCode)
格式: {CATEGORY}_{SPECIFIC} (全大写 + 下划线)
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes for structured logging.

    Usage:
        from agentic_logger import ErrorCode
        logger.error("Failed to parse", error_code=ErrorCode.PARSE_JSON)
    """

    # PARSE_* - 解析错误
    PARSE_JSON = "PARSE_JSON"
    PARSE_YAML = "PARSE_YAML"
    PARSE_XML = "PARSE_XML"
    PARSE_CSV = "PARSE_CSV"
    PARSE_REGEX = "PARSE_REGEX"
    PARSE_ENCODING = "PARSE_ENCODING"

    # IO_* - 文件系统
    IO_NOT_FOUND = "IO_NOT_FOUND"
    IO_PERMISSION = "IO_PERMISSION"
    IO_DISK_FULL = "IO_DISK_FULL"
    IO_READ_FAIL = "IO_READ_FAIL"
    IO_WRITE_FAIL = "IO_WRITE_FAIL"
    IO_LOCK_FAIL = "IO_LOCK_FAIL"

    # EXEC_* - 执行错误
    EXEC_NON_ZERO = "EXEC_NON_ZERO"
    EXEC_TIMEOUT = "EXEC_TIMEOUT"
    EXEC_NOT_FOUND = "EXEC_NOT_FOUND"
    EXEC_KILLED = "EXEC_KILLED"
    EXEC_CRASH = "EXEC_CRASH"

    # NETWORK_* - 网络错误
    NET_TIMEOUT = "NET_TIMEOUT"
    NET_DNS_FAIL = "NET_DNS_FAIL"
    NET_CONN_REFUSED = "NET_CONN_REFUSED"
    NET_SSL_ERROR = "NET_SSL_ERROR"
    NET_HTTP_ERROR = "NET_HTTP_ERROR"

    # AUTH_* - 认证授权
    AUTH_LOGIN_FAIL = "AUTH_LOGIN_FAIL"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    AUTH_UNAUTHORIZED = "AUTH_UNAUTHORIZED"

    # CONFIG_* - 配置错误
    CONFIG_MISSING = "CONFIG_MISSING"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_RANGE = "CONFIG_RANGE"

    # RESOURCE_* - 资源不足
    RES_MEMORY = "RES_MEMORY"
    RES_DISK = "RES_DISK"
    RES_CPU = "RES_CPU"
    RES_FD = "RES_FD"

    # TIMEOUT_* - 超时
    TIMEOUT_API = "TIMEOUT_API"
    TIMEOUT_DB = "TIMEOUT_DB"
    TIMEOUT_LOCK = "TIMEOUT_LOCK"

    # CONFLICT_* - 冲突
    CONFLICT_VERSION = "CONFLICT_VERSION"
    CONFLICT_LOCK = "CONFLICT_LOCK"
    CONFLICT_DUPLICATE = "CONFLICT_DUPLICATE"

    # INTERNAL_* - 内部错误
    INTERNAL_UNEXPECTED = "INTERNAL_UNEXPECTED"
    INTERNAL_ASSERT = "INTERNAL_ASSERT"
    INTERNAL_TYPE = "INTERNAL_TYPE"
    INTERNAL_KEY = "INTERNAL_KEY"
    INTERNAL_INDEX = "INTERNAL_INDEX"

    # UNKNOWN - 兜底
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value
