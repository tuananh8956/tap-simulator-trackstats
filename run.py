#!/usr/bin/env python3
import uvicorn
import argparse
from src.config import settings

def main():
    parser = argparse.ArgumentParser(description="Tap Simulator Reborn TrackStats Server")
    parser.add_argument("--port", type=int, default=settings.port, help=f"Port to bind (default: {settings.port})")
    parser.add_argument("--host", type=str, default=settings.host, help=f"Host to bind (default: {settings.host})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    print("=" * 65)
    print("  TAP SIMULATOR REBORN – TRACKSTATS SYSTEM")
    print("=" * 65)
    print(f"  [+] Host:            http://{args.host}:{args.port}")
    print(f"  [+] Dashboard UI:    http://127.0.0.1:{args.port}/")
    print(f"  [+] Telemetry Ingest: POST http://127.0.0.1:{args.port}/api/v1/telemetry")
    print(f"  [+] Target Game:     Place ID 72858262610964")
    print("=" * 65)

    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

if __name__ == "__main__":
    main()
