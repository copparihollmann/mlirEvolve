#!/bin/bash

# --- 1. Configuration ---
MODEL_NAME="quant_fusion_test"
INPUT_FILE="experiments/integer_requant_fusion/test.mlir"

# Standardize output structure exactly like the main script
BASE_DIR="compilation_${MODEL_NAME}/artifacts_riscv"
LOG_FILE="${BASE_DIR}/compilation_log.txt"

echo "--- Compiling Test Case: ${MODEL_NAME} ---"
echo "Creating directory structure in ${BASE_DIR}..."

mkdir -p "${BASE_DIR}/hal_benchmarks"
mkdir -p "${BASE_DIR}/hal_binaries"
mkdir -p "${BASE_DIR}/hal_configurations"
mkdir -p "${BASE_DIR}/hal_intermediates"
mkdir -p "${BASE_DIR}/hal_sources"
mkdir -p "${BASE_DIR}/compilation_phases"
mkdir -p "${BASE_DIR}/ir_pass_history" 

# --- 2. The Compilation Command ---
# We inject the pass pipeline specifically for this test:
# --pass-pipeline="builtin.module(func.func(iree-global-opt-fuse-quantized-matmul-bias))"

iree-compile "${INPUT_FILE}" \
  -o "${BASE_DIR}/${MODEL_NAME}.vmfb" \
  \
  --iree-hal-target-backends=llvm-cpu \
  --iree-llvmcpu-target-triple=riscv64-unknown-linux-gnu \
  --iree-llvmcpu-target-cpu-features="+m,+a,+f,+d,+v,+zvl512b,+zvfh,+zvbb" \
  --iree-llvmcpu-target-abi=lp64d \
  --iree-dispatch-creation-data-tiling \
  --iree-llvmcpu-enable-ukernels="all" \
  --iree-opt-level=O3 \
  -mlir-disable-threading \
  \
  --dump-compilation-phases-to="${BASE_DIR}/compilation_phases" \
  \
  --iree-hal-dump-executable-benchmarks-to="${BASE_DIR}/hal_benchmarks/benchmark" \
  --iree-hal-dump-executable-binaries-to="${BASE_DIR}/hal_binaries/binary" \
  --iree-hal-dump-executable-configurations-to="${BASE_DIR}/hal_configurations/config" \
  --iree-hal-dump-executable-intermediates-to="${BASE_DIR}/hal_intermediates/intermediate" \
  --iree-hal-dump-executable-sources-to="${BASE_DIR}/hal_sources/source" \
  \
  --mlir-print-ir-after-all \
  --mlir-print-ir-module-scope \
  --mlir-print-debuginfo \
  --mlir-print-local-scope \
  --mlir-print-op-on-diagnostic \
  --mlir-print-ir-tree-dir="${BASE_DIR}/ir_pass_history" \
  \
  --mlir-print-stacktrace-on-diagnostic \
  --mlir-print-op-generic \
  --mlir-elide-elementsattrs-if-larger=100 \
  \
  > "${LOG_FILE}" 2>&1

# Check exit status
if [ $? -eq 0 ]; then
    echo "✅ Test Compilation Successful."
    echo "Artifacts: ${BASE_DIR}"
else
    echo "❌ Test Compilation FAILED."
    echo "Check log: ${LOG_FILE}"
    # Print the last few lines of the log which usually contains the crash trace
    tail -n 20 "${LOG_FILE}"
fi