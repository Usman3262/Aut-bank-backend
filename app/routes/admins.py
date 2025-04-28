# app/routes/admins.py
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from app.core.rate_limiter import (
    limiter,
    get_redis_client,
    CACHE_TTL_SHORT,
    CACHE_TTL_MEDIUM,
    get_cache_key,
    get_from_cache,
    set_to_cache,
    invalidate_cache,
)
from fastapi import BackgroundTasks
import json

# Controllers
from app.controllers.admin_controller import (
    delete_user,
    get_all_admins,
    register_admin,
    login_admin,
    toggle_user_active_status,
    update_other_admin,
    update_user,
    get_analytics_summary,
    get_current_admin,
    update_current_admin,
    update_admin_password,
    get_admin_by_id,
    delete_admin,
    get_user_by_id,
    get_all_users,
)
from app.controllers.deposits.admins import get_user_deposits, create_deposit
from app.controllers.transactions.admins import (
    get_transaction_by_id,
    get_all_transactions,
    export_transactions,
)
from app.controllers.loans.admins import (
    get_loan_by_id,
    approve_loan,
    reject_loan,
    get_all_loans,
)
from app.controllers.cards.admins import (
    get_card_by_id,
    unblock_card,
    list_all_cards,
    block_card,
    update_card_admin,
)

# Schemas
from app.core.exceptions import CustomHTTPException
from app.schemas.admin_schema import (
    AdminCreate,
    AdminLogin,
    AdminOrder,
    AdminPasswordUpdate,
    AdminSortBy,
    AdminUpdate,
)
from app.schemas.transactions_schema import TransactionResponse
from app.schemas.card_schema import CardUpdate
from app.schemas.deposit_schema import DepositCreate
from app.schemas.user_schema import Order, SortBy, UserUpdate

# Core
from app.core.database import get_db
from app.core.schemas import BaseResponse, PaginatedResponse
from app.core.auth import refresh_token
from app.core.rbac import check_permission

# Models
from app.models.admin import Admin
import os
from fastapi import BackgroundTasks

router = APIRouter()


