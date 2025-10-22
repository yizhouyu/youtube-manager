#!/usr/bin/env python3
"""Startup script for YouTube Manager Web UI."""

import os
import sys
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

# Import and run the Flask app
from web.app import app

if __name__ == '__main__':
    print("=" * 80)
    print("🚀 YouTube Manager Web UI")
    print("=" * 80)
    print()
    print("📊 Access the application at:")
    print("   Home:      http://localhost:5001")
    print("   Analytics: http://localhost:5001/analytics")
    print("   Upload:    http://localhost:5001/upload")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 80)
    print()

    # Use threaded mode and configure werkzeug for large uploads
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5001,
        threaded=True,
        # Increase request timeout for large file uploads
        use_reloader=True
    )
