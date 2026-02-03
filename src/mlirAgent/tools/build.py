import subprocess
import re
import os
import sys
import shutil
from typing import Dict
from ..config import Config

def run_build(target: str = "install", 
              fast_mode: bool = False, 
              clean: bool = False, 
              reconfigure: bool = False) -> Dict[str, any]:
    """
    Executes the build process using Ninja.
    """
    build_dir = Config.BUILD_DIR
    
    # --- MODE 1: Reconfigure (CMake) ---
    if reconfigure:
        print("🔄 Agent initiating full CMake configuration...")
        
        # Optional: Clean install dir like your script does
        if os.path.exists(Config.INSTALL_DIR):
            shutil.rmtree(Config.INSTALL_DIR)
            
        return _run_cmake()

    # --- MODE 2: Ninja Build ---
    if clean:
        print("Cc Cleaning build directory...")
        subprocess.run(["ninja", "-C", str(build_dir), "-t", "clean"], check=False)

    if fast_mode:
        targets = ["llvm-tblgen", "llc", "FileCheck", "intrinsics_gen"]
    else:
        targets = target.split()

    cmd = ["ninja", "-C", str(build_dir)] + targets
    print(f"🔨 Agent executing build: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1200
        )
        return _format_result(result, " ".join(cmd))

    except subprocess.TimeoutExpired:
        return _format_timeout(" ".join(cmd))
    except FileNotFoundError:
        return _format_error("Ninja binary not found.", " ".join(cmd))


def _run_cmake() -> Dict[str, any]:
    """
    Runs the CMake configuration command.
    This logic is ported directly from your bash script.
    """
    os.makedirs(Config.BUILD_DIR, exist_ok=True)
    
    cmake_flags = [
        "-G", "Ninja",
        "-B", Config.BUILD_DIR,
        "-S", Config.IREE_SRC_PATH,
        f"-DCMAKE_INSTALL_PREFIX={Config.INSTALL_DIR}",
        "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
        "-DCMAKE_CXX_FLAGS=-Wno-error=cpp -Wno-error=maybe-uninitialized -fno-omit-frame-pointer -fdebug-types-section",
        "-DCMAKE_C_FLAGS=-fno-omit-frame-pointer -fdebug-types-section",
        "-DIREE_ENABLE_LLD=ON",
        f"-DPython3_EXECUTABLE={sys.executable}",
        "-DIREE_ENABLE_RUNTIME_TRACING=OFF",
        "-DIREE_ENABLE_COMPILER_TRACING=OFF",
        "-DIREE_BUILD_SAMPLES=OFF",
        "-DIREE_TARGET_BACKEND_DEFAULTS=OFF",
        "-DIREE_TARGET_BACKEND_LLVM_CPU=ON",
        "-DIREE_HAL_DRIVER_DEFAULTS=OFF",
        "-DIREE_HAL_DRIVER_LOCAL_SYNC=ON",
        "-DIREE_HAL_DRIVER_LOCAL_TASK=ON",
        "-DIREE_BUILD_PYTHON_BINDINGS=OFF",
        "-DIREE_ENABLE_ASSERTIONS=ON",
        "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        "-DIREE_ENABLE_ASAN=OFF"
    ]
    
    cmd = ["cmake"] + cmake_flags
    print(f"⚙️ Running CMake: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600 # 10 mins for config
        )
        return _format_result(result, "cmake configuration")
    except Exception as e:
        return _format_error(f"CMake failed: {str(e)}", "cmake")


def _format_result(result, cmd):
    success = (result.returncode == 0)
    error_summary = ""
    if not success:
        error_summary = _extract_error_summary(result.stdout, result.stderr)
        
    return {
        "success": success,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_summary": error_summary,
        "command": cmd
    }

def _format_timeout(cmd):
    return {
        "success": False,
        "returncode": -1,
        "stdout": "",
        "stderr": "Command timed out.",
        "error_summary": "Timeout.",
        "command": cmd
    }

def _format_error(msg, cmd):
    return {
        "success": False,
        "returncode": -1,
        "stdout": "",
        "stderr": msg,
        "error_summary": msg,
        "command": cmd
    }

def _extract_error_summary(stdout: str, stderr: str) -> str:
    full_log = stdout + "\n" + stderr
    error_patterns = [r"(error:.*?^)", r"(FAILED:.*?^)", r"(CMake Error.*?^)"]
    matches = []
    for pattern in error_patterns:
        found = re.findall(pattern, full_log, re.MULTILINE | re.DOTALL)
        if found: matches.extend(found[-5:])
    if matches: return "\n...\n".join(matches).strip()
    return "Command failed. Check full logs."