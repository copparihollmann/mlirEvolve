#!/bin/bash

# --- 1. Dynamic Path Resolution ---
# This ensures BASE_DIR is always next to this script, 
# even if you call it from a different folder (e.g., ../run_test.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 2. Configuration ---
MODEL_NAME="input"
INPUT_FILE="${SCRIPT_DIR}/${MODEL_NAME}.mlir"

# Output artifacts will be created inside the directory where this script lives
BASE_DIR="${SCRIPT_DIR}/artifacts_debug"
LOG_FILE="${BASE_DIR}/compilation.log"
PASS_HISTORY_DIR="${BASE_DIR}/ir_pass_history"

# --- 3. Setup ---
echo "Cleaning previous artifacts in ${BASE_DIR}..."
rm -rf "${BASE_DIR}"
mkdir -p "${PASS_HISTORY_DIR}"

# --- 4. The Compilation Command ---
echo "Starting IREE Compilation..."
echo "Input: ${INPUT_FILE}"
echo "Logs:  ${LOG_FILE}"

iree-compile "${INPUT_FILE}" \
  -o "${BASE_DIR}/${MODEL_NAME}.vmfb" \
  \
  --iree-hal-target-backends=llvm-cpu \
  --iree-llvmcpu-target-triple=riscv64-unknown-linux-gnu \
  --iree-llvmcpu-target-cpu-features="+m,+a,+f,+d,+v" \
  --iree-llvmcpu-target-abi=lp64d \
  \
  --iree-opt-level=O3 \
  -mlir-disable-threading \
  \
  --mlir-print-ir-after-all \
  --mlir-print-local-scope \
  --mlir-print-debuginfo \
  --mlir-print-ir-tree-dir="${PASS_HISTORY_DIR}" > "${LOG_FILE}" 2>&1

# --- 5. Result Analysis ---
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Compilation Successful."
    echo "Artifacts located at: ${BASE_DIR}"
    
    # Check if history was generated
    if [ -d "${PASS_HISTORY_DIR}" ]; then
        COUNT=$(ls "${PASS_HISTORY_DIR}" | wc -l)
        echo "Generated ${COUNT} IR snapshots."
        echo "History folder: ${PASS_HISTORY_DIR}"
    fi
else
    echo "❌ Compilation FAILED."
    echo "Check the log file for details:"
    echo "${LOG_FILE}"
    echo "--- Last 10 lines of error ---"
    tail -n 10 "${LOG_FILE}"
fi