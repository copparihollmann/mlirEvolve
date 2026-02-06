# mlirEvolve -- Comprehensive Repository Understanding

> **Branch:** `ashvin-exploration`
> **License:** Apache 2.0
> **Last Updated:** 2026-02-05

---

## 1. Project Overview

mlirEvolve is an **AI agent framework for working with MLIR/LLVM/IREE codebases**. It provides a suite of Python-based tools that enable an AI agent to:

- **Build** LLVM/IREE from source (CMake + Ninja).
- **Compile** MLIR programs via `iree-compile`.
- **Verify** compiler output using LLVM's `FileCheck`.
- **Trace provenance** of MLIR operations across compilation passes (both text-based and structural/binding-based approaches).
- **Mine best practices** from the LLVM git history by extracting code+test pairs (the "Golden Rule" = code change + corresponding test).
- **Navigate code** through a Neo4j knowledge graph built from SCIP-based code indexes produced by `scip-clang`.
- **Analyze compiler artifacts** using an LLM (GPT-4o via the RLM library) with awareness of the provenance tools.

This is the **core agent harness** -- it does not merely call an external agent; it IS the framework that provides tools and knowledge infrastructure for an AI to reason about, build, compile, verify, and trace MLIR code.

---

## 2. Architecture

### 2.1 Agent Tools (`src/mlirAgent/tools/`)

These are the callable tools that an AI agent (or human) uses to interact with the compiler infrastructure.

#### `compiler.py` -- IREE Compilation Tool
- Wraps `iree-compile` as a Python function `run_compile(mlir_content, flags)`.
- Accepts raw MLIR source as a string, writes it to a temp file in `data/artifacts/`, runs `iree-compile`, and returns a structured dict with success/failure, stdout/stderr, artifact path, duration, and the full command string.
- 60-second timeout for compilation.

#### `build.py` -- Build System Tool
- Wraps **Ninja** and **CMake** builds via `run_build(target, fast_mode, clean, reconfigure)`.
- **Ninja mode:** Runs `ninja -C <BUILD_DIR> <targets>` with optional `clean` and `fast_mode` (builds only `llvm-tblgen`, `llc`, `FileCheck`, `intrinsics_gen`).
- **CMake reconfigure mode:** Runs a full CMake invocation with IREE-specific flags (LLD, LLVM-CPU backend, ccache, assertions, RelWithDebInfo). This is ported from a bash build script.
- Error summary extraction via regex for `error:`, `FAILED:`, `CMake Error` patterns.
- 20-minute timeout for builds, 10-minute timeout for CMake.

#### `verifier.py` -- FileCheck Verification Tool
- Wraps LLVM's `FileCheck` binary via `verify_output(output_ir, check_content)`.
- Pipes compiler output IR into FileCheck to validate it against `// CHECK:` patterns.
- Returns structured pass/fail result.

#### `trace_provenance.py` -- Text-Based MLIR Op Tracing
- **Text-based** approach to tracing how a specific source location (e.g., `input.mlir:37`) evolves across compiler passes.
- Scans `ir_pass_history/` directories containing one `.mlir` file per pass dump.
- For each pass file, searches for the target `loc("filename":line)` marker, extracts the enclosing code block using indentation heuristics, then cleans the IR by:
  - Truncating large `dense<"0x...">` weight blobs.
  - Stripping `loc(...)` attributes.
- Performs **smart collapsing**: uses `difflib.SequenceMatcher` to diff consecutive pass outputs and collapse unchanged regions (>6 lines) to keep output compact.
- Produces a JSON timeline of `{pass, context, action (created/modified/deleted), code}` events.

#### `provenance.py` -- Structural MLIR Provenance Tracer
- **Structural** approach using official **MLIR/IREE Python bindings** (`iree.compiler.ir` or `mlir.ir`).
- Parses each pass dump file into an in-memory MLIR Module with `allow_unregistered_dialects = True`.
- Walks the IR tree to find operations by semantic Location (not text grep).
- **Structural sanitization**: modifies the in-memory IR to strip location attributes (`op.location = unknown_loc`) and truncate large attributes (>300 char string representations replaced with placeholders) before generating diffs. This ensures diffs reflect real logic changes, not noise.
- Same smart-collapse diffing as `trace_provenance.py` but operating on structurally cleaned IR.
- Creates a fresh `ir.Context()` per file to avoid cross-context segfaults.

