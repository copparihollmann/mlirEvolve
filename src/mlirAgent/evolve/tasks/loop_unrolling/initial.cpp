//===- EvolvedLoopUnroll.cpp - Evolved loop unroll heuristic ------*- C++ -*-===//
//
// Evolved by OpenEvolve / ShinkaEvolve.
//
// This file is automatically patched by the evaluator during evolution.
// The EVOLVE-BLOCK markers delimit the region that the LLM modifies.
//
// Convention: return an unroll factor >= 1.
//   1 = don't unroll, >1 = unroll by that factor.
//
// Available LoopUnrollFeatures fields:
//   LoopSize            - instruction count of the rolled loop body
//   TripCount           - exact trip count (0 if unknown)
//   MaxTripCount        - upper bound on trip count (0 if unknown)
//   TripMultiple        - trip count is guaranteed a multiple of this
//   Depth               - loop nesting depth (1 = outermost)
//   NumBlocks           - number of basic blocks in the loop
//   BEInsns             - backend edge instructions (~2)
//   Threshold           - target unroll cost threshold
//   PartialThreshold    - partial unroll cost threshold
//   MaxCount            - maximum allowed unroll factor
//   NumInlineCandidates - number of inline candidates in loop body
//   IsInnermost         - true if this is an innermost loop
//   HasExactTripCount   - true if TripCount > 0
//   MaxOrZero           - true if loop runs max trip count or zero times
//   AllowPartial        - true if partial unrolling is allowed
//   AllowRuntime        - true if runtime unrolling is allowed
//
//===----------------------------------------------------------------------===//

#include "llvm/Transforms/Scalar/EvolvedLoopUnroll.h"
#include "llvm/Support/CommandLine.h"

using namespace llvm;

// Tunable threshold scale exposed as cl::opt for Optuna inner-loop tuning
// [hyperparam]: ae-unroll-threshold-scale, int, 50, 200
static cl::opt<int> ThresholdScale("ae-unroll-threshold-scale", cl::init(100), cl::Hidden,
    cl::desc("Scale factor for unroll threshold (percent, 100 = default)"));

// EVOLVE-BLOCK-START loop_unroll_heuristic
unsigned llvm::computeEvolvedLoopUnrollCount(const LoopUnrollFeatures &F) {
    unsigned EffThreshold = F.Threshold * ThresholdScale / 100;

    // 1. Full unroll: if exact trip count known and unrolled size fits threshold
    if (F.HasExactTripCount && F.TripCount > 1) {
        unsigned UnrolledSize = F.LoopSize * F.TripCount;
        if (UnrolledSize <= EffThreshold) {
            return F.TripCount;
        }
    }

    // 2. Partial unroll: if loop is small enough and we have trip info
    if (F.AllowPartial && F.LoopSize < F.PartialThreshold) {
        unsigned MaxUnroll = (F.PartialThreshold - F.BEInsns) /
                             (F.LoopSize - F.BEInsns);
        if (MaxUnroll < 2)
            return 1;

        // Clamp to power of 2 for clean remainder handling
        unsigned Count = 1;
        while (Count * 2 <= MaxUnroll)
            Count *= 2;

        // If we know the trip count, align to it
        if (F.HasExactTripCount) {
            while (Count > 1 && F.TripCount % Count != 0)
                Count >>= 1;
        }

        if (Count > 1)
            return Count;
    }

    // 3. Don't unroll
    return 1;
}
// EVOLVE-BLOCK-END loop_unroll_heuristic
