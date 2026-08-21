"""Tests for error handling and error responses."""

from app.core.errors import AppError, NotFoundError, ValidationError, error_response


def test_app_error_attributes():
    """AppError carries code, message, and status_code."""
    err = AppError(code="TEST", message="test error", status_code=418)
    assert err.code == "TEST"
    assert err.message == "test error"
    assert err.status_code == 418
    assert str(err) == "test error"


def test_not_found_error():
    """NotFoundError defaults to 404."""
    err = NotFoundError("User")
    assert err.status_code == 404
    assert "User" in err.message


def test_validation_error():
    """ValidationError defaults to 422."""
    err = ValidationError()
    assert err.status_code == 422
    assert err.code == "VALIDATION_ERROR"


def test_error_response_format():
    """error_response returns correct JSON structure."""
    resp = error_response(400, "BAD", "bad request")
    assert resp.status_code == 400
    import json
    body = json.loads(resp.body)
    assert body["error"]["code"] == "BAD"
    assert body["error"]["message"] == "bad request"
