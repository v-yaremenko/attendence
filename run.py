import subprocess
import uvicorn
from config import settings

if __name__ == "__main__":
    cf_proc = None
    if settings.tunnel_mode == "cloudflare":
        if not settings.cloudflare_tunnel_name:
            raise RuntimeError("CLOUDFLARE_TUNNEL_NAME must be set when TUNNEL_MODE=cloudflare")
        cf_proc = subprocess.Popen(["cloudflared", "tunnel", "run", settings.cloudflare_tunnel_name])

    try:
        uvicorn.run("main:app", host="0.0.0.0", port=8000)
    finally:
        if cf_proc:
            cf_proc.terminate()
