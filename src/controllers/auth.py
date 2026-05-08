from litestar import Controller, post, get, status_codes
from litestar.exceptions import InternalServerException, NotAuthorizedException, TooManyRequestsException
from supabase import Client
from src.supabase_client import SupabaseManager
from src.models.auth import UserRegister, UserLogin, AuthResponse, PasswordRecover, PasswordUpdate

class AuthController(Controller):
    path = "/auth"

    @get("/login/google")
    async def login_google(self, supabase_client: Client) -> dict:
        """Get the Google OAuth login URL from Supabase."""
        try:
            # Force Google to show account selection by using 'prompt': 'select_account'
            # Note: Python client uses 'query_params' (snake_case)
            auth_response = supabase_client.auth.sign_in_with_oauth({
                "provider": "google",
                "options": {
                    "redirectTo": "https://vector.fdiaznem.com.ar/auth/callback",
                    "query_params": {"prompt": "select_account"}
                }
            })
            return {"url": auth_response.url}
        except Exception as e:
            error_msg = getattr(e, "message", str(e))
            raise InternalServerException(detail=f"Google login initiation failed: {error_msg}")

    @post("/recover")
    async def recover_password(self, supabase_client: Client, data: PasswordRecover) -> dict:
        """Send a password recovery email."""
        try:
            supabase_client.auth.reset_password_for_email(data.email, {
                "redirect_to": "https://vector.fdiaznem.com.ar/update-password"
            })
            return {"message": "Recovery email sent"}
        except Exception as e:
            error_msg = getattr(e, "message", str(e))
            raise InternalServerException(detail=f"Recovery failed: {error_msg}")

    @post("/update-password")
    async def update_password(self, supabase_client: Client, data: PasswordUpdate) -> dict:
        """Update the user's password. Requires an active session."""
        try:
            auth_response = supabase_client.auth.update_user({
                "password": data.password
            })
            
            if not auth_response.user:
                raise InternalServerException(detail="Password update failed")
                
            return {"message": "Password updated successfully"}
        except Exception as e:
            error_msg = getattr(e, "message", str(e))
            raise InternalServerException(detail=f"Update failed: {error_msg}")

    @post("/register", status_code=status_codes.HTTP_201_CREATED)
    async def register(self, supabase_client: Client, data: UserRegister) -> AuthResponse:
        """Register a new user in Supabase Auth."""
        try:
            auth_response = supabase_client.auth.sign_up({
                "email": data.email,
                "password": data.password,
                "options": {
                    "data": {
                        "first_name": data.first_name,
                        "last_name": data.last_name
                    }
                }
            })

            if not auth_response.user:
                raise InternalServerException(detail="User creation failed")

            profile_data = {
                "id": str(auth_response.user.id),
                "first_name": data.first_name,
                "last_name": data.last_name
            }
            
            try:
                anon_client = SupabaseManager.get_base_client()
                anon_client.table("profiles").insert(profile_data).execute()
            except Exception as profile_err:
                print(f"Profile creation notice: {str(profile_err)}")

            if not auth_response.session:
                 return AuthResponse(
                     access_token="", 
                     refresh_token="", 
                     user_id=str(auth_response.user.id)
                 )

            return AuthResponse(
                access_token=auth_response.session.access_token,
                refresh_token=auth_response.session.refresh_token,
                user_id=str(auth_response.user.id)
            )
        except Exception as e:
            error_msg = getattr(e, "message", str(e))
            if "429" in error_msg or "rate limit" in error_msg.lower():
                 raise TooManyRequestsException(detail="Too many requests. Please wait a few minutes.")
            raise InternalServerException(detail=f"Registration failed: {error_msg}")

    @post("/login")
    async def login(self, supabase_client: Client, data: UserLogin) -> AuthResponse:
        """Log in a user."""
        try:
            auth_response = supabase_client.auth.sign_in_with_password({
                "email": data.email,
                "password": data.password
            })
            
            if not auth_response.session:
                raise NotAuthorizedException("Invalid login credentials.")

            return AuthResponse(
                access_token=auth_response.session.access_token,
                refresh_token=auth_response.session.refresh_token,
                user_id=str(auth_response.user.id)
            )
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'message'):
                error_msg = e.message
            raise NotAuthorizedException(f"Login failed: {error_msg}")