### 2.2 Mining Pipeline (`src/mlirAgent/mining/`)

A three-stage pipeline to extract "cookbook recipes" from LLVM's git history.

#### Stage 1: `mine_commits.py` -- Commit Mining
- Uses **PyDriller** to traverse the LLVM git repository (`order='reverse'`, newest first).
- Filters out merges, massive refactors (>500 lines), reverts, clang-format, NFC commits.
- Classifies modified files as **Code** (`.cpp`, `.h`, `.hpp`, `.td`, `.py`) or **Test** (`.mlir`, `.ll`).
- Applies path-based subsystem filtering (e.g., `mlir/`, `llvm/include/llvm/ADT`).
- **The Golden Rule**: Only emits recipes for commits that contain BOTH code changes AND test files. This ensures each recipe is a self-contained example of a bug fix or optimization with its proof.
- Output: JSONL file with `{hash, msg, date, author, changes (diffs), tests (file contents), source_repo}`.

#### Stage 2: `enrich_metadata.py` -- GitHub Label Enrichment
- Reads the raw JSONL from Stage 1.
- Parses PR numbers from commit messages using regex (`(#12345)` or `Merge pull request #12345`).
- Uses **async** `aiohttp` with a semaphore (10 concurrent) to batch-fetch PR labels from the GitHub API (`/repos/llvm/llvm-project/pulls/{id}`).
- Handles rate limits (403 -> sleep 60s) and 404s gracefully.
- Fallback heuristic tagging: if no API labels, infers `mlir` or `bug` from commit message keywords.
- Output: Enriched JSONL with `github_labels` field added.

#### Stage 3: `extract_test_prompt.py` -- Cookbook Recipe Generation
- Reads enriched JSONL and selects the best candidate commit using priority:
  1. Optimization commits (`missed-optimization`, `vectorizers`, `loopoptim` labels).
  2. Crash fixes (`crash`, `crash-on-valid` labels).
  3. Fallback: first available recipe.
- Formats the selected commit into a structured YAML prompt template that includes the commit message, labels, C++ diffs (truncated to 4000 chars), MLIR tests (truncated to 2000 chars), and instructions for an LLM to produce a cookbook recipe.
- Output: A markdown file containing the full prompt, ready to paste into an LLM chat.

### 2.3 Knowledge Graph (`src/mlirAgent/scip/`)

SCIP-based code indexing and Neo4j graph ingestion for structural code navigation.

#### `ingest_codegraph.py` -- SCIP-to-Neo4j Ingestion
- Reads a **SCIP protobuf index** file (`index_test.scip`) produced by `scip-clang` (a C/C++ SCIP indexer).
- Parses the SCIP index using generated protobuf bindings (`scip_pb2`).
- Creates a **Neo4j knowledge graph** with the following schema:
  - **Node labels:** `FILE`, `FUNCTION`, `CLASS_STRUCTURE`, `NAMESPACE`, `METHOD`, `Symbol` (generic fallback).
  - **Relationship types:** `CALLS` (function/method calls another symbol), `DEFINES` (file defines a symbol), `HAS_METHOD` (class/struct has a method), `HAS_NESTED` (class/namespace has nested type).
  - Uniqueness constraints on `path` (for `FILE`) or `id` (for all other labels).
- Uses a **spatial scan** strategy: sorts occurrences by line, maintains a scope stack to determine parent-child relationships (e.g., a method defined inside a class).
- Classifies symbols by parsing the **SCIP symbol grammar** (trailing `.` = term/function, `#` = type/class, `!` = macro, `/` = namespace), falling back to the `Kind` integer when available.
- Batch processing (2000 nodes/edges per batch) with `MERGE` semantics for idempotent re-ingestion.

#### `check_graph_status.py` -- Neo4j Health Check
- Connects to Neo4j and reports node count, edge count, and a sample node.
- Quick verification that ingestion succeeded.

### 2.4 RLM Analysis (`src/mlirAgent/rlm/`)

