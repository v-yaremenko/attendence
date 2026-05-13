from pyngrok import ngrok, conf
from pyngrok.exception import PyngrokNgrokHTTPError
from config import settings  #

_public_url: str = ""


def start(port: int = 8000) -> str:
    global _public_url
    if settings.ngrok_auth_token:
        conf.get_default().auth_token = settings.ngrok_auth_token

    # 1. Check if a tunnel is already running locally on this machine
    tunnels = ngrok.get_tunnels()
    for t in tunnels:
        # If we find a tunnel already pointing to our local port, reuse it
        if str(port) in t.config.get('addr', ''):
            print(f"♻️  Reusing existing local ngrok tunnel...")
            _public_url = t.public_url.replace("http://", "https://")
            return _public_url

    # 2. Attempt to connect
    kwargs = {"addr": port, "proto": "http"}
    if settings.ngrok_domain:
        kwargs["hostname"] = settings.ngrok_domain

    try:
        tunnel = ngrok.connect(**kwargs)
        _public_url = tunnel.public_url.replace("http://", "https://")
    except PyngrokNgrokHTTPError as e:
        # 3. Handle the "Already Online" error
        if "already online" in str(e).lower():
            print("⚠️  Domain is already online elsewhere.")
            # Try to grab the public URL from the active tunnels again
            active_tunnels = ngrok.get_tunnels()
            if active_tunnels:
                _public_url = active_tunnels[0].public_url.replace("http://", "https://")
                print(f"🔗 Found existing URL: {_public_url}")
            else:
                print("❌ The domain is likely being used by another computer (your friend?).")
                print("   They MUST stop their ngrok process before you can start yours.")
                raise e
        else:
            raise e

    return _public_url


def get_public_url() -> str:
    return _public_url