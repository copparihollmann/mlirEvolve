// test_quant.mlir

module {
  
  // Test Case: Standard Quantization Chain
  // We use the exact constants to verify numerical accuracy
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