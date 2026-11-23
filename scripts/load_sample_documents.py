"""Download the pinned public PDF sample and optionally upload it to a UC volume.

Run `python scripts/load_sample_documents.py --help` for examples and options.
No credentials are needed for downloading public sample files.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = "databricks-demos/dbdemos-dataset"
REVISION = "1a8743c8fe783b3ac42ab37aa18118387fb3c996"
CORPUS_PATH = "llm/databricks-pdf-documentation"
SOURCE_URL = f"https://github.com/{REPOSITORY}/tree/{REVISION}/{CORPUS_PATH}"


def download_bytes(url):
    request = Request(url, headers={"User-Agent": "databricks-agentic-rag-reference"})
    with urlopen(request, timeout=120) as response:
        return response.read()


def fetch_sample(output_dir, only=None):
    """Save PDFs, the upstream notice, and a manifest with content hashes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    listing_url = f"https://api.github.com/repos/{REPOSITORY}/contents/{CORPUS_PATH}?ref={REVISION}"
    entries = json.loads(download_bytes(listing_url))
    selected = [e for e in entries if e["type"] == "file" and e["name"].lower().endswith(".pdf")]
    if only:
        requested = set(only)
        unknown = requested - {e["name"] for e in selected}
        if unknown:
            raise ValueError(f"Unknown sample filenames: {sorted(unknown)}")
        selected = [e for e in selected if e["name"] in requested]
    notice = next(e for e in entries if e["name"] == "NOTICE")

    def fetch(entry):
        name = entry["name"]
        # The listing is public, but allow only plain filenames in the output directory.
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError(f"Unsafe sample filename: {name}")
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{CORPUS_PATH}/{quote(name)}"
        data = download_bytes(url)
        blob_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if blob_hash != entry["sha"]:
            raise ValueError(f"Git content hash mismatch for {name}")
        if name.lower().endswith(".pdf") and not data.startswith(b"%PDF-"):
            raise ValueError(f"Downloaded content is not a PDF: {name}")
        destination = output_dir / name
        destination.write_bytes(data)
        return {
            "filename": name, "source_url": url, "size_bytes": len(data),
            "git_blob_sha": blob_hash, "sha256": hashlib.sha256(data).hexdigest(),
        }

    with ThreadPoolExecutor(max_workers=4) as executor:
        documents = list(executor.map(fetch, selected))
    notice_record = fetch(notice)
    manifest = {
        "repository": REPOSITORY, "revision": REVISION, "source_url": SOURCE_URL,
        "documents": sorted(documents, key=lambda item: item["filename"]),
        "notice": notice_record,
    }
    (output_dir / "sample_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def upload_sample(output_dir, manifest, volume, profile=None, use_mounted_volume=False):
    """Use the mounted volume in jobs, or the SDK with an explicit local profile."""
    if not volume.startswith("/Volumes/") or len(volume.strip("/").split("/")) < 4:
        raise ValueError("--volume must be /Volumes/<catalog>/<schema>/<volume>[/folder]")
    filenames = [d["filename"] for d in manifest["documents"]] + ["NOTICE", "sample_manifest.json"]
    if use_mounted_volume:
        destination = Path(volume)
        destination.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            target = destination / name
            source = output_dir / name
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
                    raise ValueError(f"Refusing to replace a different file: {target}")
                continue
            shutil.copyfile(source, target)
        return
    if not profile:
        raise ValueError("Supply --profile when uploading from a local computer")
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound

    workspace = WorkspaceClient(profile=profile)
    workspace.files.create_directory(volume)
    for name in filenames:
        target = volume.rstrip("/") + "/" + name
        source = output_dir / name
        try:
            existing = workspace.files.download(target).contents.read()
        except NotFound:
            existing = None
        if existing is not None:
            if hashlib.sha256(existing).digest() != hashlib.sha256(source.read_bytes()).digest():
                raise ValueError(f"Refusing to replace a different file: {target}")
            continue
        with source.open("rb") as contents:
            workspace.files.upload(target, contents, overwrite=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(tempfile.gettempdir()) / "agentic-rag-sample")
    parser.add_argument("--volume", help="Optional existing /Volumes/catalog/schema/volume[/folder] destination")
    parser.add_argument("--profile", help="Explicit Databricks CLI profile for local SDK uploads")
    parser.add_argument("--use-mounted-volume", action="store_true", help="Use the /Volumes mount in a Databricks job instead of local SDK upload")
    parser.add_argument("--only", nargs="+", help="Optional exact PDF filenames; omit to download all 29 PDFs")
    args = parser.parse_args()
    manifest = fetch_sample(args.output_dir, args.only)
    if args.volume:
        upload_sample(args.output_dir, manifest, args.volume, args.profile, args.use_mounted_volume)
    print(json.dumps({"documents": len(manifest["documents"]), "revision": REVISION,
                      "local_directory": str(args.output_dir), "volume": args.volume}, indent=2))


if __name__ == "__main__":
    main()
