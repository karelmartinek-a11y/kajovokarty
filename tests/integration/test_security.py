from kajovokarty.app.paths import AppPaths
from kajovokarty.infrastructure.security.secrets import ApiTokens, SecretStore


def test_tokens_are_outside_sqlite_and_roundtrip_encrypted(app_paths: AppPaths, database) -> None:
    store = SecretStore(app_paths)
    tokens = ApiTokens("access-secret-value", "client-secret-value")
    store.save_tokens(tokens)
    assert store.load_tokens() == tokens
    assert b"access-secret-value" not in store.path.read_bytes()
    assert database.scalar("SELECT COUNT(*) FROM app_setting WHERE typed_value LIKE '%secret%'") == 0
