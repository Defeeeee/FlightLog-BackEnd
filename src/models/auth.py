from pydantic import BaseModel, EmailStr

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str

class TokenRefresh(BaseModel):
    refresh_token: str


class PasswordRecover(BaseModel):
    email: EmailStr

class PasswordUpdate(BaseModel):
    password: str
