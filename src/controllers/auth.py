from litestar import Controller, post, status_codes
from litestar.exceptions import InternalServerException, NotAuthorizedException, TooManyRequestsException
from supabase import Client
from src.supabase_client import SupabaseManager
from src.models.auth import UserRegister, UserLogin, AuthResponse

class AuthController(Controller):
    path = "/auth"

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

            # Manually create the profile record in the public.profiles table
            # We use the base/anon client for the initial creation.
            # This requires an INSERT policy in Supabase for the 'anon' role.
            profile_data = {
                "id": str(auth_response.user.id),
                "first_name": data.first_name,
                "last_name": data.last_name
            }
            
            try:
                # Use a fresh anon client specifically for this insert 
                # (avoids issues if the dependency injection is holding state)
                anon_client = SupabaseManager.get_base_client()
                anon_client.table("profiles").insert(profile_data).execute()
            except Exception as profile_err:
                # If the profile already exists, we skip it; 
                # Otherwise, we log the error but don't fail the registration
                print(f"Profile creation notice (can be ignored if profile exists): {str(profile_err)}")

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
                 raise TooManyRequestsException(detail="Too many requests. Please wait a few minutes before trying again.")
            
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
                user_id=auth_response.user.id
            )
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'message'):
                error_msg = e.message
            raise NotAuthorizedException(f"Login failed: {error_msg}")
