from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def http_error_handler(request: Request, exc):
    detail = getattr(exc, "detail", "Request failed")
    if isinstance(detail, list):
        detail = "Invalid request data"
    return JSONResponse({"success": False, "message": str(detail)}, status_code=exc.status_code)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"success": False, "message": "Invalid request data"}, status_code=400)

