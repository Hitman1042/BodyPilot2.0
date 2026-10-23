/* BodyPilot Mini App — логика фронтенда (Vue 3, без сборки) */

(function () {
    "use strict";

    var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

    // ── Тема Telegram → CSS-переменные ──────────────────────────────────
    function applyTheme() {
        if (!tg || !tg.themeParams) return;
        var tp = tg.themeParams;
        var map = {
            "--bg": tp.bg_color,
            "--bg-secondary": tp.secondary_bg_color,
            "--text": tp.text_color,
            "--hint": tp.hint_color,
            "--accent": tp.button_color,
            "--accent-text": tp.button_text_color,
        };
        var root = document.documentElement;
        Object.keys(map).forEach(function (k) {
            if (map[k]) root.style.setProperty(k, map[k]);
        });
    }

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    // ── Константы ───────────────────────────────────────────────────────
    var MEALS = [
        { key: "breakfast", title: "Завтрак", emoji: "🍳" },
        { key: "lunch", title: "Обед", emoji: "🍲" },
        { key: "dinner", title: "Ужин", emoji: "🌙" },
        { key: "snack", title: "Перекус", emoji: "🍎" },
    ];

    var MODULES = [
        { key: "warmup", title: "Разминка", emoji: "🔥" },
        { key: "mobility", title: "Мобилизация", emoji: "🤸" },
        { key: "special", title: "Специальная разминка", emoji: "🎯" },
        { key: "strength", title: "Основная сила", emoji: "🏋️" },
        { key: "accessory", title: "ОФП", emoji: "💪" },
        { key: "cool_down", title: "Заминка", emoji: "🧘" },
    ];

    function localDate(d) {
        var p = function (n) { return String(n).padStart(2, "0"); };
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    }

    function fmtNum(v) {
        if (v === null || v === undefined || isNaN(v)) return "0";
        var n = Number(v);
        return n % 1 === 0 ? String(n) : n.toFixed(1);
    }

    class ApiError extends Error {
        constructor(status, message) {
            super(message);
            this.status = status;
        }
    }

    // ── Приложение ──────────────────────────────────────────────────────
    var app = Vue.createApp({
        data: function () {
            return {
                tab: "day",
                tabs: [
                    { key: "day", emoji: "📅", label: "День" },
                    { key: "diary", emoji: "🍽", label: "Дневник" },
                    { key: "progress", emoji: "📈", label: "Прогресс" },
                    { key: "plans", emoji: "📋", label: "Планы" },
                    { key: "coach", emoji: "🤖", label: "Коуч" },
                ],
                authError: false,
                offline: false,
                toast: "",
                toastTimer: null,
                loading: { day: true, diary: true, progress: true, plans: true },
                profile: null,
                nutrition: null,
                water: null,
                workoutToday: null,
                health: null,
                diaryDate: localDate(new Date()),
                diaryEntries: [],
                weightHistory: [],
                nutritionSummary: [],
                workoutHistory: [],
                healthSteps: [],
                healthSleep: [],
                mealPlan: null,
                mealPlanError: 0,
                workoutPlan: null,
                addPanel: false,
                addForm: { meal_type: "snack", weight_g: 100 },
                searchQuery: "",
                searchResults: [],
                searching: false,
                searchDone: false,
                searchTimer: null,
                selectedProduct: null,
                deleteTarget: null,
                saving: false,
                challenges: [],
                joiningCode: "",
                photos: [],
                photoViewer: null,
                chatMessages: [],
                chatInput: "",
                chatSending: false,
                settingsOpen: false,
                settingsForm: { weight_kg: null, height_cm: null, age: null, goal: "maintain", activity: "sedentary" },
                settingsSaving: false,
                _lastRetry: null,
                _charts: {},
            };
        },

        computed: {
            displayName: function () {
                if (this.profile && this.profile.username) return this.profile.username;
                if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.first_name) {
                    return tg.initDataUnsafe.user.first_name;
                }
                return "друг";
            },
            greeting: function () {
                var h = new Date().getHours();
                if (h < 5) return "Доброй ночи";
                if (h < 12) return "Доброе утро";
                if (h < 18) return "Добрый день";
                return "Добрый вечер";
            },
            todayLabel: function () {
                return new Date().toLocaleDateString("ru-RU", {
                    weekday: "long", day: "numeric", month: "long",
                });
            },
            calOver: function () {
                return !!(this.nutrition && this.nutrition.target_calories &&
                    this.nutrition.total_calories > this.nutrition.target_calories);
            },
            hasHealthData: function () {
                var h = this.health;
                return !!(h && (h.steps_today != null || h.sleep_last_night != null ||
                    h.resting_hr_today != null));
            },
            ringDash: function () {
                var circ = 2 * Math.PI * 52;
                var p = this.nutrition && this.nutrition.target_calories
                    ? Math.min(1, this.nutrition.total_calories / this.nutrition.target_calories)
                    : (this.nutrition && this.nutrition.total_calories > 0 ? 1 : 0);
                return (circ * p).toFixed(1) + " " + circ.toFixed(1);
            },
            macroBars: function () {
                if (!this.nutrition) return [];
                var n = this.nutrition;
                var self = this;
                return [
                    { label: "Белки", value: n.total_protein_g, target: n.target_protein_g },
                    { label: "Жиры", value: n.total_fat_g, target: n.target_fat_g },
                    { label: "Углеводы", value: n.total_carbs_g, target: n.target_carbs_g },
                ].map(function (m) {
                    m.pct = m.target ? Math.min(100, Math.round((m.value / m.target) * 100)) : 0;
                    return m;
                });
            },
            workoutModules: function () {
                return this.modulesWithItems(this.workoutToday);
            },
            workoutPlanModules: function () {
                return this.modulesWithItems(this.workoutPlan);
            },
            diaryIsToday: function () {
                return this.diaryDate >= localDate(new Date());
            },
            diaryDateLabel: function () {
                if (this.diaryDate === localDate(new Date())) return "Сегодня";
                var yest = new Date();
                yest.setDate(yest.getDate() - 1);
                if (this.diaryDate === localDate(yest)) return "Вчера";
                var parts = this.diaryDate.split("-");
                var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
                return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "short" });
            },
            diaryGroups: function () {
                var self = this;
                return MEALS.map(function (m) {
                    var entries = self.diaryEntries.filter(function (e) {
                        return (e.meal_type || "snack") === m.key;
                    });
                    var cal = entries.reduce(function (s, e) { return s + (e.calories || 0); }, 0);
                    return { key: m.key, title: m.title, emoji: m.emoji, entries: entries, calories: cal };
                }).filter(function (g) { return g.entries.length > 0; });
            },
            diaryTotals: function () {
                var t = { calories: 0, protein_g: 0, fat_g: 0, carbs_g: 0 };
                this.diaryEntries.forEach(function (e) {
                    t.calories += e.calories || 0;
                    t.protein_g += e.protein_g || 0;
                    t.fat_g += e.fat_g || 0;
                    t.carbs_g += e.carbs_g || 0;
                });
                return t;
            },
            mealPlanList: function () {
                if (!this.mealPlan || !this.mealPlan.meals) return [];
                var meals = this.mealPlan.meals;
                return MEALS.filter(function (m) { return meals[m.key]; }).map(function (m) {
                    return { key: m.key, title: m.title, emoji: m.emoji, item: meals[m.key] };
                });
            },
            photoDynamics: function () {
                var withWeight = this.photos.filter(function (p) { return p.weight_kg; });
                if (withWeight.length < 2) return "";
                var sorted = withWeight.slice().sort(function (a, b) {
                    return a.taken_at < b.taken_at ? -1 : 1;
                });
                var first = sorted[0].weight_kg;
                var last = sorted[sorted.length - 1].weight_kg;
                var delta = last - first;
                var sign = delta > 0 ? "+" : "";
                return "Динамика веса: " + fmtNum(first) + " → " + fmtNum(last) + " кг (" + sign + fmtNum(delta) + ")";
            },
        },

        methods: {
            fmt: fmtNum,

            pct: function (value, target) {
                if (!target) return 0;
                return Math.min(100, Math.round((value / target) * 100));
            },

            // ── API ───────────────────────────────────────────
            api: async function (path, options) {
                var headers = { "Content-Type": "application/json" };
                if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
                var resp;
                try {
                    resp = await fetch(path, Object.assign({ headers: headers }, options || {}));
                } catch (e) {
                    this.offline = true;
                    throw e;
                }
                if (resp.status === 401) {
                    this.authError = true;
                    throw new ApiError(401, "unauthorized");
                }
                this.offline = false;
                if (resp.status === 204) return null;
                var data = null;
                try { data = await resp.json(); } catch (e) { /* пустое тело */ }
                if (!resp.ok) {
                    throw new ApiError(resp.status, (data && data.detail) || ("HTTP " + resp.status));
                }
                return data;
            },

            showToast: function (msg) {
                var self = this;
                this.toast = msg;
                clearTimeout(this.toastTimer);
                this.toastTimer = setTimeout(function () { self.toast = ""; }, 2600);
            },

            retryLast: function () {
                if (this._lastRetry) {
                    var fn = this._lastRetry;
                    this._lastRetry = null;
                    this.offline = false;
                    fn();
                }
            },

            guard: async function (loader, retryFn, loadingKey) {
                var self = this;
                if (loadingKey) this.loading[loadingKey] = true;
                try {
                    await loader();
                } catch (e) {
                    if (e instanceof ApiError && e.status !== 401) {
                        this.showToast("Ошибка: " + e.message);
                    } else if (!(e instanceof ApiError)) {
                        this.offline = true;
                        this._lastRetry = retryFn;
                    }
                } finally {
                    if (loadingKey) this.loading[loadingKey] = false;
                }
            },

            // ── Загрузчики ────────────────────────────────────
            loadDay: function () {
                var self = this;
                var fn = function () { self.loadDay(); };
                this.guard(async function () {
                    var results = await Promise.allSettled([
                        self.api("/api/v1/profile"),
                        self.api("/api/v1/nutrition/today"),
                        self.api("/api/v1/water/today"),
                        self.api("/api/v1/workouts/plan/today"),
                        self.api("/api/v1/health/summary?days=7"),
                    ]);
                    if (results[0].status === "fulfilled") self.profile = results[0].value;
                    if (results[1].status === "fulfilled") self.nutrition = results[1].value;
                    if (results[2].status === "fulfilled") self.water = results[2].value;
                    if (results[3].status === "fulfilled") self.workoutToday = results[3].value;
                    else self.workoutToday = null;
                    if (results[4].status === "fulfilled") self.health = results[4].value;
                    else self.health = null;
                    var authFail = results.some(function (r) {
                        return r.status === "rejected" && r.reason instanceof ApiError && r.reason.status === 401;
                    });
                    if (authFail) return;
                    var netFail = results.every(function (r) {
                        return r.status === "rejected" && !(r.reason instanceof ApiError);
                    });
                    if (netFail) throw results[0].reason;
                }, fn, "day");
            },

            addWater: async function (amount) {
                try {
                    this.water = await this.api("/api/v1/water", {
                        method: "POST",
                        body: JSON.stringify({ amount_ml: amount }),
                    });
                    this.showToast("💧 +" + amount + " мл");
                } catch (e) {
                    if (!(e instanceof ApiError)) this.showToast("Нет связи, попробуй ещё");
                }
            },

            loadDiary: function () {
                var self = this;
                var fn = function () { self.loadDiary(); };
                this.guard(async function () {
                    self.diaryEntries = await self.api(
                        "/api/v1/nutrition/log?date=" + self.diaryDate
                    ) || [];
                }, fn, "diary");
            },

            shiftDiaryDate: function (delta) {
                var parts = this.diaryDate.split("-");
                var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
                d.setDate(d.getDate() + delta);
                if (delta > 0 && localDate(d) > localDate(new Date())) return;
                this.diaryDate = localDate(d);
                this.loadDiary();
            },

            loadProgress: function () {
                var self = this;
                var fn = function () { self.loadProgress(); };
                this.guard(async function () {
                    var results = await Promise.allSettled([
                        self.api("/api/v1/weight/history?days=30"),
                        self.api("/api/v1/nutrition/summary?days=7"),
                        self.api("/api/v1/workouts/history?days=7"),
                        self.api("/api/v1/challenges"),
                        self.api("/api/v1/progress/photos"),
                        self.api("/api/v1/health/metrics?metric_type=steps&days=14"),
                        self.api("/api/v1/health/metrics?metric_type=sleep_hours&days=14"),
                    ]);
                    if (results[0].status === "fulfilled") self.weightHistory = results[0].value || [];
                    if (results[1].status === "fulfilled") self.nutritionSummary = results[1].value || [];
                    if (results[2].status === "fulfilled") self.workoutHistory = results[2].value || [];
                    if (results[3].status === "fulfilled") self.challenges = results[3].value || [];
                    if (results[5].status === "fulfilled") self.healthSteps = results[5].value || [];
                    if (results[6].status === "fulfilled") self.healthSleep = results[6].value || [];
                    if (results[4].status === "fulfilled") {
                        self.photos = results[4].value || [];
                        self.photos.forEach(function (p) { self.loadPhotoBlob(p); });
                    }
                    var netFail = results.every(function (r) {
                        return r.status === "rejected" && !(r.reason instanceof ApiError);
                    });
                    if (netFail) throw results[0].reason;
                }, fn, "progress").then(function () {
                    if (self.tab === "progress") {
                        Vue.nextTick(function () { self.renderCharts(); });
                    }
                });
            },

            // ── Челленджи ───────────────────────────────────
            joinChallenge: async function (code) {
                this.joiningCode = code;
                try {
                    var updated = await this.api("/api/v1/challenges/" + code + "/join", { method: "POST" });
                    this.challenges = this.challenges.map(function (ch) {
                        return ch.code === code ? updated : ch;
                    });
                    this.showToast("🎯 Ты в игре!");
                    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
                } catch (e) {
                    this.showToast(e instanceof ApiError ? ("Ошибка: " + e.message) : "Нет связи, попробуй ещё");
                } finally {
                    this.joiningCode = "";
                }
            },

            // ── Фото прогресса ──────────────────────────────
            loadPhotoBlob: async function (photo) {
                // <img> не шлёт заголовки авторизации — качаем blob и даём object URL
                var headers = {};
                if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
                try {
                    var resp = await fetch("/api/v1/progress/photos/" + photo.id + "/file", { headers: headers });
                    if (!resp.ok) return;
                    var blob = await resp.blob();
                    photo.url = URL.createObjectURL(blob);
                } catch (e) { /* останется заглушка */ }
            },

            photoDate: function (p) {
                var d = (p.taken_at || "").slice(0, 10);
                if (!d) return "";
                return d.split("-").reverse().join(".");
            },

            // ── Настройки профиля ───────────────────────────
            openSettings: function () {
                if (this.profile) {
                    this.settingsForm = {
                        weight_kg: this.profile.weight_kg,
                        height_cm: this.profile.height_cm,
                        age: this.profile.age,
                        goal: this.profile.goal || "maintain",
                        activity: this.profile.activity || "sedentary",
                    };
                }
                this.settingsOpen = true;
            },

            saveSettings: async function () {
                var self = this;
                this.settingsSaving = true;
                try {
                    var payload = {};
                    ["weight_kg", "height_cm", "age", "goal", "activity"].forEach(function (k) {
                        var v = self.settingsForm[k];
                        if (v !== null && v !== "" && v !== undefined) payload[k] = v;
                    });
                    this.profile = await this.api("/api/v1/profile", {
                        method: "PATCH",
                        body: JSON.stringify(payload),
                    });
                    this.settingsOpen = false;
                    this.showToast("✅ Сохранено");
                    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
                    this.loadDay();
                } catch (e) {
                    this.showToast(e instanceof ApiError ? ("Ошибка: " + e.message) : "Нет связи, попробуй ещё");
                } finally {
                    this.settingsSaving = false;
                }
            },

            // ── AI-коуч ─────────────────────────────────────
            sendChat: async function () {
                var self = this;
                var question = this.chatInput.trim();
                if (!question || this.chatSending) return;
                this.chatMessages.push({ role: "user", text: question });
                this.chatInput = "";
                this.chatSending = true;
                this.scrollChat();
                try {
                    var resp = await this.api("/api/v1/chat", {
                        method: "POST",
                        body: JSON.stringify({ question: question }),
                    });
                    this.chatMessages.push({ role: "coach", text: resp.answer, tools: resp.tools_used || [] });
                    if (resp.tools_used && resp.tools_used.length) {
                        this.loadDay();
                        this.loadDiary();
                    }
                } catch (e) {
                    var msg = e instanceof ApiError && e.status === 409
                        ? "Подожди, я ещё отвечаю на прошлый вопрос ⏳"
                        : "Коуч недоступен, попробуй позже 🙁";
                    this.chatMessages.push({ role: "coach", text: msg });
                } finally {
                    this.chatSending = false;
                    this.scrollChat();
                }
            },

            scrollChat: function () {
                var self = this;
                Vue.nextTick(function () {
                    var box = self.$refs.chatBox;
                    if (box) box.scrollTop = box.scrollHeight;
                });
            },

            loadPlans: function () {
                var self = this;
                var fn = function () { self.loadPlans(); };
                this.guard(async function () {
                    var results = await Promise.allSettled([
                        self.api("/api/v1/plans/meal/today"),
                        self.api("/api/v1/workouts/plan/today"),
                    ]);
                    if (results[0].status === "fulfilled") {
                        self.mealPlan = results[0].value;
                        self.mealPlanError = 0;
                    } else if (results[0].reason instanceof ApiError) {
                        self.mealPlan = null;
                        self.mealPlanError = results[0].reason.status;
                    }
                    if (results[1].status === "fulfilled") self.workoutPlan = results[1].value;
                    else self.workoutPlan = null;
                    var netFail = results.every(function (r) {
                        return r.status === "rejected" && !(r.reason instanceof ApiError);
                    });
                    if (netFail) throw results[0].reason;
                }, fn, "plans");
            },

            // ── Тренировки: модули и схемы ────────────────────
            modulesWithItems: function (plan) {
                if (!plan || !plan.exercises || !plan.exercises.length) return [];
                var exs = plan.exercises;
                var result = [];
                MODULES.forEach(function (m) {
                    var items = exs.filter(function (e) { return e.category === m.key; });
                    if (items.length) {
                        result.push({ key: m.key, title: m.title, emoji: m.emoji, items: items });
                    }
                });
                return result;
            },

            exScheme: function (ex) {
                if (!ex) return "";
                if (ex.duration_min) return ex.duration_min + " мин";
                var parts = [];
                if (ex.sets) parts.push(ex.sets + "×" + (ex.reps_min || "?") + (ex.reps_max && ex.reps_max !== ex.reps_min ? "-" + ex.reps_max : ""));
                if (ex.weight_kg) parts.push(ex.weight_kg + " кг");
                if (ex.rest_sec) parts.push("отдых " + ex.rest_sec + " с");
                return parts.join(" · ");
            },

            // ── Дневник: добавление и удаление ────────────────
            openAddPanel: function () {
                this.addPanel = true;
                this.searchQuery = "";
                this.searchResults = [];
                this.searchDone = false;
                this.selectedProduct = null;
                this.addForm = { meal_type: "snack", weight_g: 100 };
                this.runSearch();
            },

            closeAddPanel: function () {
                this.addPanel = false;
                this.selectedProduct = null;
            },

            onSearchInput: function () {
                var self = this;
                this.selectedProduct = null;
                clearTimeout(this.searchTimer);
                this.searchTimer = setTimeout(function () { self.runSearch(); }, 300);
            },

            runSearch: async function () {
                var self = this;
                this.searching = true;
                try {
                    this.searchResults = await this.api(
                        "/api/v1/nutrition/products?query=" + encodeURIComponent(this.searchQuery.trim()) + "&limit=20"
                    ) || [];
                } catch (e) {
                    this.searchResults = [];
                    if (!(e instanceof ApiError)) this.showToast("Нет связи, попробуй ещё");
                } finally {
                    this.searching = false;
                    this.searchDone = true;
                }
            },

            selectProduct: function (p) {
                this.selectedProduct = p;
                if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
            },

            saveEntry: async function () {
                var self = this;
                if (!this.selectedProduct || !this.addForm.weight_g) return;
                this.saving = true;
                try {
                    await this.api("/api/v1/nutrition/log", {
                        method: "POST",
                        body: JSON.stringify({
                            product_id: this.selectedProduct.id,
                            weight_g: this.addForm.weight_g,
                            meal_type: this.addForm.meal_type,
                        }),
                    });
                    this.showToast("✅ Добавлено");
                    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
                    this.closeAddPanel();
                    this.loadDiary();
                } catch (e) {
                    this.showToast(e instanceof ApiError ? ("Ошибка: " + e.message) : "Нет связи, попробуй ещё");
                } finally {
                    this.saving = false;
                }
            },

            askDelete: function (entry) {
                this.deleteTarget = entry;
            },

            confirmDelete: async function () {
                var self = this;
                if (!this.deleteTarget) return;
                this.saving = true;
                try {
                    await this.api("/api/v1/nutrition/log/" + this.deleteTarget.id, { method: "DELETE" });
                    this.showToast("🗑 Запись удалена");
                    this.deleteTarget = null;
                    this.loadDiary();
                } catch (e) {
                    this.showToast(e instanceof ApiError ? ("Ошибка: " + e.message) : "Нет связи, попробуй ещё");
                } finally {
                    this.saving = false;
                }
            },

            // ── Графики ───────────────────────────────────────
            renderCharts: function () {
                if (typeof Chart === "undefined") return;
                var textColor = cssVar("--hint") || "#94a3b8";
                var accent = cssVar("--accent") || "#3390ec";
                var ok = cssVar("--ok") || "#22c55e";
                var danger = cssVar("--danger") || "#ef4444";
                Chart.defaults.color = textColor;
                Chart.defaults.borderColor = "rgba(148, 163, 184, 0.15)";

                this.renderWeightChart(accent);
                this.renderCalChart(ok, accent);
                this.renderWorkoutChart(accent);
                this.renderStepsChart(accent);
                this.renderSleepChart(ok, danger);
            },

            destroyChart: function (key) {
                if (this._charts[key]) {
                    this._charts[key].destroy();
                    delete this._charts[key];
                }
            },

            renderWeightChart: function (accent) {
                var el = this.$refs.weightChart;
                if (!el || !this.weightHistory.length) return;
                this.destroyChart("weight");
                var sorted = this.weightHistory.slice().sort(function (a, b) {
                    return a.date < b.date ? -1 : 1;
                });
                this._charts.weight = new Chart(el, {
                    type: "line",
                    data: {
                        labels: sorted.map(function (p) { return p.date.slice(5); }),
                        datasets: [{
                            label: "Вес, кг",
                            data: sorted.map(function (p) { return p.weight_kg; }),
                            borderColor: accent,
                            backgroundColor: "rgba(51, 144, 236, 0.15)",
                            fill: true,
                            tension: 0.3,
                            pointRadius: 2,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: { legend: { display: false } },
                    },
                });
            },

            renderCalChart: function (ok, accent) {
                var el = this.$refs.calChart;
                if (!el || !this.nutritionSummary.length) return;
                this.destroyChart("cal");
                var sorted = this.nutritionSummary.slice().sort(function (a, b) {
                    return a.day < b.day ? -1 : 1;
                });
                var datasets = [{
                    label: "Ккал",
                    data: sorted.map(function (d) { return d.calories; }),
                    backgroundColor: "rgba(34, 197, 94, 0.7)",
                    borderRadius: 6,
                    order: 2,
                }];
                var target = this.nutrition && this.nutrition.target_calories;
                if (target) {
                    datasets.push({
                        label: "Норма",
                        data: sorted.map(function () { return target; }),
                        type: "line",
                        borderColor: accent,
                        borderDash: [6, 4],
                        pointRadius: 0,
                        order: 1,
                    });
                }
                this._charts.cal = new Chart(el, {
                    type: "bar",
                    data: {
                        labels: sorted.map(function (d) { return d.day.slice(5); }),
                        datasets: datasets,
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: { legend: { display: false } },
                    },
                });
            },

            renderWorkoutChart: function (accent) {
                var el = this.$refs.workoutChart;
                if (!el || !this.workoutHistory.length) return;
                this.destroyChart("workout");
                var byDay = {};
                this.workoutHistory.forEach(function (s) {
                    var d = (s.date || "").slice(0, 10);
                    if (!d) return;
                    if (!byDay[d]) byDay[d] = { min: 0, tonnage: 0 };
                    byDay[d].min += s.duration_min || 0;
                    (s.exercises || []).forEach(function (ex) {
                        (ex.sets || []).forEach(function (st) {
                            byDay[d].tonnage += (st.weight_kg || 0) * (st.reps || 0);
                        });
                    });
                });
                var days = Object.keys(byDay).sort();
                if (!days.length) return;
                this._charts.workout = new Chart(el, {
                    type: "bar",
                    data: {
                        labels: days.map(function (d) { return d.slice(5); }),
                        datasets: [{
                            label: "Минуты",
                            data: days.map(function (d) { return byDay[d].min; }),
                            backgroundColor: "rgba(51, 144, 236, 0.7)",
                            borderRadius: 6,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    afterLabel: function (ctx) {
                                        var t = byDay[days[ctx.dataIndex]].tonnage;
                                        return t > 0 ? ("Тоннаж: " + Math.round(t) + " кг") : "";
                                    },
                                },
                            },
                        },
                    },
                });
            },

            _metricsByDay: function (items) {
                var byDay = {};
                items.forEach(function (m) {
                    var d = (m.ts || "").slice(0, 10);
                    if (!d) return;
                    byDay[d] = (byDay[d] || 0) + (m.value || 0);
                });
                return byDay;
            },

            renderStepsChart: function (accent) {
                var el = this.$refs.stepsChart;
                if (!el) return;
                var byDay = this._metricsByDay(this.healthSteps);
                var days = Object.keys(byDay).sort();
                if (days.length < 2) return;
                this.destroyChart("steps");
                this._charts.steps = new Chart(el, {
                    type: "bar",
                    data: {
                        labels: days.map(function (d) { return d.slice(5); }),
                        datasets: [{
                            label: "Шаги",
                            data: days.map(function (d) { return byDay[d]; }),
                            backgroundColor: "rgba(51, 144, 236, 0.7)",
                            borderRadius: 6,
                        }],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: { legend: { display: false } },
                    },
                });
            },

            renderSleepChart: function (ok, danger) {
                var el = this.$refs.sleepChart;
                if (!el) return;
                var byDay = this._metricsByDay(this.healthSleep);
                var days = Object.keys(byDay).sort();
                if (days.length < 2) return;
                this.destroyChart("sleep");
                this._charts.sleep = new Chart(el, {
                    type: "bar",
                    data: {
                        labels: days.map(function (d) { return d.slice(5); }),
                        datasets: [
                            {
                                label: "Сон, ч",
                                data: days.map(function (d) { return byDay[d]; }),
                                backgroundColor: "rgba(34, 197, 94, 0.7)",
                                borderRadius: 6,
                                order: 2,
                            },
                            {
                                label: "Норма 8 ч",
                                data: days.map(function () { return 8; }),
                                type: "line",
                                borderColor: danger,
                                borderDash: [6, 4],
                                pointRadius: 0,
                                order: 1,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        plugins: { legend: { display: false } },
                    },
                });
            },

            // ── Навигация ─────────────────────────────────────
            switchTab: function (key) {
                this.tab = key;
                if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
                if (key === "progress" && !this.loading.progress) {
                    var self = this;
                    Vue.nextTick(function () { self.renderCharts(); });
                }
                if (key === "coach") this.scrollChat();
            },
        },

        mounted: function () {
            applyTheme();
            if (tg) {
                tg.ready();
                tg.expand();
                if (tg.onEvent) {
                    var self = this;
                    tg.onEvent("themeChanged", function () {
                        applyTheme();
                        if (self.tab === "progress" && !self.loading.progress) self.renderCharts();
                    });
                }
            }
            this.loadDay();
            this.loadDiary();
            this.loadProgress();
            this.loadPlans();
        },
    });

    app.mount("#app");
})();
