# File: src/mlirAgent/rlm/analysis.py
import os
import json
from typing import Dict, Any
from rlm import RLM
from src.mlirAgent.config import Config

class LogAnalysisAgent:
    def __init__(self, model_name: str = "gpt-4o"):
        self.api_key = Config.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in Config.")

        print(f"🤖 Initializing RLM Agent (Trace Aware) with model: {model_name}...")
        self.rlm = RLM(
            backend="openai",
            backend_kwargs={
                "model_name": model_name,
                "api_key": self.api_key,
                "temperature": 0.1 
            },
            verbose=True
        )

    def analyze_compiler_artifacts(self, artifacts_path: str, query: str) -> Dict[str, Any]:
        """
        Uses RLM to analyze a massive folder of compiler artifacts (MLIR pass history).
        """
        if not os.path.exists(artifacts_path):
            return {"error": f"Artifacts path not found: {artifacts_path}"}

        # We inject the Provenance Logic into the prompt instructions
        prompt = f"""
        You are an Expert MLIR Compiler Engineer with access to a Python REPL.
        
        CONTEXT:
        You are investigating a compilation output in: '{artifacts_path}'
        This directory contains a subfolder 'ir_pass_history' with hundreds of .mlir files.
        
        USER QUERY: "{query}"
        
        YOUR TOOLBOX:
        You have access to the `src.mlirAgent.tools.provenance` module.
        
        TASK:
        1. Import the provenance tool:
           `from src.mlirAgent.tools.provenance import MLIRProvenanceTracer`
        2. Instantiate it: `tracer = MLIRProvenanceTracer()`
        3. If the user asks about a specific file/line (e.g. "input.mlir:37"), use `tracer.trace(...)`.
        4. If the user asks about a general error, scan the directory for the latest file or use standard python to grep.
        
        GOAL:
        Return a JSON object describing what happened.
        Example:
        {{
            "root_cause_pass": "19_iree-global-opt-expand-tensor-shapes.mlir",
            "explanation": "The tensor shape expanded from 16x128 to 16x32, causing a mismatch.",
            "evidence": "Code snippet..."
        }}
        """

        print(f"🕵️  RLM starting artifact analysis on {artifacts_path}...")
        
        try:
            result = self.rlm.completion(prompt)
            clean_text = result.response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        except Exception as e:
            return {"error": str(e), "raw_output": getattr(result, "response", "")}

# Singleton
log_analyzer = LogAnalysisAgent()