import os
import json
import argparse
from typing import List, Dict, Set
from pydriller import Repository
from tqdm import tqdm

# --- Configuration: The "Industry Standard" Extensions ---
# Logic: Implementation files
CODE_EXTENSIONS = {'.cpp', '.h', '.hpp', '.td', '.py'}
# Verification: The proof that the logic works
TEST_EXTENSIONS = {'.mlir', '.ll'} 

def is_relevant_path(file_path: str, subsystems: List[str]) -> bool:
    """
    Path-Based Heuristic (Robust).
    Checks if the file belongs to one of the target subsystems (e.g., 'mlir/', 'iree/').
    """
    if not file_path:
        return False
    if not subsystems:
        return True # If no restriction, everything is valid
    return any(sub in file_path for sub in subsystems)

def analyze_commit(commit, subsystems: List[str]) -> Dict:
    """
    Analyzes a commit to see if it qualifies as a "Recipe".
    Returns a dict if valid, None otherwise.
    """
    # 1. Filter Noise Commits
    # Skip merges and massive refactors (>500 lines) which confuse agents
    if commit.merge or commit.lines > 500:
        return None

    msg_lower = commit.msg.lower()
    if any(x in msg_lower for x in ["revert", "merge branch", "clang-format", "bump version", "nfc"]):
        return None

    code_changes = []
    test_files = []
    
    # 2. Iterate Files
    for file in commit.modified_files:
        # Check 1: Must be a modification (not delete/rename only)
        if file.change_type.name != 'MODIFY': 
            continue
        
        # Check 2: Must be in a target subsystem (e.g., "mlir/")
        if not is_relevant_path(file.new_path, subsystems):
            continue

        ext = os.path.splitext(file.new_path)[1]
        
        # Check 3: Classify as Code or Test
        if ext in TEST_EXTENSIONS or (file.new_path and "test/" in file.new_path):
            test_files.append({
                "path": file.new_path,
                "content": file.source_code 
            })
        elif ext in CODE_EXTENSIONS:
            code_changes.append({
                "path": file.new_path,
                "diff": file.diff,
            })

    # 3. THE GOLDEN RULE: Code + Test
    # We only want commits that change Logic (Code) and prove it (Test).
    if code_changes and test_files:
        return {
            "hash": commit.hash,
            "msg": commit.msg,
            "date": str(commit.committer_date),
            "author": commit.author.name,
            "changes": code_changes,
            "tests": test_files,
            "source_repo": "llvm-project"
        }
    
    return None

def mine_repository(repo_path: str, output_file: str, subsystems: List[str], limit: int):
    print(f"⛏️  Mining Repository: {repo_path}")
    print(f"🎯 Target Subsystems: {subsystems if subsystems else 'ALL'}")
    print(f"📂 Output: {output_file}")
    
    # Ensure directory hierarchy exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Initialize PyDriller
    # histogram_diff=True: Produces cleaner diffs that align with logical blocks
    # skip_whitespaces=True: Ignores indentation-only changes
    repo = Repository(
        repo_path, 
        order='reverse', # Newest first = most relevant API usages
        only_modifications_with_file_types=list(CODE_EXTENSIONS.union(TEST_EXTENSIONS)),
        histogram_diff=True,
        skip_whitespaces=True
    )

    count = 0
    with open(output_file, 'w') as f:
        pbar = tqdm(repo.traverse_commits(), desc="Scanning History")
        
        for commit in pbar:
            if limit > 0 and count >= limit:
                break

            recipe = analyze_commit(commit, subsystems)
            
            if recipe:
                f.write(json.dumps(recipe) + "\n")
                f.flush()
                count += 1
                pbar.set_postfix({"mined": count})

    print(f"\n✅ Success. Mined {count} robust recipes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mine Compiler Recipes (Code+Test Pairs)")
    
    parser.add_argument("--repo", type=str, required=True, help="Path to local git clone")
    parser.add_argument("--output", type=str, required=True, help="Full path to output .jsonl")
    parser.add_argument("--subsystems", type=str, default="mlir,llvm/include/llvm/ADT", help="Comma-separated paths to whitelist")
    parser.add_argument("--limit", type=int, default=1000, help="Max recipes to mine")

    args = parser.parse_args()
    
    # Parse subsystems into a list
    subs = [s.strip() for s in args.subsystems.split(',')] if args.subsystems else []
    
    mine_repository(args.repo, args.output, subs, args.limit)