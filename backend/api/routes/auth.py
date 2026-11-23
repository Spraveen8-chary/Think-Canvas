"""Register, login, logout and the user's profile."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response

from ...services.auth_service import SESSION_DAYS, AuthService
from ..deps import COOKIE, auth_limiter, auth_service, client_key, current_user
from ..schemas import LoginIn, ProfileIn, RegisterIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def public_user(user: dict) -> dict:
    created: datetime | None = user.get("created_at")
    return {"id": str(user["_id"]), "name": user["name"], "email": user["email"],
            "organisation": user.get("organisation", ""), "created_at": created.isoformat() if created else None}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/")


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, auth: AuthService = Depends(auth_service)):
    auth_limiter.check(f"register:{client_key(request)}")
    user, token, _ = auth.register(body.name, body.email, body.password, body.organisation)
    _set_cookie(response, token)
    return public_user(user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, auth: AuthService = Depends(auth_service)):
    auth_limiter.check(f"login:{client_key(request)}:{body.email.strip().lower()}")
    user, token, _ = auth.login(body.email, body.password)
    _set_cookie(response, token)
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, auth: AuthService = Depends(auth_service)):
    auth.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


@router.put("/me")
def update_me(body: ProfileIn, user: dict = Depends(current_user), auth: AuthService = Depends(auth_service)):
    return public_user(auth.update_profile(user, body.name, body.organisation))
