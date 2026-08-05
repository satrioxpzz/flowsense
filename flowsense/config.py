"""FlowSense configuration loaded from environment variables and .env."""
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path) -> None:
    """Tiny stdlib .env loader: KEY=VALUE lines, no interpolation."""
    if not Path(path).exists():
        return
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    api_url: str = "https://kudussehat.kuduskab.go.id/api/get-cctv"
    api_key: str = ""
    api_timeout: float = 25.0
    api_retries: int = 3
    api_backoff: float = 2.0
    min_conf: float = 0.35
    interval: float = 2.0
    model_path: str = "yolo11n.pt"
    db_url: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def rois_path(self) -> Path:
        return self.base_dir / "config" / "rois.json"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"


def load_config(env_path: Path = DEFAULT_ENV_PATH) -> Config:
    _load_dotenv(env_path)
    defaults = Config()
    return Config(
        api_url=os.environ.get("FLOWSENSE_API_URL", defaults.api_url),
        api_key=os.environ.get("FLOWSENSE_API_KEY", defaults.api_key),
        api_timeout=float(os.environ.get("FLOWSENSE_API_TIMEOUT", defaults.api_timeout)),
        api_retries=int(os.environ.get("FLOWSENSE_API_RETRIES", defaults.api_retries)),
        api_backoff=float(os.environ.get("FLOWSENSE_API_BACKOFF", defaults.api_backoff)),
        min_conf=float(os.environ.get("FLOWSENSE_MIN_CONF", defaults.min_conf)),
        interval=float(os.environ.get("FLOWSENSE_INTERVAL", defaults.interval)),
        model_path=os.environ.get("FLOWSENSE_MODEL", defaults.model_path),
        db_url=os.environ.get("FLOWSENSE_DB_URL", defaults.db_url),
        s3_endpoint=os.environ.get("FLOWSENSE_S3_ENDPOINT", defaults.s3_endpoint),
        s3_access_key=os.environ.get("FLOWSENSE_S3_ACCESS_KEY", defaults.s3_access_key),
        s3_secret_key=os.environ.get("FLOWSENSE_S3_SECRET_KEY", defaults.s3_secret_key),
        s3_bucket=os.environ.get("FLOWSENSE_S3_BUCKET", defaults.s3_bucket),
    )

