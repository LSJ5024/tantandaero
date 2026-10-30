"""Vercel 서버리스 진입점: 루트의 Flask app을 그대로 사용"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app  # noqa: E402,F401
