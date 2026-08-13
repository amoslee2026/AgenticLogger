//! Dependency-free ISO 8601 UTC timestamps.
//!
//! Produces `2026-08-13T05:49:19.717+00:00` (ms precision, +00:00 offset) —
//! identical to Python's `datetime.now(timezone.utc).isoformat(timespec="milliseconds")`,
//! so Python `since`/`until` string comparisons work across SDKs.
//!
//! Date math uses Howard Hinnant's civil-from-days algorithm (correct for all
//! proleptic-Gregorian dates, no external chrono dependency).

use std::time::{SystemTime, UNIX_EPOCH};

/// `YYYY-MM-DDTHH:MM:SS.mmm+00:00`
pub fn now_iso() -> String {
    let dur = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let total_ms = dur.as_millis();
    iso_from_unix_millis(total_ms as i64)
}

/// `YYYYMMDD_HHMMSSffffff` (microseconds) for log filenames.
pub fn filename_stamp() -> String {
    let dur = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let micros = dur.as_micros() as i64;
    let total_secs = micros / 1_000_000;
    let frac_micros = micros % 1_000_000; // 0..1_000_000
    let (y, mo, d, h, mi, s) = civil(total_secs);
    format!(
        "{:04}{:02}{:02}_{:02}{:02}{:02}{:06}",
        y, mo, d, h, mi, s, frac_micros
    )
}

fn iso_from_unix_millis(ms: i64) -> String {
    let total_secs = ms / 1000;
    let millis = ms % 1000;
    let (y, mo, d, h, mi, s) = civil(total_secs);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}+00:00",
        y, mo, d, h, mi, s, millis
    )
}

/// Convert Unix seconds (UTC) → (year, month, day, hour, minute, second).
fn civil(total_secs: i64) -> (i64, i64, i64, i64, i64, i64) {
    let days = total_secs.div_euclid(86400);
    let sod = total_secs.rem_euclid(86400); // 0..86400
    let h = sod / 3600;
    let mi = (sod % 3600) / 60;
    let s = sod % 60;

    // Hinnant civil_from_days: days since 1970-01-01 → (y,m,d).
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if m <= 2 { y + 1 } else { y };
    (year, m, d, h, mi, s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_epoch() {
        // 1970-01-01T00:00:00.000+00:00
        assert_eq!(iso_from_unix_millis(0), "1970-01-01T00:00:00.000+00:00");
        // 2026-01-01T00:00:00.000Z = 1767225600 seconds
        let ms = 1_767_225_600 * 1000;
        assert_eq!(iso_from_unix_millis(ms), "2026-01-01T00:00:00.000+00:00");
        // leap-day check: 2024-02-29
        let ms2 = 1_709_164_800 * 1000;
        assert_eq!(iso_from_unix_millis(ms2), "2024-02-29T00:00:00.000+00:00");
    }

    #[test]
    fn now_is_well_formed() {
        let s = now_iso();
        assert_eq!(s.len(), 29, "got {s}");
        assert_eq!(&s[4..5], "-");
        assert!(s.ends_with("+00:00"));
    }

    #[test]
    fn filename_stamp_micros() {
        let s = filename_stamp();
        // YYYYMMDD_HHMMSSffffff => 8 + 1 + 6 + 6 = 21
        assert_eq!(s.len(), 21, "got {s}");
        assert_eq!(&s[8..9], "_");
    }
}
