"""Every failure answers in the same JSON envelope and never leaks internals."""
import asyncio
import json

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from app import errors


class _Req:  # the handlers do not read the request
    pass


def _body(response):
    return json.loads(response.body)


def test_http_errors_use_the_success_false_envelope_and_keep_their_status():
    response = asyncio.run(errors.http_error_handler(_Req(), HTTPException(403, "Admin access required")))
    assert response.status_code == 403
    assert _body(response) == {"success": False, "message": "Admin access required"}


def test_a_list_detail_is_replaced_so_validation_internals_are_not_echoed():
    exc = HTTPException(422, [{"loc": ["body", "password"], "msg": "secret detail", "input": "hunter2"}])
    body = _body(asyncio.run(errors.http_error_handler(_Req(), exc)))
    assert body == {"success": False, "message": "Invalid request data"}
    assert "hunter2" not in json.dumps(body)


def test_request_validation_errors_become_a_plain_400():
    response = asyncio.run(errors.validation_error_handler(_Req(), RequestValidationError([{"loc": ["x"], "msg": "bad"}])))
    assert response.status_code == 400
    assert _body(response) == {"success": False, "message": "Invalid request data"}


def test_unexpected_errors_never_expose_sql_or_exception_text():
    boom = RuntimeError('psycopg2 error: relation "users" does not exist; password=hunter2')
    response = asyncio.run(errors.unexpected_error_handler(_Req(), boom))
    assert response.status_code == 500
    assert _body(response) == {"success": False, "message": "Internal server error"}
    assert "psycopg2" not in response.body.decode() and "hunter2" not in response.body.decode()
