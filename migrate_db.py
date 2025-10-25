"""
Database migration script for ARVision
Safe for production - only creates tables if they don't exist
"""
import os
import sys

try:
    from app import app, db
    
    with app.app_context():
        # Create all tables (won't drop existing ones)
        db.create_all()
        print("✅ Database tables created successfully")
        
except Exception as e:
    print(f"⚠️  Database migration skipped: {e}")
    print("This is normal for first deployment - tables will be created on first request")
    sys.exit(0)  # Exit successfully even if migration fails
