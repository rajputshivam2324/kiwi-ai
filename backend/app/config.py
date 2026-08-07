"""Unified settings for Kiwi AI backend (builder + research + finance)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    # ── Gemini (shared) ──────────────────────────────────────────────
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GOOGLE_API_KEY", "GEMINI_API_KEY", "google_api_key"
        ),
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        validation_alias=AliasChoices("GEMINI_BASE_URL", "gemini_base_url"),
    )
    llm_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("LLM_MODEL", "GEMINI_MODEL", "llm_model"),
    )
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 4096

    # Shared Gemini retry / backoff (finance tool-loop + builder fallback)
    gemini_max_retries: int = Field(default=8, validation_alias="GEMINI_MAX_RETRIES")
    gemini_backoff_initial_ms: int = Field(
        default=1500, validation_alias="GEMINI_BACKOFF_INITIAL_MS"
    )
    gemini_backoff_max_ms: int = Field(
        default=120_000, validation_alias="GEMINI_BACKOFF_MAX_MS"
    )
    gemini_tool_round_delay_ms: int = Field(
        default=600, validation_alias="GEMINI_TOOL_ROUND_DELAY_MS"
    )
    gemini_max_tool_result_chars: int = Field(
        default=120_000, validation_alias="GEMINI_MAX_TOOL_RESULT_CHARS"
    )

    # Builder-specific generation
    builder_max_tokens: int = 16384
    builder_max_retries: int = 3
    builder_max_fix_rounds: int = Field(default=2, validation_alias="BUILDER_MAX_FIX_ROUNDS")
    builder_temperature: float = 0.6

    # Embedding / RAG
    embedding_model: str = "gemini-embedding-001"
    chroma_db_path: str = str(BACKEND_ROOT / "data" / "chroma_db")
    collection_name: str = "arxiv_papers"

    # Database
    database_url: str = "postgresql://kiwi:kiwi_secret_2024@localhost:5432/kiwi_ai"

    # Auth (Clerk)
    clerk_secret_key: str = Field(default="", validation_alias="CLERK_SECRET_KEY")
    clerk_publishable_key: str = Field(
        default="", validation_alias="CLERK_PUBLISHABLE_KEY"
    )
    clerk_jwks_url: str = Field(default="", validation_alias="CLERK_JWKS_URL")
    # When true, decode JWT without signature verify (local/dev only)
    clerk_dev_bypass: bool = Field(default=False, validation_alias="CLERK_DEV_BYPASS")

    # Builder workspaces (disk is disposable; Postgres holds durable source)
    workspace_dir: str = Field(
        default=str(BACKEND_ROOT / "workspaces"),
        validation_alias=AliasChoices("WORKSPACE_DIR", "workspace_dir"),
    )
    preview_port_start: int = Field(
        default=5200, validation_alias="PREVIEW_PORT_START"
    )
    # Budget live-Vite: only N concurrent previews; idle ones drop disk
    builder_max_live_previews: int = Field(
        default=1, validation_alias="BUILDER_MAX_LIVE_PREVIEWS"
    )
    builder_idle_evict_seconds: int = Field(
        default=900, validation_alias="BUILDER_IDLE_EVICT_SECONDS"
    )
    builder_idle_sweep_seconds: int = Field(
        default=60, validation_alias="BUILDER_IDLE_SWEEP_SECONDS"
    )
    # Vite dev server host allowlist (comma-separated) or "true" for all hosts
    preview_allowed_hosts: str = Field(
        default="preview.kiwiai.shivamio.in,localhost,127.0.0.1",
        validation_alias="PREVIEW_ALLOWED_HOSTS",
    )

    # Groww MCP
    mcp_command: str = Field(default="npx", validation_alias="MCP_COMMAND")
    mcp_args: str = Field(
        default="-y,mcp-remote,https://mcp.groww.in/mcp",
        validation_alias="MCP_ARGS",
    )
    mcp_use_stub_tools: bool = Field(
        default=False, validation_alias="MCP_USE_STUB_TOOLS"
    )
    mcp_connect_timeout_seconds: float = Field(
        default=300.0, validation_alias="MCP_CONNECT_TIMEOUT_SECONDS"
    )

    # Rate limiting (requests per window per key)
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # API
    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    finance_enabled: bool = Field(default=True, validation_alias="FINANCE_ENABLED")

    @property
    def gemini_api_key(self) -> str:
        return self.google_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mcp_args_list(self) -> list[str]:
        return [a.strip() for a in self.mcp_args.split(",") if a.strip()]

    @property
    def preview_allowed_hosts_list(self) -> list[str] | bool:
        raw = (self.preview_allowed_hosts or "").strip()
        if not raw or raw.lower() in {"true", "*", "all"}:
            return True
        return [h.strip() for h in raw.split(",") if h.strip()]

    @property
    def finance_available(self) -> bool:
        if not self.finance_enabled:
            return False
        return self.app_env.lower() != "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
