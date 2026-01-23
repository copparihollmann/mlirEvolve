import torch
import torch.nn as nn
import os
import onnx
import numpy as np
import onnxruntime
from onnxruntime.quantization import quantize_static, QuantType, CalibrationDataReader
from onnx.external_data_helper import convert_model_to_external_data

# --- 1. Define the Simple MatMul Network ---
class SimpleMatMulNet(nn.Module):
    def __init__(self, input_dim=128, output_dim=32):
        super(SimpleMatMulNet, self).__init__()
        # nn.Linear performs the MatMul + Add (bias)
        self.fc = nn.Linear(input_dim, output_dim)
        self.relu = nn.ReLU()

    def forward(self, x):
        x = self.fc(x)
        x = self.relu(x)
        return x

# --- 2. Setup Paths (New Folder) ---
MODEL_NAME = "simple_matmul_relu"
OUTPUT_DIR = f"compilation_{MODEL_NAME}"
os.makedirs(OUTPUT_DIR, exist_ok=True)

fp32_onnx_path = os.path.join(OUTPUT_DIR, f"{MODEL_NAME}_fp32.onnx")
quant_onnx_path = os.path.join(OUTPUT_DIR, f"{MODEL_NAME}_int8_sym.onnx")
external_data_file = f"{MODEL_NAME}.data"
temp_quant_path = os.path.join(OUTPUT_DIR, "temp_quant.onnx")

# --- 3. Export FP32 ---
print(f"Exporting FP32 to {fp32_onnx_path}...")
model = SimpleMatMulNet(input_dim=128, output_dim=32).eval()
# Input shape: Batch size 1, Input Dim 128
dummy_input = torch.randn(1, 128)

torch.onnx.export(
    model, (dummy_input,), fp32_onnx_path,
    input_names=["input"], output_names=["output"],
    opset_version=17, 
    do_constant_folding=True
)

# --- 4. Quantize ---
print("Quantizing...")
class RandomDataReader(CalibrationDataReader):
    def __init__(self):
        # Create random calibration data matching input shape (1, 128)
        self.data = iter([{'input': np.random.randn(1, 128).astype(np.float32)} for _ in range(5)])
    def get_next(self): return next(self.data, None)

quantize_static(
    model_input=fp32_onnx_path,
    model_output=temp_quant_path,
    calibration_data_reader=RandomDataReader(),
    quant_format=onnxruntime.quantization.QuantFormat.QDQ,
    activation_type=QuantType.QInt8,
    weight_type=QuantType.QInt8,
    extra_options={'ActivationSymmetric': True, 'WeightSymmetric': True}
)

# --- 5. THE FIX: Aggressive Sanitization ---
# (Reused exactly as provided to ensure cleaner protos)
def sanitize_tensor_proto(t):
    """
    Ensures a TensorProto doesn't have conflicting data fields.
    If 'raw_data' (external/binary) is present, we wipe the typed fields.
    """
    if t.HasField("raw_data") and len(t.raw_data) > 0:
        t.ClearField("float_data")
        t.ClearField("int32_data")
        t.ClearField("int64_data")
        t.ClearField("double_data")

def sanitize_model(model):
    print("Sanitizing model to prevent 'one and only one value' errors...")
    
    # 1. Clean Initializers (Weights)
    for initializer in model.graph.initializer:
        sanitize_tensor_proto(initializer)

    # 2. Clean Constant Nodes
    for node in model.graph.node:
        if node.op_type == "Constant":
            for attr in node.attribute:
                if attr.type == onnx.AttributeProto.TENSOR:
                    sanitize_tensor_proto(attr.t)
    return model

# --- 6. Final Conversion and Save ---
print("Loading and cleaning...")
onnx_model = onnx.load(temp_quant_path)

# A. Sanitize existing conflicts
onnx_model = sanitize_model(onnx_model)

# B. Remove old external file if exists
ext_path_full = os.path.join(OUTPUT_DIR, external_data_file)
if os.path.exists(ext_path_full):
    os.remove(ext_path_full)

# C. Convert to External Data with Threshold
# This keeps tiny shape tensors inside the ONNX file, moves weights to .data
print(f"Splitting weights to {external_data_file}...")
convert_model_to_external_data(
    onnx_model,
    all_tensors_to_one_file=True,
    location=external_data_file,
    size_threshold=1024, 
    convert_attribute=False
)

# D. Final Save
onnx.save(onnx_model, quant_onnx_path)

# Cleanup temp file
if os.path.exists(temp_quant_path):
    os.remove(temp_quant_path)

print("------------------------------------------------")
print("SUCCESS.")
print(f"Model:   {quant_onnx_path}")
print(f"Weights: {ext_path_full}")
print("\nNow run:")
print(f"iree-import-onnx {quant_onnx_path} --opset-version 17 -o {MODEL_NAME}.mlir")