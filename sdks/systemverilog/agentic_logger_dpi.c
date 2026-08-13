// agentic_logger_dpi.c — DPI-C bridge for platform-dependent bits.
//
// SystemVerilog has no portable wall-clock, UUID, or getpid. Rather than rely
// on $system (which Verilator/many flows lack), we expose three tiny DPI
// functions. The rest of the SDK is portable SV.
//
// Compile with your simulator's C compiler (verilator --cc, vcs -C, xrun, etc.).
// @contract: sdks/INTERCHANGE.md

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <svdpi.h>

// ISO 8601 UTC, ms precision, +00:00 — identical to Python
// datetime.now(timezone.utc).isoformat(timespec="milliseconds").
// Returns a pointer to a static buffer (safe for sequential logging).
const char* agentic_get_ts(void) {
    static char buf[40];
    struct timespec ts;
#ifdef CLOCK_REALTIME
    clock_gettime(CLOCK_REALTIME, &ts);
#else
    ts.tv_sec = time(NULL);
    ts.tv_nsec = 0;
#endif
    struct tm tm;
#ifdef _WIN32
    gmtime_s(&tm, &ts.tv_sec);
#else
    gmtime_r(&ts.tv_sec, &tm);
#endif
    long ms = ts.tv_nsec / 1000000L;
    snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03d+00:00",
             tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec, (int)ms);
    return buf;
}

// 8 hex chars (uuid4 hex[:8] equivalent).
const char* agentic_gen_rid(void) {
    static char buf[9];
    static int seeded = 0;
    if (!seeded) { srand((unsigned)(time(NULL) ^ getpid())); seeded = 1; }
    unsigned r = ((unsigned)rand() << 16) ^ (unsigned)rand() ^ (unsigned)getpid();
    snprintf(buf, sizeof(buf), "%08x", r);
    return buf;
}

// Host process id (the simulator's PID) as a decimal string.
const char* agentic_get_pid(void) {
    static char buf[16];
    snprintf(buf, sizeof(buf), "%d", (int)getpid());
    return buf;
}
