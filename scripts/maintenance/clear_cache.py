from core.database import get_db

conn = get_db()

# Удаляем все планы
result = conn.execute("DELETE FROM daily_workout_plans")
deleted = result.rowcount

conn.commit()

print(f"✅ Удалено {deleted} старых планов из кэша")
print("Теперь /workout_plan сгенерирует новый план!")