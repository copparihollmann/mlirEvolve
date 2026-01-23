# Agentic Compiler Implementation Plan

## Phase 1: Proof of Concept (C++ Generation)
Goal: Verify the LLM can generate compiling C++ MLIR passes using local headers.

- [ ] **Setup Python Environment**
  - Create `requirements.txt`: `openai`, `langgraph`, `mlflow`.
  - Install dependencies.
  - Create `src/config.py` defining:
    - `LLVM_INCLUDE_DIR`: Path to `llvm-project/llvm/include`
    - `MLIR_INCLUDE_DIR`: Path to `llvm-project/mlir/include`
    - `CLANG_BIN`: Path to `clang++`

- [ ] **Create C++ Generation Script (`src/coder_agent.py`)**
  - Implement a simple loop (no LangGraph yet):
    1. Prompt LLM to write a `ZeroFoldPass.cpp` (fold `x + 0` -> `x`).
    2. Save output to disk.
    3. Run `clang++` using paths from `config.py`.
    4. Capture `stderr`.
  - Run the script and observe failure (missing headers).

- [ ] **Implement Context Injection**
  - Modify `src/coder_agent.py` to read `third_party/.../PatternMatch.h`.
  - Append header content to the System Prompt.
  - Re-run and verify the C++ file compiles successfully.

- [ ] **Test TableGen Generation**
  - Modify script to request a `.td` file for a custom Op.
  - Run `mlir-tblgen` on output.
  - If syntax errors occur, implement a basic `grep` fallback to find example Ops in `llvm-project`.

---

## Phase 2: Core Tooling (Porting Bash to Python)
Goal: Replace ad-hoc shell scripts with Python functions for the agent.

- [ ] **Compiler Wrapper (`src/tools/compiler.py`)**
  - Implement `run_compile(mlir_code, flags)`.
  - Wrap `subprocess.run` for `iree-compile`.
  - Return dictionary: `{'stdout': str, 'stderr': str, 'rc': int}`.

- [ ] **Verifier Wrapper (`src/tools/verifier.py`)**
  - Implement `verify_output(compiler_output, checks)`.
  - Pipe input string to `FileCheck` binary.
  - Return boolean success/failure.

- [ ] **Error Parser (`src/tools/parser.py`)**
  - Implement regex logic to extract the last ~3 lines of `stderr`.
  - Filter out generic noise to save tokens.

---

## Phase 3: Agent Logic (LangGraph)
Goal: Automate the compile-fix-verify loop.

- [ ] **Define State (`src/agent.py`)**
  - Create `AgentState` TypedDict: `ir_code`, `logs`, `metrics`, `history`.

- [ ] **Implement Graph Nodes**
  - `CandidateNode`: Queries LLM for next step/fix.
  - `CompilerNode`: Calls `tools.compiler.run_compile`.
  - `EvaluatorNode`: Calls `tools.verifier.verify_output`.

- [ ] **Define Edges**
  - If `CompilerNode` RC != 0 -> Loop back to `CandidateNode` with errors.
  - If `CompilerNode` RC == 0 -> Proceed to `EvaluatorNode`.

- [ ] **Add Logging**
  - Initialize MLflow in `agent.py`.
  - Log `exit_code` and `compile_time` in `CompilerNode`.

---

## Phase 4: Knowledge Base (RAG)
Goal: Scale context beyond manual header injection.

- [ ] **Ingest Manual Recipes**
  - Create `data/recipes/integer_fusion.yaml` (Problem/Solution pair).
  - Write `src/ingest_cookbook.py` to embed this into LanceDB.

- [ ] **Connect DB to Agent**
  - Modify `CandidateNode` to query LanceDB before prompting LLM.
  - Inject retrieved solution into prompt context.

---

## Phase 5: Interface
Goal: Interactive demo.

- [ ] **Chainlit Setup (`src/app.py`)**
  - Initialize LangGraph in `@cl.on_chat_start`.
  - Pass user input to graph in `@cl.on_message`.
  - Stream node execution status to UI.