"""
Auth router: login and get current user.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from core.db import get_db
from core.auth import create_token, get_current_user, pwd_context

router = APIRouter(prefix="/auth", tags=["auth"])


class UserLogin(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(data: UserLogin, request: Request = None):
    db = get_db()
    user = await db.admin_users.find_one({"username": data.username})
    if not user or not pwd_context.verify(data.password, user.get("password", "")):
        raise HTTPException(401, "Invalid credentials")

    # FIX: Legacy users from v2 might not have 'id' or 'role'
    needs_update = False
    upd_auth = {}
    if "id" not in user:
        import uuid
        user["id"] = str(uuid.uuid4())
        upd_auth["id"] = user["id"]
        needs_update = True
    if "role" not in user:
        user["role"] = "administrator"
        upd_auth["role"] = user["role"]
        needs_update = True
        
    if needs_update:
        await db.admin_users.update_one({"_id": user["_id"]}, {"$set": upd_auth})

    # Remove ObjectId so it's JSON serializable
    user.pop("_id", None)

    # Audit log: LOGIN event
    try:
        from routers.audit import log_action
        ip = request.client.host if request and request.client else ""
        await log_action(
            action="LOGIN",
            resource="auth",
            details=f"User '{data.username}' logged in",
            username=data.username,
            user_id=str(user.get("id", "")),
            ip_address=ip,
        )
    except Exception:
        pass

    return {"token": create_token(user), "user": {k: v for k, v in user.items() if k != "password"}}



@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    return {k: v for k, v in user.items() if k != "password"}
