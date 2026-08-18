from litestar import Controller, post, get, status_codes
from litestar.exceptions import InternalServerException, NotAuthorizedException, TooManyRequestsException
from supabase import Client
from src.supabase_client import SupabaseManager
from src.models.auth import UserRegister, UserLogin, AuthResponse, PasswordRecover, PasswordUpdate, TokenRefresh

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

    @post("/refresh")
    async def refresh(self, supabase_client: Client, data: TokenRefresh) -> AuthResponse:
        """
        Canjea un refresh token por un par nuevo. **La sesión de Vector no se
        renovaba nunca antes de esto.**

        El `access_token` de Supabase vive una hora; la cookie `session_token` del
        frontend vive veinticuatro. Entre la hora 1 y la 24 el proxy veía la cookie,
        dejaba pasar, y **todas las páginas pedían con un JWT vencido** → 401 →
        logout. O sea: la sesión no moría a las 24 h, moría a la hora, y encima de
        una forma que parecía un bug de datos y no de sesión.

        El `refresh_token` se venía guardando en una cookie de 30 días desde hace
        meses **sin que existiera un solo pedazo de código —ni acá ni en el
        frontend— que lo canjeara.** Este endpoint es esa mitad faltante; la otra
        vive en `src/proxy.ts`, que es el único lugar de Next donde se puede
        escribir una cookie.

        Dos cosas que hay que tener presentes al tocar esto:

        1. **Los refresh token son de un solo uso.** Cada canje devuelve uno nuevo e
           invalida el anterior, así que el llamador tiene que guardar *los dos*
           tokens que salen de acá. Guardar sólo el access token deja la sesión
           muerta en la próxima renovación, que es peor que no renovar.
        2. **GoTrue tolera reusar el mismo refresh token durante ~10 s** y en esa
           ventana devuelve la misma sesión. Es lo que salva el caso de dos
           navegaciones simultáneas con el token vencido: las dos canjean, las dos
           reciben lo mismo. Fuera de esa ventana la segunda recibe 401, y el 401
           acá significa "andá a login", no "reintentá".

        Sin guard a propósito: quien llama acá **no tiene** un access token válido
        —ése es justamente el motivo por el que llama—. La autorización es el
        refresh token mismo, que Supabase valida.
        """
        try:
            auth_response = supabase_client.auth.refresh_session(data.refresh_token)
        except Exception as e:
            # Refresh token vencido, ya usado o revocado. Es el camino esperado
            # cuando alguien vuelve después de 30 días, no un error del servidor.
            error_msg = getattr(e, "message", str(e))
            raise NotAuthorizedException(detail=f"Refresh failed: {error_msg}")

        if not auth_response.session or not auth_response.user:
            raise NotAuthorizedException(detail="Refresh failed: no session returned")

        return AuthResponse(
            access_token=auth_response.session.access_token,
            refresh_token=auth_response.session.refresh_token,
            user_id=str(auth_response.user.id),
        )
