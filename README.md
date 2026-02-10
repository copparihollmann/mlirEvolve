# mlirEvolve: Agentic Compiler Engineering Framework

**mlirEvolve** is a research framework designed to automate MLIR compiler development using LLM agents. It bridges the gap between raw compiler source code and AI agents by creating high-quality datasets and semantic knowledge graphs.

## 🚀 Key Features

### 1. "Recipe" Mining (`src/mlirAgent/mining`)
Extracts "Gold Standard" compiler recipes from git history (e.g., LLVM/IREE).
- **Heuristic:** Identifies atomic commits that modify **Logic** (C++/TableGen) and include verifying **Tests** (MLIR/LLVM IR).
- **Noise Filtering:** Automatically filters out merges, refactors, and formatting changes to ensure high-quality training data for agents.

### 2. Code Knowledge Graph (`src/mlirAgent/scip`)
Hydrates a **Neo4j** graph database with a deep semantic understanding of the codebase.
- **SCIP Integration:** Uses SCIP indexing to map definitions, references, and scopes.
- **Graph Schema:** Models complex relationships (`DEFINES`, `CALLS`, `HAS_NESTED`) between Functions, Methods, Classes, and Files, enabling agents to query the codebase structure effectively.

### 3. Agent Tooling (`src/mlirAgent/tools`)
Provides the necessary hooks for agents to interact with the compiler:
- **Compiler Wrapper:** robust execution of `iree-compile` with timeout handling and artifact management.
- **Verification:** Automated checking of generated artifacts.

## 🛠️ Setup & Installation

### Dependencies
Create a virtual environment and install the package in editable mode:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```
