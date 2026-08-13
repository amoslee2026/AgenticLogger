//! Standard error-code taxonomy (contract §6).
//!
//! Identical values to Python `agentic_logger.error_codes.ErrorCode`.

/// UPPER_SNAKE error codes. Implements `Display` so it serializes as the
/// raw string value (no quoting wrapper).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorCode {
    // PARSE_*
    ParseJson,
    ParseYaml,
    ParseXml,
    ParseCsv,
    ParseRegex,
    ParseEncoding,
    // IO_*
    IoNotFound,
    IoPermission,
    IoDiskFull,
    IoReadFail,
    IoWriteFail,
    IoLockFail,
    // EXEC_*
    ExecNonZero,
    ExecTimeout,
    ExecNotFound,
    ExecKilled,
    ExecCrash,
    // NET_*
    NetTimeout,
    NetDnsFail,
    NetConnRefused,
    NetSslError,
    NetHttpError,
    // AUTH_*
    AuthLoginFail,
    AuthTokenExpired,
    AuthForbidden,
    AuthUnauthorized,
    // CONFIG_*
    ConfigMissing,
    ConfigInvalid,
    ConfigRange,
    // RES_*
    ResMemory,
    ResDisk,
    ResCpu,
    ResFd,
    // TIMEOUT_*
    TimeoutApi,
    TimeoutDb,
    TimeoutLock,
    // CONFLICT_*
    ConflictVersion,
    ConflictLock,
    ConflictDuplicate,
    // INTERNAL_*
    InternalUnexpected,
    InternalAssert,
    InternalType,
    InternalKey,
    InternalIndex,
    // fallback
    Unknown,
}

impl ErrorCode {
    /// The canonical string value, e.g. `EXEC_NON_ZERO`.
    pub const fn as_str(self) -> &'static str {
        use ErrorCode::*;
        match self {
            ParseJson => "PARSE_JSON",
            ParseYaml => "PARSE_YAML",
            ParseXml => "PARSE_XML",
            ParseCsv => "PARSE_CSV",
            ParseRegex => "PARSE_REGEX",
            ParseEncoding => "PARSE_ENCODING",
            IoNotFound => "IO_NOT_FOUND",
            IoPermission => "IO_PERMISSION",
            IoDiskFull => "IO_DISK_FULL",
            IoReadFail => "IO_READ_FAIL",
            IoWriteFail => "IO_WRITE_FAIL",
            IoLockFail => "IO_LOCK_FAIL",
            ExecNonZero => "EXEC_NON_ZERO",
            ExecTimeout => "EXEC_TIMEOUT",
            ExecNotFound => "EXEC_NOT_FOUND",
            ExecKilled => "EXEC_KILLED",
            ExecCrash => "EXEC_CRASH",
            NetTimeout => "NET_TIMEOUT",
            NetDnsFail => "NET_DNS_FAIL",
            NetConnRefused => "NET_CONN_REFUSED",
            NetSslError => "NET_SSL_ERROR",
            NetHttpError => "NET_HTTP_ERROR",
            AuthLoginFail => "AUTH_LOGIN_FAIL",
            AuthTokenExpired => "AUTH_TOKEN_EXPIRED",
            AuthForbidden => "AUTH_FORBIDDEN",
            AuthUnauthorized => "AUTH_UNAUTHORIZED",
            ConfigMissing => "CONFIG_MISSING",
            ConfigInvalid => "CONFIG_INVALID",
            ConfigRange => "CONFIG_RANGE",
            ResMemory => "RES_MEMORY",
            ResDisk => "RES_DISK",
            ResCpu => "RES_CPU",
            ResFd => "RES_FD",
            TimeoutApi => "TIMEOUT_API",
            TimeoutDb => "TIMEOUT_DB",
            TimeoutLock => "TIMEOUT_LOCK",
            ConflictVersion => "CONFLICT_VERSION",
            ConflictLock => "CONFLICT_LOCK",
            ConflictDuplicate => "CONFLICT_DUPLICATE",
            InternalUnexpected => "INTERNAL_UNEXPECTED",
            InternalAssert => "INTERNAL_ASSERT",
            InternalType => "INTERNAL_TYPE",
            InternalKey => "INTERNAL_KEY",
            InternalIndex => "INTERNAL_INDEX",
            Unknown => "UNKNOWN",
        }
    }
}

impl std::fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_codes() {
        assert_eq!(ErrorCode::ExecNonZero.to_string(), "EXEC_NON_ZERO");
        assert_eq!(ErrorCode::IoNotFound.as_str(), "IO_NOT_FOUND");
        assert_eq!(ErrorCode::Unknown.as_str(), "UNKNOWN");
    }
}
