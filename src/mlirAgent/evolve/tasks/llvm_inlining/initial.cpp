// LLVM Inline Cost Heuristic — Evolved by OpenEvolve / ShinkaEvolve
//
// This file implements a custom InlineAdvisor that uses LLVM's predefined
// inline features (InlineCost) to decide whether to inline a call site.
// The region between EVOLVE-BLOCK-START and EVOLVE-BLOCK-END is what the
// LLM agent modifies during evolution.
//
// Reference: Magellan (ICML 2025) — evolved inlining heuristics via LLM.

#include "llvm/Analysis/InlineCost.h"
#include "llvm/Analysis/TargetTransformInfo.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/Analysis/BlockFrequencyInfo.h"
#include "llvm/Analysis/ProfileSummaryInfo.h"
#include "llvm/Support/CommandLine.h"

using namespace llvm;

// Tunable thresholds exposed as cl::opt flags for Optuna inner-loop tuning
// [hyperparam]: ae-inline-base-threshold, int, 0, 500
static cl::opt<int> BaseThreshold("ae-inline-base-threshold", cl::init(225), cl::Hidden,
    cl::desc("Base cost threshold for inlining"));

// [hyperparam]: ae-inline-cold-penalty, int, 0, 200
static cl::opt<int> ColdPenalty("ae-inline-cold-penalty", cl::init(45), cl::Hidden,
    cl::desc("Penalty for cold call sites"));

// [hyperparam]: ae-inline-loop-bonus, int, 0, 300
static cl::opt<int> LoopBonus("ae-inline-loop-bonus", cl::init(50), cl::Hidden,
    cl::desc("Bonus for call sites inside loops"));

// [hyperparam]: ae-inline-vector-bonus, int, 0, 200
static cl::opt<int> VectorBonus("ae-inline-vector-bonus", cl::init(40), cl::Hidden,
    cl::desc("Bonus for functions with vector instructions"));

/// Compute a custom inlining cost/benefit score for the given call site.
///
/// Uses LLVM's 38 predefined inline features:
///   - callee_basic_block_count, callee_instruction_count
///   - callsite_height, call_argument_setup_cost
///   - nested_inlines, jump_table_penalty
///   - case_cluster_penalty, is_cold_callsite
///   - last_call_to_static_bonus, cost_estimate, etc.
///
/// Returns: positive = inline, negative = don't inline.
// EVOLVE-BLOCK-START inline_cost_heuristic
int computeInlineCost(const InlineCostFeatures &Features) {
    int cost = BaseThreshold;

    // Basic size/complexity penalty
    int calleeSize = Features[static_cast<int>(InlineCostFeatureIndex::callee_basic_block_count)] *
                     Features[static_cast<int>(InlineCostFeatureIndex::callee_instruction_count)];
    cost -= calleeSize / 10;

    // Call site depth penalty (discourages deep inlining chains)
    int height = Features[static_cast<int>(InlineCostFeatureIndex::callsite_height)];
    if (height > 5) {
        cost -= (height - 5) * 15;
    }

    // Cold call site penalty
    int isCold = Features[static_cast<int>(InlineCostFeatureIndex::is_cold_callsite)];
    if (isCold) {
        cost -= ColdPenalty;
    }

    // Loop nesting bonus (inline hot loop bodies)
    int nestedInlines = Features[static_cast<int>(InlineCostFeatureIndex::nested_inlines)];
    if (nestedInlines > 0 && !isCold) {
        cost += LoopBonus;
    }

    // Last-call-to-static bonus (dead code elimination opportunity)
    int lastCallStatic = Features[static_cast<int>(InlineCostFeatureIndex::last_call_to_static_bonus)];
    if (lastCallStatic) {
        cost += 30;
    }

    // Jump table / switch penalty
    int jumpTablePenalty = Features[static_cast<int>(InlineCostFeatureIndex::jump_table_penalty)];
    int caseClusterPenalty = Features[static_cast<int>(InlineCostFeatureIndex::case_cluster_penalty)];
    cost -= (jumpTablePenalty + caseClusterPenalty);

    // Cost estimate from LLVM's own analysis
    int llvmCostEstimate = Features[static_cast<int>(InlineCostFeatureIndex::cost_estimate)];
    cost -= llvmCostEstimate / 5;

    return cost;
}
// EVOLVE-BLOCK-END inline_cost_heuristic
