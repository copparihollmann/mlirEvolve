import pytest
from mlirAgent.tools.verifier import verify_output

def test_verifier_logic():
    """
    Validates that the FileCheck wrapper correctly identifies matching
    and non-matching IR.
    """
    print("\n[Test] Running Verifier Tool check...")
    
    ir_code = """
    module {
      func.func @test_function() {
        return
      }
    }
    """

    # --- Test 1: Should Pass ---
    checks_pass = "// CHECK: func.func @test_function"
    result_pass = verify_output(ir_code, checks_pass)
    
    assert result_pass['success'] is True, \
        f"Verifier failed on valid input.\nStderr: {result_pass.get('stderr')}"

    # --- Test 2: Should Fail ---
    checks_fail = "// CHECK: func.func @non_existent_function"
    result_fail = verify_output(ir_code, checks_fail)
    
    assert result_fail['success'] is False, \
        "Verifier succeeded on invalid input (False Positive)."
    
    assert "error:" in result_fail['stderr'], \
        "Verifier failed but produced no standard error output."

    print("✅ Verifier logic confirmed.")