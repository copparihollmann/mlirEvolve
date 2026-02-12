import os
import re
import subprocess
import optuna
from typing import Dict, Any
from openevolve.evaluation_result import EvaluationResult

class MagellanEvaluator:
    def __init__(self, llvm_build_dir, benchmark_script):
        self.build_dir = llvm_build_dir
        self.benchmark_script = benchmark_script

    def evaluate(self, code: str) -> EvaluationResult:
        # 1. Inject Code into LLVM Source
        self._inject_code(code)

        # 2. Compile LLVM (Incremental)
        # We only rebuild the relevant library to save time
        build_cmd = ["ninja", "-C", self.build_dir, "lib/Analysis/AEInlineAdvisor.o"]
        if subprocess.run(build_cmd).returncode != 0:
            return EvaluationResult(score=float('-inf'), error="Compilation Failed")
        
        # Link the final tool (e.g., opt or clang)
        subprocess.run(["ninja", "-C", self.build_dir, "bin/opt"])

        # 3. Inner Loop: Hyperparameter Tuning (The Magellan "Secret Sauce")
        # Extract params defined in the C++ comments
        params = self._extract_hyperparams(code) 
        
        if not params:
            # No params to tune, just run once
            score = self._run_benchmark({})
            return EvaluationResult(score=score)

        # Use Optuna to tune the exposed flags
        study = optuna.create_study(direction="maximize")
        study.optimize(lambda trial: self._objective(trial, params), n_trials=20)
        
        best_score = study.best_value
        best_params = study.best_params
        
        return EvaluationResult(
            score=best_score, 
            metadata={"tuned_params": best_params}
        )

    def _objective(self, trial, params_schema):
        # Map trial suggestions to LLVM flags
        # e.g., -ae-inline-base-threshold=255
        flags = []
        for name, type_, min_v, max_v in params_schema:
            val = trial.suggest_int(name, int(min_v), int(max_v))
            flags.append(f"-{name}={val}")
            
        return self._run_benchmark(flags)

    def _run_benchmark(self, flags):
        # Execute the benchmark script with the tuned flags
        cmd = [self.benchmark_script] + flags
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Parse output for binary size reduction or execution speed
        return self._parse_score(result.stdout)

    def _extract_hyperparams(self, code):
        # Regex to find lines like: // [hyperparam]: name, type, min, max
        pattern = r"//\s*\[hyperparam\]:\s*([\w-]+),\s*(\w+),\s*(\d+),\s*(\d+)"
        return re.findall(pattern, code)

    def _inject_code(self, code):
        target_path = "llvm-project/llvm/lib/Analysis/AEInlineAdvisor.cpp"
        with open(target_path, "w") as f:
            f.write(code)