#### `analysis.py` -- LLM-Powered Artifact Analysis
- Uses the **RLM library** (Reliable Language Model) with GPT-4o (temperature 0.1) via OpenAI API.
- The `LogAnalysisAgent.analyze_compiler_artifacts(artifacts_path, query)` method:
  - Constructs a system prompt that describes the agent as an "Expert MLIR Compiler Engineer with access to a Python REPL."
  - Injects **provenance tool awareness** into the prompt -- instructs the LLM to import and use `MLIRProvenanceTracer` from the tools.
  - Asks the LLM to return structured JSON with `root_cause_pass`, `explanation`, and `evidence`.
- Singleton pattern: `log_analyzer` instance created at module load.

---

## 3. Configuration (`src/mlirAgent/config.py`)

Centralized configuration via the `Config` class, using environment variables with sensible defaults:

| Setting | Default / Source | Purpose |
|---|---|---|
| `IREE_SRC_PATH` | `/scratch2/agustin/merlin/third_party/iree_bar` | IREE source tree for CMake |
| `LLVM_SRC_PATH` | `IREE_SRC_PATH/third_party/llvm-project` | LLVM source (nested in IREE) |
| `BUILD_DIR` | `/scratch2/agustin/merlin/build/vanilla/host/debug/...` | Ninja build directory |
| `INSTALL_DIR` | `BUILD_DIR/install` | CMake install prefix |
| `IREE_COMPILE_PATH` | `BUILD_DIR/tools/iree-compile` | iree-compile binary |
| `FILECHECK_PATH` | `BUILD_DIR/llvm-project/bin/FileCheck` | FileCheck binary |
| `LLVM_LIT_PATH` | `BUILD_DIR/llvm-project/bin/lit` | LLVM LIT test runner |
| `ARTIFACTS_DIR` | `<project_root>/data/artifacts` | Compilation artifacts storage |
| `RECIPES_DIR` | `<project_root>/data/cookbook/LLVM_recipes` | Mined cookbook recipes |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt protocol endpoint |
| `NEO4J_USER` / `NEO4J_PASSWORD` | `.env` file | Neo4j credentials |
| `LANCEDB_DIR` | `<project_root>/data/lancedb` | LanceDB vector store |
| `OPENAI_API_KEY` | `.env` file | OpenAI API key for RLM |

The `Config.validate()` method runs at import time, creating the artifacts directory and warning if source/build paths are missing.

---

## 4. Directory Structure

