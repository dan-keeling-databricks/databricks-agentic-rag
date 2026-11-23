"""Browser links derived from this deployment's host and resource identifiers."""

from urllib.parse import quote


def workspace_url(host):
    """Apps may provide DATABRICKS_HOST as a hostname rather than a URL."""
    host = host.strip().rstrip("/")
    if host and "://" not in host:
        host = "https://" + host.removeprefix("//")
    return host


def trace_url(host, experiment_id, trace_id):
    if not host or not experiment_id or not trace_id:
        return ""
    return f"{workspace_url(host)}/ml/experiments/{quote(str(experiment_id), safe='')}/traces/{quote(trace_id.rsplit('/', 1)[-1], safe='')}"


def architecture_links(host, settings):
    host = workspace_url(host)
    catalog, schema, index = settings.vector_search_index.split(".")
    base = f"{host}/explore/data/{quote(catalog, safe='')}/{quote(schema, safe='')}"
    links = {
        "Prepared documents and processing status": base,
        "Search-ready chunks": f"{base}/document_chunks",
        "AI Search index": f"{base}/{quote(index, safe='')}",
    }
    if settings.source_volume:
        volume_parts = settings.source_volume.removeprefix("/Volumes/").replace(".", "/").strip("/").split("/")
        if len(volume_parts) >= 3:
            c, s, v = (quote(p, safe="") for p in volume_parts[:3])
            links["PDF landing volume"] = f"{host}/explore/data/volumes/{c}/{s}/{v}"
    if settings.pipeline_id:
        links["Document processing pipeline"] = f"{host}/pipelines/{quote(settings.pipeline_id, safe='')}"
    if settings.ingestion_job_id:
        links["Ingestion and index update job"] = f"{host}/jobs/{quote(settings.ingestion_job_id, safe='')}"
    if settings.evaluation_job_id:
        links["Benchmark evaluation job"] = f"{host}/jobs/{quote(settings.evaluation_job_id, safe='')}"
    if settings.mlflow_experiment_id:
        links["MLflow traces and evaluation results"] = f"{host}/ml/experiments/{quote(settings.mlflow_experiment_id, safe='')}"
    if settings.use_ai_gateway and len(settings.agent_endpoint.split(".")) == 3:
        model_catalog, model_schema, _ = settings.agent_endpoint.split(".")
        # Model services are visible inside their UC schema. Do not guess a
        # workspace-version-specific AI Gateway detail-page URL.
        links[f"Agent model service: {settings.agent_endpoint} (open schema)"] = (
            f"{host}/explore/data/{quote(model_catalog, safe='')}/{quote(model_schema, safe='')}"
        )
    else:
        links["Answer model endpoint"] = f"{host}/ml/endpoints/{quote(settings.agent_endpoint, safe='')}"
    if settings.repository_url:
        links["Source code and deployment guide"] = settings.repository_url
    return links
