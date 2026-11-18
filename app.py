"""Entry point for Vercel / uvicorn. The real app lives in backend/app.py; the website in frontend/."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from main import app  # noqa: E402,F401
