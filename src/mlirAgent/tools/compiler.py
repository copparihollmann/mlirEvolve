import subprocess
import hashlib
import time
from pathlib import Path
from ..config import Config

def run_compile(mlir_content: str, flags: list = None) -> dict:
    """
    Executes iree-compile on the provided MLIR string.
    
    Returns:
        dict: {
            "success": bool,
            "returncode": int,
            "stdout": str,
            "stderr": str,
            "artifact_path": str (if successful)
        }
    """
    if flags is None:
        flags = []
        
    # 1. Save input to a temporary file
    content_hash = hashlib.md5(mlir_content.encode()).hexdigest()[:8]
    timestamp = int(time.time())
    filename = f"compile_{timestamp}_{content_hash}"
    
    input_path = Config.ARTIFACTS_DIR / f"{filename}.mlir"
    output_path = Config.ARTIFACTS_DIR / f"{filename}.vmfb"
    
    with open(input_path, "w") as f:
        f.write(mlir_content)
        
    # 2. Construct command
    cmd = [
        Config.IREE_COMPILE_PATH,
        str(input_path),
        "-o", str(output_path)
    ] + flags
    
    full_command_str = " ".join(cmd)

    # 3. Run safely
    try:
        start_time = time.time() 
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        duration = time.time() - start_time

        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "artifact_path": str(output_path) if result.returncode == 0 else None,
            "command": full_command_str,
            "duration_seconds": duration,
            "input_path": str(input_path)
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Error: Compilation timed out after 60 seconds.",
            "artifact_path": None,
            "command": full_command_str,
            "input_path": str(input_path)
        }