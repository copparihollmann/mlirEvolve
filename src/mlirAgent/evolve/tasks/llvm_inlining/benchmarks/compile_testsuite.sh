#!/bin/bash
# Compile LLVM test-suite benchmarks to .bc (bitcode) files
# Using: clang-18 -O1 -Xclang -disable-llvm-optzns -emit-llvm
# This produces unoptimized bitcode suitable for our custom opt pass
set -e

CLANG="clang-18"
CLANGXX="clang++-18"
LLVM_LINK="llvm-link-18"
TESTSUITE="/scratch/ashvin/llvm-test-suite"
OUTDIR="/scratch/ashvin/merlin/mlirEvolve/src/mlirAgent/evolve/tasks/llvm_inlining/benchmarks/testsuite"
TMPDIR="/tmp/testsuite_build_$$"

# Flags: -O1 enables optimizations but -disable-llvm-optzns prevents LLVM
# opts from running (only Clang frontend opts). This avoids noinline attrs.
COMMON_FLAGS="-O1 -Xclang -disable-llvm-optzns -emit-llvm"
C_FLAGS="$COMMON_FLAGS -std=c17"
CXX_FLAGS="$COMMON_FLAGS"

mkdir -p "$OUTDIR" "$TMPDIR"

compile_ok=0
compile_fail=0

echo "=== Compiling LLVM test-suite benchmarks to .bc ==="
echo ""

#--------------------------------------------------------------------
# 1. SPASS - Theorem Prover (C)
#--------------------------------------------------------------------
echo "--- [1/7] SPASS ---"
SPASS_DIR="$TESTSUITE/MultiSource/Applications/SPASS"
SPASS_TMP="$TMPDIR/spass"
mkdir -p "$SPASS_TMP"

