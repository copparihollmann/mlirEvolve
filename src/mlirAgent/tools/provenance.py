import os
import re
import difflib
import json
import argparse
from typing import List, Dict, Optional, Any

# --- ROBUST BINDING IMPORT ---
# We prioritize IREE bindings as they include the specific dialects (flow, stream, hal)
# found in your artifacts.
HAS_BINDINGS = False
try:
    import iree.compiler.ir as ir
    HAS_BINDINGS = True
except ImportError:
    try:
        import mlir.ir as ir
        HAS_BINDINGS = True
    except ImportError:
        pass

class MLIRProvenanceTracer:
    """
    End-to-End tool for tracing MLIR operations across compilation history.
    
    FEATURES:
    1. Robust Parsing: Uses official C++ bindings to parse generic and custom dialects.
    2. Structural Search: Finds operations by semantic Location, not text matching.
    3. Structural Sanitization: Modifies the in-memory IR to strip noise (Locations, Large Weights)
       before generating diffs, ensuring changes are real logic changes, not just line shifts.
    4. Smart Diffing: Collapses unchanged regions to keep LLM context small.
    """

    def __init__(self):
        if not HAS_BINDINGS:
            raise ImportError(
                "❌ CRITICAL: MLIR/IREE Python bindings not found. "
                "This tool requires 'iree-compiler' or 'mlir' python packages."
            )

    # --- 1. FILE DISCOVERY ---
    def _natural_key(self, text):
        """Sorts filenames naturally (1, 2, ... 10) instead of lexicographically (1, 10, 2)."""
        return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]

    def _get_history_files(self, root_dir: str) -> List[Dict]:
        """Scans the history directory for .mlir files."""
        files = []
        if not os.path.exists(root_dir):
            return []
            
        for dirpath, _, filenames in os.walk(root_dir):
            for f in filenames:
                if f.endswith(".mlir"):
                    files.append({
                        "path": os.path.join(dirpath, f),
                        "name": f,
                        "rel_dir": os.path.basename(dirpath),
                        "sort_key": self._natural_key(f)
                    })
        files.sort(key=lambda x: x["sort_key"])
        return files

    # --- 2. STRUCTURAL PROCESSING (The Core Binding Logic) ---
    
    def _sanitize_operation_in_place(self, op, ctx):
        """
        Modifies the Operation IN-MEMORY to remove noise.
        This allows for 'Semantic Diffing' - we diff the logic, not the line numbers.
        """
        unknown_loc = ir.Location.unknown(context=ctx)
        
        def callback(child_op):
            # 1. Strip Location
            # This structurally removes the "loc(...)" attribute from the Op
            child_op.location = unknown_loc
            
            # 2. Truncate Massive Attributes (e.g. Weights, Dense Elements)
            # We iterate over a copy of the named attributes to allow modification.
            try:
                for named_attr in list(child_op.attributes):
                    attr_name = named_attr.name
                    attr_val = named_attr.attr
                    
                    # Heuristic: Check if it's a Dense Element or just massive string repr
                    s_val = str(attr_val)
                    if len(s_val) > 300: # Threshold for "Noise"
                        # We replace the attribute value with a lightweight StringAttr placeholder.
                        # This keeps the IR valid enough for printing, but clean for reading.
                        placeholder = ir.StringAttr.get(f"... [TRUNCATED {len(s_val)} chars] ...", context=ctx)
                        child_op.attributes[attr_name] = placeholder
            except Exception:
                # Some attributes might be system-managed/read-only; skip them safely
                pass
                
            return 0 # Continue walk

        # Apply to self and all children
        self._recursive_walk(op, callback)

    def _recursive_walk(self, op, callback):
        """Recursively walks regions/blocks to visit every operation."""
        callback(op)
        if hasattr(op, "regions"):
            for region in op.regions:
                for block in region:
                    for child in block:
                        self._recursive_walk(child, callback)

    def _find_op_and_process(self, module, filename: str, line: int, ctx) -> Optional[str]:
        """
        1. Walks the parsed module to find the op at `filename:line`.
        2. Sanitizes it (strips locs/weights).
        3. Returns the clean string dump.
        """
        # We search using the ORIGINAL locations found in the file.
        target_marker = f'"{filename}":{line}'
        best_op = None
        
        def find_callback(op):
            nonlocal best_op
            if target_marker in str(op.location):
                # Heuristic: Prefer specific instructions over containers.
                # If we hit a Module or Func, keep looking for a specific op inside it.
                is_container = op.name in [
                    "builtin.module", "util.func", "func.func", 
                    "stream.executable", "stream.executable.export"
                ]
                
                if best_op is None:
                    best_op = op
                elif not is_container:
                    # We found a specific instruction (e.g. arith.constant) inside.
                    best_op = op
            return 0

        self._recursive_walk(module.operation, find_callback)
        
        if best_op:
            # SANITIZATION:
            # We modify the in-memory object to remove locations and huge weights.
            # Since we parsed a fresh module for this file, this is safe.
            self._sanitize_operation_in_place(best_op, ctx)
            
            # PRINTING:
            # The standard str(op) now uses the MLIR printer on our cleaned object.
            return str(best_op)
            
        return None

    # --- 3. TEXT DIFFERENCING (Smart Collapse) ---
    def _smart_collapse(self, prev_text: str, curr_text: str) -> str:
        """
        Performs a diff between two text blocks, collapsing unchanged regions.
        """
        if not prev_text: return curr_text 

        prev_lines = prev_text.splitlines()
        curr_lines = curr_text.splitlines()
        
        matcher = difflib.SequenceMatcher(None, prev_lines, curr_lines)
        output = []
        
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            # opcode is one of: 'replace', 'delete', 'insert', 'equal'
            if opcode == 'equal':
                block_len = j2 - j1
                if block_len < 6:
                    # Keep small context
                    output.extend(curr_lines[j1:j2])
                else:
                    # Collapse large unchanged blocks
                    output.extend(curr_lines[j1:j1+2])
                    skipped = block_len - 4
                    output.append(f"    ... [collapsed {skipped} unchanged lines] ...")
                    output.extend(curr_lines[j2-2:j2])
            else:
                # For changes, we just output the new lines (simplification for Agent readability)
                # Ideally, a real diff format (-/+) might be better, but agents often prefer
                # just seeing the "New State".
                output.extend(curr_lines[j1:j2])
                
        return "\n".join(output)

    # --- 4. MAIN TRACE API ---
    def trace(self, artifacts_root: str, source_filename: str, line_number: int) -> Dict[str, Any]:
        """
        Main entry point. Scans history, parses files, tracks changes.
        """
        # Determine history directory
        history_root = os.path.join(artifacts_root, "ir_pass_history")
        if not os.path.exists(history_root) and "ir_pass_history" in artifacts_root:
            history_root = artifacts_root
            
        if not os.path.exists(history_root):
            return {"error": f"History directory not found: {history_root}"}

        files = self._get_history_files(history_root)
        timeline = []
        last_clean_code = None
        
        print(f"🕵️  Tracing {source_filename}:{line_number} across {len(files)} passes...")

        for file_info in files:
            # CRITICAL: Create a fresh Context for every file.
            # MLIR Contexts define the "Universe" of the IR. Trying to parse multiple files
            # into the same context or mixing ops from different contexts causes segfaults.
            ctx = ir.Context()
            ctx.allow_unregistered_dialects = True
            
            try:
                with open(file_info['path'], 'r') as f:
                    content = f.read()
                
                # Skip empty dumps
                if not content.strip(): continue

                # 1. Parse
                module = ir.Module.parse(content, context=ctx)
                
                # 2. Find, Sanitize, Dump
                current_clean_code = self._find_op_and_process(module, source_filename, line_number, ctx)
                
                # 3. Detect Changes
                status = "unchanged"
                display_code = None
                
                if current_clean_code and not last_clean_code:
                    status = "created"
                    display_code = current_clean_code
                elif not current_clean_code and last_clean_code:
                    status = "deleted"
                    display_code = ""
                elif current_clean_code and last_clean_code:
                    # Compare the SANITIZED strings. 
                    # If they differ, it means logic changed, not just line numbers.
                    if current_clean_code != last_clean_code:
                        status = "modified"
                        display_code = self._smart_collapse(last_clean_code, current_clean_code)

                if status != "unchanged":
                    timeline.append({
                        "pass": file_info['name'],
                        "context": file_info['rel_dir'],
                        "action": status,
                        "code": display_code
                    })
                
                if current_clean_code:
                    last_clean_code = current_clean_code

            except Exception as e:
                # If a specific intermediate IR is invalid (common in dev), skip it.
                # print(f"Warning: Failed to parse {file_info['name']}: {e}")
                pass

        return {
            "query": f"{source_filename}:{line_number}",
            "total_events": len(timeline),
            "events": timeline
        }

# --- CLI ENTRY POINT ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Structural MLIR Provenance Tracer")
    parser.add_argument("filename", help="Source filename (e.g. input.mlir)")
    parser.add_argument("line", type=int, help="Source line number")
    parser.add_argument("--root", required=True, help="Path to artifacts or ir_pass_history")
    parser.add_argument("--output", help="Path to save JSON output")
    
    args = parser.parse_args()
    
    try:
        tracer = MLIRProvenanceTracer()
        result = tracer.trace(args.root, args.filename, args.line)
        
        print(json.dumps(result, indent=2))
        
        if args.output:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2)
            print(f"\n✅ Results saved to {args.output}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)