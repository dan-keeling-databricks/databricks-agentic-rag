"""Deploy the reference, load example PDFs, refresh search, and start the app.

Credentials stay with the Databricks CLI and SDK; this script never handles a
token. Re-running uses the same bundle state and skips already-uploaded PDFs.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import PermissionsChange, Privilege, SecurableType

ROOT = Path(__file__).resolve().parents[1]


def cli(profile, *arguments, capture=False):
    result = subprocess.run(
        ["databricks", *arguments, "--profile", profile], cwd=ROOT, text=True,
        stdout=subprocess.PIPE if capture else None, check=True,
    )
    return result.stdout if capture else None


def grant(workspace, kind, name, principal, privileges):
    workspace.grants.update(
        securable_type=kind, full_name=name,
        changes=[PermissionsChange(principal=principal, add=privileges)],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--schema", default="agentic_rag")
    parser.add_argument("--app-name", default="agentic-pdf-rag")
    parser.add_argument("--search-endpoint", default="agentic-pdf-rag-search")
    parser.add_argument("--skip-sample-data", action="store_true")
    args = parser.parse_args()
    variables = {"catalog": args.catalog, "schema": args.schema,
                 "warehouse_id": args.warehouse_id, "app_name": args.app_name,
                 "search_endpoint": args.search_endpoint}
    location = ROOT / ".databricks/bundle/demo/variable-overrides.json"
    location.parent.mkdir(parents=True, exist_ok=True)
    # Preserve advanced model/channel settings chosen by the deployer.
    previous = json.loads(location.read_text()) if location.exists() else {}
    location.write_text(json.dumps(previous | variables, indent=2) + "\n")
    workspace = WorkspaceClient(profile=args.profile)
    print(f"Deploying to {workspace.config.host}, catalog {args.catalog}, schema {args.schema}", flush=True)
    preview = workspace.workspace_settings_v2.get_public_workspace_setting("ai_prep_search")
    if not preview.effective_boolean_val or not preview.effective_boolean_val.value:
        raise RuntimeError(
            "AI Prep Search Preview is disabled. Ask a workspace admin to enable AI Prep Search "
            "in Settings > Previews, then rerun setup. No document processing has been started."
        )
    cli(args.profile, "bundle", "validate", "--strict", "-t", "demo")
    cli(args.profile, "bundle", "deploy", "-t", "demo", "--auto-approve")

    volume = f"/Volumes/{args.catalog}/{args.schema}/source_documents"
    if not args.skip_sample_data:
        subprocess.run([sys.executable, str(ROOT / "scripts/load_sample_documents.py"),
                        "--profile", args.profile, "--volume", volume], cwd=ROOT, check=True)
    cli(args.profile, "bundle", "run", "ingest_documents", "-t", "demo")

    # The index cannot be attached at app creation because its source pipeline
    # has not run yet. Grant this one index after the ingestion job creates it.
    app = workspace.apps.get(args.app_name)
    principal = app.service_principal_client_id
    grant(workspace, SecurableType.CATALOG, args.catalog, principal, [Privilege.USE_CATALOG])
    grant(workspace, SecurableType.SCHEMA, f"{args.catalog}.{args.schema}", principal, [Privilege.USE_SCHEMA])
    grant(workspace, SecurableType.TABLE, f"{args.catalog}.{args.schema}.document_index", principal, [Privilege.SELECT])
    grant(workspace, SecurableType.SCHEMA, f"{args.catalog}.{args.schema}_traces", principal,
          [Privilege.USE_SCHEMA, Privilege.SELECT, Privilege.MODIFY])
    cli(args.profile, "bundle", "run", "rag", "-t", "demo")
    summary = json.loads(cli(args.profile, "bundle", "summary", "-t", "demo", "-o", "json", capture=True))
    destination = ROOT / ".local/deployment.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    app = workspace.apps.get(args.app_name)
    print(f"App: {app.url}\nSaved deployment links to {destination}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError:
        raise SystemExit("Setup stopped because a Databricks command failed. Read the error above, fix it, and rerun the same setup command.")
    except RuntimeError as error:
        raise SystemExit(str(error))
