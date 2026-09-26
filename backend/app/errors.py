"""Единый формат ошибок API: {"error": {"code": ..., "message": ...}} с понятным текстом на русском."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def bad_request(message: str, code: str = "bad_request", **details) -> ApiError:
    return ApiError(400, code, message, details or None)


def not_found(message: str, code: str = "not_found", **details) -> ApiError:
    return ApiError(404, code, message, details or None)


def not_ready() -> ApiError:
    return ApiError(503, "snapshot_not_ready",
                    "Прогноз ещё не построен: пайплайн не опубликовал ни одного snapshot. Попробуйте через минуту.")


def _body(code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


_TYPE_MESSAGES = {
    "int_parsing": "ожидается целое число",
    "missing": "обязательный параметр",
    "enum": "недопустимое значение",
    "literal_error": "недопустимое значение",
    "greater_than_equal": "значение слишком мало",
    "less_than_equal": "значение слишком велико",
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return ORJSONResponse(_body(e.code, e.message, e.details), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        parts = []
        for err in e.errors():
            field = err["loc"][-1] if err.get("loc") else "?"
            text = _TYPE_MESSAGES.get(err.get("type"), err.get("msg", "некорректное значение"))
            if err.get("type") in ("enum", "literal_error") and err.get("ctx", {}).get("expected"):
                text += f" (допустимо: {err['ctx']['expected'].replace(' or ', ', ')})"
            parts.append(f"«{field}» — {text}")
        return ORJSONResponse(_body("validation_error", "Некорректные параметры запроса: " + "; ".join(parts)),
                              status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        message = {404: "Ресурс не найден", 405: "Метод не поддерживается"}.get(e.status_code, str(e.detail))
        return ORJSONResponse(_body(f"http_{e.status_code}", message), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, e: Exception):
        log.exception("Необработанная ошибка")
        return ORJSONResponse(_body("internal_error", "Внутренняя ошибка сервера. Попробуйте повторить запрос позже."),
                              status_code=500)
