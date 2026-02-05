import json
import argparse
import os

# The Exact Prompt Template used in Production
RECIPE_PROMPT = """
You are a Compiler Engineer writing a 'Cookbook' for an AI Agent.
Analyze this Git Commit which contains a BUG FIX or OPTIMIZATION.

CONTEXT:
- Commit Message: {msg}
- GitHub Labels: {labels}
- C++ Changes (Logic): 
{diffs}
- MLIR Tests (Verification): 
{tests}

TASK:
Create a structured YAML recipe.
If the labels include 'crash', focus on stability.
If 'missed-optimization', focus on performance.

OUTPUT FORMAT (YAML):
id: "git-{hash}"
tags: [{labels}, inferred_keywords]
problem:
  summary: "One sentence description"
  description: "Detailed context from commit msg"
solution:
  pattern: "Explain the coding pattern (e.g. 'Use rewriter.replaceOp')"
  changes:
    - file: "filename.cpp"
      action: "modify"
      explanation: "Why this change?"
verification:
  input_ir_pattern: "Snippet from test input"
  expected_output: "Snippet from CHECK lines"
"""

def extract_best_candidate(input_file, output_file):
    print(f"🔍 Scanning {input_file} for a 'Gold Standard' example...")
    
    if not os.path.exists(input_file):
        print(f"❌ Error: Input file not found: {input_file}")
        return

    with open(input_file, 'r') as f:
        # Load all lines to search globally
        recipes = [json.loads(line) for line in f]
    
    best_candidate = None
    search_strategy = ""
    
    # --- Priority Level 1: Optimizations (The hardest logic) ---
    for r in recipes:
        labels = r.get('github_labels', [])
        # Look for tasty labels
        if any(tag in labels for tag in ['missed-optimization', 'vectorizers', 'loopoptim']):
            best_candidate = r
            search_strategy = f"Found High-Priority Optimization ({labels})"
            break
    
    # --- Priority Level 2: Crash Fixes (Good for logic tests) ---
    if not best_candidate:
        for r in recipes:
            labels = r.get('github_labels', [])
            if 'crash' in labels or 'crash-on-valid' in labels:
                best_candidate = r
                search_strategy = f"Found Crash Fix ({labels})"
                break
                
    # --- Priority Level 3: Fallback (First valid MLIR recipe) ---
    if not best_candidate:
        best_candidate = recipes[0]
        search_strategy = "Fallback (First available recipe)"

    print(f"✅ Selected Candidate: {best_candidate['hash'][:7]}")
    print(f"🎯 Reason: {search_strategy}")

    # --- Format the Prompt ---
    c_changes = best_candidate.get('changes', [])
    t_changes = best_candidate.get('tests', [])
    
    # Format diffs (Truncate slightly to ensure it fits in Chat)
    diffs = "\n".join([f"File: {c['path']}\n{c['diff'][:4000]}" for c in c_changes])
    tests = "\n".join([f"File: {t['path']}\n{t['content'][:2000]}" for t in t_changes])
    labels = ", ".join(best_candidate.get('github_labels', []))
    
    full_prompt = RECIPE_PROMPT.format(
        msg=best_candidate['msg'],
        labels=labels,
        diffs=diffs,
        tests=tests,
        hash=best_candidate['hash']
    )
    
    # Save to file
    with open(output_file, 'w') as out:
        out.write(full_prompt)
        
    print(f"\n🚀 Prompt successfully saved to: {output_file}")
    print("👉 Action: Open 'test.md', copy the content, and paste it into the chat!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to enriched jsonl")
    parser.add_argument("--output", default="test.md", help="Output markdown file")
    args = parser.parse_args()
    
    extract_best_candidate(args.input, args.output)