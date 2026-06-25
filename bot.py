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
    res = sb.table("bot_users").select("user_id, first_name").eq("notifications", True).execute()
    return res.data or []

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
    await message.answer(f"✨ <b>Привет, {user.first_name}!</b>\n\nДобро пожаловать в <b>IAM</b> — дневник трансформации личности.\n\n🎯 Ставь цели во всех сферах жизни\n🔥 Проходи 21-дневный челлендж\n✍️ Веди дневник визуализации\n📊 Отслеживай прогресс каждый день\n\n<i>У успешных людей 5000+ целей.\nНачни прямо сейчас 👇</i>", reply_markup=main_kb())

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("📖 <b>Команды IAM:</b>\n\n/start — главное меню\n/stats — твой прогресс\n/refer — пригласить друга\n/notify on|off — включить/выключить уведомления\n\n❓ Нужна помощь? Пиши @IAM_support", reply_markup=open_app_kb())

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    stats = get_user_stats(message.from_user.id)
    await message.answer(f"📊 <b>Твой прогресс IAM</b>\n\n👥 Приглашено друзей: <b>{stats.get('referrals',0)}</b>\n🎁 Бонусных целей: <b>{stats.get('extra_goals',0)}</b>\n\nОстальная статистика — в приложении 👇", reply_markup=open_app_kb("Открыть статистику 📊"))

@dp.message(Command("refer"))
async def cmd_refer(message: Message):
    ref_link = f"https://t.me/IAM_app_bot?start=ref_{message.from_user.id}"
    await message.answer(f"🎁 <b>Пригласи друга — оба получите +5 целей!</b>\n\nТвоя ссылка:\n<code>{ref_link}</code>\n\nОтправь её другу. Когда он запустит бота — вы оба получите бонус 🎯")

@dp.message(Command("notify"))
async def cmd_notify(message: Message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in ("on", "off"):
        await message.answer("Используй: /notify on или /notify off")
        return
    enabled = args[1] == "on"
    sb.table("bot_users").update({"notifications": enabled}).eq("user_id", message.from_user.id).execute()
    await message.answer(f"Уведомления {'включены ✅' if enabled else 'выключены ❌'}")

@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery):
    await call.answer()
    await cmd_stats(call.message)

@dp.callback_query(F.data == "streak")
async def cb_streak(call: CallbackQuery):
    await call.answer()
    await call.message.answer("🔥 <b>Стрик</b> — это дни подряд когда ты делаешь чек-ин в IAM.\n\nОткрой приложение и отметь сегодняшний день!\nНе теряй стрик — это твой главный показатель 💪", reply_markup=open_app_kb("Отметить чек-ин ✓"))

@dp.callback_query(F.data == "refer")
async def cb_refer(call: CallbackQuery):
    await call.answer()
    await cmd_refer(call.message)

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
    "💫 <b>До конца дня ещё есть время!</b>\n\nСделай чек-ин чтобы не потерять стрик 🔥\nЗапиши вечерние мысли 📝",
    "🌙 <b>Вечерний ритуал ждёт!</b>\n\nКаждый вечер — это подготовка к лучшему завтра.\nОткрой IAM и закрой день правильно 🎯",
]

async def send_morning_push():
    users = get_all_users_with_notifications()
    if not users: return
    import random
    text = random.choice(MORNING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Утренний ритуал ☀️"), parse_mode=ParseMode.HTML)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Morning push failed for {u['user_id']}: {e}")
    logger.info(f"Morning push sent to {count} users")

async def send_evening_push():
    users = get_all_users_with_notifications()
    if not users: return
    import random
    text = random.choice(EVENING_MESSAGES)
    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Вечерний ритуал 🌙"), parse_mode=ParseMode.HTML)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Evening push failed for {u['user_id']}: {e}")
    logger.info(f"Evening push sent to {count} users")

async def send_streak_warning():
    users = get_all_users_with_notifications()
    text = "⚠️ <b>Стрик под угрозой!</b>\n\nТы ещё не сделал чек-ин сегодня.\nОсталось несколько часов — не теряй серию! 🔥"
    for u in users:
        try:
            await bot.send_message(u["user_id"], text, reply_markup=open_app_kb("Сделать чек-ин ✓"), parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Streak warning failed for {u['user_id']}: {e}")

async def main():
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_morning_push,   "cron", hour=6,  minute=0)
    scheduler.add_job(send_streak_warning, "cron", hour=17, minute=0)
    scheduler.add_job(send_evening_push,   "cron", hour=18, minute=0)
    scheduler.start()
    logger.info("IAM Bot started ✅")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
