import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from investment_research.auth.schemas import AuthResponse, LoginRequest, RegisterRequest
from investment_research.auth.security import AuthSettings
from investment_research.auth.service import AuthenticationError, AuthService, CsrfValidationError
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork, create_unit_of_work

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_auth_settings() -> AuthSettings:
    return AuthSettings()


def get_auth_service(settings: AuthSettings = Depends(get_auth_settings)) -> AuthService:
    return AuthService(create_unit_of_work(), settings=settings)


def get_authenticated_user(
    request: Request,
    service: AuthService = Depends(get_auth_service),
    settings: AuthSettings = Depends(get_auth_settings),
) -> User:
    access_token = request.cookies.get(settings.access_cookie_name)
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")
    csrf_token = None
    if request.method.upper() in _UNSAFE_METHODS:
        csrf_token = _require_csrf(request, settings)
    try:
        return service.get_current_user(access_token, expected_csrf=csrf_token)
    except CsrfValidationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _set_auth_cookies(
    response: Response,
    auth_response: AuthResponse,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
    settings: AuthSettings,
) -> None:
    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        expires=auth_response.access_expires_at,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        expires=auth_response.refresh_expires_at,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        expires=auth_response.refresh_expires_at,
        domain=settings.cookie_domain,
        path=settings.cookie_path,
    )


def _clear_auth_cookies(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(settings.access_cookie_name, domain=settings.cookie_domain, path=settings.cookie_path)
    response.delete_cookie(settings.refresh_cookie_name, domain=settings.cookie_domain, path=settings.cookie_path)
    response.delete_cookie(settings.csrf_cookie_name, domain=settings.cookie_domain, path=settings.cookie_path)


def _require_csrf(request: Request, settings: AuthSettings) -> str:
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    csrf_header = request.headers.get(settings.csrf_header_name)
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=403, detail="Missing CSRF token")
    if not secrets.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return csrf_header


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: AuthSettings = Depends(get_auth_settings),
) -> AuthResponse:
    try:
        auth_response, tokens = service.register(payload)
    except AuthenticationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_auth_cookies(response, auth_response, tokens.access_token, tokens.refresh_token, tokens.csrf_token, settings)
    return auth_response


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: AuthSettings = Depends(get_auth_settings),
) -> AuthResponse:
    try:
        auth_response, tokens = service.login(payload)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_auth_cookies(response, auth_response, tokens.access_token, tokens.refresh_token, tokens.csrf_token, settings)
    return auth_response


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: AuthSettings = Depends(get_auth_settings),
) -> AuthResponse:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    csrf_token = _require_csrf(request, settings)
    try:
        auth_response, tokens = service.refresh(refresh_token, expected_csrf=csrf_token)
    except CsrfValidationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_auth_cookies(response, auth_response, tokens.access_token, tokens.refresh_token, tokens.csrf_token, settings)
    return auth_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: AuthSettings = Depends(get_auth_settings),
) -> Response:
    csrf_token = _require_csrf(request, settings)
    try:
        service.logout(request.cookies.get(settings.refresh_cookie_name), expected_csrf=csrf_token)
    except CsrfValidationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=User)
def me(
    user: User = Depends(get_authenticated_user),
) -> User:
    return user
