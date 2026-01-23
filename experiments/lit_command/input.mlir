// RUN: iree-opt --pass-pipeline="builtin.module(func.func(canonicalize))" %s | FileCheck %s

// --- THE CODE (State) ---
func.func @test_math() -> i32 {
  %c2 = arith.constant 2 : i32
  %c3 = arith.constant 3 : i32
  // The agent (or pass) needs to fold this:
  %sum = arith.addi %c2, %c3 : i32
  return %sum : i32
}

// --- THE GOAL (Reward Function) ---
// We want to verify that the addition was folded into a single constant 5.

// CHECK-LABEL: func.func @test_math
// CHECK-DAG:     %[[RES:.+]] = arith.constant 5 : i32
// CHECK:         return %[[RES]]