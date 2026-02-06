import os
import sys
from typing import List

# Allow running as a script without installation
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    try:
        from fastmcp import FastMCP
    except Exception as exc:
        raise ImportError(
            "MCP Python SDK is required to run the MCP server. "
            "Install with: pip install mcp"
        ) from exc

from mlirAgent.tools.build import run_build
from mlirAgent.tools.compiler import run_compile
from mlirAgent.tools.provenance import MLIRProvenanceTracer
from mlirAgent.tools.trace_provenance import trace_provenance
from mlirAgent.tools.verifier import verify_output

mcp = FastMCP("mlirEvolve")


def _error_result(message: str, command: str) -> dict:
    return {
        "success": False,
        "returncode": -1,
        "stdout": "",
        "stderr": message,
        "command": command,
    }


@mcp.tool
def build(target: str = "install", fast_mode: bool = False, clean: bool = False, reconfigure: bool = False) -> dict:
    """Run Ninja/CMake build using repo defaults."""
    try:
        return run_build(target=target, fast_mode=fast_mode, clean=clean, reconfigure=reconfigure)
    except Exception as exc:
        return _error_result(str(exc), "build")


@mcp.tool
def compile_mlir(mlir_text: str, flags: List[str] | None = None) -> dict:
    """Compile MLIR text with iree-compile."""
    try:
        return run_compile(mlir_text, flags=flags or [])
    except Exception as exc:
        return _error_result(str(exc), "compile_mlir")


@mcp.tool
def compile_mlir_file(path: str, flags: List[str] | None = None) -> dict:
    """Compile an MLIR file from disk with iree-compile."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            mlir_text = f.read()
        return run_compile(mlir_text, flags=flags or [])
    except Exception as exc:
        return _error_result(str(exc), "compile_mlir_file")


@mcp.tool
def verify_ir(ir_text: str, check_text: str) -> dict:
    """Run FileCheck against IR text."""
    try:
        return verify_output(ir_text, check_text)
    except Exception as exc:
        return _error_result(str(exc), "verify_ir")


@mcp.tool
def verify_ir_files(ir_path: str, check_path: str) -> dict:
    """Run FileCheck against IR/check files on disk."""
    try:
        with open(ir_path, "r", encoding="utf-8") as f:
            ir_text = f.read()
        with open(check_path, "r", encoding="utf-8") as f:
            check_text = f.read()
        return verify_output(ir_text, check_text)
    except Exception as exc:
        return _error_result(str(exc), "verify_ir_files")


@mcp.tool
def provenance_trace(artifacts_root: str, source_filename: str, line: int) -> dict:
    """Trace an MLIR op across pass history using bindings."""
    try:
        tracer = MLIRProvenanceTracer()
        return tracer.trace(artifacts_root, source_filename, line)
    except Exception as exc:
        return _error_result(str(exc), "provenance_trace")


@mcp.tool
def provenance_trace_text(artifacts_root: str, source_filename: str, line: int) -> dict:
    """Text-based provenance tracing fallback (no bindings)."""
    try:
        result_json = trace_provenance(artifacts_root, source_filename, line)
        return {"success": True, "result_json": result_json}
    except Exception as exc:
        return _error_result(str(exc), "provenance_trace_text")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
