from app import app, db
from sqlalchemy import text, inspect

def migrate_db():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('user_model')]
        
        if 'usdz_filename' not in columns:
            print("Adding usdz_filename column to user_model table...")
            try:
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE user_model ADD COLUMN usdz_filename VARCHAR(255)"))
                    conn.commit()
                print("Column added successfully.")
            except Exception as e:
                print(f"Error adding column: {e}")
        else:
            print("usdz_filename column already exists.")

if __name__ == "__main__":
    migrate_db()
