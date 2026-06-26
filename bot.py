import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, CallbackQuery
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

# ====== PUSH MESSAGES ======

MORNING_MESSAGES = [
    "☀️ <b>Доброе утро!</b>\n\nНачни день с осознанности.\nПрочитай свои цели и сделай утренний ритуал 🌟",
    "🌅 <b>Новый день — новые возможности!</b>\n\nТвои цели ждут тебя.\nПотрать 5 минут на визуализацию 🎯",
    "✨ <b>Утро меняет жизнь!</b>\n\nУспешные люди начинают день с намерения.\nОткрой IAM и задай тон дню 🚀",
    "🔥 <b>Привет!</b>\n\nКаждое утро — это шанс стать лучше.\nТвой утренний ритуал занимает всего 5 минут 💫",
    "🎯 <b>Доброе утро!</b>\n\nМысли создают реальность.\nНачни день с чтения своих целей и визуализации ☀️",
]

EVENING_MESSAGES = [
    "🌙 <b>Вечерний ритуал!</b>\n\nКак прошёл твой день?\nЗапиши мысли в дневник и отметь чек-ин 🔥",
    "⭐ <b>Время подвести итоги дня!</b>\n\nЧто хорошего случилось сегодня?\nЗапиши 3 благодарности в IAM 🙏",
    "🌟 <b>Вечер осознанности!</b>\n\nНе засыпай без рефлексии.\nДневник + благодарность + чек-ин = идеальный вечер ✨",
    "💫 <b>До конца дня ещё время!</b>\n\nСделай чек-ин чтобы не потерять стрик 🔥\nЗапиши вечерние мысли 📝",
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
    text = random.choice(EXTRA_PU(EXTRA_PUSH_MESSAGES)
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
    CHA = ["goals","vision","gratitude","diary","vision","diary","diary","goals","vision","diary",
           "gratitude","vision","diary","goals","gratitude","vision","diary","stats","goals","vision","diary"]
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
                "diary": data.get("diary") or [],
                "gratitude": data.get("grat") or []
            }
            arr = arr_map.get(day_type, [])
            if any(e.get("date", "")[:10] == today for e in arr):
                count_skipped += 1
                continue
            day_num = current_day_idx + 1
            type_label = {
                "vision": "визуализацию ✨",
                "diary": "запись в дневнике 📝",
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
    scheduler.add_job(send_morning_push,       "cron", minute=0)
    scheduler.add_job(send_goal_reminders,     "cron", hour=10, minute=5)
    scheduler.add_job(send_streak_warning,     "cron", minute=0)
    scheduler.add_job(send_evening_push,       "cron", minute=0)
    scheduler.add_job(send_challenge_reminder, "cron", minute=0)
    scheduler.add_job(send_extra_push,         "cron", minute=0)
    scheduler.start()
    logger.info("IAM Bot started ✅")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
