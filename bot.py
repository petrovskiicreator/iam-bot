import asyncio
import json
import logging
import os
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, CallbackQuery, LabeledPrice, PreCheckoutQuery
)
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
SUPABASE_URL  = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY", "")
WEBAPP_URL    = os.getenv("WEBAPP_URL", "https://petrovskiicreator.github.io/iam-app/")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher()
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ====== STARS PRODUCTS ======

STAR_PRODUCTS = {
    "goals25":  {"title": "+25 целей", "desc": "Добавь 25 слотов для целей в IAM",  "stars": 75,   "goals": 25},
    "goals100": {"title": "+100 целей","desc": "Добавь 100 слотов для целей в IAM", "stars": 250,  "goals": 100},
    "goals500": {"title": "+500 целей","desc": "Добавь 500 слотов для целей в IAM", "stars": 999,  "goals": 500},
    "lvlSEEKER":   {"title": "Уровень Искатель 🔍", "desc": "30 дней уровня SEEKER в IAM",    "stars": 199, "lvl": "SEEKER"},
    "lvlCREATOR":  {"title": "Уровень Творец ⚡",   "desc": "30 дней уровня CREATOR в IAM",   "stars": 499, "lvl": "CREATOR"},
    "lvlVISIONARY":{"title": "Уровень Визионер 👁", "desc": "30 дней уровня VISIONARY в IAM", "stars": 999, "lvl": "VISIONARY"},
}

# ====== KEYBOARDS ======

FREQ_LABELS = {
    "off":      "🔕 Только важные",
    "standard": "🌅 Стандарт (утро + вечер)",
    "3h":       "⏰ Каждые 3 часа",
    "1h":       "🔔 Каждый час",
}

def open_app_kb(text="Открыть IAM ✨"):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=WEBAPP_URL))
    ]])

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть IAM", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="📊 Мой прогресс", callback_data="stats"),
         InlineKeyboardButton(text="🔥 Стрик", callback_data="streak")],
        [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="refer")],
        [InlineKeyboardButton(text="⚙️ Частота уведомлений", callback_data="settings")],
    ])

