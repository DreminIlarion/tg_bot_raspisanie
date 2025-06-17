import asyncio
from datetime import datetime, timedelta
import logging
import signal
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
import os
from aiohttp import web

load_dotenv()
KEY_TG = os.getenv('KEY_TG')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=KEY_TG)
dp = Dispatcher()

# Данные приложения
user_data = {}
confirmed_duties = {}
NAMES = ['Аня', 'Ларик', 'Маша']
START_DATE = datetime(2025, 6, 14)
MONTHS_RU = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
    5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
    9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
}

async def handle_health_check(request):
    return web.Response(text="Bot is running")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8000)
    await site.start()
    logger.info("Web server started on port 8000")
    return runner

async def on_shutdown():
    logger.info("Shutting down...")
    await bot.session.close()

async def graceful_shutdown(signal, loop):
    """Обработка graceful shutdown"""
    logger.info(f"Received exit signal {signal.name}...")
    await on_shutdown()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def get_names_keyboard():
    builder = ReplyKeyboardBuilder()
    for name in NAMES:
        builder.add(KeyboardButton(text=name))
    return builder.as_markup(resize_keyboard=True)

def get_duty_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Иду дежурить! ✅", callback_data="confirm_duty")]
    ])

def format_date_ru(date):
    day = date.day
    month = MONTHS_RU[date.month]
    return f"{day} {month}".lstrip('0').replace(' 0', ' ')

def get_duty_info(selected_name):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_start = (today - START_DATE).days
    cycle_day = days_since_start % 9
    
    if cycle_day == 0:
        current_duty_name = NAMES[0]
    elif cycle_day == 3:
        current_duty_name = NAMES[1]
    elif cycle_day == 6:
        current_duty_name = NAMES[2]
    else:
        current_duty_name = None
    
    selected_index = NAMES.index(selected_name)
    days_until_duty = None
    for i in range(9):
        check_day = (days_since_start + i) % 9
        if (selected_index == 0 and check_day == 0) or \
           (selected_index == 1 and check_day == 3) or \
           (selected_index == 2 and check_day == 6):
            days_until_duty = i
            break
    if days_until_duty is None or (days_until_duty == 0 and today > datetime.now()):
        days_until_duty = 9 - cycle_day + (selected_index * 3) % 9
    next_duty_date = today + timedelta(days=days_until_duty)
    
    return current_duty_name, next_duty_date

@dp.message(Command("start"))
async def start_command(message: types.Message):
    welcome_message = (
        "Привет! 👋 Этот бот поможет тебе следить за графиком дежурств в ванной. "
        "Выбери своё имя, и я буду присылать тебе напоминания три раза в день "
        "(в 12:00, 18:00 и 21:00) в твой день дежурства! 🛁"
    )
    await message.answer(welcome_message)
    await message.answer("Выбери своё имя:", reply_markup=get_names_keyboard())

@dp.message(lambda message: message.text in NAMES)
async def handle_name_selection(message: types.Message):
    user_id = message.from_user.id
    selected_name = message.text
    user_data[user_id] = selected_name
    
    _, next_duty_date = get_duty_info(selected_name)
    formatted_date = format_date_ru(next_duty_date)
    
    await message.answer(
        f"Вы выбрали расписание для {selected_name}. "
        f"Твоё ближайшее дежурство: {formatted_date}. "
        f"Напоминания будут приходить в 12:00, 18:00 и 21:00 в день дежурства.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.callback_query(lambda c: c.data == "confirm_duty")
async def confirm_duty(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    confirmed_duties[user_id] = today
    
    await callback.message.edit_text(
        f"Отлично, {user_data.get(user_id, 'друг')}! Ты подтвердил дежурство на сегодня. "
        f"Больше уведомлений сегодня не будет! 🛁"
    )
    await callback.answer()

async def send_duty_reminders():
    while True:
        try:
            now = datetime.now()
            if now.minute == 0 and now.hour in [12, 18, 21]:
                today = now.replace(hour=0, minute=0, second=0, microsecond=0)
                days_since_start = (today - START_DATE).days
                cycle_day = days_since_start % 9
                
                if cycle_day in [0, 3, 6]:
                    current_index = cycle_day // 3
                    current_duty_name = NAMES[current_index]
                    logger.info(f"Сегодня ({format_date_ru(today)}) дежурит: {current_duty_name}")
                    
                    formatted_date = format_date_ru(today)
                    for user_id, name in user_data.items():
                        if name == current_duty_name and confirmed_duties.get(user_id) != today:
                            try:
                                await bot.send_message(
                                    user_id,
                                    f"Напоминание: {name}, сегодня ({formatted_date}) ты дежуришь в ванной! 🛁",
                                    reply_markup=get_duty_confirmation_keyboard()
                                )
                            except Exception as e:
                                logger.error(f"Ошибка отправки сообщения: {e}")
                else:
                    logger.info(f"Сегодня ({format_date_ru(today)}) никто не дежурит")
            
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("Reminder task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in reminder task: {e}")
            await asyncio.sleep(60)

async def set_bot_commands():
    commands = [BotCommand(command="/start", description="Начать и выбрать имя")]
    await bot.set_my_commands(commands)

async def on_startup():
    await set_bot_commands()
    asyncio.create_task(send_duty_reminders())
    await run_web_server()

async def main():
    loop = asyncio.get_event_loop()
    
    # Обработка сигналов для graceful shutdown
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(graceful_shutdown(s, loop))
        )
    
    dp.startup.register(on_startup)
    
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    finally:
        await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")