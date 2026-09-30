import httpx
from .config import settings


def wise_headers():
    return {"Authorization": f"Bearer {settings.wisesub_api_key or ''}", "X-API-Secret": settings.wisesub_api_secret or "", "X-Environment": settings.wisesub_environment, "Accept": "application/json", "Content-Type": "application/json"}


async def wise_purchase(payload: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.post(f"{settings.wisesub_base_url.rstrip('/')}/purchase", json=payload, headers=wise_headers())


async def paystack(path: str, method: str = "GET", payload: dict | None = None):
    if not settings.paystack_secret_key:
        raise RuntimeError("Payment system is not configured yet.")
    headers = {"Authorization": f"Bearer {settings.paystack_secret_key}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.request(method, f"https://api.paystack.co{path}", json=payload, headers=headers)


async def send_brevo(to: str, subject: str, html: str):
    if not settings.brevo_api_key or not settings.brevo_from_email:
        raise RuntimeError("Brevo email configuration is missing.")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post("https://api.brevo.com/v3/smtp/email", json={"sender": {"name": settings.brevo_from_name, "email": settings.brevo_from_email}, "to": [{"email": to}], "subject": subject, "htmlContent": html}, headers={"api-key": settings.brevo_api_key, "Accept": "application/json"})
        response.raise_for_status()
        return response.json()

