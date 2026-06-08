import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

bearer_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """Verify the JWT token from the Authorization header and return the user's email. Ensures only valid requests are handled."""
    try:
        # decode the JWT token using same key as set in fronend env.local
        payload = jwt.decode(
            credentials.credentials,
            os.environ["JWT_SECRET"],
            algorithms=["HS256"],
        )
        identifier: str = payload.get("identifier")
        if not identifier:
            raise HTTPException(status_code=401, detail="Invalid token")
        return identifier
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
