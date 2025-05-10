from db import db

def add_cancelled_column():
    try:
        # Проверяем существование колонки
        db.cursor.execute("PRAGMA table_info(orders)")
        columns = [col[1] for col in db.cursor.fetchall()]
        
        if 'is_cancelled' not in columns:
            db.cursor.execute("ALTER TABLE orders ADD COLUMN is_cancelled BOOLEAN DEFAULT FALSE")
            db.conn.commit()
            print("✅ Колонка is_cancelled успешно добавлена")
        else:
            print("ℹ️ Колонка is_cancelled уже существует")
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")

if __name__ == "__main__":
    print("Запуск миграции БД...")
    add_cancelled_column()
    print("Миграция завершена")