import pytest
from unittest.mock import patch, MagicMock
from mlirAgent.tools.build import run_build

@patch('mlirAgent.tools.build.subprocess.run')
def test_clean_build_logic(mock_subprocess):
    """
    Verifies that setting clean=True triggers the correct ninja clean command.
    We MOCK the subprocess so we don't actually wipe your drive.
    """
    mock_response = MagicMock()
    mock_response.returncode = 0
    mock_response.stdout = "Clean successful"
    mock_response.stderr = ""
    mock_subprocess.return_value = mock_response

    print("\n[Test] Verifying clean command generation (Mocked)...")
    
    result = run_build(fast_mode=True, clean=True)

    # Assertions
    assert result['success'] is True
    
    was_clean_called = False
    for call in mock_subprocess.call_args_list:
        args = call[0][0]
        if "-t" in args and "clean" in args:
            was_clean_called = True
            print(f"   Found expected command: {' '.join(args)}")
            
    assert was_clean_called, "The 'ninja -t clean' command was never executed!"