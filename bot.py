import time
import asyncio
import sys
import json
import os
import logging
import calendar
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes
)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ——— Configuration —————————————————————————————————————————————————————
BOT_TOKEN    = '' #FILL THIS
DRIVER_PATH = os.environ.get('DRIVER_PATH', '/usr/bin/chromedriver')
BROWSER_BIN = os.environ.get('BROWSER_BIN', '/usr/bin/chromium')
service = Service(executable_path=DRIVER_PATH)
DATA_FILE    = 'user_data.json'

# ——— States ————————————————————————————————————————————————————————————
ORIGIN, CALENDAR_STATE, TIME_STATE, PASSENGERS = range(4)

# ——— In-memory store + persistence ——————————————————————————————————————
user_data_store = {}  # chat_id (str) → list of prompt dicts

def load_user_data():
    global user_data_store
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                content = f.read().strip()
                user_data_store = json.loads(content) if content else {}
        except json.JSONDecodeError:
            print("⚠️ Corrupted user_data.json, resetting...")
            user_data_store = {}
    else:
        user_data_store = {}


def save_user_data():
    with open(DATA_FILE, 'w') as f:
        json.dump(user_data_store, f, indent=2)

# ——— Conversation handlers ———————————————————————————————————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("WOODLANDS CIQ", callback_data='WOODLANDS CIQ')],
        [InlineKeyboardButton("JB SENTRAL",     callback_data='JB SENTRAL')]
    ]
    await update.message.reply_text(
        'Choose your origin station:',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORIGIN

async def origin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    origin = query.data
    destination = 'JB SENTRAL' if origin=='WOODLANDS CIQ' else 'WOODLANDS CIQ'
    context.user_data.update(origin=origin, destination=destination)
    await query.edit_message_text(f"Origin: {origin}\nDestination: {destination}")
    await show_calendar(update, context)
    return CALENDAR_STATE

async def show_calendar(update, context, year=None, month=None):
    now   = datetime.now()
    year  = year or now.year
    month = month or now.month
    context.user_data['cal_year']  = year
    context.user_data['cal_month'] = month

    keyboard = [
        [InlineKeyboardButton(calendar.month_name[month] + " " + str(year), callback_data="IGNORE")],
        [InlineKeyboardButton(d, callback_data="IGNORE") for d in ['Mo','Tu','We','Th','Fr','Sa','Su']]
    ]
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day==0:
                row.append(InlineKeyboardButton(" ", callback_data="IGNORE"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"DATE_{day}"))
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("«", callback_data="PREV_MONTH"),
        InlineKeyboardButton("»", callback_data="NEXT_MONTH")
    ])

    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text("📅 Select a date:", reply_markup=markup)
    else:
        await update.message.reply_text("📅 Select a date:", reply_markup=markup)

async def calendar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query
    data = q.data
    if data=="PREV_MONTH" or data=="NEXT_MONTH":
        year  = context.user_data['cal_year']
        month = context.user_data['cal_month'] + (1 if data=="NEXT_MONTH" else -1)
        if month==0:   month, year = 12, year-1
        if month==13:  month, year = 1,  year+1
        await show_calendar(update, context, year, month)
        return CALENDAR_STATE

    if data.startswith("DATE_"):
        day   = data.split("_")[1].zfill(2)
        month = context.user_data['cal_month']
        year  = context.user_data['cal_year']
        context.user_data.update(
            day=day,
            month=calendar.month_abbr[month].upper(),
            year=str(year)
        )
        origin = context.user_data['origin']
        times = (
            ['08:30','09:45','11:00','12:30','13:45','15:00','16:15','17:30','18:45','20:00','21:15','22:30','23:45']
            if origin=="WOODLANDS CIQ"
            else ['08:45','10:00','11:30','12:45','14:00','15:15','16:30','17:45','19:00','20:15','21:30','22:45']
        )
        kb = [[InlineKeyboardButton(t, callback_data=t)] for t in times]
        await q.edit_message_text("Choose time:", reply_markup=InlineKeyboardMarkup(kb))
        return TIME_STATE

    await q.answer()
    return CALENDAR_STATE

