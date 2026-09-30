import hashlib
import json
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings, ROOT
from .database import db_session, engine, init_schema, q
from .providers import paystack, send_brevo, wise_purchase
from .security import (clear_session, current_user_id, new_session, password_check,
                        password_hash, require_admin, require_user,
                        valid_paystack_signature)

app = FastAPI(title="MELODEXS CONNECT API", docs_url=None if settings.production else "/docs")
from fastapi.exceptions import RequestValidationError
from .errors import http_error_handler, validation_error_handler
from .rate_limit import allowed, init_rate_limit_table
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, application):
        super().__init__(application)

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        allowed_origins = {"https://melodexs-connect.onrender.com"}
        if settings.cheapdata_public_url:
            allowed_origins.add(settings.cheapdata_public_url.rstrip("/"))
        if not settings.production:
            allowed_origins.update({"http://localhost:3000", "http://127.0.0.1:3000", str(request.base_url).rstrip("/")})
        if origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse({"success": False, "message": "CORS origin not allowed"}, status_code=403)
        if origin:
            if request.method == "OPTIONS":
                response = Response(status_code=204)
            else:
                response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            response.headers["Vary"] = "Origin"
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path != "/api/paystack/webhook" and origin:
            configured = settings.cheapdata_public_url.rstrip("/") if settings.production else origin.rstrip("/")
            if origin.rstrip("/") != configured and origin.rstrip("/") != "https://melodexs-connect.onrender.com":
                return JSONResponse({"success": False, "message": "Cross-origin request blocked."}, status_code=403)
        rate_ok, rate_message = allowed(request.url.path, (request.client.host if request.client else "unknown") + ":" + request.url.path)
        if not rate_ok:
            return JSONResponse({"success": False, "message": rate_message}, status_code=429)
        return response


app.add_middleware(SecurityMiddleware)
from .admin_routes import router as admin_router
app.include_router(admin_router)


@app.on_event("startup")
def startup():
    init_schema(); init_rate_limit_table()


def user_row(db, user_id: int, include_secret=False):
    cols = "id,name,email,phone,balance,virtual_account_number,virtual_bank_name,kyc_status,is_admin,created_at"
    if include_secret:
        cols += ",password,purchase_pin"
    return q(db, f"SELECT {cols} FROM users WHERE id=:id", {"id": user_id}).mappings().first()


def public_user(row):
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"], "phone": row["phone"], "balance": float(row["balance"] or 0), "virtual_account_number": row["virtual_account_number"], "virtual_bank_name": row["virtual_bank_name"], "kyc_status": row["kyc_status"], "is_admin": row["is_admin"], "created_at": row["created_at"], "has_purchase_pin": bool(row.get("purchase_pin")) if hasattr(row, "get") else False}


def nigeria_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"(?:\+234|234|0)\d{10}", str(phone).strip()))


@app.get("/api/status")
def status():
    return {"success": True, "message": "API is running"}


@app.get("/api/session")
def session_status(request: Request, response: Response):
    user_id = current_user_id(request)
    if not user_id:
        return {"success": True, "loggedIn": False, "user": None, "has_purchase_pin": False}
    with db_session() as db:
        user = user_row(db, user_id, True)
    if not user:
        clear_session(request, response)
        return {"success": True, "loggedIn": False, "user": None, "has_purchase_pin": False}
    result = public_user(user)
    result["has_purchase_pin"] = bool(user["purchase_pin"])
    return {"success": True, "loggedIn": True, "user": result, "has_purchase_pin": result["has_purchase_pin"]}


