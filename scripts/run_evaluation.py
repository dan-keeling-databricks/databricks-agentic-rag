"""Pass bundle settings into the shared evaluation runner on serverless Jobs."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["agent-endpoint", "judge-endpoint", "index", "experiment-id", "warehouse-id"]:
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    os.environ.update({
        "AGENT_ENDPOINT": args.agent_endpoint,
        "JUDGE_ENDPOINT": args.judge_endpoint,
        "VECTOR_SEARCH_INDEX": args.index,
        "MLFLOW_EXPERIMENT_ID": args.experiment_id,
        "MLFLOW_TRACING_SQL_WAREHOUSE_ID": args.warehouse_id,
        "USE_AI_GATEWAY": "true",
    })
    os.chdir(ROOT)
    from evaluation.runner import main as evaluate
    # Workspace source files can be read-only on Jobs. MLflow artifacts are the
    # durable output; use the worker's temporary disk for intermediate reports.
    with tempfile.TemporaryDirectory(prefix="pdf-rag-evaluation-") as output_dir:
        evaluate(["--output-dir", output_dir])


if __name__ == "__main__":
    main()
