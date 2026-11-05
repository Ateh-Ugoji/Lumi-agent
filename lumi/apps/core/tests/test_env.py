import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core import env


def test_parse_standard_url():
    cfg = env.parse_database_url(
        "postgresql://us%40er:p%2Fw@db.example:5433/lumi?sslmode=require"
    )
    assert cfg["ENGINE"] == "django.db.backends.postgresql"
    assert (cfg["USER"], cfg["PASSWORD"], cfg["HOST"], cfg["PORT"], cfg["NAME"]) == (
        "us@er",
        "p/w",
        "db.example",
        "5433",
        "lumi",
    )
    assert cfg["OPTIONS"] == {"sslmode": "require"}


def test_parse_pgserver_socket_url():
    cfg = env.parse_database_url("postgresql://postgres:@/postgres?host=/tmp/pgdata")
    assert cfg["HOST"] == "/tmp/pgdata"
    assert cfg["NAME"] == "postgres"
    assert "OPTIONS" not in cfg


@pytest.mark.parametrize("url", ["sqlite:///lumi.db", "sqlite+aiosqlite:///lumi.db"])
def test_sqlite_is_rejected(url):
    with pytest.raises(ImproperlyConfigured, match="SQLite"):
        env.parse_database_url(url)


def test_asyncpg_scheme_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="asyncpg"):
        env.parse_database_url("postgresql+asyncpg://u:p@h/db")


@pytest.mark.parametrize("url", ["", "mysql://u:p@h/db", "postgresql://u:p@h"])
def test_invalid_urls_name_the_variable(url):
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        env.parse_database_url(url)


def test_error_never_echoes_the_password():
    with pytest.raises(ImproperlyConfigured) as exc:
        env.parse_database_url("mysql://user:topsecretpass@h/db")
    assert "topsecretpass" not in str(exc.value)


def test_missing_database_url_fails_clearly(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["manage.py", "runserver"])
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        env.database_config()


def test_missing_database_url_is_tolerated_by_check_keys(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["manage.py", "check_keys"])
    assert env.database_config()["ENGINE"] == "django.db.backends.postgresql"


def test_env_file_does_not_override_real_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        'A_VAR=from_file\nB_VAR="quoted value"\n# comment\nC_VAR=x # trailing\n'
    )
    monkeypatch.setenv("A_VAR", "from_env")
    monkeypatch.delenv("B_VAR", raising=False)
    monkeypatch.delenv("C_VAR", raising=False)
    loaded = env.load_env_file(path)
    assert env.get("A_VAR") == "from_env"
    assert env.get("B_VAR") == "quoted value"
    assert env.get("C_VAR") == "x"
    assert "A_VAR" not in loaded


def test_get_bool_rejects_garbage(monkeypatch):
    monkeypatch.setenv("FLAG", "maybe")
    with pytest.raises(ImproperlyConfigured, match="FLAG"):
        env.get_bool("FLAG")
