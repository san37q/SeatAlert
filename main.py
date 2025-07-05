import asyncio
from playwright.async_api import async_playwright
from telegram import Bot
from telegram.constants import ParseMode
from collections import defaultdict
from datetime import datetime, timedelta
import json

# 📥 Load config
import os

config_json = os.getenv("CONFIG_JSON")
if not config_json:
    raise ValueError("❌ CONFIG_JSON environment variable is missing!")

CONFIGS = json.loads(config_json)

TELEGRAM_BOT_TOKEN = "7616332352:AAEXYsoQk7mOe2okiNxrwJUaC0l1guQB6qM"
TELEGRAM_USER_ID = 834245089

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_telegram_message(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_USER_ID, text=message, parse_mode=ParseMode.HTML)
        print("✅ Telegram message sent!")
    except Exception as e:
        print("❌ Telegram error:", e)

def is_row_in_range(aria_label, valid_rows):
    try:
        parts = aria_label.lower().split("row ")
        if len(parts) > 1:
            row = parts[1].split(",")[0].strip().upper()
            return row in list(valid_rows)
    except:
        pass
    return False

def log_to_file(message, movie_name):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(f"log_{movie_name.replace(' ', '_')}.txt", "a", encoding="utf-8") as f:
        f.write(f"[{now}] {message}\n\n")

async def click_imax_tab(page):
    try:
        await page.wait_for_selector("#imaxd", timeout=10000)
        imax_tab = page.locator("#imaxd")
        class_attr = await imax_tab.get_attribute("class")
        if class_attr and "MDPFilterPills_active__MoRCa" in class_attr:
            return
        clickable = imax_tab.locator("div[aria-label*='IMAX']")
        for attempt in range(5):
            try:
                if await clickable.is_visible():
                    await clickable.scroll_into_view_if_needed()
                    await clickable.click(force=True)
                    print("✅ IMAX tab clicked.")
                    return
                else:
                    print(f"⏳ IMAX clickable not visible (attempt {attempt + 1})")
            except Exception as e:
                print(f"⚠️ Click failed (attempt {attempt + 1}): {e}")
            await asyncio.sleep(1)
        print("❌ Failed to click IMAX tab after retries.")
    except Exception as e:
        print(f"❌ IMAX tab selector error: {e}")

async def check_available_shows(movie_url, showdate, seat_row, seat_range, movie_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"🌐 Checking {movie_name} on {showdate}...")

        now = datetime.now()

        try:
            await page.goto(movie_url)
            await click_imax_tab(page)

            date_selector = page.locator(".DatesMobileV2_movieDateText__AA4n3", has_text=showdate)
            if await date_selector.count() == 0:
                msg = f"❌ Show date '{showdate}' not found for {movie_name}"
                print(msg)
                await send_telegram_message(msg)
                return
            await date_selector.first.click()

            await page.wait_for_selector(".MovieSessionsListing_time___f5tm", timeout=10000)
            shows = page.locator(".MovieSessionsListing_time___f5tm")
            show_count = await shows.count()

            valid_shows = []

            for i in range(show_count):
                show_el = shows.nth(i)
                class_list = await show_el.get_attribute("class")
                if "greyCol" in class_list:
                    continue

                raw_text = (await show_el.inner_text()).strip()
                show_time_text = raw_text.splitlines()[0].strip()
                try:
                    show_time_obj = datetime.strptime(show_time_text, "%I:%M %p").time()
                    current_year = now.year
                    show_day = datetime.strptime(f"{showdate} {now.strftime('%b')} {current_year}", "%d %b %Y").date()
                    show_datetime = datetime.combine(show_day, show_time_obj)
                    if show_datetime >= now + timedelta(hours=1):
                        valid_shows.append((show_el, show_time_text))
                except Exception as e:
                    print(f"⚠️ Skipping show '{show_time_text}': {e}")
                    continue

            if not valid_shows:
                msg = f"❌ No valid shows after 1 hour for <b>{movie_name}</b> on <b>{showdate}</b>."
                print(msg)
                await send_telegram_message(msg)
                return

            for show_el, show_time_text in valid_shows:
                print(f"🎫 Checking show at {show_time_text}...")
                await show_el.click()

                try:
                    await page.wait_for_selector("div.FixedSeating_seatDiv__NvlNl", timeout=10000)
                except:
                    msg = f"❌ Show at {show_time_text} is not accessible (possibly sold out)."
                    print(msg)
                    await send_telegram_message(msg)
                    await page.go_back()
                    await click_imax_tab(page)
                    await page.locator(".DatesMobileV2_cinemaDates__d82fR", has_text=showdate).click()
                    continue

                seats = await page.query_selector_all("span.available[role='button']")
                row_map = defaultdict(list)

                for seat in seats:
                    aria_label = await seat.get_attribute("aria-label")
                    if aria_label and is_row_in_range(aria_label, seat_row):
                        row_part = aria_label.lower().split("row ")[1]
                        row = row_part.split(",")[0].strip().upper()
                        price = aria_label.lower().split("price ")[1].strip()
                        label_el = await seat.query_selector("label")
                        seat_number_text = await label_el.inner_text() if label_el else "?"

                        try:
                            seat_number = int(seat_number_text)
                        except:
                            seat_number = None

                        if seat_range and seat_number:
                            if not (seat_range[0] <= seat_number <= seat_range[1]):
                                continue  # 🚫 Skip seat outside configured range

                        row_map[row].append((seat_number_text, price))

                if row_map:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message_lines = [f"🎯 <b>{movie_name}</b> | <i>{showdate}, {show_time_text}</i> | Rows {seat_row} at {ts}:"]
                    for row in sorted(row_map):
                        cols = ", ".join([col for col, _ in row_map[row]])
                        price = row_map[row][0][1]
                        message_lines.append(f"{row} - {cols} (₹{price})")
                    final_message = "\n".join(message_lines)
                    print(final_message)
                    await send_telegram_message(final_message)
                    log_to_file(final_message, movie_name)
                else:
                    msg = f"😴 No seats in rows {seat_row} (range {seat_range}) for {movie_name} at {show_time_text} on {showdate}."
                    print(msg)
                    await send_telegram_message(msg)

                await page.go_back()
                await page.wait_for_selector("#imaxd", timeout=10000)
                await click_imax_tab(page)
                await page.wait_for_selector(".DatesMobileV2_movieDateText__AA4n3", timeout=10000)
                await page.locator(".DatesMobileV2_movieDateText__AA4n3", has_text=showdate).click()

        except Exception as e:
            err_msg = f"❌ Error for {movie_name}: {e}"
            print(err_msg)
            await send_telegram_message(err_msg)

        await browser.close()

async def run_all():
    while True:
        for cfg in CONFIGS:
            await check_available_shows(
                cfg["movie_url"],
                cfg["showdate"],
                cfg["rows"],
                cfg.get("seat_range"),
                cfg["movie_name"]
            )
        print("⏳ Waiting 3 minutes...\n")
        await asyncio.sleep(180)

if __name__ == "__main__":
    asyncio.run(run_all())
