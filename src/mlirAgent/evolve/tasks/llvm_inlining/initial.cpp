//===- EvolvedInlineCost.cpp - Evolved inline cost heuristic -----*- C++ -*-===//
//
// Evolved by OpenEvolve / ShinkaEvolve.
// Reference: Magellan (ICML 2025) — evolved inlining heuristics via LLM.
//
// This file is automatically patched by the evaluator during evolution.
// The EVOLVE-BLOCK markers delimit the region that the LLM modifies.
//
// Convention: return NEGATIVE to inline (beneficial), POSITIVE to skip (costly).
// LLVM uses: Cost < Threshold → inline.  We set Threshold=0, so inline when < 0.
//
// Available InlineCostFeatureIndex features (each is an int in the Features array):
//   HEURISTIC (accumulated cost components, summed by default LLVM inliner):
//     callsite_cost          - negative of call overhead (eliminating call saves this)
//     call_penalty           - penalty for calls within the callee
//     call_argument_setup    - cost of setting up call arguments
//     load_relative_intrinsic - cost of load-relative intrinsics
//     lowered_call_arg_setup - cost of lowered call argument setup
//     indirect_call_penalty  - penalty for indirect calls
//     jump_table_penalty     - cost of jump tables in switch statements
//     case_cluster_penalty   - cost of case clusters
//     switch_default_dest_penalty - cost of switch default destination
//     switch_penalty         - general switch statement cost
//     unsimplified_common_instructions - cost of instructions that couldn't simplify
//     num_loops              - loop penalty (LoopPenalty * num_loops)
//     cold_cc_penalty        - 1 if callee has cold calling convention, else 0
//     last_call_to_static_bonus - 1 if sole call to a local function, else 0
//     load_elimination       - accumulated load elimination opportunities
//
//   NON-HEURISTIC (informational, NOT summed by default LLVM inliner):
//     sroa_savings           - potential SROA savings (scalar replacement of aggregates)
//     sroa_losses            - SROA losses when args escape
//     is_multiple_blocks     - 1 if callee has multiple basic blocks
//     dead_blocks            - number of dead blocks in callee
//     simplified_instructions - number of instructions simplified during analysis
//     constant_args          - number of constant arguments at call site
//     constant_offset_ptr_args - number of constant-offset pointer arguments
//     nested_inlines         - number of nested inlines considered
//     nested_inline_cost_estimate - estimated cost of nested inlines
//     threshold              - LLVM's computed threshold (includes hot/cold adjustments)
//
//===----------------------------------------------------------------------===//

#include "llvm/Analysis/EvolvedInlineCost.h"
#include "llvm/Analysis/InlineModelFeatureMaps.h"
#include "llvm/Support/CommandLine.h"

using namespace llvm;

// Tunable thresholds exposed as cl::opt flags for Optuna inner-loop tuning
// [hyperparam]: ae-inline-base-threshold, int, 50, 1000
static cl::opt<int> BaseThreshold("ae-inline-base-threshold", cl::init(225), cl::Hidden,
    cl::desc("Base cost threshold for inlining (LLVM -O2 default is 225)"));

// [hyperparam]: ae-inline-sroa-weight, int, 0, 200
static cl::opt<int> SROAWeight("ae-inline-sroa-weight", cl::init(100), cl::Hidden,
    cl::desc("Weight for SROA savings (percent, 100 = full weight)"));

// [hyperparam]: ae-inline-simplify-weight, int, 0, 200
static cl::opt<int> SimplifyWeight("ae-inline-simplify-weight", cl::init(0), cl::Hidden,
    cl::desc("Weight for simplified instruction bonus (percent)"));

// EVOLVE-BLOCK-START inline_cost_heuristic
int llvm::computeEvolvedInlineCost(const InlineCostFeatures &Features) {
    // ---- Heuristic features: sum as the default LLVM inliner does ----
    int cost = 0;

    // Call overhead savings (negative value = benefit)
    cost += Features[static_cast<int>(InlineCostFeatureIndex::callsite_cost)];

    // Accumulated penalties from callee analysis
    cost += Features[static_cast<int>(InlineCostFeatureIndex::call_penalty)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::call_argument_setup)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::load_relative_intrinsic)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::lowered_call_arg_setup)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::indirect_call_penalty)];

    // Switch/jump table penalties
    cost += Features[static_cast<int>(InlineCostFeatureIndex::jump_table_penalty)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::case_cluster_penalty)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::switch_default_dest_penalty)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::switch_penalty)];

    // Unsimplified instructions and loop penalties
    cost += Features[static_cast<int>(InlineCostFeatureIndex::unsimplified_common_instructions)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::num_loops)];

    // Boolean indicators (0 or 1)
    cost += Features[static_cast<int>(InlineCostFeatureIndex::cold_cc_penalty)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::last_call_to_static_bonus)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::load_elimination)];

    // ---- Non-heuristic features: optional adjustments for evolution ----
    // SROA savings: more savings = lower cost (encourage inlining)
    int sroaSavings = Features[static_cast<int>(InlineCostFeatureIndex::sroa_savings)];
    int sroaLosses = Features[static_cast<int>(InlineCostFeatureIndex::sroa_losses)];
    cost -= (sroaSavings - sroaLosses) * SROAWeight / 100;

    // Simplified instructions bonus
    int simplified = Features[static_cast<int>(InlineCostFeatureIndex::simplified_instructions)];
    cost -= simplified * SimplifyWeight / 100;

    // ---- Compare against base threshold ----
    // Note: Features[threshold] reflects the features analyzer's internal threshold
    // (starts at 5, NOT the InlineParams default of 225). We use BaseThreshold
    // (default 225, matching LLVM's -O2 inline threshold) for proper baseline behavior.

    // Return: negative = inline, positive = don't inline
    return cost - BaseThreshold;
}
// EVOLVE-BLOCK-END inline_cost_heuristic
