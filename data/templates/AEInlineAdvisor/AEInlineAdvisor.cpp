#include "llvm/Analysis/InlineAdvisor.h"
#include "llvm/Support/CommandLine.h"

using namespace llvm;

// EVOLVE-BLOCK-START
// [hyperparam]: ae-inline-base-threshold, int, 10, 500
static cl::opt<int> BaseThreshold("ae-inline-base-threshold", cl::init(200), cl::Hidden);

// [hyperparam]: ae-inline-call-penalty, int, 0, 50
static cl::opt<int> CallPenalty("ae-inline-call-penalty", cl::init(25), cl::Hidden);

std::unique_ptr<InlineAdvice> AEInlineAdvisor::getAdviceImpl(CallBase &CB) {
    Function *Callee = CB.getCalledFunction();
    if (!Callee || Callee->isDeclaration()) return {};

    // Heuristic: Calculate cost based on instruction complexity
    int Cost = 0;
    for (const auto &BB : *Callee) {
        for (const auto &I : BB) {
            // Penalize calls inside the callee
            if (isa<CallBase>(I)) {
                Cost += CallPenalty; 
            } else {
                Cost += 1;
            }
        }
    }

    bool ShouldInline = Cost < BaseThreshold;
    return std::make_unique<InlineAdvice>(this, CB, ORE, ShouldInline);
}
// EVOLVE-BLOCK-END