def freq_kb(current="standard"):
    rows = []
    for key, label in FREQ_LABELS.items():
        text = ("✅ " if key == current else "") + label
        rows.append([InlineKeyboardButton(text=text, callback_data=f"freq_{key}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ====== REMINDER STATE MACHINE ======
# SQL to create table in Supabase:
# CREATE TABLE reminders (
#   id bigserial PRIMARY KEY,
#   user_id bigint NOT NULL,
#   goal_text text NOT NULL,
#   remind_time text NOT NULL,
#   frequency text NOT NULL,
#   tz_offset int NOT NULL DEFAULT 3,
#   created_at timestamptz DEFAULT now()
# );

remind_state: dict = {}  # uid -> {"step", "goals", "page", "goal_text", "remind_time"}

REMIND_FREQ_OPTIONS = [
    ("daily", "📅 Ежедневно"),
    ("1h",    "⏰ Каждый час"),
    ("2h",    "⏰ Каждые 2 часа"),
    ("4h",    "⏰ Каждые 4 часа"),
    ("6h",    "⏰ Каждые 6 часов"),
    ("12h",   "⏰ Каждые 12 часов"),
]
REMIND_FREQ_NAMES = {
    "daily": "ежедневно",
    "1h":   "каждый час",
    "2h":   "каждые 2ч",
    "4h":   "каждые 4ч",
    "6h":   "каждые 6ч",
    "12h":  "каждые 12ч",
}

def goals_page_kb(goals: list, page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    total = len(goals)
    start = page * page_size
    end = min(start + page_size, total)
    rows = []
    for i, g in enumerate(goals[start:end]):
        short = g["text"][:48] + ("…" if len(g["text"]) > 48 else "")
        rows.append([InlineKeyboardButton(text=short, callback_data=f"rmd_goal_{start + i}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"rmd_page_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"rmd_page_{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="rmd_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def freq_remind_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"rmd_freq_{key}")]
        for key, label in REMIND_FREQ_OPTIONS
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="rmd_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def reminders_list_kb(reminders: list) -> InlineKeyboardMarkup:
    rows = []
    for r in reminders:
        freq_label = REMIND_FREQ_NAMES.get(r["frequency"], r["frequency"])
        rows.append([
            InlineKeyboardButton(
                text=f"🕐 {r['remind_time']} · {freq_label}",
                callback_data=f"rmd_info_{r['id']}"
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"rmd_del_{r['id']}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ====== DB HELPERS ======

def upsert_user(user_id, username, first_name, ref_by=None):
    data = {
        "user_id": user_id,
        "username": username or "",
        "first_name": first_name or "",
        "notifications": True,
        "last_seen": datetime.utcnow().isoformat()
    }
    if ref_by:
        data["ref_by"] = ref_by
    sb.table("bot_users").upsert(data, on_conflict="user_id").execute()

def get_all_users_with_notifications():
    res = sb.table("bot_users").select("user_id, first_name, tz_offset, notif_freq").eq("notifications", True).execute()
    return res.data or []

def users_at_local_hour(users: list, target_hour: int) -> list:
    utc_hour = datetime.utcnow().hour
    result = []
    for u in users:
        tz = u.get("tz_offset", 3)
        local_hour = (utc_hour + tz) % 24
        if local_hour == target_hour:
            result.append(u)
    return result

def add_referral(inviter_id):
    try:
        res = sb.table("bot_users").select("referrals, extra_goals").eq("user_id", inviter_id).execute()
        if res.data:
            row = res.data[0]
            sb.table("bot_users").update({
                "referrals": (row.get("referrals") or 0) + 1,
                "extra_goals": (row.get("extra_goals") or 0) + 5
            }).eq("user_id", inviter_id).execute()
    except Exception as e:
        logger.error(f"add_referral error: {e}")

def get_user_stats(user_id):
    try:
        res = sb.table("bot_users").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else {}
    except:
        return {}

def get_user_freq(user_id):
    try:
        res = sb.table("bot_users").select("notif_freq, notifications").eq("user_id", user_id).execute()
        if res.data:
            notif = res.data[0].get("notifications", True)
            if not notif:
                return "off"
            return res.data[0].get("notif_freq") or "standard"
        return "standard"
    except:
        return "standard"

def get_goals_for_remind(user_id: int) -> list:
    try:
        res = sb.table("user_data").select("data").eq("user_id", user_id).execute()
        if res.data:
            goals = res.data[0].get("data", {}).get("goals", [])
            return [g for g in goals if not g.get("done")]
    except Exception as e:
        logger.error(f"get_goals_for_remind: {e}")
    return []

def save_reminder(user_id: int, goal_text: str, remind_time: str, frequency: str, tz_offset: int) -> bool:
    try:
        sb.table("reminders").insert({
            "user_id":     user_id,
            "goal_text":   goal_text,
            "remind_time": remind_time,
            "frequency":   frequency,
            "tz_offset":   tz_offset,
            "created_at":  datetime.utcnow().isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.error(f"save_reminder: {e}")
        return False

def get_user_reminders(user_id: int) -> list:
    try:
        res = sb.table("reminders").select("*").eq("user_id", user_id).order("created_at").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_user_reminders: {e}")
        return []

def delete_reminder(reminder_id: int, user_id: int) -> bool:
    try:
        sb.table("reminders").delete().eq("id", reminder_id).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        logger.error(f"delete_reminder: {e}")
        return False

def get_all_active_reminders() -> list:
    try:
        res = sb.table("reminders").select("*").execute()
        return res.data or []
    except Exception as e:
        logger.error(f"get_all_active_reminders: {e}")
        return []

# ====== COMMAND HANDLERS ======

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    args = message.text.split()
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_by = int(args[1].replace("ref_", ""))
            if ref_by != user.id:
                add_referral(ref_by)
                await bot.send_message(
                    ref_by,
                    "🎉 По твоей ссылке пришёл новый пользователь!\n✅ +5 целей добавлено в твой аккаунт"
                )
        except:
            pass
    # Telegram Stars purchase via deep link
    if len(args) > 1 and args[1].startswith("buy_"):
        product_key = args[1][4:]  # strip "buy_"
        if product_key in STAR_PRODUCTS:
            p = STAR_PRODUCTS[product_key]
            prices = [LabeledPrice(label=p["title"], amount=p["stars"])]
            await bot.send_invoice(
                message.chat.id,
                title=p["title"],
                description=p["desc"],
                payload=f"iam_{product_key}_{user.id}",
                currency="XTR",
                prices=prices,
            )
            return

    upsert_user(user.id, user.username, user.first_name, ref_by)
    await message.answer(
        f"✨ <b>Привет, {user.first_name}!</b>\n\n"
        "Добро пожаловать в <b>IAM</b> — дневник трансформации личности.\n\n"
        "🎯 Ставь цели во всех сферах жизни\n"
        "🔥 Проходи 21-дневный челлендж\n"
        "✍️ Веди дневник визуализации\n"
        "📊 Отслеживай прогресс каждый день\n\n"
        "<i>У успешных людей 5000+ целей.\nНачни прямо сейчас 👇</i>",
        reply_markup=main_kb()
    )

@dp.message(Command("notify"))
async def cmd_notify(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in ("on", "off"):
        await message.answer("Используй: /notify on или /notify off")
        return
    enabled = args[1] == "on"
    sb.table("bot_users").update({"notifications": enabled}).eq("user_id", message.from_user.id).execute()
    await message.answer(f"Уведомления {'включены ✅' if enabled else 'выключены ❌'}")

@dp.message(Command("remind"))
async def cmd_remind(message: Message):
    uid = message.from_user.id
    goals = get_goals_for_remind(uid)
    if not goals:
        await message.answer(
            "🎯 У тебя нет активных целей для напоминания.\n\nСначала добавь цели в IAM!",
            reply_markup=open_app_kb("Добавить цели 🎯")
        )
        return
    remind_state[uid] = {"step": "goal", "goals": goals, "page": 0}
    await message.answer(
        "🔔 <b>Новое напоминание о цели</b>\n\nВыбери цель:",
        reply_markup=goals_page_kb(goals, page=0)
    )

@dp.message(Command("reminders"))
async def cmd_reminders(message: Message):
    uid = message.from_user.id
    rems = get_user_reminders(uid)
    if not rems:
        await message.answer(
            "🔔 У тебя нет активных напоминаний.\n\n"
            "Используй /remind чтобы создать напоминание о цели."
        )
        return
    lines = []
    for r in rems:
        freq_label = REMIND_FREQ_NAMES.get(r["frequency"], r["frequency"])
        lines.append(
            f"🔔 <b>{r['remind_time']}</b> · {freq_label}\n"
            f"<i>{r['goal_text'][:70] + ('…' if len(r['goal_text']) > 70 else '')}</i>"
        )
    text = "📋 <b>Твои напоминания о целях:</b>\n\n" + "\n\n".join(lines) + "\n\n<i>Нажми 🗑 рядом с напоминанием чтобы удалить</i>"
    await message.answer(text, reply_markup=reminders_list_kb(rems))

@dp.message(Command("remind_save"))
async def cmd_remind_save(message: Message):
    uid = message.from_user.id
    raw = message.text or ""
    try:
        json_str = raw[raw.index(" ") + 1:]
        payload = json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"remind_save parse error uid={uid}: {e}")
        await message.answer("❌ Ошибка формата данных.")
        return
    goal_text   = payload.get("goal_text", "").strip()
    remind_time = payload.get("remind_time", "09:00")
    frequency   = payload.get("frequency", "daily")
    if not goal_text or frequency not in REMIND_FREQ_NAMES:
        await message.answer("❌ Неверные данные напоминания.")
        return
    if not re.match(r"^\d{2}:\d{2}$", remind_time):
        await message.answer("❌ Неверный формат времени.")
        return
    tz_offset = 3
    try:
        res = sb.table("bot_users").select("tz_offset").eq("user_id", uid).execute()
        if res.data:
            tz_offset = res.data[0].get("tz_offset", 3) or 3
    except Exception:
        pass
    ok = save_reminder(uid, goal_text, remind_time, frequency, tz_offset)
    if ok:
        await message.answer(f"✅ Напоминание создано на {remind_time}")
    else:
        await message.answer("❌ Не удалось сохранить. Попробуй /remind")

# ====== CALLBACK HANDLERS ======

@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    stats = get_user_stats(uid)
    await call.message.answer(
        f"📊 <b>Твой прогресс IAM</b>\n\n"
        f"👥 Приглашено друзей: <b>{stats.get('referrals', 0)}</b>\n"
        f"🎁 Бонусных целей: <b>{stats.get('extra_goals', 0)}</b>\n\n"
        "Остальная статистика — в приложении 👇",
        reply_markup=open_app_kb("Открыть статистику 📊")
    )

@dp.callback_query(F.data == "streak")
async def cb_streak(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "🔥 <b>Стрик</b> — дни подряд когда ты делаешь чек-ин в IAM.\n\n"
        "Открой приложение и отметь сегодняшний день!\n"
        "Не теряй стрик — это твой главный показатель 💪",
        reply_markup=open_app_kb("Отметить чек-ин ✓")
    )

@dp.callback_query(F.data == "refer")
async def cb_refer(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    ref_link = f"https://t.me/IAM_app_bot?start=ref_{uid}"
    await call.message.answer(
        f"🎁 <b>Пригласи друга — оба получите +5 целей!</b>\n\n"
        f"Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        "Отправь её другу. Когда он запустит бота — вы оба получите бонус 🎯"
    )

@dp.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    freq = get_user_freq(uid)
    await call.message.answer(
        "⚙️ <b>Частота уведомлений</b>\n\n"
        "🔕 <b>Только важные</b> — стрик, дедлайны, челлендж\n"
        "🌅 <b>Стандарт</b> — утром (8:00) и вечером (20:00)\n"
        "⏰ <b>Каждые 3 часа</b> — в 8, 11, 14, 17, 20\n"
        "🔔 <b>Каждый час</b> — с 8:00 до 22:00",
        reply_markup=freq_kb(freq)
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def payment_success(message: Message):
    payload = message.successful_payment.invoice_payload  # "iam_goals25_123456"
    parts = payload.split("_")
    uid = message.from_user.id
    try:
        if len(parts) >= 3 and parts[0] == "iam":
            product_key = parts[1]  # e.g. "goals25" or "lvlCREATOR"
            p = STAR_PRODUCTS.get(product_key, {})
            if "goals" in p:
                # Add extra goals
                res = sb.table("bot_users").select("extra_goals").eq("user_id", uid).execute()
                cur = res.data[0].get("extra_goals", 0) if res.data else 0
                sb.table("bot_users").update({"extra_goals": cur + p["goals"]}).eq("user_id", uid).execute()
                # Sync to user_data
                dr = sb.table("user_data").select("data").eq("user_id", uid).execute()
                if dr.data:
                    data = dr.data[0].get("data", {})
                    data["extraGoals"] = data.get("extraGoals", 0) + p["goals"]
                    sb.table("user_data").upsert({"user_id": uid, "data": data, "updated_at": datetime.utcnow().isoformat()}, on_conflict="user_id").execute()
                await message.answer(
                    f"⭐ <b>Оплата прошла!</b>\n\n+<b>{p['goals']} целей</b> добавлено 🎯\n\nОткрой IAM — слоты уже доступны!",
                    reply_markup=open_app_kb("Открыть IAM 🚀")
                )
            elif "lvl" in p:
                # Quick level 30 days
                from datetime import timedelta
                exp = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
                dr = sb.table("user_data").select("data").eq("user_id", uid).execute()
                if dr.data:
                    data = dr.data[0].get("data", {})
                    data["quickLvl"] = p["lvl"]
                    data["quickExp"] = exp
                    sb.table("user_data").upsert({"user_id": uid, "data": data, "updated_at": datetime.utcnow().isoformat()}, on_conflict="user_id").execute()
                await message.answer(
                    f"⭐ <b>Оплата прошла!</b>\n\n{p['title']} активен до <b>{exp}</b> 🏆\n\nОткрой IAM!",
                    reply_markup=open_app_kb("Открыть IAM 🚀")
                )
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        await message.answer("✅ Оплата прошла! Открой IAM — обновления уже применены.", reply_markup=open_app_kb())

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery):
    await call.answer()
    await call.message.answer(
        "Главное меню 👇",
        reply_markup=main_kb()
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("freq_"))
async def cb_freq(call: CallbackQuery):
    await call.answer()
    freq = call.data.replace("freq_", "")
    uid = call.from_user.id
    if freq == "off":
        sb.table("bot_users").update({"notif_freq": "off"}).eq("user_id", uid).execute()
        label = "🔕 Мотивационные пуши выключены.\nВажные уведомления (стрик, дедлайны, челлендж) продолжат приходить."
    else:
        sb.table("bot_users").update({"notifications": True, "notif_freq": freq}).eq("user_id", uid).execute()
        label = f"✅ Установлено: {FREQ_LABELS.get(freq, freq)}"
    try:
        await call.message.edit_text(
            "⚙️ <b>Частота уведомлений</b>\n\n"
            "🔕 <b>Только важные</b> — стрик, дедлайны, челлендж\n"
            "🌅 <b>Стандарт</b> — утром (8:00) и вечером (20:00)\n"
            "⏰ <b>Каждые 3 часа</b> — в 8, 11, 14, 17, 20\n"
            "🔔 <b>Каждый час</b> — с 8:00 до 22:00\n\n"
            f"<i>{label}</i>",
            reply_markup=freq_kb(freq)
        )
    except Exception:
        pass

@dp.callback_query(lambda c: c.data and c.data.startswith("rmd_"))
async def cb_remind_flow(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    data = call.data
    state = remind_state.get(uid, {})

    if data == "rmd_cancel":
        remind_state.pop(uid, None)
        try:
            await call.message.edit_text("❌ Отменено.")
        except Exception:
            pass
        return

    if data.startswith("rmd_page_"):
        page = int(data.replace("rmd_page_", ""))
        goals = state.get("goals", [])
        remind_state[uid]["page"] = page
        try:
            await call.message.edit_reply_markup(reply_markup=goals_page_kb(goals, page=page))
        except Exception:
            pass
        return

    if data.startswith("rmd_goal_"):
        idx = int(data.replace("rmd_goal_", ""))
        goals = state.get("goals", [])
        if idx >= len(goals):
            return
        goal_text = goals[idx]["text"]
        remind_state[uid] = {"step": "time", "goal_text": goal_text}
        short = goal_text[:80] + ("…" if len(goal_text) > 80 else "")
        try:
            await call.message.edit_text(
                f"🎯 <b>Цель:</b> <i>{short}</i>\n\n"
                "🕐 Напиши время напоминания в формате <b>ЧЧ:ММ</b>\n"
                "<i>Например: 09:00 или 20:30</i>"
            )
        except Exception:
            pass
        return

    if data.startswith("rmd_freq_"):
        freq = data.replace("rmd_freq_", "")
        goal_text = state.get("goal_text", "")
        remind_time = state.get("remind_time", "09:00")
        tz_offset = 3
        try:
            res = sb.table("bot_users").select("tz_offset").eq("user_id", uid).execute()
            if res.data:
                tz_offset = res.data[0].get("tz_offset", 3) or 3
        except Exception:
            pass
        ok = save_reminder(uid, goal_text, remind_time, freq, tz_offset)
        remind_state.pop(uid, None)
        freq_label = REMIND_FREQ_NAMES.get(freq, freq)
        try:
            if ok:
                await call.message.edit_text(
                    f"✅ <b>Напоминание создано!</b>\n\n"
                    f"🎯 {goal_text[:70]}\n"
                    f"🕐 {remind_time} · {freq_label}\n\n"
                    "<i>Управляй напоминаниями через /reminders</i>"
                )
            else:
                await call.message.edit_text("❌ Ошибка сохранения. Попробуй снова /remind")
        except Exception:
            pass
        return

    if data.startswith("rmd_info_"):
        await call.answer("Нажми 🗑 чтобы удалить это напоминание", show_alert=False)
        return

    if data.startswith("rmd_del_"):
        reminder_id = int(data.replace("rmd_del_", ""))
        delete_reminder(reminder_id, uid)
        rems = get_user_reminders(uid)
        try:
            if rems:
                lines = []
                for r in rems:
                    freq_label = REMIND_FREQ_NAMES.get(r["frequency"], r["frequency"])
                    short = r["goal_text"][:70] + ("…" if len(r["goal_text"]) > 70 else "")
                    lines.append(f"🔔 <b>{r['remind_time']}</b> · {freq_label}\n<i>{short}</i>")
                text = "📋 <b>Твои напоминания о целях:</b>\n\n" + "\n\n".join(lines) + "\n\n<i>Нажми 🗑 рядом с напоминанием чтобы удалить</i>"
                await call.message.edit_text(text, reply_markup=reminders_list_kb(rems))
            else:
                await call.message.edit_text(
                    "✅ Напоминание удалено.\n\n"
                    "Активных напоминаний нет. /remind — создать новое"
                )
        except Exception:
            pass
        return

@dp.message(F.text)
async def handle_time_input(message: Message):
    """Handles HH:MM time input during /remind flow."""
    if message.text.startswith("/"):
        return
    uid = message.from_user.id
    state = remind_state.get(uid)
    if not state or state.get("step") != "time":
        return
    time_str = message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", time_str):
        await message.answer("❌ Неверный формат. Напиши время как <b>ЧЧ:ММ</b>, например: <b>09:00</b>")
        return
    try:
        h, m = map(int, time_str.split(":"))
        if h > 23 or m > 59:
            raise ValueError
        time_str = f"{h:02d}:{m:02d}"
    except ValueError:
        await message.answer("❌ Неверное время. Пример: <b>09:00</b>, <b>20:30</b>")
        return
    remind_state[uid]["remind_time"] = time_str
    remind_state[uid]["step"] = "freq"
    goal_short = state.get("goal_text", "")[:60]
    await message.answer(
        f"🕐 Время: <b>{time_str}</b>\n"
        f"🎯 <i>{goal_short}</i>\n\n"
        "📅 Выбери частоту:",
        reply_markup=freq_remind_kb()
    )

@dp.message(F.web_app_data)
async def handle_webapp_data(message: Message):
    """Receives data sent via Telegram.WebApp.sendData() from the mini-app."""
    try:
        data = json.loads(message.web_app_data.data)
    except Exception:
        return
    uid = message.from_user.id
    if data.get("action") != "remind":
        return
    goal_text  = data.get("goal_text", "").strip()
    remind_time = data.get("remind_time", "09:00")
    frequency  = data.get("frequency", "daily")
    if not goal_text or frequency not in REMIND_FREQ_NAMES:
        await message.answer("❌ Неверные данные напоминания.")
        return
    # Validate HH:MM
    if not re.match(r"^\d{2}:\d{2}$", remind_time):
        await message.answer("❌ Неверный формат времени.")
        return
    tz_offset = 3
    try:
        res = sb.table("bot_users").select("tz_offset").eq("user_id", uid).execute()
        if res.data:
            tz_offset = res.data[0].get("tz_offset", 3) or 3
    except Exception:
        pass
    ok = save_reminder(uid, goal_text, remind_time, frequency, tz_offset)
    freq_label = REMIND_FREQ_NAMES.get(frequency, frequency)
    if ok:
        await message.answer(
            f"✅ <b>Напоминание создано!</b>\n\n"
            f"🎯 {goal_text[:70]}\n"
            f"🕐 {remind_time} · {freq_label}\n\n"
            "<i>Управляй напоминаниями через /reminders</i>"
        )
    else:
        await message.answer("❌ Не удалось сохранить напоминание. Попробуй через /remind")

# ====== PUSH MESSAGES ======

MORNING_MESSAGES = [
    "☀️ <b>Доброе утро!</b>\n\n<b>Изобилие</b> начинается с осознанности.\nПрочитай свои цели и сделай утренний ритуал 🌟",
    "🌅 <b>Новый день — новые возможности!</b>\n\nТвои цели ждут тебя.\nПотрать 5 минут на визуализацию 🎯",
    "✨ <b>Утро меняет жизнь!</b>\n\nУспешные люди начинают день с намерения.\nОткрой IAM и задай тон дню 🚀",
    "🔥 <b>Привет!</b>\n\nКаждое утро — это шанс стать лучше.\nТвой утренний ритуал занимает всего 5 минут 💫",
    "🎯 <b>Доброе утро!</b>\n\nМысли создают реальность.\nНачни день с чтения своих целей и визуализации ☀️",
]

EVENING_MESSAGES = [
    "🌙 <b>Вечерний ритуал!</b>\n\nКак прошёл твой день?\nЗапиши мысли в дневник и отметь чек-ин 🔥",
    "⭐ <b>Время подвести итоги дня!</b>\n\nЧто хорошего случилось сегодня?\nЗапиши 3 благодарности в IAM 🙏",
    "🌟 <b>Вечер осознанности!</b>\n\nНе засыпай без рефлексии.\nДневник + благодарность + чек-ин = идеальный вечер ✨",
    "💫 <b>До конца дня ещё есть время!</b>\n\nСделай чек-ин чтобы не потерять стрик 🔥\nЗапиши вечерние мысли 📝",
    "🌙 <b>Вечерний ритуал ждёт!</b>\n\nКаждый вечер — это подготовка к лучшему завтра.\nОткрой IAM и закрой день правильно 🎯",
]

EXTRA_PUSH_MESSAGES = [
    "⚡ <b>Момент для практики!</b>\n\nОткрой IAM и сделай одно микродействие — запись, цель или визуализацию 🎯",
    "🌟 <b>Время напоминания!</b>\n\nКаждое действие приближает тебя к новой версии себя 💫",
    "🔥 <b>Не теряй импульс!</b>\n\nЗайди в IAM — 2 минуты практики меняют всё ✨",
    "💡 <b>Мысли создают реальность.</b>\n\nЗапиши свою визуализацию прямо сейчас 🚀",
    "🎯 <b>Небольшая пауза?</b>\n\nИспользуй её — перечитай цели или напиши благодарность 🙏",
]

# ====== SCHEDULED PUSH FUNCTIONS ======

async def send_morning_push():
    import random
    all_users = get_all_users_with_notifications()
    users = [u for u in users_at_local_hour(all_users, 8) if (u.get("notif_freq") or "standard") != "off"]
    if not users:
        return
    text = random.choice(MORNING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Утренний ритуал ☀️"))
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Morning push failed for {u['user_id']}: {e}")
    logger.info(f"Morning push sent to {count} users")

async def send_evening_push():
    import random
    all_users = get_all_users_with_notifications()
    users = [u for u in users_at_local_hour(all_users, 20) if (u.get("notif_freq") or "standard") != "off"]
    if not users:
        return
    text = random.choice(EVENING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Вечерний ритуал 🌙"))
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Evening push failed for {u['user_id']}: {e}")
    logger.info(f"Evening push sent to {count} users")

async def send_extra_push():
    """Доп. пуши для пользователей с freq='3h' (11,14,17) и freq='1h' (9-22 кроме 8 и 20)."""
    import random
    utc_hour = datetime.utcnow().hour
    all_users = get_all_users_with_notifications()
    if not all_users:
        return
    count = 0
    text = random.choice(EXTRA_PUSH_MESSAGES)
    for u in all_users:
        freq = u.get("notif_freq") or "standard"
        if freq not in ("3h", "1h"):
            continue
        tz = u.get("tz_offset", 3)
        local_hour = (utc_hour + tz) % 24
        if freq == "3h" and local_hour not in (11, 14, 17):
            continue
        if freq == "1h" and (local_hour < 9 or local_hour > 22 or local_hour == 20):
            continue
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Открыть IAM ✨"))
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Extra push failed for {u['user_id']}: {e}")
    logger.info(f"Extra push sent to {count} users (UTC hour={utc_hour})")

async def send_streak_warning():
    """21:00 по местному — если нет чек-ина сегодня."""
    all_users = get_all_users_with_notifications()
    users = users_at_local_hour(all_users, 21)
    if not users:
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    text = "⚠️ <b>Стрик под угрозой!</b>\n\nТы ещё не сделал чек-ин сегодня.\nОсталось несколько часов — не теряй серию! 🔥"
    count_sent = 0
    count_skipped = 0
    for u in users:
        try:
            res = sb.table("user_data").select("data").eq("user_id", u["user_id"]).execute()
            if res.data:
                checkins = res.data[0].get("data", {}).get("checkins", [])
                if today in checkins:
                    count_skipped += 1
                    continue
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Сделать чек-ин ✓"))
            count_sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Streak warning failed for {u['user_id']}: {e}")
    logger.info(f"Streak warning: sent={count_sent}, skipped={count_skipped}")

async def send_goal_reminders():
    """10:05 UTC — напоминания о целях с дедлайнами."""
    users = get_all_users_with_notifications()
    if not users:
        return
    today = datetime.utcnow().date()
    count = 0
    for u in users:
        try:
            res = sb.table("user_data").select("data").eq("user_id", u["user_id"]).execute()
            if not res.data:
                continue
            goals = res.data[0].get("data", {}).get("goals", [])
            reminders = []
            for g in goals:
                if g.get("done") or not g.get("deadline"):
                    continue
                try:
                    deadline = datetime.strptime(g["deadline"], "%Y-%m-%d").date()
                    days_left = (deadline - today).days
                except Exception:
                    continue
                if days_left < 0:
                    continue
                should_remind = False
                if days_left <= 3:
                    should_remind = True
                elif days_left <= 7:
                    should_remind = (today.toordinal() % 2 == 0)
                elif days_left <= 30:
                    should_remind = (today.weekday() == 0)
                if should_remind:
                    reminders.append((g, days_left))
            if not reminders:
                continue
            lines = []
            for g, dl in reminders[:3]:
                tag = "🔴 Сегодня!" if dl == 0 else "🟠 Завтра" if dl == 1 else f"🟡 {dl} дн." if dl <= 3 else f"🟢 {dl} дн."
                short = g["text"][:60] + ("…" if len(g["text"]) > 60 else "")
                lines.append(f"{tag} — {short}")
            text = "🎯 <b>Напоминание о целях</b>\n\n" + "\n".join(lines)
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Открыть цели 🎯"))
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Goal reminder failed for {u['user_id']}: {e}")
    logger.info(f"Goal reminders sent to {count} users")

async def send_goal_own_reminders():
    """Ежедневно в 09:00 UTC — напоминания по целям с индивидуальной частотой."""
    users = get_all_users_with_notifications()
    if not users:
        return
    today = datetime.utcnow().date()
    count = 0
    for u in users:
        try:
            res = sb.table("user_data").select("data").eq("user_id", u["user_id"]).execute()
            if not res.data:
                continue
            goals = res.data[0].get("data", {}).get("goals", [])
            remind_goals = []
            for g in goals:
                if g.get("done"):
                    continue
                rm = g.get("remind")
                if not rm or rm == "off":
                    continue
                should = False
                if rm == "daily":
                    should = True
                elif rm == "3d":
                    created_ms = g.get("id", 0)
                    try:
                        created_date = datetime.utcfromtimestamp(created_ms / 1000).date()
                        days_since = (today - created_date).days
                        should = (days_since % 3 == 0)
                    except Exception:
                        should = True
                elif rm == "weekly":
                    should = (today.weekday() == 0)  # Monday
                if should:
                    remind_goals.append(g)
            if not remind_goals:
                continue
            lines = []
            for g in remind_goals[:3]:
                short = g["text"][:55] + ("…" if len(g["text"]) > 55 else "")
                dl_txt = ""
                if g.get("deadline"):
                    try:
                        dl = (datetime.strptime(g["deadline"], "%Y-%m-%d").date() - today).days
                        if dl >= 0:
                            dl_txt = f" · {dl} дн. до дедлайна"
                    except Exception:
                        pass
                lines.append(f"🎯 {short}{dl_txt}")
            text = "🔔 <b>Напоминание о твоих целях:</b>\n\n" + "\n".join(lines) + "\n\n<i>Перечитай и визуализируй ✨</i>"
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Открыть цели 🎯"))
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Goal own reminder failed for {u['user_id']}: {e}")
    logger.info(f"Goal own reminders sent to {count} users")

async def send_custom_reminders():
    """Every minute — dispatch reminders from the 'reminders' table."""
    reminders = get_all_active_reminders()
    if not reminders:
        return
    now_utc = datetime.utcnow()
    utc_h, utc_m = now_utc.hour, now_utc.minute
    count = 0
    for r in reminders:
        try:
            tz = r.get("tz_offset", 3) or 3
            local_h = (utc_h + tz) % 24
            local_m = utc_m
            rem_h, rem_m = map(int, r["remind_time"].split(":"))
            if local_m != rem_m:
                continue
            freq = r.get("frequency", "daily")
            if freq == "daily":
                should_fire = (local_h == rem_h)
            else:
                interval = int(freq.replace("h", ""))
                diff = (local_h - rem_h) % 24
                should_fire = (diff % interval == 0) and (6 <= local_h <= 23)
            if not should_fire:
                continue
            short = r["goal_text"][:80] + ("…" if len(r["goal_text"]) > 80 else "")
            await bot.send_message(
                r["user_id"],
                f"🔔 <b>Напоминание о цели</b>\n\n"
                f"🎯 {short}\n\n"
                "<i>Перечитай и визуализируй ✨</i>",
                reply_markup=open_app_kb("Открыть IAM 🎯")
            )
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Custom reminder failed uid={r.get('user_id')}: {e}")
    if count:
        logger.info(f"Custom reminders sent: {count}")

async def send_challenge_reminder():
    """19:00 по местному — если незакрытый день челленджа."""
    all_users = get_all_users_with_notifications()
    users = users_at_local_hour(all_users, 19)
    if not users:
        return
    today = datetime.utcnow().strftime("%Y-%m-%d")
    count_sent = 0
    count_skipped = 0
    AUTO_COMPLETE_TYPES = {"goals", "stats"}
    CHA = ["goals","vision","gratitude","vision","vision","gratitude","vision","goals","vision","gratitude",
           "gratitude","vision","vision","goals","gratitude","vision","gratitude","stats","goals","vision","gratitude"]
    for u in users:
        try:
            res = sb.table("user_data").select("data").eq("user_id", u["user_id"]).execute()
            if not res.data:
                continue
            data = res.data[0].get("data", {})
            ch_day = data.get("chDay", 0)
            if ch_day <= 0:
                continue
            current_day_idx = ch_day % 21
            day_type = CHA[current_day_idx]
            if day_type in AUTO_COMPLETE_TYPES:
                continue
            arr_map = {
                "vision": data.get("vis") or [],
                "gratitude": data.get("grat") or []
            }
            arr = arr_map.get(day_type, [])
            if any(e.get("date", "")[:10] == today for e in arr):
                count_skipped += 1
                continue
            day_num = current_day_idx + 1
            type_label = {
                "vision": "визуализацию ✨",
                "gratitude": "благодарности 🙏"
            }.get(day_type, "задание")
            text = (
                f"🔥 <b>День {day_num}/21 ещё не закрыт!</b>\n\n"
                f"Осталось совсем немного — напиши {type_label} и закрой день челленджа.\n\n"
                "Не прерывай серию 💪"
            )
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Выполнить задание 🔥"))
            count_sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Challenge reminder failed for {u['user_id']}: {e}")
    logger.info(f"Challenge reminder: sent={count_sent}, skipped={count_skipped}")

# ====== MAIN ======

async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_morning_push,        "cron", minute=0)
    scheduler.add_job(send_goal_reminders,      "cron", hour=10, minute=5)
    scheduler.add_job(send_goal_own_reminders,  "cron", hour=9,  minute=0)
    scheduler.add_job(send_streak_warning,      "cron", minute=0)
    scheduler.add_job(send_evening_push,        "cron", minute=0)
    scheduler.add_job(send_challenge_reminder,  "cron", minute=0)
    scheduler.add_job(send_extra_push,          "cron", minute=0)
    scheduler.add_job(send_custom_reminders,    "interval", minutes=1)
    scheduler.start()
    logger.info("IAM Bot started ✅")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
