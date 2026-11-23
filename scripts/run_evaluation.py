"""Pass bundle settings into the shared evaluation runner on serverless Jobs."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

def project_root(script_file, argv0):
    """Jobs may execute the script without defining Python's __file__ variable."""
    for location in (script_file, argv0):
        if not location or location in {"-", "-c"}:
            continue
        root = Path(location).resolve().parent.parent
        if (root / "evaluation" / "runner.py").is_file() and (root / "src" / "rag").is_dir():
            return root
    raise RuntimeError(
        "Cannot find the deployed evaluation source. Run scripts/run_evaluation.py "
        "from the bundle's workspace files so its script path is available in sys.argv[0]."
    )


ROOT = project_root(globals().get("__file__"), sys.argv[0] if sys.argv else None)
sys.path.insert(0, str(ROOT))


def main():
    print("Evaluation job: reading deployment settings.", flush=True)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["agent-endpoint", "judge-endpoint", "index", "experiment-id", "warehouse-id"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--limit", type=int, default=0,
                        help="Smoke test: first N questions. Zero runs the full benchmark.")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit cannot be negative; use zero for the full benchmark.")
    os.environ.update({
        "AGENT_ENDPOINT": args.agent_endpoint,
        "JUDGE_ENDPOINT": args.judge_endpoint,
        "VECTOR_SEARCH_INDEX": args.index,
        "MLFLOW_EXPERIMENT_ID": args.experiment_id,
        "MLFLOW_TRACING_SQL_WAREHOUSE_ID": args.warehouse_id,
        "USE_AI_GATEWAY": "true",
    })
    os.chdir(ROOT)
    print("Evaluation job: importing the shared evaluation runner.", flush=True)
    from evaluation.runner import main as evaluate
    # Workspace source files can be read-only on Jobs. MLflow artifacts are the
    # durable output; use the worker's temporary disk for intermediate reports.
    with tempfile.TemporaryDirectory(prefix="pdf-rag-evaluation-") as output_dir:
        print("Evaluation job: starting evaluation; reports will be saved as MLflow artifacts.", flush=True)
        runner_args = ["--output-dir", output_dir]
        if args.limit > 0:
            runner_args.extend(["--limit", str(args.limit)])
        evaluate(runner_args)


if __name__ == "__main__":
    main()
