from flowsense.config import Config, load_config


def test_defaults(tmp_path):
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.api_key == ""
    assert cfg.api_url == "https://kudussehat.kuduskab.go.id/api/get-cctv"
    assert cfg.interval == 2.0
    assert cfg.min_conf == 0.35
    assert cfg.rois_path.name == "rois.json"
    assert cfg.data_dir.name == "data"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOWSENSE_API_KEY", "env-secret")
    monkeypatch.setenv("FLOWSENSE_INTERVAL", "5.5")
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.api_key == "env-secret"
    assert cfg.interval == 5.5


def test_dotenv_loaded_when_env_unset(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        'FLOWSENSE_API_KEY=dot-secret\nFLOWSENSE_INTERVAL=7\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("FLOWSENSE_API_KEY", raising=False)
    monkeypatch.delenv("FLOWSENSE_INTERVAL", raising=False)
    cfg = load_config(env_path=env)
    assert cfg.api_key == "dot-secret"
    assert cfg.interval == 7.0


def test_env_beats_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('FLOWSENSE_API_KEY=dot-secret\n', encoding="utf-8")
    monkeypatch.setenv("FLOWSENSE_API_KEY", "real-secret")
    cfg = load_config(env_path=env)
    assert cfg.api_key == "real-secret"


def test_db_s3_config_defaults(tmp_path):
    from flowsense.config import load_config
    cfg = load_config(env_path=tmp_path / "missing.env")
    assert cfg.db_url == ""
    assert cfg.s3_endpoint == ""
    assert cfg.s3_access_key == ""
    assert cfg.s3_secret_key == ""
    assert cfg.s3_bucket == ""

