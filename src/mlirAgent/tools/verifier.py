import subprocess
import tempfile
import os
from typing import Dict
from ..config import Config

def verify_output(output_ir: str, check_content: str) -> Dict[str, any]:
    """
    Pipes 'output_ir' into FileCheck, validating it against 'check_content'.
    
    Args:
        output_ir (str): The stdout from the compiler (the IR to verify).
        check_content (str): The expected pattern (e.g., "// CHECK: linalg.matmul").
        
    Returns:
        dict: {
            "success": bool,
            "stdout": str,
            "stderr": str
        }
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.mlir', delete=False) as tmp_check:
        tmp_check.write(check_content)
        tmp_check_path = tmp_check.name

    try:
        # Command: FileCheck <check_file> --input-file=<input_stream>
        
        cmd = [Config.FILECHECK_PATH, tmp_check_path]
        
        process = subprocess.run(
            cmd,
            input=output_ir,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        return {
            "success": process.returncode == 0,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "command": f"FileCheck {tmp_check_path}"
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Verification timed out.",
            "command": "FileCheck"
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"FileCheck binary not found at {Config.FILECHECK_PATH}",
            "command": "FileCheck"
        }
    finally:
        # Cleanup
        if os.path.exists(tmp_check_path):
            os.remove(tmp_check_path)