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

def open_app_kb(text="Открыть IAM ✨"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=WEBAPP_URL))]])

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть IAM", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="📊 Мой прогресс", callback_data="stats"), InlineKeyboardButton(text="🔥 Стрик", callback_data="streak")],
        [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="refer")],
    ])

def upsert_user(user_id, username, first_name, ref_by=None):
    data = {"user_id": user_id, "username": username or "", "first_name": first_name or "", "notifications": True, "last_seen": datetime.utcnow().isoformat()}
    if ref_by:
        data["ref_by"] = ref_by
    sb.table("bot_users").upsert(data, on_conflict="user_id").execute()

def get_all_users_with_notifications():
    res = sb.table("bot_users").select("user_id, first_name, tz_offset").eq("notifications", True).execute()
    return res.data or []

def users_at_local_hour(users: list, target_hour: int) -> list:
    """Возвращает пользователей, у которых сейчас target_hour по местному времени."""
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
            sb.table("bot_users").update({"referrals": (row.get("referrals") or 0) + 1, "extra_goals": (row.get("extra_goals") or 0) + 5}).eq("user_id", inviter_id).execute()
    except Exception as e:
        logger.error(f"add_referral error: {e}")

def get_user_stats(user_id):
    try:
        res = sb.table("bot_users").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else {}
    except:
        return {}

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
                await bot.send_message(ref_by, "🎉 По твоей ссылке пришёл новый пользователь!\n✅ +5 целей добавлено в твой аккаунт")
        except:
            pass
    upsert_user(user.id, user.username, user.first_name, ref_by)
    await message.answer(f"✨ <b>Привет, {user.first_name}!</b>\n\nДобро пожаловать в <b>IAM</b> — дневник трансформации личности.\n\n🎯 Ставь цели во всех сферахжизни\n���� Проходи 21-дневный челлендж�n✍️ веди дневник визуализации\n📊 Отслеживай прогресс каждый день\n\n<i>У успешных людей 5000+ целей.\nНачни прямо сейчас 👇</i>", reply_markup=main_kb())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("📖 <b>Команды IAM:</b>\n\n/start — главное меню\n/stats — твой прогресс\n/refer — пригласить друга\n/notify on|off — включить/выключить уведомления\n\n❓ Ьужна помощь? Пиши @JAM_support", reply_markup=open_app_kb())

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = get_user_stats(message.from_user.id)
    await message.answer(f"📊 <b>Твой прогресс IAM</b>\n\n👥 Приглашено друзей: <b>{stats.get('referrals',0)}</b>\n🎁 Бонусных целей: <b>{stats.get('extra_goals',0)}</b>\n\nОстальная статистика — в приложении 👇", reply_markup=open_app_kb("Открыть статистику 📊"))

@dp.message(Command("refer"))
async def cmd_refer(message: Message):
    ref_link = f"https://t.me/IAM_app_bot?start=ref_{message.from_user.id}"
    await message.answer(f"🎁 <b>Пригласи друга — сба получите +5 ц�лей!</b>\n\nТвоя ссылка:\n<code>{ref_link}</code>\n\nОтправь её другу. Когда он запустит бота — Вы оба получите бонус 🎯")

@dp.message(Command("notify"))
async def cmd_notify(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in ("on", "off"):
        await message.answer("Используй: /notify on или /notify off")
        return
    enabled = args[1] == "on"
    sb.table("bot_users").update({"notifications": enabled}).eq("user_id", message.from_user.id).execute()
    await message.answer(f"Уведомления {'включены\u✅' if enabled else 'выключены\u❌'}")

@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery):
    await call.answer()
    await cmd_stats(call.message)

@dp.callback_query(F.data == "streak")
async def cb_streak(call: CallbackQuery):
    await call.answer()
    await call.message.answer("🔥 <b>Стрик</b> — это дни подряд когда ты делаешь чек-ио IAM.\n\nОткрой приложение и отметь сегодняшний день!\nНе теряй стрик — это твой главный показатель 💪", reply_markup=open_app_kb("Отметить чек-ин ✓"))

@dp.callback_query(F.data == "refer")
async def cb_refer(call: CallbackQuery):
    await call.answer()
    await cmd_refer(call.message)

MORNING_MESSAGES = [
    "☀️ <b>Доброе утро!</b>\n\nНачни день с осознанности.\nПрочитай свои цели и сделай утренний ритуал 🌟",
    "🌅 <b>Новый день — новые возможности!</b>\n\nТвои цели ждут тебя.\nПотрать 5 минут на визуализацию 🎯",
    "✨ <b>Утро меняет жизнь!</b>\n\nУспешные люди начинают день с намерения.\nОткрой IAM и задай тон дню 🚀",
    "🔥 <b>Привет!</b>\n\nКаждое утро — это шанс стать лучше.\nТвой утренный ритуал занимает всего 5 минут 💫",
    "🎯 <b>Доброе утро!</b>\n\nМысли создают реальность.\nНачни день с чтения своих целей и визуализации ☀️",
]

