//===- EvolvedInlineCost.cpp - Evolved inline cost heuristic -----*- C++ -*-===//
//===----------------------------------------------------------------------===//

#include "llvm/Analysis/EvolvedInlineCost.h"
#include "llvm/Analysis/InlineModelFeatureMaps.h"
#include "llvm/Support/CommandLine.h"

using namespace llvm;

// Strategy 10: Threshold 60, minimal inlining, only tiny callees

// [hyperparam]: ae-inline-base-threshold, int, 50, 1000
static cl::opt<int> BaseThreshold("ae-inline-base-threshold", cl::init(60), cl::Hidden,
    cl::desc("Base cost threshold for inlining"));

// [hyperparam]: ae-inline-sroa-weight, int, 0, 200
static cl::opt<int> SROAWeight("ae-inline-sroa-weight", cl::init(100), cl::Hidden,
    cl::desc("Weight for SROA savings (percent)"));

// [hyperparam]: ae-inline-simplify-weight, int, 0, 200
static cl::opt<int> SimplifyWeight("ae-inline-simplify-weight", cl::init(0), cl::Hidden,
    cl::desc("Weight for simplified instruction bonus (percent)"));

// EVOLVE-BLOCK-START inline_cost_heuristic
int llvm::computeEvolvedInlineCost(const InlineCostFeatures &Features) {
    int cost = 0;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::callsite_cost)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::call_penalty)] * 3 / 2;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::call_argument_setup)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::load_relative_intrinsic)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::lowered_call_arg_setup)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::indirect_call_penalty)] * 3;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::jump_table_penalty)] * 3;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::case_cluster_penalty)] * 3;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::switch_default_dest_penalty)] * 3;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::switch_penalty)] * 3;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::unsimplified_common_instructions)];
    cost += Features[static_cast<int>(InlineCostFeatureIndex::num_loops)] * 4;
    cost += Features[static_cast<int>(InlineCostFeatureIndex::cold_cc_penalty)] * 100;
    if (Features[static_cast<int>(InlineCostFeatureIndex::last_call_to_static_bonus)]) {
        cost -= 30;
    }
    cost += Features[static_cast<int>(InlineCostFeatureIndex::load_elimination)];
    if (Features[static_cast<int>(InlineCostFeatureIndex::is_multiple_blocks)]) {
        cost += 40;
    }
    cost += Features[static_cast<int>(InlineCostFeatureIndex::nested_inline_cost_estimate)] / 2;
    return cost - BaseThreshold;
}
// EVOLVE-BLOCK-END inline_cost_heuristic
