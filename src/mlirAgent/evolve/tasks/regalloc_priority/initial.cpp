//===- EvolvedRegAllocPriority.cpp - Evolved regalloc priority ----*- C++ -*-===//
//
// Evolved by OpenEvolve / ShinkaEvolve.
// Reference: Magellan (ICML 2025) — evolved register allocation priority.
//
// This file is automatically patched by the evaluator during evolution.
// The EVOLVE-BLOCK markers delimit the region that the LLM modifies.
//
// Convention: return higher values for higher priority (allocated first).
// The register allocator processes live ranges in descending priority order.
//
// Available RegAllocPriorityFeatures fields:
//   Size              - spill weight × number of instructions (getSize())
//   Stage             - allocation stage: 0=New, 1=Assign, 2=Split, 3=Split2,
//                       4=Spill, 5=Done
//   IsLocal           - true if live range is within one basic block
//   ForceGlobal       - true if register class has GlobalPriority or range is
//                       very large relative to available registers
//   AllocationPriority - register class priority (5 bits, 0-31), e.g. GPR
//                       classes may have higher priority than FP classes
//   HasPreference     - true if VRM has a known register hint (e.g. from copy)
//   NumAllocatable    - number of allocatable physical registers in the class
//   BeginDist         - instruction distance from range start to function end
//                       (meaningful for local ranges)
//   EndDist           - instruction distance from function start to range end
//                       (meaningful for local ranges)
//   NumInstrs         - approximate number of instructions in the range
//   IsCSR             - true if preferred register is callee-saved
//
//===----------------------------------------------------------------------===//

#include "llvm/CodeGen/EvolvedRegAllocPriority.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/MathExtras.h"

using namespace llvm;

// Tunable parameters exposed as cl::opt flags for Optuna inner-loop tuning
// [hyperparam]: ae-regalloc-size-weight, int, 1, 100
static cl::opt<int> SizeWeight("ae-regalloc-size-weight", cl::init(1), cl::Hidden,
    cl::desc("Weight for live range size in priority (default: 1x)"));

// [hyperparam]: ae-regalloc-hint-bonus, int, 0, 1000
static cl::opt<int> HintBonus("ae-regalloc-hint-bonus", cl::init(0), cl::Hidden,
    cl::desc("Bonus priority for ranges with register hints"));

// EVOLVE-BLOCK-START regalloc_priority
unsigned llvm::computeEvolvedRegAllocPriority(const RegAllocPriorityFeatures &F) {
    // Default LLVM priority logic (bit-packed encoding)
    // This is a faithful reproduction of DefaultPriorityAdvisor::getPriority()

    unsigned Prio;

    if (F.Stage == 2 /* RS_Split */) {
        // Unsplit ranges that couldn't be allocated: deferred until everything
        // else has been allocated
        Prio = F.Size * SizeWeight;
    } else {
        if (F.IsLocal && F.Stage == 1 /* RS_Assign */ && !F.ForceGlobal) {
            // Local ranges: allocate in linear instruction order
            Prio = F.BeginDist;
        } else {
            // Global and split ranges: long→short order
            Prio = F.Size * SizeWeight;
        }

        // Clamp to 24 bits
        Prio = std::min(Prio, (unsigned)maxUIntN(24));

        // Encode allocation priority and global bit
        unsigned GlobalBit = (F.IsLocal && F.Stage == 1 && !F.ForceGlobal) ? 0 : 1;
        Prio |= GlobalBit << 29 | F.AllocationPriority << 24;

        // Bit 31: prioritize RS_Assign/local above RS_Split
        Prio |= (1u << 31);

        // Bit 30: boost ranges with register hints
        if (F.HasPreference)
            Prio |= (1u << 30);
    }

    // Optional hint bonus (for Optuna tuning)
    if (F.HasPreference && HintBonus > 0)
        Prio += HintBonus;

    return Prio;
}
// EVOLVE-BLOCK-END regalloc_priority
