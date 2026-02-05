import os
import sys
import difflib

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    import iree.compiler.ir as ir
    print("✅ Loaded 'iree.compiler.ir'")
except ImportError:
    try:
        import mlir.ir as ir
        print("⚠️  Loaded 'mlir.ir' (generic). IREE dialects may parse generically.")
    except ImportError:
        print("❌ Error: No MLIR bindings found. Please set PYTHONPATH correctly.")
        sys.exit(1)

# Target File
TARGET_FILE = "/scratch2/agustin/merlin/mlirEvolve/experiments/iree_artifacts/compilation_quantized_matmul/artifacts_riscv/ir_pass_history/builtin_module_no-symbol-name/68_iree-stream-materialize-encodings.mlir"


class Traversal:
    CONTINUE = 0
    INTERRUPT = 1

class MLIRGranularExplorer:
    def __init__(self, filepath):
        self.filepath = filepath
        self.ctx = ir.Context()
        self.ctx.allow_unregistered_dialects = True 
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "r") as f:
            self.content = f.read()
        
        print(f"Parsing module ({len(self.content)} bytes)...")
        self.module = ir.Module.parse(self.content, context=self.ctx)

    def explore_structure(self):
        """Walks the IR and prints a granular hierarchy."""
        print("\n🔍 --- DECOMPOSING IR STRUCTURE ---")
        self._visit_op(self.module.operation, depth=0)

    def _visit_op(self, op, depth):
        indent = "  " * depth
        
        # 1. Identify Op
        name = op.name
        loc = self._parse_location(op.location)
        
        # Print Summary
        print(f"{indent}🔹 [OP] {name}")
        if loc:
            print(f"{indent}    📍 Loc: {loc}")

        # 2. Inspect Attributes
        if len(op.attributes) > 0:
            print(f"{indent}    🏷️  Attributes ({len(op.attributes)}):")
            for attr in op.attributes:
                key = attr.name
                val = attr.attr
                val_str = str(val)
                if len(val_str) > 80: val_str = val_str[:80] + "..."
                print(f"{indent}      - {key}: {val_str}")

        # 3. Inspect Results (Produced Values)
        if len(op.results) > 0:
            print(f"{indent}    📤 Results ({len(op.results)}):")
            for i, res in enumerate(op.results):
                print(f"{indent}      - Result #{i}: {res.type}")

        # 4. Inspect Operands (Consumed Values)
        if len(op.operands) > 0:
            print(f"{indent}    📥 Operands ({len(op.operands)}):")
            for i, operand in enumerate(op.operands):
                self._print_operand_info(operand, indent, i)

        # 5. Recurse into Regions -> Blocks
        for i, region in enumerate(op.regions):
            print(f"{indent}    📦 Region #{i}")
            for j, block in enumerate(region):
                arg_info = f"({len(block.arguments)} args)" if len(block.arguments) > 0 else ""
                print(f"{indent}      🧱 Block #{j} {arg_info}")
                
                # Print Block Arguments
                for k, arg in enumerate(block.arguments):
                    print(f"{indent}        ↳ BlockArg #{k}: {arg.type}")

                for child_op in block:
                    self._visit_op(child_op, depth + 3)

    def _print_operand_info(self, value, indent, index):
        """Robustly prints information about a Value, identifying if it's an OpResult or BlockArg."""
        try:
            # Check for OpResult
            if isinstance(value, ir.OpResult):
                producer = value.owner
                print(f"{indent}      - Arg #{index}: OpResult from '{producer.name}' (Result Idx: {value.result_number})")
            
            # Check for BlockArgument
            elif isinstance(value, ir.BlockArgument):
                arg_num = value.arg_number if hasattr(value, 'arg_number') else "?"
                print(f"{indent}      - Arg #{index}: BlockArgument #{arg_num} (Defined in Block)")
            
            else:
                # Fallback for generic Value wrapper
                print(f"{indent}      - Arg #{index}: Value (Type: {value.type})")
                
        except Exception as e:
            print(f"{indent}      - Arg #{index}: [Error inspecting value: {e}]")

    def _parse_location(self, loc):
        s = str(loc)
        if "quantized_matmul.mlir" in s:
            return s
        return None

    def demonstrate_modification(self):
        """Demonstrates modifying the IR in memory and printing the diff."""
        print("\n🛠️  --- MODIFICATION DEMO ---")
        
        # 1. Capture State BEFORE
        print("📸 Capturing original module state...")
        original_ir = str(self.module)

        # 2. Perform Modification
        modified_count = 0
        
        def walker(op):
            nonlocal modified_count
            if op.name == "arith.constant":
                try:
                    if "value" in op.attributes:
                        val_attr = op.attributes["value"]
                        if isinstance(val_attr, ir.IntegerAttr):
                            old_val = val_attr.value
                            if old_val == 0:
                                new_val = 1337 
                                new_attr = ir.IntegerAttr.get(val_attr.type, new_val)
                                op.attributes["value"] = new_attr
                                
                                print(f"✅ Modified arith.constant at {op.location}")
                                print(f"   Value change: {old_val} -> {new_val}")
                                modified_count += 1
                                return Traversal.INTERRUPT
                except Exception as e:
                    print(f"⚠️  Modification failed: {e}")
            return Traversal.CONTINUE

        # Manual Recursive Walk
        def recursive_walk(op):
            if walker(op) == Traversal.INTERRUPT: return True
            for region in op.regions:
                for block in region:
                    for child in block:
                        if recursive_walk(child): return True
            return False

        recursive_walk(self.module.operation)

        if modified_count == 0:
            print("❌ No operations were modified.")
            return

        # 3. Capture State AFTER
        print("📸 Capturing modified module state...")
        modified_ir = str(self.module)

        # 4. Generate Diff
        print("\n📊 --- IR DIFF (Before vs After) ---")
        self._print_diff(original_ir, modified_ir)

    def _print_diff(self, original: str, modified: str):
        """Prints a colored unified diff."""
        diff = difflib.unified_diff(
            original.splitlines(),
            modified.splitlines(),
            fromfile='Original',
            tofile='Modified',
            n=3, # Show 3 lines of context
            lineterm=''
        )
        
        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                print(f"\033[92m{line}\033[0m") # Green for Additions
            elif line.startswith('-') and not line.startswith('---'):
                print(f"\033[91m{line}\033[0m") # Red for Deletions
            elif line.startswith('@'):
                print(f"\033[96m{line}\033[0m") # Cyan for Metadata
            else:
                print(line)

def main():
    if not os.path.exists(TARGET_FILE):
        print("❌ Target file not found.")
        return

    explorer = MLIRGranularExplorer(TARGET_FILE)
    
    # Run Inspection
    try:
        # Suppress massive output for the demo if you just want to see the diff
        # explorer.explore_structure() 
        pass 
    except KeyboardInterrupt:
        print("\n(Stopping traversal...)")

    explorer.demonstrate_modification()

if __name__ == "__main__":
    main()