"""Small, environment-based configuration shared by the app and evaluation job."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    agent_endpoint: str
    vector_search_index: str
    mlflow_experiment_id: str = ""
    judge_endpoint: str = ""
    ai_gateway_base_url: str = ""
    use_ai_gateway: bool = True
    max_searches: int = 3
    retrieval_k: int = 6
    max_context_characters: int = 48000
    max_history_messages: int = 12
    source_volume: str = ""
    pipeline_id: str = ""
    ingestion_job_id: str = ""
    evaluation_job_id: str = ""
    repository_url: str = ""

    def __post_init__(self):
        if not self.agent_endpoint or len(self.vector_search_index.split(".")) != 3:
            raise ValueError("Set AGENT_ENDPOINT and VECTOR_SEARCH_INDEX (catalog.schema.index).")
        if not 1 <= self.max_searches <= 10:
            raise ValueError("MAX_SEARCHES must be between 1 and 10.")
        if not 1 <= self.retrieval_k <= 50:
            raise ValueError("RETRIEVAL_K must be between 1 and 50.")
        if self.max_context_characters < 1000 or self.max_history_messages < 0:
            raise ValueError("Context must allow at least 1,000 characters; history cannot be negative.")

    @classmethod
    def from_env(cls):
        return cls(
            agent_endpoint=os.getenv("AGENT_ENDPOINT", ""),
            vector_search_index=os.getenv("VECTOR_SEARCH_INDEX", ""),
            mlflow_experiment_id=os.getenv("MLFLOW_EXPERIMENT_ID", ""),
            judge_endpoint=os.getenv("JUDGE_ENDPOINT", os.getenv("AGENT_ENDPOINT", "")),
            ai_gateway_base_url=os.getenv("AI_GATEWAY_BASE_URL", ""),
            use_ai_gateway=os.getenv("USE_AI_GATEWAY", "true").lower() == "true",
            max_searches=int(os.getenv("MAX_SEARCHES", "3")),
            retrieval_k=int(os.getenv("RETRIEVAL_K", "6")),
            max_context_characters=int(os.getenv("MAX_CONTEXT_CHARACTERS", "48000")),
            max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "12")),
            source_volume=os.getenv("SOURCE_VOLUME", ""),
            pipeline_id=os.getenv("PIPELINE_ID", ""),
            ingestion_job_id=os.getenv("INGESTION_JOB_ID", ""),
            evaluation_job_id=os.getenv("EVALUATION_JOB_ID", ""),
            repository_url=os.getenv("REPOSITORY_URL", ""),
        )