@app.post("/api/register")
def register(request: Request, response: Response, body: dict):
    name, email, phone, password = (body.get(x) for x in ("name", "email", "phone", "password"))
    if not all((name, email, phone, password)):
        raise HTTPException(400, "Please fill in all fields")
    if not nigeria_phone(phone):
        raise HTTPException(400, "Please enter a valid Nigerian phone number")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    email, phone = str(email).strip().lower(), str(phone).strip()
    with db_session() as db:
        if q(db, "SELECT id FROM users WHERE email=:email OR phone=:phone", {"email": email, "phone": phone}).first():
            raise HTTPException(400, "Email or phone number already exists")
        row = q(db, "INSERT INTO users(name,email,phone,password,balance,kyc_status,is_admin) VALUES(:name,:email,:phone,:password,0,'pending',0) RETURNING id", {"name": name, "email": email, "phone": phone, "password": password_hash(password)}).mappings().first()
        user = user_row(db, int(row["id"]), True)
    new_session(response, int(user["id"]))
    return {"success": True, "message": "Account created successfully", "user": public_user(user)}


@app.post("/api/login")
def login(response: Response, body: dict):
    email, password = body.get("email"), body.get("password")
    if not email or not password:
        raise HTTPException(400, "Email and password are required")
    with db_session() as db:
        user = q(db, "SELECT * FROM users WHERE LOWER(email)=:email", {"email": str(email).strip().lower()}).mappings().first()
    if not user or not password_check(str(password), user["password"]):
        raise HTTPException(401, "Invalid email or password")
    new_session(response, int(user["id"]))
    return {"success": True, "message": "Login successful", "user": public_user(user)}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    clear_session(request, response)
    return {"success": True, "message": "Logged out"}


