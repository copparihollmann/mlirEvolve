// RUN: iree-opt %s --pass-pipeline="builtin.module(func.func(iree-global-opt-fuse-quantized-matmul-bias))" --split-input-file | FileCheck %s

// Explicit module allows us to define globals if we need to test that edge case later
module {
  
  // Test Case: Standard Quantization Chain
  // We use the exact constants from your Math description to verify numerical accuracy
  func.func @quantized_matmul_epilogue(
      %accumulator: tensor<16x128xi32>, 
      %bias: tensor<128xi32>
  ) -> tensor<16x128xi8> {
    
    // Constants (Derived from your Effective Scale M = 0.0006191469)
    %cst_scale_in = arith.constant 1.04389628E-5 : f32
    %cst_scale_out = arith.constant 0.0168602373 : f32
    %cst_zp = arith.constant 0.000000e+00 : f32
    
    // Constants for Clipping (i8 limits)
    %cst_min = arith.constant -1.280000e+02 : f32
    %cst_max = arith.constant 1.270000e+02 : f32

    %empty_f32 = tensor.empty() : tensor<16x128xf32>
    %empty_i8 = tensor.empty() : tensor<16x128xi8>

    // 1. Dequantize Accumulator (The pattern start)
    %dequant_acc = linalg.generic {
        indexing_maps = [affine_map<(d0, d1) -> (d0, d1)>, affine_map<(d0, d1) -> (d0, d1)>], 
        iterator_types = ["parallel", "parallel"]
    } ins(%accumulator : tensor<16x128xi32>) outs(%empty_f32 : tensor<16x128xf32>) {
    ^bb0(%in: i32, %out: f32):
      %0 = arith.sitofp %in : i32 to f32
      // This Mulf matches the "Input Scale * Weight Scale"
      %1 = arith.mulf %0, %cst_scale_in : f32
      linalg.yield %1 : f32
    } -> tensor<16x128xf32>

    // 2. Requantize to Output (The pattern end)
    %result = linalg.generic {
        indexing_maps = [affine_map<(d0, d1) -> (d0, d1)>, affine_map<(d0, d1) -> (d0, d1)>], 
        iterator_types = ["parallel", "parallel"]
    } ins(%dequant_acc : tensor<16x128xf32>) outs(%empty_i8 : tensor<16x128xi8>) {
    ^bb0(%in: f32, %out: i8):
      // This Divf matches "Output Scale"
      %div = arith.divf %in, %cst_scale_out : f32
      %round = math.roundeven %div : f32
      %add = arith.addf %round, %cst_zp : f32
      %clamp_min = arith.maximumf %add, %cst_min : f32
      %clamp_max = arith.minimumf %clamp_min, %cst_max : f32
      %res = arith.fptosi %clamp_max : f32 to i8
      linalg.yield %res : i8
    } -> tensor<16x128xi8>

    return %result : tensor<16x128xi8>
  }
}

// --- CHECKS ---

// CHECK-LABEL: module
// CHECK-LABEL: func.func @quantized_matmul_epilogue

// 1. Check that float math is gone
// CHECK-NOT: arith.sitofp
// CHECK-NOT: arith.mulf
// CHECK-NOT: arith.divf

// 2. Check for the specific calculated constants (The "SOTA" Verification)
// Multiplier for 0.000619... * 2^31 approx 1329634
// CHECK-DAG: %[[MULT:.+]] = arith.constant 1329634 : i32
// CHECK-DAG: %[[SHIFT:.+]] = arith.constant 31 : i32

// 3. Check for Integer Math Sequence
// CHECK: linalg.generic
// CHECK:   arith.muli %{{.+}}, %[[MULT]]
// CHECK:   arith.shrsi %{{.+}}, %[[SHIFT]]