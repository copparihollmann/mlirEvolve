import json
import re
import os
import aiohttp
import asyncio
import argparse
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables (GITHUB_TOKEN) from .env
load_dotenv()

# Constants
GITHUB_API_BASE = "https://api.github.com/repos/llvm/llvm-project"
# Regex to find PR numbers in commit messages (Standard LLVM merge format)
# Matches: "Merge pull request #12345" OR "(#12345)"
PR_PATTERN = re.compile(r"\(#(\d+)\)|Merge pull request #(\d+)")

async def fetch_pr_labels(session, pr_number, token):
    """
    Fetches labels for a specific PR from GitHub API.
    """
    url = f"{GITHUB_API_BASE}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {token}", 
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return [label['name'] for label in data.get('labels', [])]
            
            elif response.status == 403:
                # 403 usually means Rate Limit Exceeded
                print("\n⚠️  GitHub Rate Limit Hit. Sleeping for 60s...")
                await asyncio.sleep(60)
                return []
            
            elif response.status == 404:
                # PR not found (happens with direct commits or very old history)
                return []
            
            else:
                return []
    except Exception as e:
        print(f"\n❌ Network Error on PR #{pr_number}: {e}")
        return []

async def enrich_recipes(input_file, output_file, token):
    print(f"🏷️  Enriching Metadata")
    print(f"    ├── Input:  {input_file}")
    print(f"    └── Output: {output_file}")
    
    # 1. Read existing raw recipes
    if not os.path.exists(input_file):
        print(f"❌ Error: Input file not found: {input_file}")
        return

    with open(input_file, 'r') as f:
        recipes = [json.loads(line) for line in f]

    print(f"    └── Found {len(recipes)} recipes to process.")

    # 2. Prepare Async Tasks
    async with aiohttp.ClientSession() as session:
        pending_enrichments = []

        for i, recipe in enumerate(recipes):
            # Parse PR number from commit message
            match = PR_PATTERN.search(recipe.get('msg', ''))
            
            if match:
                # Group 1 or 2 depending on which regex part matched
                pr_id = match.group(1) or match.group(2)
                recipe['pr_id'] = pr_id
                
                # Create a task for this PR
                pending_enrichments.append((i, fetch_pr_labels(session, pr_id, token)))
            else:
                recipe['github_labels'] = [] # No PR number found

        # 3. Execute in Batches (Semaphore to respect API limits)
        # 10 concurrent requests is safe for Personal Access Tokens
        semaphore = asyncio.Semaphore(10) 
        
        async def sem_task(task):
            async with semaphore:
                return await task

        if pending_enrichments:
            indices, futures = zip(*pending_enrichments)
            # Use tqdm to show real-time progress bar
            results = await asyncio.gather(*(sem_task(f) for f in tqdm(futures, desc="Fetching Tags")))
            
            # 4. Merge results back into the recipe objects
            enriched_count = 0
            for idx, labels in zip(indices, results):
                recipes[idx]['github_labels'] = labels
                if labels: enriched_count += 1
                
                # Fallback: Heuristic tagging if API fails or no labels exist
                if not labels:
                    msg = recipes[idx].get('msg', '').lower()
                    if "mlir" in msg:
                        recipes[idx]['github_labels'].append('mlir')
                    if "fix" in msg:
                        recipes[idx]['github_labels'].append('bug')

            print(f"\n✅ Enrichment Stats: {enriched_count}/{len(pending_enrichments)} PRs successfully tagged.")
        else:
            print("\n⚠️  No PR numbers found in commit messages. Skipping API calls.")

    # 5. Save Enriched Data
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        for recipe in recipes:
            f.write(json.dumps(recipe) + "\n")
            
    print(f"💾 Saved enriched recipes to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input .jsonl from Stage 1")
    parser.add_argument("--output", required=True, help="Output enriched .jsonl")
    parser.add_argument("--token", help="GitHub Token (Overrides .env)")
    args = parser.parse_args()

    # Priority: CLI Argument > Environment Variable (.env)
    token = args.token or os.getenv("GITHUB_TOKEN")
    
    if not token:
        print("❌ CRITICAL ERROR: No GitHub Token found.")
        print("   1. Create a token at https://github.com/settings/tokens")
        print("   2. Add 'GITHUB_TOKEN=ghp_...' to your .env file")
        print("   3. Or pass it via --token argument")
        exit(1)

    asyncio.run(enrich_recipes(args.input, args.output, token))