@app.post("/api/forgot-password")
async def forgot_password(request: Request, body: dict):
    email = str(body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Please enter your email address.")
    with db_session() as db:
        user = q(db, "SELECT id,email FROM users WHERE LOWER(email)=:email", {"email": email}).mappings().first()
        if user:
            token = secrets.token_hex(32)
            hashed = hashlib.sha256(token.encode()).hexdigest()
            q(db, "UPDATE users SET reset_token_hash=:hash, reset_token_expires_at=:expires WHERE id=:id", {"hash": hashed, "expires": int(time.time()*1000)+900000, "id": user["id"]})
        else:
            token = None
    if user and settings.production:
        url = f"{settings.cheapdata_public_url}/reset-password.html?token={quote(token)}"
        await send_brevo(user["email"], "MELODEXS CONNECT Password Reset", f"<p>Reset your password: <a href=\"{url}\">Reset Password</a></p><p>This link expires in 15 minutes.</p>")
    elif user:
        print(f"PASSWORD RESET LINK: {settings.cheapdata_public_url}/reset-password.html?token={token}")
    return {"success": True, "message": "If an account exists with that email, password reset instructions will be provided."}


@app.post("/api/reset-password")
def reset_password(body: dict):
    token, new_password = body.get("token"), body.get("newPassword")
    if not token or not new_password:
        raise HTTPException(400, "Reset token and new password are required.")
    if len(new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    hashed = hashlib.sha256(str(token).encode()).hexdigest()
    with db_session() as db:
        user = q(db, "SELECT id,reset_token_expires_at FROM users WHERE reset_token_hash=:hash", {"hash": hashed}).mappings().first()
        if not user:
            raise HTTPException(400, "This password reset link is invalid or has already been used.")
        if not user["reset_token_expires_at"] or int(time.time()*1000) > int(user["reset_token_expires_at"]):
            raise HTTPException(400, "This password reset link has expired. Please request a new one.")
        q(db, "UPDATE users SET password=:password,reset_token_hash=NULL,reset_token_expires_at=NULL WHERE id=:id", {"password": password_hash(new_password), "id": user["id"]})
        q(db, "DELETE FROM sessions WHERE sess LIKE :needle", {"needle": f'%"userId": {user["id"]}%'} )
    return {"success": True, "message": "Password reset successfully. You can now log in."}


@app.get("/api/user/{user_id}")
def profile(request: Request, user_id: int):
    current = require_user(request)
    if current != user_id:
        raise HTTPException(403, "You can only view your own profile")
    with db_session() as db:
        user = user_row(db, user_id, True)
    if not user:
        raise HTTPException(404, "User not found")
    return {"success": True, "user": public_user(user), "has_purchase_pin": bool(user["purchase_pin"])}


@app.get("/api/transactions/{user_id}")
def transactions(request: Request, user_id: int):
    current_id = require_user(request)
    if current_id != user_id:
        with db_session() as auth_db:
            is_admin = q(auth_db, "SELECT is_admin FROM users WHERE id=:id", {"id": current_id}).scalar()
        if not is_admin:
            raise HTTPException(403, "You can only view your own transactions")
    with db_session() as db:
        rows = q(db, "SELECT id,type,amount,status,reference,description,created_at FROM transactions WHERE user_id=:id ORDER BY id DESC", {"id": user_id}).mappings().all()
    return {"success": True, "transactions": [dict(x) for x in rows]}


@app.get("/api/data-plans")
def data_plans():
    with db_session() as db:
        rows = q(db, "SELECT id,network,plan,selling_price,data_size,validity FROM data_plans WHERE active=1 AND LOWER(TRIM(source))='wisesub' ORDER BY selling_price,id").mappings().all()
    return {"success": True, "plans": [dict(x) for x in rows]}


@app.get("/api/admin/stats")
def admin_stats(request: Request):
    require_admin(request)
    with db_session() as db:
        row = q(db, """SELECT (SELECT COUNT(*) FROM users) total_users,(SELECT COALESCE(SUM(balance),0) FROM users) total_balance,(SELECT COUNT(*) FROM transactions) total_transactions,(SELECT COUNT(*) FROM transactions WHERE type='debit' AND status='successful' AND LOWER(description) LIKE '%data purchase%') data_purchases,(SELECT COUNT(*) FROM transactions WHERE type='debit' AND status='successful' AND LOWER(description) LIKE '%airtime purchase%') airtime_purchases,(SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='debit' AND status='successful' AND (LOWER(description) LIKE '%data purchase%' OR LOWER(description) LIKE '%airtime purchase%')) total_revenue""").mappings().first()
    return {"success": True, "stats": {"totalUsers": int(row["total_users"]), "totalBalance": float(row["total_balance"]), "totalTransactions": int(row["total_transactions"]), "dataPurchases": int(row["data_purchases"]), "airtimePurchases": int(row["airtime_purchases"]), "totalRevenue": float(row["total_revenue"])}}


@app.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = q(db, "SELECT id,name,email,phone,balance,virtual_account_number,virtual_bank_name,kyc_status,is_admin,created_at FROM users ORDER BY id DESC").mappings().all()
    return {"success": True, "users": [dict(x) for x in rows]}


@app.get("/api/admin/transactions")
def admin_transactions(request: Request):
    require_admin(request)
    with db_session() as db:
        rows = q(db, "SELECT t.id,u.name user_name,u.email user_email,t.type,t.amount,t.status,t.reference,t.description,t.created_at FROM transactions t JOIN users u ON u.id=t.user_id ORDER BY t.id DESC LIMIT 100").mappings().all()
    return {"success": True, "transactions": [dict(x) for x in rows]}


def validate_pin(pin):
    if pin is None or not re.fullmatch(r"\d{4}", str(pin)):
        raise HTTPException(400, "Purchase PIN must be exactly 4 digits")
    return str(pin)


@app.post("/api/purchase-pin/set")
def set_pin(request: Request, body: dict):
    user_id = require_user(request); pin = validate_pin(body.get("pin"))
    with db_session() as db:
        user = q(db, "SELECT purchase_pin FROM users WHERE id=:id", {"id": user_id}).mappings().first()
        if not user: raise HTTPException(404, "User not found")
        if user["purchase_pin"]: raise HTTPException(400, "Purchase PIN has already been set")
        q(db, "UPDATE users SET purchase_pin=:pin WHERE id=:id", {"pin": password_hash(pin), "id": user_id})
    return {"success": True, "message": "Purchase PIN created successfully"}


@app.post("/api/purchase-pin/change")
def change_pin(request: Request, body: dict):
    user_id = require_user(request); old, new = validate_pin(body.get("currentPin")), validate_pin(body.get("newPin"))
    if old == new: raise HTTPException(400, "New PIN must be different from current PIN")
    with db_session() as db:
        user = q(db, "SELECT purchase_pin FROM users WHERE id=:id", {"id": user_id}).mappings().first()
        if not user or not user["purchase_pin"]: raise HTTPException(400, "Purchase PIN has not been set")
        if not password_check(old, user["purchase_pin"]): raise HTTPException(401, "Current Purchase PIN is incorrect")
        q(db, "UPDATE users SET purchase_pin=:pin WHERE id=:id", {"pin": password_hash(new), "id": user_id})
    return {"success": True, "message": "Purchase PIN changed successfully"}


@app.post("/api/purchase-pin/verify")
def verify_pin(request: Request, body: dict):
    user_id = require_user(request); pin = validate_pin(body.get("pin"))
    with db_session() as db: user = q(db, "SELECT purchase_pin FROM users WHERE id=:id", {"id": user_id}).mappings().first()
    if not user or not user["purchase_pin"]: raise HTTPException(400, "Purchase PIN has not been set")
    if not password_check(pin, user["purchase_pin"]): raise HTTPException(401, "Incorrect Purchase PIN")
    return {"success": True, "message": "Purchase PIN verified"}


def ref():
    return datetime.now().strftime("%Y%m%d%H%M") + secrets.token_urlsafe(7).lower()


async def purchase(request: Request, body: dict, service: str):
    user_id = require_user(request)
    network, phone, pin = body.get("network"), body.get("phone"), body.get("pin")
    pin = validate_pin(pin)
    if not network or not phone or not nigeria_phone(phone): raise HTTPException(400, "Please enter a valid Nigerian phone number")
    if network not in {"MTN", "Airtel", "Glo", "9mobile"}: raise HTTPException(400, "Invalid network")
    with db_session() as db:
        user = q(db, "SELECT id,balance,purchase_pin FROM users WHERE id=:id", {"id": user_id}).mappings().first()
        if not settings.database_url.startswith("sqlite"):
            user = q(db, "SELECT id,balance,purchase_pin FROM users WHERE id=:id FOR UPDATE", {"id": user_id}).mappings().first()
        if not user or not user["purchase_pin"]: raise HTTPException(400, "Please create a Purchase PIN before buying")
        if not password_check(pin, user["purchase_pin"]): raise HTTPException(401, "Incorrect Purchase PIN")
        if service == "data":
            plan = body.get("plan")
            selected = q(db, "SELECT * FROM data_plans WHERE network=:network AND plan=:plan AND active=1 AND source='wisesub'", {"network": network, "plan": plan}).mappings().first()
            if not selected: raise HTTPException(400, "That data plan is not currently available")
            amount = float(selected["selling_price"]); payload = {"service_type":"data","reference":ref(),"provider_code":selected["provider_code"],"package_code":selected["provider_package_code"],"recipient":"08011111111" if settings.wisesub_environment == "test" else phone}
            description = f"{network} {plan} data purchase for {phone}"
        else:
            amount = float(body.get("amount") or 0)
            if not amount.is_integer() or amount < 50 or amount > 50000: raise HTTPException(400, "Airtime amount must be between ₦50 and ₦50,000")
            amount = int(amount)
            if amount <= 0: raise HTTPException(400, "A valid airtime amount is required")
            payload = {"service_type":"airtime","reference":ref(),"provider_code":{"MTN":"mtn","Airtel":"airtel","Glo":"glo","9mobile":"9mobile"}[network],"recipient":"08011111111" if settings.wisesub_environment == "test" else phone,"amount":amount}; description = f"{network} airtime purchase for {phone}"
        if user["balance"] < amount: raise HTTPException(400, "Insufficient wallet balance")
        reference = payload["reference"]
        q(db, "UPDATE users SET balance=balance-:amount WHERE id=:id", {"amount": amount, "id": user_id})
        q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:uid,'debit',:amount,'pending',:reference,:description)", {"uid": user_id, "amount": amount, "reference": reference, "description": description + " | Pending WiseSub confirmation"})
    try:
        provider_response = await wise_purchase(payload)
        provider_data = provider_response.json()
    except Exception:
        return JSONResponse({"success": False, "pending": True, "message": "We could not immediately confirm your purchase. Please do not retry this purchase.", "reference": reference}, status_code=202)
    if provider_response.status_code >= 500:
        return JSONResponse({"success": False, "pending": True, "message": "We could not immediately confirm your purchase. Please do not retry this purchase.", "reference": reference}, status_code=202)
    if provider_response.status_code >= 400 or provider_data.get("success") is not True:
        with db_session() as db:
            q(db, "UPDATE users SET balance=balance+:amount WHERE id=:id", {"amount": amount, "id": user_id}); q(db, "UPDATE transactions SET status='failed',description=:description WHERE reference=:reference AND user_id=:id", {"description": description + " | WiseSub rejected the purchase", "reference": reference, "id": user_id})
        return JSONResponse({"success": False, "message": "Purchase was rejected by the provider. Your wallet has been refunded.", "reference": reference}, status_code=502)
    provider_reference = (provider_data.get("data") or {}).get("reference")
    if not provider_reference:
        return JSONResponse({"success": False, "pending": True, "message": "Your purchase was accepted by the provider but could not yet be fully confirmed.", "reference": reference}, status_code=202)
    with db_session() as db:
        q(db, "UPDATE transactions SET status='successful',description=:description WHERE reference=:reference AND user_id=:id AND status='pending'", {"description": description + " | WiseSub reference: " + str(provider_reference), "reference": reference, "id": user_id})
        balance = q(db, "SELECT balance FROM users WHERE id=:id", {"id": user_id}).scalar()
    result = {"success": True, "message": f"{service.title()} purchase successful", "network": network, "phone": phone, "amount": amount, "balance": float(balance), "reference": reference, "providerReference": provider_reference}
    if service == "data": result["plan"] = body.get("plan")
    return result


@app.post("/api/purchase-data")
async def purchase_data(request: Request, body: dict): return await purchase(request, body, "data")


@app.post("/api/purchase-airtime")
async def purchase_airtime(request: Request, body: dict): return await purchase(request, body, "airtime")


@app.post("/api/fund-wallet")
async def fund_wallet(request: Request, response: Response, body: dict):
    user_id = require_user(request); amount = float(body.get("amount") or 0)
    if amount < 100 or amount > 500000: raise HTTPException(400, "Funding amount must be between ₦100 and ₦500,000.")
    with db_session() as db:
        user = q(db, "SELECT id,email FROM users WHERE id=:id", {"id": user_id}).mappings().first()
        if not user: raise HTTPException(404, "User account not found.")
        reference = "CD-" + str(int(time.time()*1000)) + "-" + secrets.token_hex(6)
        q(db, "INSERT INTO transactions(user_id,type,amount,status,reference,description) VALUES(:id,'wallet_funding',:amount,'pending',:reference,'Paystack wallet funding')", {"id": user_id, "amount": amount, "reference": reference})
    try:
        pay = await paystack("/transaction/initialize", "POST", {"email": user["email"], "amount": str(round(amount*100)), "currency":"NGN", "reference":reference, "callback_url":f"{settings.cheapdata_public_url}/fund-wallet.html", "metadata":{"user_id":str(user_id),"purpose":"wallet_funding"}})
        data = pay.json()
    except Exception:
        raise HTTPException(502, "Payment initialization could not be confirmed. Please try again later.")
    if pay.status_code >= 400 or not data.get("status") or not data.get("data") or data["data"].get("reference") != reference:
        with db_session() as db: q(db, "UPDATE transactions SET status='failed' WHERE reference=:reference", {"reference": reference})
        raise HTTPException(400, data.get("message", "Unable to initialize payment."))
    return {"success": True, "message":"Payment initialized successfully.", "authorization_url":data["data"].get("authorization_url"), "access_code":data["data"].get("access_code"), "reference":reference}


async def credit_paystack(reference: str, payment: dict):
    with db_session() as db:
        tx = q(db, "SELECT id,user_id,amount,status FROM transactions WHERE reference=:reference AND type='wallet_funding'" + (" FOR UPDATE" if not settings.database_url.startswith("sqlite") else ""), {"reference": reference}).mappings().first()
        if not tx: return "Transaction not found"
        if tx["status"] == "successful": return "Already processed"
        if payment.get("status") != "success" or str(payment.get("currency", "")).upper() != "NGN" or int(payment.get("amount", 0)) != round(float(tx["amount"])*100) or str((payment.get("metadata") or {}).get("user_id")) != str(tx["user_id"]) or str(payment.get("reference")) != reference:
            raise ValueError("Payment validation failed")
        q(db, "UPDATE users SET balance=balance+:amount WHERE id=:id", {"amount": tx["amount"], "id": tx["user_id"]})
        q(db, "UPDATE transactions SET status='successful',description='Paystack wallet funding credited' WHERE id=:id AND status='pending'", {"id": tx["id"]})
    return "Webhook processed"


@app.post("/api/fund-wallet/verify")
async def verify_wallet(request: Request, body: dict):
    user_id = require_user(request); reference = str(body.get("reference") or "").strip()
    if not reference or len(reference) > 100: raise HTTPException(400, "A valid payment reference is required.")
    with db_session() as db: tx = q(db, "SELECT * FROM transactions WHERE reference=:reference AND type='wallet_funding' AND user_id=:id", {"reference":reference,"id":user_id}).mappings().first()
    if not tx: raise HTTPException(404, "Funding transaction not found.")
    if tx["status"] == "successful":
        with db_session() as db: balance=q(db,"SELECT balance FROM users WHERE id=:id",{"id":user_id}).scalar()
        return {"success":True,"message":"Payment has already been credited.","balance":float(balance),"reference":reference}
    pay = await paystack(f"/transaction/verify/{quote(reference)}")
    data = pay.json()
    if pay.status_code >= 400 or not data.get("status") or not data.get("data"): raise HTTPException(400, data.get("message", "Unable to verify payment."))
    try: await credit_paystack(reference, data["data"])
    except ValueError: raise HTTPException(400, "Payment could not be verified as a valid MELODEXS CONNECT wallet funding.")
    with db_session() as db: balance=q(db,"SELECT balance FROM users WHERE id=:id",{"id":user_id}).scalar()
    return {"success":True,"message":"Payment verified and wallet credited successfully.","balance":float(balance),"amount":float(tx["amount"]),"reference":reference}


@app.post("/api/paystack/webhook")
async def paystack_webhook(request: Request):
    raw = await request.body()
    if not valid_paystack_signature(settings.paystack_secret_key, raw, request.headers.get("x-paystack-signature")): return PlainTextResponse("Invalid signature", status_code=401)
    try: event=json.loads(raw)
    except json.JSONDecodeError: return PlainTextResponse("Invalid JSON", status_code=400)
    if event.get("event") != "charge.success": return PlainTextResponse("Event received")
    try: message=await credit_paystack(str((event.get("data") or {}).get("reference") or ""), event.get("data") or {})
    except ValueError: return PlainTextResponse("Payment validation failed", status_code=400)
    return PlainTextResponse(message)


web_dir = ROOT / "apps/web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

