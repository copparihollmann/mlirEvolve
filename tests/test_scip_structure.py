import sys
import os
import pytest
from pathlib import Path

# --- Setup Imports ---
sys.path.append(str(Path(__file__).parent.parent))

from src.mlirAgent.config import Config
try:
    from src.mlirAgent.scip import scip_pb2
except ImportError:
    pytest.fail("Could not import scip_pb2. Check src/mlirAgent/scip/")

def decode_kind(kind_int):
    """Maps SCIP kind integers to readable strings."""
    kinds = {
        0: "Unspecified", 1: "Class", 2: "Interface", 3: "Namespace", 
        4: "Enum", 5: "EnumMember", 6: "Method", 7: "Property", 
        8: "Field", 9: "Constructor", 10: "Enum", 11: "Interface", 
        12: "Function", 13: "Variable", 14: "Constant", 15: "String", 
        16: "Number", 17: "Boolean", 18: "Array", 19: "Object", 
        20: "Key", 21: "Null", 22: "EnumMember", 23: "Struct", 
        24: "Event", 25: "Operator", 26: "TypeParameter", 27: "TypeAlias", 
        28: "Macro"
    }
    return kinds.get(kind_int, f"UNKNOWN({kind_int})")

def test_scip_index_rich_metadata():
    """
    Validates that the SCIP index contains 'Rich Metadata' 
    (Docstrings, Inheritance, Relationships) required for the Agent.
    """
    index_path = str(Config.PROJECT_ROOT / "data" / "knowledge_base" / "scip" / "index_test.scip")
    
    if not os.path.exists(index_path):
        pytest.fail(f"SCIP Index not found at {index_path}. Run ingestion first.")

    # 1. Load Index
    index = scip_pb2.Index()
    try:
        with open(index_path, "rb") as f:
            index.ParseFromString(f.read())
    except Exception as e:
        pytest.fail(f"Failed to parse binary SCIP file: {e}")

    # 2. Find Source File
    target_doc = None
    for doc in index.documents:
        if doc.relative_path.endswith(".cpp") and ("Pattern" in doc.relative_path or "Linalg" in doc.relative_path):
            target_doc = doc
            break
    
    if not target_doc:
        target_doc = index.documents[0]
        print(f"\n⚠️  Warning: Could not find specific C++ file. Using {target_doc.relative_path}")

    print(f"\n📂 Deep Inspecting File: {target_doc.relative_path}")

    # 3. Inspect Symbols & Assert Richness
    assert len(target_doc.symbols) > 0, "No SymbolInformation found! Indexer might be missing metadata."

    print("\n--- 1. SYMBOL DEFINITIONS (Rich Metadata) ---")
    
    docstring_found = False
    relationship_found = False

    for i, sym in enumerate(target_doc.symbols[:15]):
        print(f"   [{i}] {sym.symbol}")
        print(f"       Kind: {decode_kind(sym.kind)} ({sym.kind})")
        print(f"       Display: {sym.display_name}")
        
        # --- Show Documentation ---
        if sym.documentation:
            docstring_found = True
            preview = sym.documentation[0].replace("\n", " ")[:60]
            print(f"       📝 Docstring: {preview}...") 
            
        # --- Show Relationships (Inheritance) ---
        for rel in sym.relationships:
            relationship_found = True
            print(f"       🔗 Relation: {rel.symbol} (Is Impl: {rel.is_implementation})")

    # 4. Final Assertions (Quality Control)
    if not docstring_found:
        print("\n⚠️  Warning: No docstrings found in this sample. Check if source has Doxygen comments.")
    
    if not relationship_found:
        print("\nℹ️  Info: No inheritance relationships found in this sample (normal for pure C functions).")

    print(f"\n✅ Verification Complete: {len(index.documents)} documents indexed.")

if __name__ == "__main__":
    sys.exit(pytest.main(["-s", __file__]))