@router.post("/bootstrap_admin", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def bootstrap_admin(
    request: Request, admin: AdminCreate, db: Session = Depends(get_db)
):
    if db.query(Admin).count() > 0:
        raise CustomHTTPException(
            status_code=403, message="Admin bootstrap only allowed when no admins exist"
        )
    return register_admin(admin, db)


@router.post("/register", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def register(
    request: Request,
    admin: AdminCreate,
    current_admin: Admin = Depends(check_permission("admin:register")),
    db: Session = Depends(get_db),
):
    result = register_admin(admin, db)
    invalidate_cache("admins:")  # Invalidate admin list cache
    return result


@router.post("/login", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_LOGIN", "5/minute"))
def login(request: Request, credentials: AdminLogin, db: Session = Depends(get_db)):
    return login_admin(credentials, db)


@router.post("/refresh", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def refresh(request: Request, token: str, db: Session = Depends(get_db)):
    return refresh_token(token, db, Admin, "Admin", "AdminID")


@router.get("/me", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_current_admin_route(
    request: Request,
    current_admin: Admin = Depends(check_permission("admin:view_self")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, f"admin:{current_admin.AdminID}")
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_current_admin(current_admin.AdminID, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.put("/me", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def update_current_admin_route(
    request: Request,
    admin_update: AdminUpdate,
    current_admin: Admin = Depends(check_permission("admin:update_self")),
    db: Session = Depends(get_db),
):
    result = update_current_admin(current_admin.AdminID, admin_update, db)
    invalidate_cache(f"admin:{current_admin.AdminID}")
    invalidate_cache("admins:")
    return result


@router.put("/me/password", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def update_admin_password_route(
    request: Request,
    password_update: AdminPasswordUpdate,
    current_admin: Admin = Depends(check_permission("admin:update_self")),
    db: Session = Depends(get_db),
):
    return update_admin_password(current_admin.AdminID, password_update, db)


@router.get("/admins/{admin_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_admin_by_id_route(
    request: Request,
    admin_id: int,
    current_admin: Admin = Depends(check_permission("admin:view_all")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, f"admin:{admin_id}")
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_admin_by_id(admin_id, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.put("/admins/{admin_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def update_admin_route(
    request: Request,
    admin_id: int,
    update_data: AdminUpdate,
    current_admin: Admin = Depends(check_permission("admin:update_other")),
    db: Session = Depends(get_db),
):
    result = update_other_admin(admin_id, update_data, current_admin.AdminID, db)
    invalidate_cache(f"admin:{admin_id}")
    invalidate_cache("admins:")
    return result


@router.delete("/admins/{admin_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def delete_admin_route(
    request: Request,
    admin_id: int,
    current_admin: Admin = Depends(check_permission("admin:delete")),
    db: Session = Depends(get_db),
):
    result = delete_admin(admin_id, current_admin.AdminID, db)
    invalidate_cache(f"admin:{admin_id}")
    invalidate_cache("admins:")
    return result


@router.get("/users/{user_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_user_by_id_route(
    request: Request,
    user_id: int,
    current_admin: Admin = Depends(check_permission("user:view_all")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, f"user:{user_id}")
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_user_by_id(user_id, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.get("/users/{user_id}/deposits", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_user_deposits_route(
    request: Request,
    user_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    deposit_status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_by: Optional[str] = Query("CreatedAt"),
    order: Optional[str] = Query("desc"),
    current_admin: Admin = Depends(check_permission("deposit:view_all")),
    db: Session = Depends(get_db),
):
    params = {
        "page": page,
        "per_page": per_page,
        "deposit_status": deposit_status,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "sort_by": sort_by,
        "order": order,
    }
    cache_key = get_cache_key(
        request, f"user_deposits:{user_id}", current_admin.AdminID, params
    )
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = get_user_deposits(
        user_id,
        db,
        page,
        per_page,
        deposit_status,
        start_date,
        end_date,
        sort_by,
        order,
    )
    set_to_cache(cache_key, result.model_dump(), CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.get("/loans/{loan_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_loan_by_id_route(
    request: Request,
    loan_id: int,
    current_admin: Admin = Depends(check_permission("loan:view_all")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, f"loan:{loan_id}")
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_loan_by_id(loan_id, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.put("/loans/{loan_id}/reject", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
async def reject_loan_route(
    request: Request,
    loan_id: int,
    background_tasks: BackgroundTasks,
    current_admin: Admin = Depends(check_permission("loan:approve")),
    db: Session = Depends(get_db),
):
    result = await reject_loan(loan_id, current_admin, db, background_tasks)
    invalidate_cache("loans:")
    invalidate_cache("analytics:summary")
    return result


@router.get("/cards/{card_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_card_by_id_route(
    request: Request,
    card_id: int,
    current_admin: Admin = Depends(check_permission("card:view_all")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, f"card:{card_id}")
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_card_by_id(card_id, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.put("/cards/{card_id}/unblock", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def unblock_card_route(
    request: Request,
    card_id: int,
    current_admin: Admin = Depends(check_permission("card:manage")),
    db: Session = Depends(get_db),
):
    result = unblock_card(card_id, db)
    invalidate_cache("cards:")
    return result


@router.get("/transactions/details/{transaction_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_transaction_by_id_route(
    request: Request,
    transaction_id: int,
    transaction_type: Optional[str] = Query(None),
    current_admin: Admin = Depends(check_permission("transaction:view_all")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(
        request, f"transaction:{transaction_type}:{transaction_id}"
    )
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_transaction_by_id(transaction_id, transaction_type, db)
    set_to_cache(cache_key, result, CACHE_TTL_MEDIUM)  # 1 hr TTL
    return result


@router.get("/analytics/summary", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def get_analytics_summary_route(
    request: Request,
    current_admin: Admin = Depends(check_permission("analytics:view")),
    db: Session = Depends(get_db),
):
    cache_key = get_cache_key(request, "analytics:summary", current_admin.AdminID)
    cached = get_from_cache(cache_key)
    if cached:
        return BaseResponse(**cached)
    result = get_analytics_summary(db)
    set_to_cache(cache_key, result, CACHE_TTL_SHORT)  # 5 min TTL for analytics
    return result


@router.get("/admins", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def list_all_admins(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    username: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    sort_by: Optional[AdminSortBy] = Query(None),
    order: Optional[AdminOrder] = Query(None),
    current_admin: Admin = Depends(check_permission("admin:view_all")),
    db: Session = Depends(get_db),
):
    params = {
        "page": page,
        "per_page": per_page,
        "username": username,
        "email": email,
        "role": role,
        "sort_by": sort_by,
        "order": order,
    }
    cache_key = get_cache_key(request, "admins", current_admin.AdminID, params)
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = get_all_admins(
        db,
        current_admin_id=current_admin.AdminID,
        page=page,
        per_page=per_page,
        username=username,
        email=email,
        role=role,
        sort_by=sort_by,
        order=order,
    )
    set_to_cache(
        cache_key, result.model_dump(), CACHE_TTL_MEDIUM
    )  # 1 hr TTL for admin list
    return result


@router.put("/users/toggle_user_status/{user_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def toggle_user_status(
    request: Request,
    user_id: int,
    current_admin: Admin = Depends(check_permission("user:approve")),
    db: Session = Depends(get_db),
):
    result = toggle_user_active_status(user_id, current_admin.AdminID, db)
    invalidate_cache(f"users:user:{user_id}")  # Invalidate user-specific cache
    invalidate_cache("users:")  # Invalidate user list cache
    return result


@router.get("/users", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    username: Optional[str] = None,
    email: Optional[str] = None,
    isactive: Optional[bool] = None,
    account_type: Optional[str] = None,
    balance_min: Optional[float] = None,
    balance_max: Optional[float] = None,
    sort_by: Optional[SortBy] = None,
    order: Optional[Order] = None,
    current_admin: Admin = Depends(check_permission("user:view_all")),
    db: Session = Depends(get_db),
):
    params = {
        "page": page,
        "per_page": per_page,
        "username": username,
        "email": email,
        "isactive": isactive,
        "account_type": account_type,
        "balance_min": balance_min,
        "balance_max": balance_max,
        "sort_by": sort_by,
        "order": order,
    }
    cache_key = get_cache_key(request, "users", current_admin.AdminID, params)
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = get_all_users(
        page,
        per_page,
        username,
        email,
        isactive,
        account_type,
        balance_min,
        balance_max,
        sort_by,
        order,
        db,
    )
    set_to_cache(cache_key, result, CACHE_TTL_SHORT)
    return result


@router.post("/users/{user_id}/deposits", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
async def create_user_deposit(
    request: Request,
    user_id: int,
    deposit: DepositCreate,
    background_tasks: BackgroundTasks,
    current_admin: Admin = Depends(check_permission("deposit:manage")),
    db: Session = Depends(get_db),
):
    result = await create_deposit(
        user_id=user_id,
        admin_id=current_admin.AdminID,
        deposit=deposit,
        db=db,
        background_tasks=background_tasks,
    )
    invalidate_cache(f"users:user:{user_id}")  # Invalidate user-specific cache
    invalidate_cache("analytics:summary")  # Invalidate analytics cache
    return result


@router.get("/loans", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def list_all_loans(
    request: Request,
    current_admin: Admin = Depends(check_permission("loan:view_all")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    loan_status: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    loan_type_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_by: Optional[str] = Query("CreatedAt"),
    order: Optional[str] = Query("desc"),
):
    params = {
        "page": page,
        "per_page": per_page,
        "loan_status": loan_status,
        "user_id": user_id,
        "loan_type_id": loan_type_id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "sort_by": sort_by,
        "order": order,
    }
    cache_key = get_cache_key(request, "loans", current_admin.AdminID, params)
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = get_all_loans(
        db,
        page,
        per_page,
        loan_status,
        user_id,
        loan_type_id,
        start_date,
        end_date,
        sort_by,
        order,
    )
    set_to_cache(cache_key, result.model_dump(), CACHE_TTL_SHORT)
    return result


@router.put("/loans/{loan_id}/approve", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
async def approve_loan_route(
    request: Request,
    loan_id: int,
    background_tasks: BackgroundTasks,
    current_admin: Admin = Depends(check_permission("loan:approve")),
    db: Session = Depends(get_db),
):
    result = await approve_loan(loan_id, current_admin, db, background_tasks)
    invalidate_cache("loans:")
    invalidate_cache("analytics:summary")
    return result


@router.put("/users/{user_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def update_user_route(
    request: Request,
    user_id: int,
    user_update: UserUpdate,
    current_admin: Admin = Depends(check_permission("user:update")),
    db: Session = Depends(get_db),
):
    result = update_user(user_id, user_update, db)
    invalidate_cache(f"users:user:{user_id}")
    invalidate_cache("users:")
    return result


@router.delete("/users/{user_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def delete_user_route(
    request: Request,
    user_id: int,
    current_admin: Admin = Depends(check_permission("user:delete")),
    db: Session = Depends(get_db),
):
    result = delete_user(user_id, db)
    invalidate_cache(f"users:user:{user_id}")
    invalidate_cache("users:")
    return result


@router.get("/transactions", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def list_all_transactions(
    request: Request,
    current_admin: Admin = Depends(check_permission("transaction:view_all")),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    user_id: Optional[int] = Query(None),
    transaction_type: Optional[str] = Query(None),
    transaction_status: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: Optional[str] = Query("CreatedAt"),
    order: Optional[str] = Query("desc"),
    db: Session = Depends(get_db),
):
    params = {
        "page": page,
        "per_page": per_page,
        "transaction_type": transaction_type,
        "transaction_status": transaction_status,
        "user_id": user_id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "sort_by": sort_by,
        "order": order,
    }
    cache_key = get_cache_key(request, "transactions", current_admin.AdminID, params)
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = get_all_transactions(
        db,
        page,
        per_page,
        transaction_type,
        transaction_status,
        user_id,
        start_date,
        end_date,
        sort_by,
        order,
    )
    set_to_cache(
        cache_key, result.model_dump(), CACHE_TTL_SHORT
    )  # 5 min TTL for transactions
    return result


@router.get("/cards", response_model=PaginatedResponse)
@limiter.limit(os.getenv("RATE_LIMIT_USER_DEFAULT", "100/hour"))
def list_all_cards_route(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    user_id: Optional[int] = Query(None),
    current_admin: Admin = Depends(check_permission("card:view_all")),
    db: Session = Depends(get_db),
):
    params = {"page": page, "per_page": per_page, "user_id": user_id}
    cache_key = get_cache_key(request, "cards", current_admin.AdminID, params)
    cached = get_from_cache(cache_key)
    if cached:
        return PaginatedResponse(**cached)
    result = list_all_cards(db, page, per_page, user_id)
    set_to_cache(cache_key, result.model_dump(), CACHE_TTL_MEDIUM)  # 1 hr TTL for cards
    return result


@router.put("/cards/{card_id}/block", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def block_card_route(
    request: Request,
    card_id: int,
    current_admin: Admin = Depends(check_permission("card:manage")),
    db: Session = Depends(get_db),
):
    result = block_card(card_id, db)
    invalidate_cache("cards:")
    return result


@router.put("/cards/{card_id}", response_model=BaseResponse)
@limiter.limit(os.getenv("RATE_LIMIT_ADMIN_CRITICAL", "10/minute"))
def update_card_admin_route(
    request: Request,
    card_id: int,
    card_update: CardUpdate,
    current_admin: Admin = Depends(check_permission("card:manage")),
    db: Session = Depends(get_db),
):
    result = update_card_admin(card_id, card_update, db)
    invalidate_cache("cards:")
    return result


@router.get("/transactions/export")
@limiter.limit(os.getenv("RATE_LIMIT_EXPORT", "5/hour"))
def export_transactions_route(
    request: Request,
    user_id: Optional[int] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    transaction_status: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    current_admin: Admin = Depends(check_permission("transactions:export")),
    db: Session = Depends(get_db),
):
    return export_transactions(
        db, user_id, start_date, end_date, transaction_status, transaction_type
    )
