from pyngrok import ngrok, conf

from config import settings


_public_url: str = ""


def start(port: int = 8000) -> str:
    global _public_url
    if settings.ngrok_auth_token:
        conf.get_default().auth_token = settings.ngrok_auth_token
    kwargs = {"addr": port, "proto": "http"}
    if settings.ngrok_domain:
        kwargs["hostname"] = settings.ngrok_domain
    tunnel = ngrok.connect(**kwargs)
    _public_url = tunnel.public_url.replace("http://", "https://")
    return _public_url


def get_public_url() -> str:
    return _public_url
