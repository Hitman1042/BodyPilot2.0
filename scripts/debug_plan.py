from core.training_service import generate_daily_workout_plan

plan = generate_daily_workout_plan(756020893, force_refresh=True)

if not plan:
    print("❌ План пустой!")
else:
    print(f"✅ План сгенерирован!")
    print(f"Всего упражнений: {len(plan.get('exercises', []))}")

    modules = plan.get('modules', {})
    for mod_name, exercises in modules.items():
        print(f"  {mod_name}: {len(exercises)} упражнений")
        for ex in exercises[:3]:
            print(f"    • {ex['name']}")