import asyncio
from datetime import datetime, timedelta
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from aiohttp import web
import socket

load_dotenv()

# Конфигурация
PORT = int(os.getenv('PORT', 10000))
KEY_TG = os.getenv('KEY_TG')
NAMES = ['Аня', 'Ларик', 'Маша']
START_DATE = datetime(2025, 6, 14)
MONTHS_RU = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
    5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
    9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
}

# Инициализация
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=KEY_TG)
dp = Dispatcher()
user_data = {}
confirmed_duties = {}

class WebServer:
    def __init__(self):
        self.runner = None
        self.site = None

    async def start(self):
        app = web.Application()
        app.router.add_get('/', self.health_check)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        
        port = PORT
        while True:
            try:
                self.site = web.TCPSite(self.runner, '0.0.0.0', port)
                await self.site.start()
                logger.info(f"Web server started on port {port}")
                return port
            except OSError as e:
                if "address already in use" in str(e):
                    port += 1
                    logger.warning(f"Port {port-1} busy, trying {port}")
                    continue
                raise

    async def health_check(self, request):
        return web.Response(text="Bot is running")

    async def stop(self):
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

class DutyReminder:
    def __init__(self):
        self.task = None
        self.stop_flag = False

    async def start(self):
        self.stop_flag = False
        self.task = asyncio.create_task(self.run_reminders())

    async def run_reminders(self):
        while not self.stop_flag:
            now = datetime.now()
            if now.minute == 0 and now.hour in [12, 18, 21]:
                await self.send_reminders()
            await asyncio.sleep(60)

    async def send_reminders(self):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_start = (today - START_DATE).days
        cycle_day = days_since_start % 9
        
        if cycle_day in [0, 3, 6]:
            current_duty_name = NAMES[cycle_day // 3]
            formatted_date = self.format_date(today)
            
            for user_id, name in user_data.items():
                if name == current_duty_name and confirmed_duties.get(user_id) != today:
                    try:
                        await bot.send_message(
                            user_id,
                            f"Напоминание: {name}, сегодня ({formatted_date}) ты дежуришь в ванной! 🛁",
                            reply_markup=self.get_confirmation_keyboard()
                        )
                    except Exception as e:
                        logger.error(f"Send message error: {e}")

    def format_date(self, date):
        return f"{date.day} {MONTHS_RU[date.month]}"

    def get_confirmation_keyboard(self):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Иду дежурить! ✅", callback_data="confirm_duty")]
        ])

    async def stop(self):
        self.stop_flag = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

# Handlers
@dp.message(Command("start"))
async def start_command(message: types.Message):
    await message.answer(
        "Привет! 👋 Этот бот поможет тебе следить за графиком дежурств в ванной. "
        "Выбери своё имя:",
        reply_markup=get_names_keyboard()
    )

def get_names_keyboard():
    builder = ReplyKeyboardBuilder()
    for name in NAMES:
        builder.add(KeyboardButton(text=name))
    return builder.as_markup(resize_keyboard=True)

@dp.message(lambda message: message.text in NAMES)
async def handle_name_selection(message: types.Message):
    user_id = message.from_user.id
    selected_name = message.text
    user_data[user_id] = selected_name
    
    _, next_duty = get_next_duty(selected_name)
    formatted_date = format_date_ru(next_duty)
    
    await message.answer(
        f"Вы выбрали расписание для {selected_name}. "
        f"Ближайшее дежурство: {formatted_date}.",
        reply_markup=types.ReplyKeyboardRemove()
    )

def get_next_duty(name):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_start = (today - START_DATE).days
    cycle_day = days_since_start % 9
    index = NAMES.index(name)
    days_until = (9 - cycle_day + (index * 3)) % 9
    return None, today + timedelta(days=days_until)

def format_date_ru(date):
    return f"{date.day} {MONTHS_RU[date.month]}"

@dp.callback_query(lambda c: c.data == "confirm_duty")
async def confirm_duty(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    confirmed_duties[user_id] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    await callback.message.edit_text("✅ Дежурство подтверждено!")
    await callback.answer()

async def main():
    webserver = WebServer()
    reminder = DutyReminder()
    
    try:
        port = await webserver.start()
        await reminder.start()
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Shutting down...")
        await reminder.stop()
        await webserver.stop()
        await bot.session.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")