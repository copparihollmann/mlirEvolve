#!/bin/bash
# Build CTMark benchmarks from LLVM test-suite into single .bc files
# Usage: bash build_ctmark.sh
set -e

TESTSUITE=/scratch/ashvin/llvm-test-suite
OUTDIR="$(dirname "$0")/testsuite"
TMPDIR=$(mktemp -d /tmp/ctmark_build_XXXXXX)
CC=clang-18
CXX=clang++-18
LINK=llvm-link-18
CFLAGS="-O1 -Xclang -disable-llvm-optzns -emit-llvm -std=c17"
CXXFLAGS="-O1 -Xclang -disable-llvm-optzns -emit-llvm -std=c++14"

mkdir -p "$OUTDIR"

compile_c() {
    local src="$1"; shift
    local out="$1"; shift
    $CC $CFLAGS "$@" -c "$src" -o "$out" 2>&1 || echo "WARN: failed $src"
}

compile_cxx() {
    local src="$1"; shift
    local out="$1"; shift
    $CXX $CXXFLAGS "$@" -c "$src" -o "$out" 2>&1 || echo "WARN: failed $src"
}

link_bc() {
    local outfile="$1"; shift
    local bcs=()
    for f in "$@"; do
        [ -f "$f" ] && bcs+=("$f")
    done
    if [ ${#bcs[@]} -gt 0 ]; then
        $LINK "${bcs[@]}" -o "$outfile"
        echo "  -> $(basename "$outfile") ($(du -h "$outfile" | cut -f1))"
    else
        echo "  ERROR: no .bc files to link for $outfile"
    fi
}

# --- SPASS ---
echo "Building SPASS..."
BD="$TMPDIR/spass"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/SPASS"
for f in "$SRC"/*.c; do
    name=$(basename "$f" .c)
    compile_c "$f" "$BD/${name}.bc" -DCLOCK_NO_TIMING -fno-strict-aliasing -I"$SRC"
done
link_bc "$OUTDIR/spass.bc" "$BD"/*.bc

# --- sqlite3 ---
echo "Building sqlite3..."
BD="$TMPDIR/sqlite3"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/sqlite3"
for f in sqlite3.c shell.c; do
    name=$(basename "$f" .c)
    compile_c "$SRC/$f" "$BD/${name}.bc" \
        -DSTDC_HEADERS=1 -DHAVE_SYS_TYPES_H=1 -DHAVE_SYS_STAT_H=1 \
        -DHAVE_STDLIB_H=1 -DHAVE_STRING_H=1 -DHAVE_MEMORY_H=1 \
        -DHAVE_STRINGS_H=1 -DHAVE_INTTYPES_H=1 -DHAVE_STDINT_H=1 \
        -DHAVE_UNISTD_H=1 -DSQLITE_OMIT_LOAD_EXTENSION=1 \
        -DSQLITE_THREADSAFE=0 -I"$SRC"
done
link_bc "$OUTDIR/sqlite3.bc" "$BD"/*.bc

# --- consumer-typeset ---
echo "Building consumer-typeset..."
BD="$TMPDIR/typeset"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/consumer-typeset"
for f in "$SRC"/*.c; do
    name=$(basename "$f" .c)
    compile_c "$f" "$BD/${name}.bc" \
        -DOS_UNIX=1 -DOS_DOS=0 -DOS_MAC=0 -DDB_FIX=0 -DUSE_STAT=1 \
        -DSAFE_DFT=0 -DCOLLATE=1 -DLIB_DIR=\"lout.lib\" -DFONT_DIR=\"font\" \
        -DMAPS_DIR=\"maps\" -DINCL_DIR=\"include\" -DDATA_DIR=\"data\" \
        -DHYPH_DIR=\"hyph\" -DLOCALE_DIR=\"locale\" -DCHAR_IN=1 -DCHAR_OUT=0 \
        -DLOCALE_ON=1 -DASSERT_ON=1 -DDEBUG_ON=0 -DPDF_COMPRESSION=0 \
        -D_FORTIFY_SOURCE=0
done
link_bc "$OUTDIR/consumer-typeset.bc" "$BD"/*.bc

# --- lencod ---
echo "Building lencod..."
BD="$TMPDIR/lencod"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/lencod"
for f in "$SRC"/*.c; do
    name=$(basename "$f" .c)
    compile_c "$f" "$BD/${name}.bc" -fcommon -D__USE_LARGEFILE64 -D_FILE_OFFSET_BITS=64 -I"$SRC"
done
link_bc "$OUTDIR/lencod.bc" "$BD"/*.bc

# --- mafft (pairlocalalign) ---
echo "Building mafft..."
BD="$TMPDIR/mafft"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/mafft"
MAFFT_FILES="Calignm1.c constants.c defs.c Falign.c fft.c fftFunctions.c
Galign11.c genalign11.c genGalign11.c Halignmm.c io.c Lalign11.c Lalignmm.c
mltaln9.c MSalign11.c MSalignmm.c mtxutl.c pairlocalalign.c partQalignmm.c
partSalignmm.c Qalignmm.c Ralignmm.c rna.c SAalignmm.c Salignmm.c
suboptalign11.c tddis.c"
for f in $MAFFT_FILES; do
    name=$(basename "$f" .c)
    compile_c "$SRC/$f" "$BD/${name}.bc" -DLLVM -I"$SRC"
done
link_bc "$OUTDIR/mafft.bc" "$BD"/*.bc

# --- tramp3d-v4 ---
echo "Building tramp3d-v4..."
BD="$TMPDIR/tramp3d"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/tramp3d-v4"
for f in "$SRC"/*.cpp; do
    name=$(basename "$f" .cpp)
    compile_cxx "$f" "$BD/${name}.bc" -fno-exceptions -I"$SRC"
done
link_bc "$OUTDIR/tramp3d-v4.bc" "$BD"/*.bc

# --- kimwitu++ (kc) ---
echo "Building kimwitu++..."
BD="$TMPDIR/kc"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/kimwitu++"
for f in "$SRC"/*.cc; do
    name=$(basename "$f" .cc)
    compile_cxx "$f" "$BD/${name}.bc" -I"$SRC" -DYYDEBUG=1
done
link_bc "$OUTDIR/kimwitu.bc" "$BD"/*.bc

# --- Bullet ---
echo "Building Bullet..."
BD="$TMPDIR/bullet"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/Bullet"
# Find all .cpp files recursively
find "$SRC" -name '*.cpp' | while read f; do
    name=$(echo "$f" | sed "s|$SRC/||g; s|/|_|g; s|\.cpp$||")
    compile_cxx "$f" "$BD/${name}.bc" -I"$SRC/include" -DNO_TIME
done
link_bc "$OUTDIR/bullet.bc" "$BD"/*.bc

# --- ClamAV ---
echo "Building ClamAV..."
BD="$TMPDIR/clamav"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/ClamAV"
for f in "$SRC"/*.c; do
    name=$(basename "$f" .c)
    compile_c "$f" "$BD/${name}.bc" \
        -DHAVE_CONFIG_H -I"$SRC" -I"$SRC/zlib" -DDONT_LOCK_DBDIRS \
        -DC_LINUX -DWORDS_BIGENDIAN=0 -DFPU_WORDS_BIGENDIAN=0 \
        -Wno-error=incompatible-pointer-types
done
link_bc "$OUTDIR/clamav.bc" "$BD"/*.bc

# --- 7zip ---
echo "Building 7zip..."
BD="$TMPDIR/7zip"
mkdir -p "$BD"
SRC="$TESTSUITE/CTMark/7zip"
ZIP_CFLAGS="-DBREAK_HANDLER -DUNICODE -D_UNICODE -I$SRC/C -I$SRC/CPP/myWindows -I$SRC/CPP/include_windows -I$SRC/CPP -I$SRC -D_FILE_OFFSET_BITS=64 -D_LARGEFILE_SOURCE -DNDEBUG -D_REENTRANT -DENV_UNIX -D_7ZIP_LARGE_PAGES -pthread"
# C files
for f in "$SRC"/C/*.c; do
    name=$(basename "$f" .c)
    compile_c "$f" "$BD/C_${name}.bc" $ZIP_CFLAGS
done
# CPP files - find all recursively
find "$SRC/CPP" -name '*.cpp' | while read f; do
    name=$(echo "$f" | sed "s|$SRC/CPP/||g; s|/|_|g; s|\.cpp$||")
    compile_cxx "$f" "$BD/CPP_${name}.bc" $ZIP_CFLAGS -Wno-error=narrowing
done
link_bc "$OUTDIR/7zip.bc" "$BD"/*.bc

# Summary
echo ""
echo "=== CTMark Benchmarks Built ==="
ls -lh "$OUTDIR"/*.bc 2>/dev/null | awk '{print $5, $NF}'

rm -rf "$TMPDIR"