async def time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data['time'] = q.data
    kb = [[InlineKeyboardButton(str(i), callback_data=str(i))] for i in range(1,7)]
    await q.edit_message_text("How many passengers?", reply_markup=InlineKeyboardMarkup(kb))
    return PASSENGERS

async def passenger_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    chat_id = str(q.message.chat_id)
    context.user_data['passengers'] = int(q.data)

    # build prompt entry
    d = context.user_data
    prompt = dict(
        origin=d['origin'],
        destination=d['destination'],
        day=d['day'],
        month=d['month'],
        year=d['year'],
        time=d['time'],
        passengers=d['passengers'],
        return_day=d['day'],
        return_month=d['month'],
        return_year=d['year'],
        completed=False
    )
    user_data_store.setdefault(chat_id, []).append(prompt)
    save_user_data()

    summary = (
        f"🔍 Monitoring for:\n"
        f"From: {prompt['origin']}\n"
        f"To: {prompt['destination']}\n"
        f"Date: {prompt['day']} {prompt['month']} {prompt['year']}\n"
        f"Time: {prompt['time']}\n"
        f"Passengers: {prompt['passengers']}"
    )
    await q.edit_message_text(summary)

    # launch background check
    asyncio.create_task(run_selenium_check(prompt, context.bot, chat_id))
    return ConversationHandler.END

# ——— Selenium checking loop ——————————————————————————————————————————————
import re
import tempfile
import shutil

async def run_selenium_check(data, bot, chat_id):
    retry_delay = 60

    while not data.get("completed", False):
        try:
            user_data_dir = tempfile.mkdtemp()

            options = Options()
            options.binary_location = BROWSER_BIN
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-logging')
            options.add_argument('--disable-notifications')
            options.add_argument('--disable-default-apps')
            options.add_argument('--disable-background-networking')
            options.add_argument('--disable-background-timer-throttling')
            options.add_argument('--disable-backgrounding-occluded-windows')
            options.add_argument('--disable-breakpad')
            options.add_argument('--disable-component-extensions-with-background-pages')
            options.add_argument('--disable-features=TranslateUI')
            options.add_argument('--disable-ipc-flooding-protection')
            options.add_argument(f'--user-data-dir={user_data_dir}')

            driver = webdriver.Chrome(service=service, options=options)
            driver.set_window_size(1024, 768)
            wait = WebDriverWait(driver, 10)

            try:
                # Main loop
                driver.get('https://shuttleonline.ktmb.com.my/Home/Shuttle')
                last_notified = None
                while not data.get("completed", False):
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal.fade.show')))
                        driver.execute_script("document.querySelector('button[data-dismiss=\"modal\"]').click()")
                        await asyncio.sleep(1)
                    except Exception:
                        pass

                    # Fill and submit form
                    driver.execute_script(f"document.getElementById('FromStationId').value='{data['origin']}';")
                    driver.execute_script(f"document.getElementById('ToStationId').value='{data['destination']}';")
                    driver.execute_script(f"document.getElementById('OnwardDate').value='{data['day']} {data['month']} {data['year']}';")
                    driver.execute_script(f"document.getElementById('ReturnDate').value='{data['return_day']} {data['return_month']} {data['return_year']}';")
                    Select(driver.find_element(By.ID, 'PassengerCount')).select_by_visible_text(f"{data['passengers']} Pax")
                    driver.execute_script("document.getElementById('btnSubmit').click()")

                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'tbody.return-trips tr')))
                    except Exception:
                        await bot.send_message(chat_id, "⚠️ Timeout loading train list. Retrying.")
                        await asyncio.sleep(30)
                        continue

                    target = data['time'].replace(':', '')
                    rows = driver.find_elements(By.CSS_SELECTOR, 'tr[data-hourminute]')
                    found = False
                    for r in rows:
                        if r.get_attribute('data-hourminute') == target:
                            tds = r.find_elements(By.TAG_NAME, 'td')
                            if len(tds) >= 5:
                                raw = tds[4].get_attribute("innerText").strip()
                                m = re.search(r'(\d+)', raw)
                                found = True
                                if not m:
                                    await bot.send_message(chat_id, f"⚠️ Unexpected format: “{raw}”")
                                    break
                                cnt = int(m.group(1))
                                if cnt >= data['passengers']:
                                    await bot.send_message(chat_id, f"✅ Train on {data['day']} {data['month']} {data['year']} at {data['time']} → {cnt} seats.")
                                    data['completed'] = True
                                    save_user_data()
                                    break
                                if last_notified != cnt:
                                    await bot.send_message(chat_id, f"🔄 Train on {data['day']} {data['month']} {data['year']} at {data['time']} → {cnt} seats, need {data['passengers']}.")
                                    last_notified = cnt
                            break

                    if not found:
                        seen = [r.get_attribute("data-hourminute") for r in rows]
                        await bot.send_message(chat_id, f"❌ Train at {data['time']} not found. Seen: {seen}")

                    if not data.get("completed", False):
                        driver.refresh()
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Train on {data['day']} {data['month']} {data['year']} at {data['time']} → {cnt} seats.", flush=True)
                        await asyncio.sleep(30)
                    

            except Exception as e:
                print(chat_id, f"⚠️ Internal loop error: {e}")

            finally:
                driver.quit()
                shutil.rmtree(user_data_dir, ignore_errors=True)

        except Exception as e:
            print(chat_id, f"❗ Outer error: {e}\nRetrying in {retry_delay} seconds.")
            await asyncio.sleep(retry_delay)



