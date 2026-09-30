"""Staff authentication shared by every privileged API route."""
import os
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

basic = HTTPBasic(auto_error=False)


def require_staff(credentials: HTTPBasicCredentials | None = Depends(basic)):
    username = os.environ.get("TAKEAWAY_STAFF_USERNAME", "")
    password = os.environ.get("TAKEAWAY_STAFF_PASSWORD", "")
    if not username or len(password) < 16:
        raise HTTPException(403, "Staff login has not been configured.")
    supplied_user = credentials.username if credentials else ""
    supplied_password = credentials.password if credentials else ""
    user_ok = secrets.compare_digest(supplied_user.encode(), username.encode())
    password_ok = secrets.compare_digest(supplied_password.encode(), password.encode())
    if not (user_ok and password_ok):
        raise HTTPException(401, "Incorrect staff username or password.",
                            headers={"WWW-Authenticate": "Basic"})
