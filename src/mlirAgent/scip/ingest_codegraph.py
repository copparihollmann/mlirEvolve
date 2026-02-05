import sys
import os
import time
import re
from pathlib import Path
from neo4j import GraphDatabase


# [0] scip -> [1] mlirAgent -> [2] src -> [3] mlirEvolve (Root)
project_root = Path(__file__).resolve().parents[3]
sys.path.append(str(project_root))

from src.mlirAgent.config import Config
try:
    from src.mlirAgent.scip import scip_pb2
except ImportError:
    print("❌ Error: scip_pb2 not found. Check src/mlirAgent/scip/")
    sys.exit(1)

# SCIP Kind Mapping (Fallback if metadata ever appears)
KIND_TO_LABEL = {
    6: "METHOD", 12: "FUNCTION", 1: "CLASS_STRUCTURE", 23: "CLASS_STRUCTURE",
    28: "MACRO", 13: "VARIABLE", 3: "NAMESPACE"
}

class CodeGraphIngestor:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            Config.NEO4J_URI, 
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD)
        )
        self.scip_path = str(Config.PROJECT_ROOT / "data" / "knowledge_base" / "scip" / "index_test.scip")

    def close(self):
        self.driver.close()

    def load_index(self):
        print(f"📂 Loading SCIP Index from {self.scip_path}...")
        if not os.path.exists(self.scip_path):
            raise FileNotFoundError(f"Index not found at {self.scip_path}")
        index = scip_pb2.Index()
        with open(self.scip_path, "rb") as f:
            index.ParseFromString(f.read())
        return index

    def ingest_to_neo4j(self, index):
        total_docs = len(index.documents)
        print(f"💾 Ingesting {total_docs} documents (Strict Parsing Mode)...")
        
        with self.driver.session() as session:
            self._setup_schema(session)
            
            print("   • Starting Ingestion...")
            batch_nodes = []
            batch_rels = []
            batch_size = 2000
            start_time = time.time()
            
            for i, doc in enumerate(index.documents):

                # 1. Map Local Symbols
                symbol_meta = {}
                for sym in doc.symbols:
                    kind_label = self._classify_symbol(sym.symbol, sym.kind)
                    doc_text = sym.documentation[0] if sym.documentation else ""
                    symbol_meta[sym.symbol] = {"label": kind_label, "doc": doc_text}

                # 2. Create File Node
                batch_nodes.append({
                    "label": "FILE",
                    "props": {"path": doc.relative_path, "name": os.path.basename(doc.relative_path)}
                })

                # 3. Spatial Scan
                occurrences = sorted(doc.occurrences, key=lambda x: x.range[0])
                scope_stack = [{'id': doc.relative_path, 'label': 'FILE', 'end_line': 999999}]

                for occ in occurrences:
                    symbol_id = occ.symbol
                    is_def = (occ.symbol_roles & scip_pb2.SymbolRole.Definition)
                    
                    while len(scope_stack) > 1 and occ.range[0] > scope_stack[-1]['end_line']:
                        scope_stack.pop()
                    
                    parent = scope_stack[-1]

                    if is_def:
                        meta = symbol_meta.get(symbol_id, {})
                        label = meta.get("label") or self._classify_symbol(symbol_id, 0)
                        docstring = meta.get("doc", "")
                        end_line = occ.range[2] if len(occ.range) >= 3 else occ.range[0]
                        
                        batch_nodes.append({
                            "label": label,
                            "props": {
                                "id": symbol_id,
                                "name": self._extract_name(symbol_id),
                                "file_path": doc.relative_path,
                                "body_location": list(occ.range),
                                "docstring": docstring[:500] 
                            }
                        })

                        rel_type = "DEFINES"
                        if parent['label'] in ["CLASS_STRUCTURE", "NAMESPACE"]:
                            rel_type = "HAS_METHOD" if label == "METHOD" else "HAS_NESTED"
                        
                        batch_rels.append({
                            "source_label": parent['label'], "source_id": parent['id'],
                            "target_label": label, "target_id": symbol_id,
                            "rel_type": rel_type
                        })
                        scope_stack.append({'id': symbol_id, 'label': label, 'end_line': end_line})

                    else:
                        if parent['label'] in ["FUNCTION", "METHOD"]:
                            batch_rels.append({
                                "source_label": parent['label'], "source_id": parent['id'],
                                "target_label": "Symbol", 
                                "target_id": symbol_id,
                                "rel_type": "CALLS"
                            })

                # 4. Commit Batch 
                if len(batch_nodes) >= batch_size or i == total_docs - 1:
                    self._commit_batch(session, batch_nodes, batch_rels)
                    
                    # Print every time we commit a batch
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    print(f"   • Batch Committed at File {i+1}/{total_docs} ({rate:.1f} files/sec)")
                    
                    batch_nodes = []
                    batch_rels = []

        print("🎉 Knowledge Graph Hydrated & Connected!")

    def _classify_symbol(self, symbol_id, kind_int):
        """
        Parses SCIP Symbol Grammar because Kind is 0.
        """
        if kind_int and kind_int > 0:
            return KIND_TO_LABEL.get(kind_int, "Symbol")
        
        # --- Strict SCIP String Parser ---
        
        if symbol_id.endswith("."):
            # It is a Term (Value, Function, Method)
            # Check Parent to distinguish Method vs Function
            if self._has_type_parent(symbol_id):
                return "METHOD"
            return "FUNCTION"
            
        if symbol_id.endswith("#"):
            return "CLASS_STRUCTURE" # Type
            
        if symbol_id.endswith("!"):
            return "MACRO"
            
        if symbol_id.endswith("/"):
            return "NAMESPACE"
            
        return "Symbol" # Unknown/Generic

    def _has_type_parent(self, symbol_id):
        """
        Parses the string: `.../Class#method.` -> Parent is Type (#) -> Method
        Parses the string: `.../namespace/func.` -> Parent is Namespace (/) -> Function
        """
        # Remove trailing dot
        base = symbol_id[:-1] 
        
        if "#" in base:
            # Check if the # is closer to the end than any /
            # This handles nested classes in namespaces correctly
            last_hash = base.rfind("#")
            last_slash = base.rfind("/")
            if last_hash > last_slash:
                return True 
        return False

    def _extract_name(self, symbol):
        # cxx...#match(ID). -> match
        parts = re.split(r'[#/.](?=[^#/.]+$)', symbol)
        name = parts[-1]
        name = name.split("(")[0]
        return name.strip(".$!#")

    def _setup_schema(self, session):
        for label in ["FILE", "FUNCTION", "CLASS_STRUCTURE", "NAMESPACE", "METHOD", "Symbol"]:
            key = "path" if label == "FILE" else "id"
            session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")

    def _commit_batch(self, session, nodes, rels):
        # Merge Nodes
        nodes_by_label = {}
        for n in nodes:
            nodes_by_label.setdefault(n['label'], []).append(n['props'])
            
        for label, props in nodes_by_label.items():
            key = "path" if label == "FILE" else "id"
            session.run(f"""
            UNWIND $batch AS row
            MERGE (n:{label} {{{key}: row.{key}}})
            SET n += row
            """, batch=props)

        # Merge Edges
        rels_by_type = {}
        for r in rels:
            rels_by_type.setdefault(r['rel_type'], []).append(r)

        for rel_type, batch in rels_by_type.items():
            session.run(f"""
            UNWIND $batch AS row
            MATCH (source) WHERE (labels(source)[0] = row.source_label OR row.source_label = 'Symbol') 
                           AND (source.id = row.source_id OR source.path = row.source_id)
            MATCH (target) WHERE (labels(target)[0] = row.target_label OR row.target_label = 'Symbol') 
                           AND target.id = row.target_id
            MERGE (source)-[:{rel_type}]->(target)
            """, batch=batch)

if __name__ == "__main__":
    ingestor = CodeGraphIngestor()
    ingestor.ingest_to_neo4j(ingestor.load_index())
    ingestor.close()