EVENING_MESSAGES = [
    "🌙 <b>Вечерний ритуал!</b>\n\nКак прошёл твой день?\nЗапиши мысли в дневник и отметь чек-ин 🔥",
    "⭐ <b>Время подвести итоги дня!</b>\n\nЧто хорошего случилось сегодня?\nЗапиши 3 благодарности в IAM 🙏",
    "🌟 <b>Вечер осознанности!</b>\n\nНе засыпай без рефлексии.\nДневник + благодарность + чек-ин = идеальный вечер ✨",
    "💫 <b>До конха дня ещё есть время!</b>\n\nСделай чек-ин чтобы не потерять стрик 🔥\nЗапиши вечерние мысли 📝",
    "🌙 <b>Вечерний ритуал ждёт!</b>\n\nКаждый вечер — это подготовка к лучшему завтра.\nОткрой IAM и закрой день правильно 🎯",
]

async def send_morning_push():
    """Шлём утренний пуш пользователям, у которых сейчас 8:00 по местному времени."""
    import random
    all_users = get_all_users_with_notifications()
    users = users_at_local_hour(all_users, 8)
    if not users: return
    text = random.choice(MORNING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Утренний ритуал ☀️"), parse_mode=ParseMode.HTML)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Morning push failed for {u['user_id']}: {e}")
    logger.info(f"Morning push sent to {count}/{len(all_users)} users")

async def send_evening_push():
    """Шлём вечерний пуш пользователям, у которых сейчас 20:00 по местному времени."""
    import random
    all_users = get_all_users_with_notifications()
    users = users_at_local_hour(all_users, 20)
    if not users: return
    text = random.choice(EVENING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Вечерний ритуал 🌙"), parse_mode=ParseMode.HTML)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Evening push failed for {u['user_id']}: {e}")
    logger.info(f"Evening push sent to {count}/{len(all_users)} users")

async def send_streak_warning():
    """Шлём предупреждение пользователям у которых 21:00 по местному И нет чек-ина сегодня."""
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
            # Проверяем чек-ин за сегодня в user_data
            res = sb.table("user_data").select("data").eq("user_id", u["user_id"]).execute()
            if res.data:
                checkins = res.data[0].get("data", {}).get("checkins", [])
                if today in checkins:
                    count_skipped += 1
                    continue  # уже сделал чек-ин — не беспокоим

            await bot.send_message(
                u["user_id"], text,
                reply_markup=open_app_kb("Сделать чек-ин ✓"),
                parse_mode=ParseMode.HTML
            )
            count_sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Streak warning failed for {u['user_id']}: {e}")

    logger.info(f"Streak warning: sent={count_sent}, skipped(already checked in)={count_skipped}")

async def send_goal_reminders():
    """Напоминания о целях с дедлайнами.
    ≤3 дня  → каждый день
    4-7 дней → каждые 2 дня (чётные дни года

    8-30 дней → раз в неделю (понедельник)
    >30 дней  → не беспокоим
    """
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
                    continue  # просрочена — не беспокоим

                should_remind = False
                if days_left <= 3:
                    should_remind = True                          # каждый день
                elif days_left <= 7:
                    should_remind = (today.toordinal() % 2 == 0) # каждые 2 дня
                elif days_left <= 30:
                    should_remind = (today.weekday() == 0)        # по понедельникам

                if should_remind:
                    reminders.append((g, days_left))

            if not reminders:
                continue

            lines = []
            for g, dl in reminders[:3]:  # не больше 3 целей в одном сообщении
                if dl == 0:
                    tag = "🔴 Сегодня!"
                elif dl == 1:
                    tag = "🟠 Завтра"
                elif dl <= 3:
                    tag = f"🟡 {dl} дн."
                else:
                    tag = f"🟢 {dl} дн."
                short = g["text"][:60] + ("…" if len(g["text"]) > 60 else "")
                lines.append(f"{tag} — {short}")

            text = "🎯 <b>Напоминание о целях</b>\n\n" + "\n".join(lines)
            await bot.send_message(
                u["user_id"], text,
                reply_markup=open_app_kb("Открыть цели 🎯"),
                parse_mode=ParseMode.HTML
            )
            count += 1
            await asyncio.sleep(0.05)

        except Exception as e:
            logger.warning(f"Goal reminder failed for {u['user_id']}: {e}")

    logger.info(f"Goal reminders sent to {count} users")


async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    # Запускаем каждый час — внутри каждой функции фильтр по местному времени пользователя
    scheduler.add_job(send_morning_push,   "cron", minute=0)
    scheduler.add_job(send_goal_reminders, "cron", hour=10, minute=5)
    scheduler.add_job(send_streak_warning, "cron", minute=0)
    scheduler.add_job(send_evening_push,   "cron", minute=0)
    scheduler.start()
    logger.info("IAM Bot started ✅")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