```
mlirEvolve/
|-- README.md                          # Quickstart (API key, pip install -e ., tree tips)
|-- LICENSE                            # Apache 2.0
|-- docker-compose.yml                 # Neo4j 5.16 + APOC + GDS plugins
|-- .gitignore                         # Ignores artifacts, SCIP outputs, Neo4j data, API keys
|
|-- src/
|   `-- mlirAgent/
|       |-- config.py                  # Central configuration (paths, Neo4j, LanceDB, OpenAI)
|       |-- tools/
|       |   |-- compiler.py            # iree-compile wrapper
|       |   |-- build.py               # Ninja/CMake build wrapper
|       |   |-- verifier.py            # FileCheck wrapper
|       |   |-- trace_provenance.py    # Text-based MLIR op tracing across passes
|       |   `-- provenance.py          # Structural tracing via MLIR Python bindings
|       |-- mining/
|       |   |-- mine_commits.py        # PyDriller-based LLVM commit mining (Golden Rule)
|       |   |-- enrich_metadata.py     # Async GitHub API label enrichment
|       |   `-- extract_test_prompt.py # YAML cookbook recipe prompt generation
|       |-- scip/
|       |   |-- ingest_codegraph.py    # SCIP protobuf -> Neo4j graph ingestion
|       |   `-- check_graph_status.py  # Neo4j health/status check
|       `-- rlm/
|           `-- analysis.py            # LLM-powered artifact analysis (GPT-4o via RLM)
|
|-- tests/
|   |-- test_build_tool.py             # Mocked Ninja build test
|   |-- test_tool_verifier.py          # FileCheck verifier pass/fail test
|   |-- test_mlir_bindings.py          # MLIR Python bindings exploration/demo
|   `-- manual_compiler_tool_config.py # Manual iree-compile integration test
|
|-- experiments/
|   |-- debug_info/                    # MLIR debug info dump experiments
|   |   |-- compile_and_print.sh       # Shell script to compile with debug flags
|   |   `-- input.mlir                 # Sample MLIR input
|   |-- lit_command/                   # LLVM LIT integration experiments
|   |   |-- opt_and_check.sh           # Shell script running mlir-opt + FileCheck
|   |   `-- input.mlir                 # Sample LIT test input
|   `-- iree_artifacts/                # IREE compilation artifact experiments
|       |-- compile_and_organize.sh    # Shell script to compile + dump all pass IR
|       |-- compile_test.sh            # Compilation test script
|       |-- example_onnx_fc.py         # ONNX fully-connected model export
|       |-- example_onnx_model.py      # ONNX model export for IREE ingestion
|       `-- test.mlir                  # Sample MLIR test input
|
|-- data/
|   |-- artifacts/                     # Runtime artifacts (compile outputs, provenance traces)
|   |   `-- provenance_trace.json      # ~6MB example provenance trace
|   `-- cookbook/                       # Mined cookbook recipes (LLVM_recipes subdir)
|       `-- (empty, recipes gitignored or stored externally)
|
|-- docs/
|   `-- neo4j_setup.md                 # Detailed Neo4j + LanceDB setup guide (no Docker/sudo)
|
`-- third_party/                       # External dependencies (git submodules or cloned repos)
    |-- CompilerGym/                   # OpenAI/Facebook compiler optimization gym
    |-- CompilerDream/                 # Compiler optimization research framework
    |-- CompilerAgentBench/            # Benchmarking suite for compiler agents
    |-- openevolve/                    # Evolutionary optimization framework
    |-- rlm/                           # Reliable Language Model library (RLM)
    |-- scip-clang/                    # C/C++ SCIP indexer (produces .scip protobuf indexes)
    |-- graphiti/                      # Knowledge graph construction library
    |-- lancedb/                       # Embedded vector database
    |-- langgraph/                     # LangChain graph-based agent orchestration
    `-- autocomp/                      # Automated compiler optimization
