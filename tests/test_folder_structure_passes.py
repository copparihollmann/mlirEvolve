import os
import sys
import re

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    import iree.compiler.ir as ir
except ImportError:
    try:
        import mlir.ir as ir
    except ImportError:
        print("❌ Bindings not found.")
        sys.exit(1)

# The root folder you are testing
TARGET_ROOT = "experiments/iree_artifacts/compilation_quantized_matmul/artifacts_riscv/ir_pass_history/builtin_module_no-symbol-name"

def get_first_mlir_file(root):
    for f in os.listdir(root):
        if f.endswith(".mlir"):
            return os.path.join(root, f)
    return None

def main():
    print(f"🕵️  Diagnosing Location Strings in: {TARGET_ROOT}")
    
    target_file = get_first_mlir_file(TARGET_ROOT)
    if not target_file:
        print("❌ No .mlir files found in directory.")
        return

    print(f"📄 Parsing sample file: {os.path.basename(target_file)}")
    
    ctx = ir.Context()
    ctx.allow_unregistered_dialects = True
    
    with open(target_file, "r") as f:
        content = f.read()
    
    try:
        module = ir.Module.parse(content, context=ctx)
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return

    print("\n🔍 Scanning for Locations...")
    print("-" * 40)
    
    # Set of unique location strings found
    seen_locs = set()
    count = 0
    
    def callback(op):
        nonlocal count
        loc_str = str(op.location)
        
        # We only care about FileLineCol locations (containing ":")
        if ":" in loc_str and loc_str not in seen_locs:
            seen_locs.add(loc_str)
            # Print the first 10 unique locations we find
            if len(seen_locs) <= 10:
                print(f"   found: {loc_str}")
        
        # Also recurse
        if hasattr(op, "regions"):
            for r in op.regions:
                for b in r:
                    for c in b:
                        callback(c)

    callback(module.operation)
    print("-" * 40)
    print(f"Total unique locations found: {len(seen_locs)}")
    
    # Heuristic check for your specific file
    print("\n🧠 Analysis:")
    match = any("quantized_matmul.mlir" in l for l in seen_locs)
    if match:
        print("✅ Found 'quantized_matmul.mlir' in locations.")
        # Find the specific one to copy-paste
        for l in seen_locs:
            if "quantized_matmul.mlir" in l:
                print(f"👉 Use this path prefix in your test: {l}")
                break
    else:
        print("❌ 'quantized_matmul.mlir' NOT found in locations. The compiler might have dropped debug info.")

if __name__ == "__main__":
    main()