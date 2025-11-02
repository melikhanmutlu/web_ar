"""
Database migration script to add ModelVersion table
Run this script to add version tracking to existing database
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Add ModelVersion table to existing database"""
    
    db_path = 'instance/app.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        print("Creating new database...")
        os.makedirs('instance', exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if table already exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='model_version'
        """)
        
        if cursor.fetchone():
            print("⚠️  ModelVersion table already exists!")
            response = input("Do you want to drop and recreate it? (yes/no): ")
            if response.lower() == 'yes':
                cursor.execute("DROP TABLE model_version")
                print("✅ Dropped existing table")
            else:
                print("❌ Migration cancelled")
                return False
        
        # Create ModelVersion table
        cursor.execute("""
            CREATE TABLE model_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id VARCHAR(36) NOT NULL,
                version_number INTEGER NOT NULL,
                filename VARCHAR(255) NOT NULL,
                file_size INTEGER,
                operation_type VARCHAR(50) NOT NULL,
                operation_details TEXT,
                dimensions TEXT,
                vertices INTEGER,
                faces INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                comment VARCHAR(500),
                FOREIGN KEY (model_id) REFERENCES user_model(id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX idx_model_version_model_id 
            ON model_version(model_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_model_version_created_at 
            ON model_version(created_at)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_model_version_number 
            ON model_version(model_id, version_number)
        """)
        
        conn.commit()
        print("✅ ModelVersion table created successfully!")
        print("✅ Indexes created successfully!")
        
        # Show table info
        cursor.execute("PRAGMA table_info(model_version)")
        columns = cursor.fetchall()
        print("\n📊 Table structure:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def verify_migration():
    """Verify that migration was successful"""
    
    db_path = 'instance/app.db'
    
    if not os.path.exists(db_path):
        print("❌ Database not found")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='model_version'
        """)
        
        if not cursor.fetchone():
            print("❌ ModelVersion table not found")
            return False
        
        # Check indexes
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND tbl_name='model_version'
        """)
        
        indexes = cursor.fetchall()
        print(f"\n✅ Found {len(indexes)} indexes:")
        for idx in indexes:
            print(f"  - {idx[0]}")
        
        # Count versions
        cursor.execute("SELECT COUNT(*) FROM model_version")
        count = cursor.fetchone()[0]
        print(f"\n📊 Current version count: {count}")
        
        return True
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False
        
    finally:
        conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Database Migration: Add ModelVersion Table")
    print("=" * 60)
    print()
    
    # Run migration
    if migrate_database():
        print("\n" + "=" * 60)
        print("✅ Migration completed successfully!")
        print("=" * 60)
        print()
        
        # Verify
        print("🔍 Verifying migration...")
        if verify_migration():
            print("\n✅ Verification passed!")
            print("\n📝 Next steps:")
            print("  1. Restart your Flask application")
            print("  2. Upload a new model to test version tracking")
            print("  3. Make modifications and check version history")
        else:
            print("\n⚠️  Verification failed - please check manually")
    else:
        print("\n❌ Migration failed - please check errors above")
