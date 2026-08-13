// Package agenticlogger is the Go SDK for AgenticLogger.
//
// Emits byte-compatible JSONL readable by the AgenticLogger Python query layer
// (cli / mcp_server) without any conversion.
//
// @contract: sdks/INTERCHANGE.md
package agenticlogger

// ErrorCode constants (contract §6). Identical values to the Python enum.
const (
	ErrParseJSON         = "PARSE_JSON"
	ErrParseYAML         = "PARSE_YAML"
	ErrParseXML          = "PARSE_XML"
	ErrParseCSV          = "PARSE_CSV"
	ErrParseRegex        = "PARSE_REGEX"
	ErrParseEncoding     = "PARSE_ENCODING"
	ErrIoNotFound        = "IO_NOT_FOUND"
	ErrIoPermission      = "IO_PERMISSION"
	ErrIoDiskFull        = "IO_DISK_FULL"
	ErrIoReadFail        = "IO_READ_FAIL"
	ErrIoWriteFail       = "IO_WRITE_FAIL"
	ErrIoLockFail        = "IO_LOCK_FAIL"
	ErrExecNonZero       = "EXEC_NON_ZERO"
	ErrExecTimeout       = "EXEC_TIMEOUT"
	ErrExecNotFound      = "EXEC_NOT_FOUND"
	ErrExecKilled        = "EXEC_KILLED"
	ErrExecCrash         = "EXEC_CRASH"
	ErrNetTimeout        = "NET_TIMEOUT"
	ErrNetDnsFail        = "NET_DNS_FAIL"
	ErrNetConnRefused    = "NET_CONN_REFUSED"
	ErrNetSslError       = "NET_SSL_ERROR"
	ErrNetHttpError      = "NET_HTTP_ERROR"
	ErrAuthLoginFail     = "AUTH_LOGIN_FAIL"
	ErrAuthTokenExpired  = "AUTH_TOKEN_EXPIRED"
	ErrAuthForbidden     = "AUTH_FORBIDDEN"
	ErrAuthUnauthorized  = "AUTH_UNAUTHORIZED"
	ErrConfigMissing     = "CONFIG_MISSING"
	ErrConfigInvalid     = "CONFIG_INVALID"
	ErrConfigRange       = "CONFIG_RANGE"
	ErrResMemory         = "RES_MEMORY"
	ErrResDisk           = "RES_DISK"
	ErrResCpu            = "RES_CPU"
	ErrResFd             = "RES_FD"
	ErrTimeoutAPI        = "TIMEOUT_API"
	ErrTimeoutDB         = "TIMEOUT_DB"
	ErrTimeoutLock       = "TIMEOUT_LOCK"
	ErrConflictVersion   = "CONFLICT_VERSION"
	ErrConflictLock      = "CONFLICT_LOCK"
	ErrConflictDuplicate = "CONFLICT_DUPLICATE"
	ErrInternalUnexpected = "INTERNAL_UNEXPECTED"
	ErrInternalAssert    = "INTERNAL_ASSERT"
	ErrInternalType      = "INTERNAL_TYPE"
	ErrInternalKey       = "INTERNAL_KEY"
	ErrInternalIndex     = "INTERNAL_INDEX"
	ErrUnknown           = "UNKNOWN"
)
