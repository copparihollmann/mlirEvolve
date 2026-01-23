#!/bin/bash

# --- 1. Configuration ---
# Update this to match the name of the .mlir file you generated in the previous step
MODEL_NAME="simple_matmul_relu_int8_sym"
# Assumes you ran: iree-import-onnx ... -o compilation_simple_matmul_relu/simple_matmul_relu.mlir
INPUT_FILE="compilation_${MODEL_NAME}/${MODEL_NAME}.mlir"

# Base Output Directory
BASE_DIR="compilation_${MODEL_NAME}/artifacts_riscv"
OUTPUT_VMFB="${BASE_DIR}/${MODEL_NAME}_riscv.vmfb"
LOG_FILE="${BASE_DIR}/compilation_log.txt"

# Create the directory structure
echo "Creating directory structure in ${BASE_DIR}..."
mkdir -p "${BASE_DIR}/hal_benchmarks"
mkdir -p "${BASE_DIR}/hal_binaries"
mkdir -p "${BASE_DIR}/hal_configurations"
mkdir -p "${BASE_DIR}/hal_intermediates"
mkdir -p "${BASE_DIR}/hal_sources"
mkdir -p "${BASE_DIR}/compilation_phases"
mkdir -p "${BASE_DIR}/ir_pass_history" 

# --- 2. The Compilation Command ---
echo "Starting IREE Compilation for ${MODEL_NAME}..."
echo "Logging stdout/stderr to: ${LOG_FILE}"

# NOTE: We use > ... 2>&1 to capture both Standard Output and Standard Error 
# because MLIR printing often goes to stderr.

iree-compile "${INPUT_FILE}" \
  -o "${OUTPUT_VMFB}" \
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
  > "${LOG_FILE}" 2>&1

# Check exit status
if [ $? -eq 0 ]; then
    echo "--------------------------------------------------------"
    echo "Compilation Complete Successfully."
    echo "Artifacts are located in: ${BASE_DIR}"
    echo "Pass history (IR dump) is in: ${BASE_DIR}/ir_pass_history"
    
    # Optional: Check if tree command exists before running
    if command -v tree &> /dev/null; then
        echo "Visualizing directory structure:"
        tree "${BASE_DIR}" -L 2 --dirsfirst
    else
        echo "('tree' command not found, skipping directory visualization)"
    fi
else
    echo "--------------------------------------------------------"
    echo "Compilation FAILED."
    echo "Check the log file for errors: ${LOG_FILE}"
    tail -n 20 "${LOG_FILE}"
fi