import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- User Profile ---
# Set MERLIN_PROFILE=agustin or MERLIN_PROFILE=ashvin to switch paths.
# Defaults to auto-detect from the mlirEvolve repo location.
_PROFILES = {
    "agustin": {
        "merlin_root": "/scratch2/agustin/merlin",
        "build_dir": "/scratch2/agustin/merlin/build/vanilla/host/debug/iree-spacemit-3.10.0.dev",
    },
    "ashvin": {
        "merlin_root": "/scratch/ashvin/merlin",
        "build_dir": "/scratch/ashvin/merlin/build/vanilla/host/debug/iree-spacemit-3.10.0.dev",
    },
}

def _auto_detect_merlin_root():
    """Walk up from this file to find merlin root, with profile override."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def _get_profile():
    """Return the active profile dict based on MERLIN_PROFILE env var."""
    profile_name = os.getenv("MERLIN_PROFILE", "").lower()
    if profile_name in _PROFILES:
        return _PROFILES[profile_name]
    # Auto-detect: derive from repo location
    root = _auto_detect_merlin_root()
    return {"merlin_root": root, "build_dir": os.path.join(root, "build", "vanilla", "host", "debug", "iree-spacemit-3.10.0.dev")}

_profile = _get_profile()

class Config:
    # --- Source Paths ---
    # We need the source to run CMake!
    # Set MERLIN_PROFILE=agustin|ashvin or override individual env vars.
    _MERLIN_ROOT = os.getenv("MERLIN_ROOT", _profile["merlin_root"])
    IREE_SRC_PATH = os.getenv("IREE_SRC_PATH", os.path.join(_MERLIN_ROOT, "third_party", "iree_bar"))
    LLVM_SRC_PATH = os.getenv("LLVM_SRC_PATH", os.path.join(IREE_SRC_PATH, "third_party", "llvm-project"))

    # --- Build Paths ---
    BUILD_DIR = os.getenv("BUILD_DIR", _profile["build_dir"])
    INSTALL_DIR = os.path.join(BUILD_DIR, "install") # Derived from build dir
    
    # --- Binaries ---
    BUILD_LLVM_DIR = os.getenv("BUILD_LLVM_DIR", os.path.join(BUILD_DIR, "llvm-project"))
    LLVM_LIT_PATH = os.getenv("LLVM_LIT_PATH", os.path.join(BUILD_LLVM_DIR, "bin", "lit"))
    FILECHECK_PATH = os.getenv("FILECHECK_PATH", os.path.join(BUILD_LLVM_DIR, "bin", "FileCheck"))
    
    BUILD_TOOLS_DIR = os.getenv("BUILD_TOOLS_DIR", os.path.join(BUILD_DIR, "tools"))
    IREE_COMPILE_PATH = os.getenv("IREE_COMPILE_PATH", os.path.join(BUILD_TOOLS_DIR, "iree-compile"))
    
    # --- Evolve Harness ---
    EVOLVE_CONFIGS_DIR = os.getenv("EVOLVE_CONFIGS_DIR", os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "configs"))
    OPENEVOLVE_PATH = os.getenv("OPENEVOLVE_PATH", os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "third_party", "openevolve"))

    # --- Agent Data ---
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    ARTIFACTS_DIR = PROJECT_ROOT / "data" / "artifacts"
    RECIPES_DIR = PROJECT_ROOT / "data" / "cookbook" / "LLVM_recipes"
    
    # Neo4j Configuration
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    
    # LanceDB
    LANCEDB_DIR = PROJECT_ROOT / "data" / "lancedb"
    
    # --- .emv Variables ---
    # OpenAI API Key
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # Neo4j Credentials
    NEO4J_USER = os.getenv("NEO4J_USER")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    @classmethod
    def validate(cls):
        """Ensures the environment is set up correctly."""
        os.makedirs(cls.ARTIFACTS_DIR, exist_ok=True)

        if not os.path.exists(cls.IREE_SRC_PATH):
             print(f"⚠️  WARNING: Source path not found at {cls.IREE_SRC_PATH}. 'reconfigure=True' will fail.")

        ninja_file = os.path.join(cls.BUILD_DIR, "build.ninja")
        if not os.path.exists(ninja_file):
            print(f"⚠️  WARNING: No 'build.ninja' found. Agent must run `reconfigure=True`.")

# Run validation
Config.validate()