import os
import re
import sys
import json
import difflib
import argparse

# --- UTILS ---

def natural_keys(text):
    return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', text)]

def get_all_history_files(root_dir):
    files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.endswith(".mlir"):
                full_path = os.path.join(dirpath, f)
                files.append({
                    "path": full_path,
                    "name": f,
                    "rel_dir": os.path.basename(dirpath)
                })
    files.sort(key=lambda x: natural_keys(x["name"]))
    return files

# --- CLEANING LOGIC ---

def clean_mlir_code(text):
    if not text: return ""

    # 1. Truncate Weights
    text = re.sub(
        r'(dense<"0x)([0-9a-fA-F]{16})([0-9a-fA-F]+)([0-9a-fA-F]{16})(">)',
        r'\1\2...[TRUNCATED]...\4\5',
        text
    )

    # 2. Remove 'loc(...)' attributes
    result = []
    i = 0
    n = len(text)
    
    while i < n:
        if text[i:].startswith(" loc(") or (i == 0 and text.startswith("loc(")):
            if text[i] == ' ': i += 1
            i += 3 
            if i < n and text[i] == '(':
                depth = 1
                i += 1
                while i < n and depth > 0:
                    if text[i] == '(': depth += 1
                    elif text[i] == ')': depth -= 1
                    i += 1
                continue 
        result.append(text[i])
        i += 1

    lines = [line.rstrip() for line in "".join(result).splitlines()]
    return "\n".join(lines)

# --- SMART COLLAPSING LOGIC (The "Smart" Part) ---

def smart_collapse(prev_text, curr_text):
    """
    Compares prev and curr. Collapses unchanged regions > 6 lines.
    Always preserves the first line (signature) and last line.
    """
    if not prev_text: return curr_text # New file? Show all.

    prev_lines = prev_text.splitlines()
    curr_lines = curr_text.splitlines()
    
    matcher = difflib.SequenceMatcher(None, prev_lines, curr_lines)
    output = []
    
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        # opcode is one of: 'replace', 'delete', 'insert', 'equal'
        
        if opcode == 'equal':
            # This block is UNCHANGED. We can compress it.
            block_len = j2 - j1
            
            # Heuristic: If block is small (<6 lines), keep it for context.
            # If it's the START of the file (j1==0), keep at least the first line.
            if block_len < 6:
                output.extend(curr_lines[j1:j2])
            else:
                # Keep first 2 lines of the block context
                output.extend(curr_lines[j1:j1+2])
                
                # Insert marker
                skipped = block_len - 4
                if skipped > 0:
                    output.append(f"    ... [collapsed {skipped} unchanged lines] ...")
                
                # Keep last 2 lines of the block context
                output.extend(curr_lines[j2-2:j2])
                
        else:
            # This block CHANGED ('insert', 'replace').
            # We MUST show it fully. This is the "Relevant" part.
            output.extend(curr_lines[j1:j2])
            
    return "\n".join(output)

# --- EXTRACTION LOGIC ---

def extract_block_by_loc(file_path, target_filename, target_line):
    with open(file_path, 'r') as f:
        lines = f.readlines()

    search_marker = f'{target_filename}":{target_line}'
    
    match_index = -1
    for i, line in enumerate(lines):
        if search_marker in line:
            match_index = i
            break
    
    if match_index == -1:
        return None

    # Heuristic: Indentation based block extraction
    start_idx = match_index
    match_indent = len(lines[match_index]) - len(lines[match_index].lstrip())
    
    # Expand UP
    cur = match_index
    while cur >= 0:
        line = lines[cur]
        if not line.strip(): 
            cur -= 1
            continue
        indent = len(line) - len(line.lstrip())
        if line.strip() == "}" and cur != match_index: break
        if indent <= match_indent and not line.strip().startswith("//"):
            start_idx = cur
            if indent < match_indent: break 
        cur -= 1

    # Expand DOWN
    cur = match_index + 1
    end_idx = match_index
    start_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    while cur < len(lines):
        line = lines[cur]
        if not line.strip(): 
            cur += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= start_indent:
            if line.strip().startswith("}"):
                end_idx = cur
                break
            if indent == start_indent and not line.strip().startswith("//"):
                end_idx = cur - 1
                break
        end_idx = cur
        cur += 1

    return "".join(lines[start_idx : end_idx + 1])

# --- MAIN ---

def trace_provenance(base_dir, source_file_name, line_number):
    history_root = os.path.join(base_dir, "ir_pass_history")
    
    if not os.path.exists(history_root):
        return json.dumps({"error": f"Path not found: {history_root}"})

    history_files = get_all_history_files(history_root)
    timeline = []
    
    previous_clean = None
    
    for file_info in history_files:
        raw_snippet = extract_block_by_loc(file_info["path"], source_file_name, line_number)
        clean_current = clean_mlir_code(raw_snippet)
        
        status = "unchanged"
        display_code = None
        
        if clean_current and not previous_clean:
            status = "created"
            # For creation, we default to full display (or head/tail if huge)
            display_code = clean_current 
            if len(display_code) > 3000: # Fallback for massive creations
                 display_code = display_code[:1000] + "\n... [Huge Creation Truncated] ...\n" + display_code[-1000:]
                 
        elif not clean_current and previous_clean:
            status = "deleted"
            display_code = "" # No code to show
            
        elif clean_current and previous_clean:
            if "".join(clean_current.split()) != "".join(previous_clean.split()):
                status = "modified"
                # THE SMART PART: Collapse the boring parts
                display_code = smart_collapse(previous_clean, clean_current)
        
        if status in ["created", "modified", "deleted"]:
            timeline.append({
                "pass": file_info["name"],
                "context": file_info["rel_dir"],
                "action": status,
                "code": display_code
            })
            
        if clean_current:
            previous_clean = clean_current

    return json.dumps({
        "query": f"{source_file_name}:{line_number}",
        "total_events": len(timeline),
        "events": timeline
    }, indent=2)

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__)) 
    project_root = os.path.dirname(script_dir)              
    default_output_path = os.path.join(project_root, "output", "trace4.json")

    parser = argparse.ArgumentParser(description="Trace an MLIR operation.")
    parser.add_argument("filename", help="The source filename (e.g., input.mlir)")
    parser.add_argument("line", type=int, help="The source line number to track")
    parser.add_argument("--root", required=True, help="Path to the artifacts_debug directory")
    parser.add_argument("--output", default=default_output_path, required=False, help="Output file path")
    
    args = parser.parse_args()
    result = trace_provenance(args.root, args.filename, args.line)
    
    print(result)

    if args.output:
        output_path = os.path.abspath(args.output)
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(result)