# ——— Commands: stop, list, cont —————————————————————————————————————————
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    load_user_data()
    if chat_id in user_data_store:
        for p in user_data_store[chat_id]:
            p["completed"] = True
        await update.message.reply_text("🛑 All your monitoring prompts have been stopped.")
    else:
        await update.message.reply_text("No active prompts found.")


async def list_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    load_user_data()
    if chat_id in user_data_store:
        active_prompts = [p for p in user_data_store[chat_id] if not p["completed"]]
        if active_prompts:
            msg = "📋 Ongoing prompts:\n\n"
            for i, p in enumerate(active_prompts, 1):
                msg += (f"{i}. {p['origin']} ➝ {p['destination']} "
                        f"on {p['day']} {p['month']} {p['year']} at {p['time']} "
                        f"({p['passengers']} pax)\n")
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text("✅ You have no active monitoring prompts.")
    else:
        await update.message.reply_text("No prompts found for you.")


async def remove_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    load_user_data()

    if chat_id not in user_data_store:
        await update.message.reply_text("No prompts found for you.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /remove <index>")
        return

    index = int(context.args[0]) - 1
    active_prompts = [p for p in user_data_store[chat_id] if not p["completed"]]

    if not active_prompts:
        await update.message.reply_text("✅ You have no active monitoring prompts.")
        return

    if 0 <= index < len(active_prompts):
        to_remove = active_prompts[index]

        # Remove the matching prompt from the full list
        user_data_store[chat_id] = [
            p for p in user_data_store[chat_id]
            if not (
                not p["completed"] and
                p["origin"] == to_remove["origin"] and
                p["destination"] == to_remove["destination"] and
                p["day"] == to_remove["day"] and
                p["month"] == to_remove["month"] and
                p["year"] == to_remove["year"] and
                p["time"] == to_remove["time"] and
                p["passengers"] == to_remove["passengers"]
            )
        ]

        save_user_data()
        await update.message.reply_text("🗑️ Prompt removed successfully.")
    else:
        await update.message.reply_text("Invalid index. Use /list to see active prompts.")


# ——— Application setup —————————————————————————————————————————————————
async def resume_prompts(app):
    for chat_id, prompts in user_data_store.items():
        for prompt in prompts:
            if not prompt.get("completed", False):
                asyncio.create_task(run_selenium_check(prompt, app.bot, chat_id))

def main():
    load_user_data()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ✅ Async post-init hook
    app.post_init = resume_prompts

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ORIGIN:         [CallbackQueryHandler(origin_handler)],
            CALENDAR_STATE: [CallbackQueryHandler(calendar_handler)],
            TIME_STATE:     [CallbackQueryHandler(time_handler)],
            PASSENGERS:     [CallbackQueryHandler(passenger_handler)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("list", list_prompts))
    app.add_handler(CommandHandler("remove", remove_prompt))

    app.run_polling()


if __name__ == '__main__':
    main()