SPASS_SRCS=$(ls "$SPASS_DIR"/*.c 2>/dev/null)
SPASS_OK=1
for src in $SPASS_SRCS; do
    base=$(basename "$src" .c)
    $CLANG $C_FLAGS -DCLOCK_NO_TIMING -fno-strict-aliasing \
        -I"$SPASS_DIR" \
        -c "$src" -o "$SPASS_TMP/${base}.bc" 2>/dev/null || {
        echo "  WARN: Failed to compile $base.c"
        SPASS_OK=0
    }
done
if [ "$SPASS_OK" = "1" ]; then
    $LLVM_LINK "$SPASS_TMP"/*.bc -o "$OUTDIR/spass.bc" 2>/dev/null && {
        echo "  OK: spass.bc ($(stat -c%s "$OUTDIR/spass.bc") bytes)"
        compile_ok=$((compile_ok + 1))
    } || {
        echo "  FAIL: llvm-link failed for SPASS"
        compile_fail=$((compile_fail + 1))
    }
else
    # Try linking what we have
    bc_count=$(ls "$SPASS_TMP"/*.bc 2>/dev/null | wc -l)
    if [ "$bc_count" -gt 0 ]; then
        $LLVM_LINK "$SPASS_TMP"/*.bc -o "$OUTDIR/spass.bc" 2>/dev/null && {
            echo "  OK (partial): spass.bc ($(stat -c%s "$OUTDIR/spass.bc") bytes)"
            compile_ok=$((compile_ok + 1))
        } || {
            echo "  FAIL: llvm-link failed for SPASS"
            compile_fail=$((compile_fail + 1))
        }
    else
        echo "  FAIL: No .bc files produced for SPASS"
        compile_fail=$((compile_fail + 1))
    fi
fi

#--------------------------------------------------------------------
# 2. tramp3d-v4 - C++ Template Metaprogramming Benchmark
#--------------------------------------------------------------------
echo "--- [2/7] tramp3d-v4 ---"
TRAMP_DIR="$TESTSUITE/MultiSource/Benchmarks/tramp3d-v4"
$CLANGXX $CXX_FLAGS -std=c++14 -fno-exceptions \
    -c "$TRAMP_DIR/tramp3d-v4.cpp" -o "$OUTDIR/tramp3d.bc" 2>/dev/null && {
    echo "  OK: tramp3d.bc ($(stat -c%s "$OUTDIR/tramp3d.bc") bytes)"
    compile_ok=$((compile_ok + 1))
} || {
    echo "  FAIL: tramp3d-v4.cpp"
    compile_fail=$((compile_fail + 1))
}

#--------------------------------------------------------------------
# 3. Bullet - Physics Engine (C++)
#--------------------------------------------------------------------
echo "--- [3/7] Bullet ---"
BULLET_DIR="$TESTSUITE/MultiSource/Benchmarks/Bullet"
BULLET_TMP="$TMPDIR/bullet"
mkdir -p "$BULLET_TMP"

BULLET_SRCS=$(ls "$BULLET_DIR"/*.cpp 2>/dev/null)
BULLET_OK=1
for src in $BULLET_SRCS; do
    base=$(basename "$src" .cpp)
    $CLANGXX $CXX_FLAGS -std=c++98 -DNO_TIME \
        -I"$BULLET_DIR/include" -I"$BULLET_DIR" \
        -c "$src" -o "$BULLET_TMP/${base}.bc" 2>/dev/null || {
        echo "  WARN: Failed to compile $base.cpp"
        BULLET_OK=0
    }
done
bc_count=$(ls "$BULLET_TMP"/*.bc 2>/dev/null | wc -l)
if [ "$bc_count" -gt 0 ]; then
    $LLVM_LINK "$BULLET_TMP"/*.bc -o "$OUTDIR/bullet.bc" 2>/dev/null && {
        echo "  OK: bullet.bc ($(stat -c%s "$OUTDIR/bullet.bc") bytes)"
        compile_ok=$((compile_ok + 1))
    } || {
        echo "  FAIL: llvm-link failed for Bullet"
        compile_fail=$((compile_fail + 1))
    }
else
    echo "  FAIL: No .bc files produced for Bullet"
    compile_fail=$((compile_fail + 1))
fi

#--------------------------------------------------------------------
# 4. ClamAV - Antivirus Engine (C)
#--------------------------------------------------------------------
echo "--- [4/7] ClamAV ---"
CLAMAV_DIR="$TESTSUITE/MultiSource/Applications/ClamAV"
CLAMAV_TMP="$TMPDIR/clamav"
mkdir -p "$CLAMAV_TMP"

# ClamAV needs specific defines for Linux
CLAMAV_DEFS="-DHAVE_CONFIG_H -DDONT_LOCK_DBDIRS -DC_LINUX -DWORDS_BIGENDIAN=0 -DFPU_WORDS_BIGENDIAN=0"
CLAMAV_INCLUDES="-I$CLAMAV_DIR -I$CLAMAV_DIR/zlib"

CLAMAV_SRCS=$(ls "$CLAMAV_DIR"/*.c 2>/dev/null)
CLAMAV_FAIL_COUNT=0
for src in $CLAMAV_SRCS; do
    base=$(basename "$src" .c)
    $CLANG $C_FLAGS $CLAMAV_DEFS $CLAMAV_INCLUDES \
        -Wno-incompatible-pointer-types \
        -c "$src" -o "$CLAMAV_TMP/${base}.bc" 2>/dev/null || {
        CLAMAV_FAIL_COUNT=$((CLAMAV_FAIL_COUNT + 1))
    }
done
bc_count=$(ls "$CLAMAV_TMP"/*.bc 2>/dev/null | wc -l)
echo "  Compiled $bc_count files ($CLAMAV_FAIL_COUNT failures)"
if [ "$bc_count" -gt 0 ]; then
    $LLVM_LINK "$CLAMAV_TMP"/*.bc -o "$OUTDIR/clamav.bc" 2>/dev/null && {
        echo "  OK: clamav.bc ($(stat -c%s "$OUTDIR/clamav.bc") bytes)"
        compile_ok=$((compile_ok + 1))
    } || {
        echo "  FAIL: llvm-link failed for ClamAV"
        compile_fail=$((compile_fail + 1))
    }
else
    echo "  FAIL: No .bc files produced for ClamAV"
    compile_fail=$((compile_fail + 1))
fi

#--------------------------------------------------------------------
# 5. hexxagon - C++ Game AI
#--------------------------------------------------------------------
echo "--- [5/7] hexxagon ---"
HEXX_DIR="$TESTSUITE/MultiSource/Applications/hexxagon"
HEXX_TMP="$TMPDIR/hexxagon"
mkdir -p "$HEXX_TMP"

HEXX_SRCS=$(ls "$HEXX_DIR"/*.cpp 2>/dev/null)
for src in $HEXX_SRCS; do
    base=$(basename "$src" .cpp)
    $CLANGXX $CXX_FLAGS -std=c++14 \
        -I"$HEXX_DIR" \
        -c "$src" -o "$HEXX_TMP/${base}.bc" 2>/dev/null || {
        echo "  WARN: Failed to compile $base.cpp"
    }
done
bc_count=$(ls "$HEXX_TMP"/*.bc 2>/dev/null | wc -l)
if [ "$bc_count" -gt 0 ]; then
    $LLVM_LINK "$HEXX_TMP"/*.bc -o "$OUTDIR/hexxagon.bc" 2>/dev/null && {
        echo "  OK: hexxagon.bc ($(stat -c%s "$OUTDIR/hexxagon.bc") bytes)"
        compile_ok=$((compile_ok + 1))
    } || {
        echo "  FAIL: llvm-link failed for hexxagon"
        compile_fail=$((compile_fail + 1))
    }
else
    echo "  FAIL: No .bc files produced for hexxagon"
    compile_fail=$((compile_fail + 1))
fi

#--------------------------------------------------------------------
# 6. PAQ8p - Data Compression (single C++ file)
#--------------------------------------------------------------------
echo "--- [6/7] PAQ8p ---"
PAQ_DIR="$TESTSUITE/MultiSource/Benchmarks/PAQ8p"
$CLANGXX $CXX_FLAGS -DNOASM -DLLVM \
    -c "$PAQ_DIR/paq8p.cpp" -o "$OUTDIR/paq8p.bc" 2>/dev/null && {
    echo "  OK: paq8p.bc ($(stat -c%s "$OUTDIR/paq8p.bc") bytes)"
    compile_ok=$((compile_ok + 1))
} || {
    echo "  FAIL: paq8p.cpp"
    compile_fail=$((compile_fail + 1))
}

#--------------------------------------------------------------------
# 7. Fhourstones - Game Tree Search (C)
#--------------------------------------------------------------------
echo "--- [7/7] Fhourstones ---"
FHOUR_DIR="$TESTSUITE/MultiSource/Benchmarks/Fhourstones"
FHOUR_TMP="$TMPDIR/fhourstones"
mkdir -p "$FHOUR_TMP"

for src in "$FHOUR_DIR"/c4.c "$FHOUR_DIR"/play.c "$FHOUR_DIR"/trans.c; do
    if [ -f "$src" ]; then
        base=$(basename "$src" .c)
        $CLANG $C_FLAGS -I"$FHOUR_DIR" \
            -c "$src" -o "$FHOUR_TMP/${base}.bc" 2>/dev/null || {
            echo "  WARN: Failed to compile $(basename $src)"
        }
    fi
done
bc_count=$(ls "$FHOUR_TMP"/*.bc 2>/dev/null | wc -l)
if [ "$bc_count" -gt 0 ]; then
    $LLVM_LINK "$FHOUR_TMP"/*.bc -o "$OUTDIR/fhourstones.bc" 2>/dev/null && {
        echo "  OK: fhourstones.bc ($(stat -c%s "$OUTDIR/fhourstones.bc") bytes)"
        compile_ok=$((compile_ok + 1))
    } || {
        echo "  FAIL: llvm-link failed for Fhourstones"
        compile_fail=$((compile_fail + 1))
    }
else
    echo "  FAIL: No .bc files produced for Fhourstones"
    compile_fail=$((compile_fail + 1))
fi

#--------------------------------------------------------------------
# Summary
#--------------------------------------------------------------------
echo ""
echo "=== Summary ==="
echo "Compiled: $compile_ok / 7"
echo "Failed:   $compile_fail / 7"
echo ""
echo "Output .bc files:"
ls -lh "$OUTDIR"/*.bc 2>/dev/null || echo "  (none)"

# Cleanup
rm -rf "$TMPDIR"
