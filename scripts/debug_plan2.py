from core.training_service import generate_daily_workout_plan
from core.database import get_user

user_id = 756020893  # Твой ID
print(f"Проверка для пользователя {user_id}...")

user = get_user(user_id)
print(f"Пользователь: {user}")

print("\nГенерация плана...")
plan = generate_daily_workout_plan(user_id, force_refresh=True)

if not plan:
    print("❌ План пустой (None)!")
elif not plan.get('exercises'):
    print("❌ План есть, но упражнений нет!")
    print(f"Plan: {plan}")
else:
    print(f"✅ План сгенерирован!")
    print(f"Всего упражнений: {len(plan.get('exercises', []))}")

    modules = plan.get('modules', {})
    for mod_name, exercises in modules.items():
        print(f"  {mod_name}: {len(exercises)} упражнений")
        for ex in exercises[:2]:
            print(f"    • {ex.get('name', '???')}")