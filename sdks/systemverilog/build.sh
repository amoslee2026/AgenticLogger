#!/usr/bin/env bash
# build.sh — compile & run the SystemVerilog testbench with Verilator + DPI.
#
# SystemVerilog has no portable wall-clock/uuid, so agentic_logger_pkg.sv uses
# three DPI-C functions (agentic_logger_dpi.c). Verilator 5.x compiles the .c
# but does NOT auto-link it into the final binary (VK_USER_OBJS stays empty),
# so we let --binary build all objects (its link step fails harmlessly) and then
# finish the link ourselves.
#
# VCS / Xcelium / Questa users: compile agentic_logger_dpi.c with your sim's C
# compiler and add agentic_logger_pkg.sv to the compile list — those flows link
# DPI sources natively (no manual link needed).
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:-/tmp/xlang_sv}"
VROOT="$(verilator --getenv VERILATOR_ROOT 2>/dev/null || echo /usr/share/verilator)"
VINC="-I$VROOT/include -I$VROOT/include/vltstd"

rm -rf obj_dir agentic_logger_dpi.o
mkdir -p "$OUT"

gcc -c $VINC -O2 agentic_logger_dpi.c -o agentic_logger_dpi.o

# --binary compiles every object; its link fails only because the DPI object
# isn't on the link line — that's expected, ignore the non-zero exit.
verilator --binary -Wno-fatal -Wno-WIDTH -Wno-UNUSED -Wno-UNOPTFLAT -Wno-TIMESCALEMOD \
  --top-module tb_agentic agentic_logger_pkg.sv tb_agentic.sv agentic_logger_dpi.c \
  >/dev/null 2>&1 || true

# Deterministic final link: verilated archive + DPI + runtime.
if [ ! -x obj_dir/Vtb_agentic ]; then
  g++ -o obj_dir/Vtb_agentic \
    obj_dir/Vtb_agentic__ALL.a "$(pwd)/agentic_logger_dpi.o" \
    obj_dir/verilated.o obj_dir/verilated_threads.o \
    -lpthread -latomic
fi

./obj_dir/Vtb_agentic +OUT="$OUT"
echo "SV testbench wrote to: $OUT"
