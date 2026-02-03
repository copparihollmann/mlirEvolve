from mlirAgent.tools.compiler import run_compile
import os

def test_compiler_execution():
    dummy_mlir = """
    module {
      func.func @test(%arg0: i32) -> i32 {
        return %arg0 : i32
      }
    }
    """

    print("Testing Compiler Tool...")
    result = run_compile(dummy_mlir, flags=["--iree-hal-target-backends=vmvx"])

    # Assertions make it a real test
    assert result['success'], f"Compilation failed: {result['stderr']}"
    assert os.path.exists(result['artifact_path']), "Artifact file was not created"
    
    print(f"✅ Success! Artifact at: {result['artifact_path']}")