```

Note: All `third_party/` subdirectories are currently empty placeholders (submodule references or pending clones).

---

## 5. Third-Party Dependencies

| Dependency | Purpose |
|---|---|
| **CompilerGym** | OpenAI/Facebook reinforcement learning environment for compiler optimization. Provides standardized gym-style interface for compiler passes. |
| **CompilerDream** | Compiler optimization research framework. |
| **CompilerAgentBench** | Benchmark suite for evaluating AI agents on compiler tasks. |
| **openevolve** | Evolutionary optimization framework, likely used for evolving MLIR transformations. |
| **rlm** | Reliable Language Model library. Wraps OpenAI/other LLM backends with a clean API. Used in `analysis.py` for GPT-4o artifact analysis. |
| **scip-clang** | C/C++ SCIP indexer. Produces `.scip` protobuf index files that encode symbol definitions, references, and relationships for C++ codebases (like LLVM/IREE). |
| **graphiti** | Knowledge graph construction library for building and querying structured knowledge. |
| **lancedb** | Embedded columnar vector database. Configured in `Config.LANCEDB_DIR` for vector similarity search (likely for embedding-based code search). |
| **langgraph** | LangChain-based graph agent orchestration framework. Likely used for multi-step agent workflows. |
| **autocomp** | Automated compiler optimization tooling. |

Python library dependencies (from imports across the codebase):
- `pydriller` -- Git repository mining
- `aiohttp` -- Async HTTP for GitHub API
- `neo4j` -- Neo4j Python driver
- `tqdm` -- Progress bars
- `python-dotenv` -- `.env` file loading
- `protobuf` -- SCIP protobuf parsing (`scip_pb2`)
- `difflib` (stdlib) -- Text differencing for smart collapse
- `iree-compiler` or `mlir` -- MLIR Python bindings for structural provenance

---

## 6. Infrastructure: Neo4j Knowledge Graph

### Docker Setup (`docker-compose.yml`)
- **Image:** `neo4j:5.16.0`
- **Ports:** 7474 (HTTP browser), 7687 (Bolt protocol)
- **Plugins:** APOC (utility procedures) + Graph Data Science (PageRank, community detection)
- **Memory:** 1GB initial heap, 2GB max heap
- **Volumes:** Persistent data, logs, config, and plugins under `data/knowledge_base/neo4j/`

### User-Space Setup (`docs/neo4j_setup.md`)
- Alternative to Docker for servers without root/Docker access.
- Uses Conda for Java 17 and Python isolation.
- Manual Neo4j tarball installation + APOC plugin JAR.
- SSH port forwarding for remote access.

---

## 7. Commit History Summary

The repository has ~30 commits tracing a clear development arc:

### Phase 1: Early Experiments
- `99372f0` -- First experiment: dumping debug info from MLIR passes.
- `043c9ff` -- Simple experiment using LLVM LIT.
- `185e277` -- Creating IREE compilation artifacts with per-pass IR dumps.
- `ce2a58a` -- Tooling for reconstructing diffs for agents.

### Phase 2: Cookbook & Recipe Format
- `c420696` -- Simple dummy recipe example for teaching LLMs.
- `83e9081` -- New format for cookbook recipes.
- `5c05128` -- Gitignore updates.
- `6f314f5` -- Provenance artifact for future reference.

### Phase 3: Agent Tool Development
- `2569e50` -- **Build tool** (`build.py`) for Ninja/CMake.
- `41944d8` -- **Compile tool** (`compiler.py`) for iree-compile.
- `7c67d1b` -- **Trace provenance** tool (text-based, across long pass chains).
- `a11f86c` -- **Verifier** FileCheck tool.
- `ebcacf9` -- Pytest for the FileCheck verifier.
- `335b6d6` -- Reorganization of the trace provenance tool.

### Phase 4: Configuration & Infrastructure
- `522a9b7` -- Removed TODO.md, switched to Notion.
- `3042018` -- Added Neo4j/tree reference commands to README.
- `5f5ee95` -- Neo4j local setup guide.
- `5d7f7b4` -- Central `config.py` file.
- `5a016fe` -- Eliminated in-tree LLVM recipes.
- `543785f` -- Added external cookbook repo reference.

### Phase 5: Structural Provenance & MLIR Bindings
- `8c595cd` -- Full test of MLIR Python bindings with code modification and navigation.

### Phase 6: Mining Pipeline
- `bbf31b7` -- `mine_commits.py` implementation (PyDriller-based).
- `7ca9221` -- `enrich_metadata.py` (GitHub API label enrichment).
- `697feb8` -- Python script for fetching info from enriched PRs with manual LLM usage.
- `eaff678` -- First RLM test for fetching parsed information.

### Phase 7: Knowledge Graph & Neo4j
- `a4c6e80` -- Replacement for full-folder parsing of MLIR passes and phases.
- `0bcd041` -- Docker Compose for Neo4j with APOC + GDS.
- `74154a5` -- Fixed gitignore for artifacts.
- `4f76331` -- Option to check online Neo4j graph (node/edge counts).
- `8bcaabe` -- **First working prototype** of SCIP-to-Neo4j graph ingestion.

---

## 8. Role in the Agent Harness

mlirEvolve is **the core agent framework** itself. It is not a wrapper around an external agent -- it provides the foundational infrastructure for an AI system to work with compiler code:

1. **Action Layer (Tools):** The agent can build the compiler (`build.py`), compile MLIR programs (`compiler.py`), verify outputs (`verifier.py`), and trace how operations transform across passes (`provenance.py`, `trace_provenance.py`).

2. **Knowledge Layer (Mining + Graph):** The mining pipeline extracts proven code+test patterns from LLVM's 20+ year git history, enriches them with GitHub metadata, and formats them as structured recipes. The Neo4j knowledge graph provides structural code navigation (call graphs, class hierarchies, file-to-symbol mappings).

3. **Reasoning Layer (RLM Analysis):** The LLM-powered analysis module can examine compilation artifacts, use the provenance tools, and produce structured diagnoses of compilation failures or optimization opportunities.

4. **Data Layer (LanceDB + Artifacts):** Vector embeddings in LanceDB for similarity-based code/recipe search, plus persistent storage of compilation artifacts and provenance traces.

The design philosophy is **tool-augmented AI**: rather than giving an LLM raw compiler source and hoping for the best, mlirEvolve gives it structured tools that mirror how a human compiler engineer works -- build, compile, check, trace, and reference known patterns from history.
