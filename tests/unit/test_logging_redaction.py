from __future__ import annotations

import json
import logging

from kajovokarty.infrastructure.diagnostics.logging import configure_logging, log_event, redact


def test_redact_masks_tokens_cards_and_email_even_inside_message_values(tmp_path) -> None:
    access = "".join(("ey", "Jvery-secret-token-value-123456789012345"))
    client = "".join(("bh", "_c_very-secret-token-value-123456789012345"))
    value = redact({"message": f"X-Access-Token: {access}; {client}; user@example.com; 1234567890123456"})
    text = str(value)
    assert access not in text
    assert client not in text
    assert "user@example.com" not in text
    assert "1234567890123456" not in text

    logger = configure_logging(tmp_path, max_lines=10, retention_files=2)
    log_event(logger, logging.ERROR, "TEST_SECRET", f"Bearer {access}", detail=f"Client Token={client}")
    for handler in logger.handlers:
        handler.close()
    payload = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert access not in payload["message"]
    assert client not in json.dumps(payload, ensure_ascii=False)
