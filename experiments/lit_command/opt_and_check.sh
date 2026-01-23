#!/bin/bash

# --- Configuration ---
# distinct paths based on your environment
IREE_OPT="/scratch2/agustin/merlin/build-BAR-iree-host-debug-OPU/tools/iree-opt"
FILECHECK="/scratch2/agustin/merlin/build-BAR-iree-host-debug-OPU/install/bin/FileCheck"
TEST_FILE="input.mlir"

# Check if input file exists
if [ ! -f "$TEST_FILE" ]; then
    echo "Error: $TEST_FILE not found in the current directory."
    exit 1
fi

echo "=========================================================="
echo "🤖 RL AGENT SIMULATION"
echo "Target File: $TEST_FILE"
echo "=========================================================="
echo ""

# ---------------------------------------------------------
# STEP 1: The "Bad" Action (CSE)
# ---------------------------------------------------------
echo ">> [Step 1] Agent chooses action: 'cse' (Common Subexpression Elimination)"
echo "   EXPECTATION: Failure (CSE does not fold constants like 2 + 3)"

# We run the command and capture the output
OUTPUT=$($IREE_OPT --pass-pipeline="builtin.module(func.func(cse))" "$TEST_FILE" 2>&1 | $FILECHECK "$TEST_FILE" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "   RESULT: ✅ FAILED AS EXPECTED (Negative Reward)"
    echo "   (The tool correctly reported that 'constant 5' was missing)"
    echo ""
    echo "   --- ERROR LOG START ---"
    echo "$OUTPUT"
    echo "   --- ERROR LOG END ---"
else
    echo "   RESULT: ❌ UNEXPECTED SUCCESS"
    echo "   (Something is wrong with the test setup; CSE should not have passed.)"
fi

echo ""
echo "----------------------------------------------------------"
echo ""

# ---------------------------------------------------------
# STEP 2: The "Good" Action (Canonicalize)
# ---------------------------------------------------------
echo ">> [Step 2] Agent learns and chooses action: 'canonicalize' (Constant Folding)"
echo "   EXPECTATION: Success (Canonicalize turns 2 + 3 into 5)"

OUTPUT=$($IREE_OPT --pass-pipeline="builtin.module(func.func(canonicalize))" "$TEST_FILE" 2>&1 | $FILECHECK "$TEST_FILE" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "   RESULT: ✅ SUCCESS (Positive Reward)"
    echo "   (The output matched the CHECK lines perfectly)"
else
    echo "   RESULT: ❌ FAILED"
    echo "   (Canonicalize should have worked. Here is the error:)"
    echo "$OUTPUT"
fi

echo ""
echo "=========================================================="
echo "Simulation Complete."