import torch
import torch.nn as nn
import os
import onnx
import numpy as np
import onnxruntime
from onnxruntime.quantization import quantize_static, QuantType, CalibrationDataReader
from onnx.external_data_helper import convert_model_to_external_data

# --- 1. Define the Hybrid Network ---
class SimpleHybridNet(nn.Module):
    def __init__(self, input_channels=3, img_size=32, num_classes=10):
        super(SimpleHybridNet, self).__init__()
        self.conv = nn.Conv2d(in_channels=input_channels, out_channels=16, kernel_size=3, stride=2, padding=1)
        self.relu = nn.ReLU()
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=16, nhead=4, dim_feedforward=64, 
            dropout=0.0, activation='relu', batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=1)
        self.fc = nn.Linear(16 * 16 * 16, num_classes)

    def forward(self, x):
        x = self.conv(x)
        x = self.relu(x)
        b, c, h, w = x.shape
        x = x.view(b, c, h * w).permute(0, 2, 1)
        x = self.transformer(x)
        x = x.flatten(start_dim=1)
        x = self.fc(x)
        return x

# --- 2. Setup Paths ---
MODEL_NAME = "hybrid_conv_transformer"
OUTPUT_DIR = f"compilation_{MODEL_NAME}"
os.makedirs(OUTPUT_DIR, exist_ok=True)

fp32_onnx_path = os.path.join(OUTPUT_DIR, f"{MODEL_NAME}_fp32.onnx")
quant_onnx_path = os.path.join(OUTPUT_DIR, f"{MODEL_NAME}_int8_sym.onnx")
external_data_file = f"{MODEL_NAME}.data"

# --- 3. Export FP32 ---
print(f"Exporting FP32 to {fp32_onnx_path}...")
model = SimpleHybridNet(img_size=32).eval()
dummy_input = torch.randn(1, 3, 32, 32)

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
        self.data = iter([{'input': np.random.randn(1, 3, 32, 32).astype(np.float32)} for _ in range(5)])
    def get_next(self): return next(self.data, None)

# We use a temporary path for the "dirty" quantized model
temp_quant_path = os.path.join(OUTPUT_DIR, "temp_quant.onnx")

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
def sanitize_tensor_proto(t):
    """
    Ensures a TensorProto doesn't have conflicting data fields.
    If 'raw_data' (external/binary) is present, we wipe the typed fields.
    """
    if t.HasField("raw_data") and len(t.raw_data) > 0:
        # If binary data exists, typed fields MUST be empty
        t.ClearField("float_data")
        t.ClearField("int32_data")
        t.ClearField("int64_data")
        t.ClearField("double_data")

def sanitize_model(model):
    print("Sanitizing model to prevent 'one and only one value' errors...")
    
    # 1. Clean Initializers (Weights)
    for initializer in model.graph.initializer:
        sanitize_tensor_proto(initializer)

    # 2. Clean Constant Nodes (Shapes like val_4)
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
# This keeps val_4 (tiny) INSIDE the file, and moves weights OUTSIDE.
print(f"Splitting weights to {external_data_file}...")
convert_model_to_external_data(
    onnx_model,
    all_tensors_to_one_file=True,
    location=external_data_file,
    size_threshold=1024,  # <--- Critical: Keeps shape tensors inline
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