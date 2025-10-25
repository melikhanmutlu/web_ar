"""
Production server starter using Waitress (Windows compatible)
"""
from waitress import serve
from app import app
import os

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"=" * 60)
    print(f"🚀 Starting ARVision Production Server")
    print(f"=" * 60)
    print(f"Server: Waitress (Production WSGI)")
    print(f"Host: 0.0.0.0")
    print(f"Port: {port}")
    print(f"Threads: 4")
    print(f"Timeout: 300 seconds")
    print(f"=" * 60)
    print(f"\n✅ Server running at:")
    print(f"   - http://localhost:{port}")
    print(f"   - http://127.0.0.1:{port}")
    print(f"\n⏹️  Press CTRL+C to stop")
    print(f"=" * 60)
    print()
    
    # Start server with production settings
    serve(
        app,
        host='0.0.0.0',
        port=port,
        threads=4,  # Handle multiple requests
        channel_timeout=300,  # 5 minutes for long conversions
        cleanup_interval=30,
        asyncore_use_poll=True
    )
