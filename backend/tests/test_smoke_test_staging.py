from scripts.smoke_test_staging import HttpResult, Reporter, check_health


def health_result(status: int, body: bytes) -> HttpResult:
    return HttpResult(
        status=status,
        headers=None,
        body=body,
        final_url="https://staging.example.test/health",
    )


def test_health_check_accepts_exact_endpoint_contract(capsys) -> None:
    reporter = Reporter()

    check_health(reporter, health_result(200, b'{"status":"ok"}'))

    assert reporter.counts == {"PASS": 1, "WARN": 0, "FAIL": 0}
    assert "[PASS] GET /health devuelve el JSON mínimo esperado" in capsys.readouterr().out


def test_health_check_rejects_invalid_json(capsys) -> None:
    reporter = Reporter()

    check_health(reporter, health_result(200, b'{"status":'))

    assert reporter.counts == {"PASS": 0, "WARN": 0, "FAIL": 1}
    assert "payload inesperado o no válido" in capsys.readouterr().out


def test_health_check_rejects_unexpected_payload(capsys) -> None:
    reporter = Reporter()

    check_health(
        reporter,
        health_result(200, b'{"status":"ok","app":"autonogrow"}'),
    )

    assert reporter.counts == {"PASS": 0, "WARN": 0, "FAIL": 1}
    assert "payload inesperado o no válido" in capsys.readouterr().out


def test_health_check_rejects_non_200_status(capsys) -> None:
    reporter = Reporter()

    check_health(reporter, health_result(503, b'{"status":"ok"}'))

    assert reporter.counts == {"PASS": 0, "WARN": 0, "FAIL": 1}
    assert "[FAIL] GET /health no devuelve 200" in capsys.readouterr().out
