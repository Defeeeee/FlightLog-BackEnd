"""
Que la verificación local de tokens no afloje nada de lo que la de red garantizaba.

Corre offline, sin base ni servidor: `python test_verify_token.py`.

## Por qué existe este archivo

Hasta el 2026-09-18 cada request autenticado le preguntaba a GoTrue —en
us-east-1, con el backend en São Paulo— de quién era el token. Medido desde el
server: **145 a 640 ms**, en el camino caliente, sin cache más allá de 10 s. Y
como el guard es `async` y la llamada era sincrónica, además **bloqueaba el event
loop**: seis requests concurrentes salían en escalera de ~197 ms de escalón en vez
de solaparse.

El proyecto firma con **ES256** y publica la clave pública en su JWKS, así que ese
viaje no compraba nada: la firma se puede comprobar acá, en 0,05 ms.

Cambiar una verificación de identidad por otra es exactamente el tipo de
optimización que se puede hacer mal en silencio —un token adulterado que pasa no
tira ningún error, sólo deja entrar a quien no va—, así que lo que este archivo
cubre no es el camino feliz sino **los rechazos**: firma adulterada, token
vencido, `aud`/`iss` de otro emisor, y sobre todo la **confusión de algoritmo**,
que es el modo de falla clásico de verificar JWT con claves asimétricas. Un
atacante firma HS256 usando la clave *pública* —que es pública— como si fuera el
secreto HMAC; si la lista de `algorithms` incluye HS256, la librería lo valida y
el atacante se hace pasar por cualquiera. Por eso `_verificar_localmente` lista
sólo algoritmos asimétricos, y por eso hay un test que lo prueba.

El keypair es propio y generado acá: el test no toca la red ni depende del JWKS
real, sólo del código de verificación.
"""

import base64
import hashlib
import hmac
import json
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import src.supabase_client as sc
from src.config import settings

ISS = f"{settings.supabase_url.rstrip('/')}/auth/v1"

_priv = ec.generate_private_key(ec.SECP256R1())
_pub = _priv.public_key()
_priv_pem = _priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_pub_pem = _pub.public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)


class _ClaveFalsa:
    """La pública del keypair de arriba, con la forma que espera el verificador."""

    key = _pub


# Se reemplaza la búsqueda de la clave, no el cache: así el test no sale a la red
# y sigue ejercitando `jwt.decode` con los mismos parámetros que producción.
sc._clave_de_firma = lambda token: _ClaveFalsa()


def _b64(crudo: bytes) -> bytes:
    return base64.urlsafe_b64encode(crudo).rstrip(b"=")


def acuñar(**reemplazos) -> str:
    """Un token como los que emite Supabase, firmado con el keypair del test."""
    ahora = int(time.time())
    claims = {
        "sub": "user-123",
        "aud": "authenticated",
        "iss": ISS,
        "exp": ahora + 3600,
        "iat": ahora,
    }
    claims.update(reemplazos)
    return jwt.encode(claims, _priv_pem, algorithm="ES256")


def rechaza(token: str) -> bool:
    """Verdadero si la verificación local no acepta ese token."""
    try:
        sc._verificar_localmente(token)
        return False
    except Exception:
        return True


_ok = 0
_fallaron = 0


def check(nombre: str, obtenido, esperado) -> None:
    global _ok, _fallaron
    if obtenido == esperado:
        _ok += 1
        print(f"  PASS  {nombre}")
    else:
        _fallaron += 1
        print(f"  FAIL  {nombre}: obtenido {obtenido!r}, esperado {esperado!r}")


def main() -> int:
    print("--- acepta lo que tiene que aceptar ---")
    check("token válido devuelve el sub", sc._verificar_localmente(acuñar()), "user-123")

    print("--- rechaza lo que tiene que rechazar ---")
    check("vencido", rechaza(acuñar(exp=int(time.time()) - 10)), True)
    check("audiencia de otro", rechaza(acuñar(aud="anon")), True)
    check("emisor de otro", rechaza(acuñar(iss="https://evil.example/auth/v1")), True)
    check(
        "sin exp",
        rechaza(jwt.encode({"sub": "u", "aud": "authenticated", "iss": ISS}, _priv_pem, algorithm="ES256")),
        True,
    )
    check("basura que no es un JWT", rechaza("no.es.un.jwt"), True)

    # Payload reescrito conservando la firma original.
    cabecera, _, firma = acuñar().split(".")
    payload_ajeno = _b64(
        json.dumps(
            {"sub": "attacker", "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 3600}
        ).encode()
    ).decode()
    check("payload adulterado", rechaza(f"{cabecera}.{payload_ajeno}.{firma}"), True)

    # Confusión de algoritmo: HS256 usando la clave pública como secreto HMAC.
    # PyJWT se niega a *firmar* así, con lo cual el atacante lo arma crudo; lo que
    # se prueba es el lado de la verificación, que es el que tiene que plantarse.
    cab = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    pay = _b64(
        json.dumps(
            {"sub": "attacker", "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 3600}
        ).encode()
    )
    sig = _b64(hmac.new(_pub_pem, cab + b"." + pay + b"", hashlib.sha256).digest())
    check(
        "confusión de algoritmo (HS256 con la clave pública)",
        rechaza((cab + b"." + pay + b"." + sig).decode()),
        True,
    )

    print(f"\n{_ok} passed, {_fallaron} failed")
    return 1 if _fallaron else 0


if __name__ == "__main__":
    raise SystemExit(main())
