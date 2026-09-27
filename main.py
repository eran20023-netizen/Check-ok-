import os
import shutil
import asyncio
import uuid
import json
import base64
import requests
import time
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, FSInputFile, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

# ==========================================
# تنظیمات توکن ربات و سورس پروکسی
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ مقدار BOT_TOKEN پیدا نشد! لطفا آن را در Railway تنظیم کن.")

# در صورت تمایل می‌توانید لینک پروکسی را به عنوان ENV در ریل‌وی تنظیم کنید
PROXY_SOURCE_URL = os.getenv("PROXY_SOURCE_URL", "")

router = Router()

SESSION_BASE_DIR = "bot_sessions"
if os.path.exists(SESSION_BASE_DIR):
    shutil.rmtree(SESSION_BASE_DIR, ignore_errors=True)
os.makedirs(SESSION_BASE_DIR, exist_ok=True)

# ==========================================
# لیست پروکسی‌های پیش‌فرض (در صورت نبود لینک)
# ==========================================
PROXY_LIST = [
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@104.207.60.223:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@209.50.172.154:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@209.50.185.152:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@65.111.2.72:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@216.26.251.100:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@104.207.62.5:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@216.26.231.8:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@65.111.14.22:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@104.207.51.42:3129",
    "http://bvsfmwq1pkcx:rc3ne2cfcecl786@104.207.36.37:3129"
]

# ==========================================
# موتور هوشمند پارس و استانداردسازی پروکسی
# ==========================================
def normalize_proxy(line: str) -> str:
    """
    تبدیل هوشمند انواع فرمت‌های پروکسی به فرمت استاندارد http://user:pass@host:port
    پشتیبانی از IP، دامنه، بدون رمز، با رمز، و جابه‌جایی پارامترها
    """
    if not line:
        return None
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    scheme = "http"
    if "://" in line:
        parts_scheme = line.split("://", 1)
        scheme = parts_scheme[0].lower()
        line = parts_scheme[1]

    # حالت فرمت استاندارد دارای @
    if "@" in line:
        auth_part, netloc = line.split("@", 1)
        return f"{scheme}://{auth_part}@{netloc}"

    # تفکیک بر اساس دو نقطه (:)
    parts = line.split(":")

    # حالت ۱: دو قسمتی -> host:port
    if len(parts) == 2:
        host, port = parts
        if port.isdigit():
            return f"{scheme}://{host}:{port}"

    # حالت ۲: چهار قسمتی -> تشخیص خودکار جایگاه پورت و مشخصات
    elif len(parts) == 4:
        p1, p2, p3, p4 = parts

        # مدل اول: host:port:user:pass (رایج‌ترین فرمت)
        if p2.isdigit() and not p4.isdigit():
            return f"{scheme}://{p3}:{p4}@{p1}:{p2}"

        # مدل دوم: user:pass:host:port
        elif p4.isdigit() and not p2.isdigit():
            return f"{scheme}://{p1}:{p2}@{p3}:{p4}"

        # در صورتی که هر دو پارامتر عددی بودند (تشخیص هوشمند از روی کاراکترهای هاست/دامنه)
        elif p2.isdigit() and p4.isdigit():
            if "." in p1 and "." not in p3:
                return f"{scheme}://{p3}:{p4}@{p1}:{p2}"
            elif "." in p3 and "." not in p1:
                return f"{scheme}://{p1}:{p2}@{p3}:{p4}"
            else:
                return f"{scheme}://{p3}:{p4}@{p1}:{p2}"

    # حالت ۳: سه قسمتی (host:port:user یا user:host:port)
    elif len(parts) == 3:
        p1, p2, p3 = parts
        if p2.isdigit():
            return f"{scheme}://{p3}@{p1}:{p2}"
        elif p3.isdigit():
            return f"{scheme}://{p1}@{p2}:{p3}"

    return None

def fetch_proxies_from_url(url: str):
    """دریافت آنلاین پروکسی‌ها از لینک و پاکسازی و بارگذاری در حافظه"""
    global PROXY_LIST
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return 0, f"خطای HTTP: {response.status_code}"

        parsed_proxies = []
        for raw_line in response.text.splitlines():
            cleaned = normalize_proxy(raw_line)
            if cleaned and cleaned not in parsed_proxies:
                parsed_proxies.append(cleaned)

        if parsed_proxies:
            PROXY_LIST = parsed_proxies
            return len(parsed_proxies), None
        return 0, "هیچ پروکسی معتبری داخل متن لینک پیدا نشد."
    except Exception as e:
        return 0, f"خطای ارتباط: {type(e).__name__}"

def get_random_proxy():
    selected = random.choice(PROXY_LIST)
    return {
        "http": selected,
        "https": selected
    }

def test_proxy_on_startup():
    global PROXY_LIST
    if PROXY_SOURCE_URL:
        print(f"🌐 [Startup] دریافت پروکسی‌ها از لینک تعریف‌شده...")
        count, err = fetch_proxies_from_url(PROXY_SOURCE_URL)
        if count > 0:
            print(f"✅ تعداد {count} پروکسی با موفقیت بارگذاری شد.")
        else:
            print(f"⚠️ عدم موفقیت در دریافت پروکسی از لینک: {err}. استفاده از لیست پیش‌فرض.")

    print("🔍 [Startup] بررسی سلامت یکی از پروکسی‌ها به صورت تصادفی...")
    try:
        proxies = get_random_proxy()
        raw_target = proxies['http'].split('@')[-1] if '@' in proxies['http'] else proxies['http'].replace('http://', '')
        res = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=15)
        if res.status_code == 200:
            print(f"✅ ارتباط با سرور پروکسی ({raw_target}) موفق بود! آی‌پی خروجی: {res.json().get('ip')}")
            return True
    except Exception as e:
        print(f"⚠️ خطای پروکسی در استارتاپ: {type(e).__name__}")
    return False

# ==========================================
# استخراج توکن‌ها از JSON سشن اکانت
# ==========================================
def extract_tokens_from_json(data):
    access_token, refresh_token = None, None
    try:
        for cookie in data.get('cookies', []):
            if cookie.get('name') in ['tokenMS', 'token']:
                access_token = cookie.get('value')
            elif cookie.get('name') == 'refresh_token':
                refresh_token = cookie.get('value')

        if not access_token or not refresh_token:
            for origin in data.get('origins', []):
                for item in origin.get('localStorage', []):
                    if item.get('name') in ['tokenMS', 'token'] and not access_token:
                        access_token = item.get('value')
                    elif item.get('name') == 'refresh_token' and not refresh_token:
                        refresh_token = item.get('value')
    except Exception:
        pass
    return access_token, refresh_token

def get_account_meta_from_token(token):
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        user_id = data.get('cerberusId') or data.get('alternativeCustomerId') or data.get('userId')
        phone = data.get('username') or data.get('userName') or "نامشخص"
        return user_id, phone
    except Exception:
        return None, "نامشخص"

def refresh_okala_token(refresh_token, proxies):
    url = "https://apigateway.okala.com/api/v1/accounts/tokens"
    payload = {
        "grant_type": "refresh_token",
        "client_id": "customer_client_id",
        "client_secret": "u_M{'57j!%LI21#",
        "scope": "offline_access",
        "refresh_token": refresh_token
    }
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile"
    }
    try:
        res = requests.post(url, data=payload, headers=headers, proxies=proxies, timeout=30)
        if res.status_code == 200:
            d = res.json()
            return d.get('access_token'), d.get('refresh_token')
    except Exception:
        pass
    return None, None

def check_single_account(token, proxies):
    user_uuid, phone = get_account_meta_from_token(token)
    if not user_uuid:
        return "error_uuid", phone

    api_url = f"https://apigateway.okala.com/api/discount/v1/discounts/customer/{user_uuid}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json, text/plain, */*',
        'source': 'okala',
        'ui-version': '2.0',
        'origin': 'https://www.okala.com',
        'X-Correlation-Id': str(uuid.uuid4()),
        'X-User-Unique-Id': str(uuid.uuid4()),
        'session-id': str(uuid.uuid4()),
        'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
        'sec-ch-ua-mobile': '?1',
        'sec-ch-ua-platform': '"Android"',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile'
    }

    try:
        res = requests.get(api_url, headers=headers, proxies=proxies, timeout=30)
        if res.status_code == 200:
            discounts = res.json().get('data', [])
            if not discounts:
                return 0, phone
            valid_amounts = [d.get('discountAmount', 0) for d in discounts if d.get('discountAmount')]
            return (max(valid_amounts) if valid_amounts else 0), phone
        elif res.status_code == 401:
            return "expired", phone
        else:
            return f"error_api_{res.status_code}", phone
    except Exception as e:
        return f"error_net_{type(e).__name__}", phone

# ==========================================
# بررسی موازی لینک‌های ارسالی کاربر
# ==========================================
def worker_process_link(url):
    try:
        res = requests.get(url, timeout=25, proxies=get_random_proxy())
        if res.status_code != 200:
            return url, "نامشخص", f"خطای دانلود لینک ({res.status_code})"
        json_data = res.json()
    except Exception as e:
        return url, "نامشخص", f"خطا در خواندن داده: {type(e).__name__}"

    acc_token, ref_token = extract_tokens_from_json(json_data)
    if not acc_token:
        return url, "نامشخص", "توکن پیدا نشد"

    _, phone = get_account_meta_from_token(acc_token)

    result = "error_net_init"
    for _ in range(3):
        current_proxy = get_random_proxy()
        result, phone = check_single_account(acc_token, proxies=current_proxy)
        if "error_net" not in str(result):
            break
        time.sleep(1)

    if result == "expired" and ref_token:
        new_acc = None
        for _ in range(3):
            current_proxy = get_random_proxy()
            new_acc, _ = refresh_okala_token(ref_token, proxies=current_proxy)
            if new_acc:
                break
            time.sleep(1.5)

        if new_acc:
            for _ in range(3):
                current_proxy = get_random_proxy()
                result, phone = check_single_account(new_acc, proxies=current_proxy)
                if "error_net" not in str(result):
                    break
                time.sleep(1)

    if isinstance(result, int):
        if result > 0:
            return url, phone, int(result / 10000)
        return url, phone, 0
    elif result == "expired":
        return url, phone, "منقضی شده"
    return url, phone, str(result)

def process_links_list(links):
    results = []
    with ThreadPoolExecutor(max_workers=min(12, len(links))) as executor:
        futures = {executor.submit(worker_process_link, url): url for url in links}
        for f in as_completed(futures):
            results.append(f.result())
    return results

# ==========================================
# بررسی فایل‌های زیپ اکانت‌ها
# ==========================================
def get_tokens_from_local_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return extract_tokens_from_json(json.load(f))
    except Exception:
        return None, None

def update_file_tokens(file_path, old_acc, new_acc, old_ref, new_ref):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if old_acc and new_acc:
            content = content.replace(old_acc, new_acc)
        if old_ref and new_ref:
            content = content.replace(old_ref, new_ref)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception:
        pass

def worker_check_account_file(file_path, filename):
    time.sleep(random.uniform(0.1, 0.4))
    acc_token, ref_token = get_tokens_from_local_file(file_path)
    if not acc_token:
        return filename, file_path, "no_token"

    result = "error_net_init"
    for _ in range(3):
        current_proxy = get_random_proxy()
        result, _ = check_single_account(acc_token, proxies=current_proxy)
        if "error_net" not in str(result):
            break
        time.sleep(1)

    if "error_net" in str(result):
        return filename, file_path, result

    if result == "expired" and ref_token:
        new_acc, new_ref = None, None
        for _ in range(3):
            current_proxy = get_random_proxy()
            new_acc, new_ref = refresh_okala_token(ref_token, proxies=current_proxy)
            if new_acc:
                break
            time.sleep(1.5)

        if new_acc:
            update_file_tokens(file_path, acc_token, new_acc, ref_token, new_ref)
            for _ in range(3):
                current_proxy = get_random_proxy()
                result, _ = check_single_account(new_acc, proxies=current_proxy)
                if "error_net" not in str(result):
                    break
                time.sleep(1)

    return filename, file_path, result

def process_and_categorize(extracted_dir, session_dir):
    src_accounts, src_data = None, None
    for root, dirs, _ in os.walk(extracted_dir):
        if 'accounts' in dirs and not src_accounts:
            src_accounts = os.path.join(root, 'accounts')
        if 'data' in dirs and not src_data:
            src_data = os.path.join(root, 'data')

    if not src_accounts:
        return None, None, "پوشه 'accounts' داخل فایل زیپ پیدا نشد."

    categories = {}
    stats = {"total": 0, "discounts": 0, "nodiscounts": 0, "expired": 0, "errors": 0}

    nodiscount_path = os.path.join(session_dir, "No_Discount")
    os.makedirs(os.path.join(nodiscount_path, 'accounts'), exist_ok=True)
    os.makedirs(os.path.join(nodiscount_path, 'data'), exist_ok=True)
    if src_data and os.path.exists(os.path.join(src_data, 'accounts.json')):
        shutil.copy2(os.path.join(src_data, 'accounts.json'), os.path.join(nodiscount_path, 'data'))

    all_files = [f for f in os.listdir(src_accounts) if os.path.isfile(os.path.join(src_accounts, f))]
    stats["total"] = len(all_files)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(worker_check_account_file, os.path.join(src_accounts, filename), filename): filename
            for filename in all_files
        }

        for future in as_completed(futures):
            filename, file_path, result = future.result()

            if result == "no_token":
                shutil.copy2(file_path, os.path.join(nodiscount_path, 'accounts'))
                stats["errors"] += 1
                continue

            if isinstance(result, int) and result > 0:
                stats["discounts"] += 1
                amount_hezar_toman = int(result / 10000)

                cat_id = f"dl_{amount_hezar_toman}"
                if cat_id not in categories:
                    cat_path = os.path.join(session_dir, f"Discount_{amount_hezar_toman}T")
                    os.makedirs(os.path.join(cat_path, 'accounts'), exist_ok=True)
                    os.makedirs(os.path.join(cat_path, 'data'), exist_ok=True)
                    if src_data and os.path.exists(os.path.join(src_data, 'accounts.json')):
                        shutil.copy2(os.path.join(src_data, 'accounts.json'), os.path.join(cat_path, 'data'))
                    categories[cat_id] = {
                        "title": f"تخفیف {amount_hezar_toman} هزار تومانی",
                        "path": cat_path,
                        "count": 0,
                        "file_name": f"Discount_{amount_hezar_toman}T_Final"
                    }

                shutil.copy2(file_path, os.path.join(categories[cat_id]['path'], 'accounts'))
                categories[cat_id]['count'] += 1
            else:
                shutil.copy2(file_path, os.path.join(nodiscount_path, 'accounts'))
                if result == 0:
                    stats["nodiscounts"] += 1
                elif result == "expired":
                    stats["expired"] += 1
                else:
                    stats["errors"] += 1

    total_nodiscounts = stats["nodiscounts"] + stats["expired"] + stats["errors"]
    if total_nodiscounts > 0:
        categories["dl_nodiscount"] = {
            "title": "بدون تخفیف (یا منقضی/خطا)",
            "path": nodiscount_path,
            "count": total_nodiscounts,
            "file_name": "No_Discount_Final"
        }

    return categories, stats, None

# ==========================================
# ارسال گزارش متنی
# ==========================================
async def generate_and_send_txt_report(message: Message, urls: list):
    wait_msg = await message.answer(f"⏳ در حال بررسی {len(urls)} لینک با ورکرها و پروکسی‌های اختصاصی...")
    results = await asyncio.to_thread(process_links_list, urls)
    await wait_msg.delete()

    discounted = []
    no_discount = []
    failed = []

    for url, phone, res in results:
        if isinstance(res, int) and res > 0:
            discounted.append((phone, res, url))
        elif res == 0:
            no_discount.append((phone, url))
        else:
            failed.append((phone, res, url))

    lines = [
        "============================================================",
        "                  گزارش بررسی لینک‌های اکانت                ",
        "============================================================",
        f"تعداد کل لینک‌های بررسی شده: {len(urls)}",
        f"تعداد اکانت‌های دارای تخفیف: {len(discounted)}",
        f"تعداد بدون تخفیف: {len(no_discount)}",
        f"تعداد منقضی یا دارای خطا: {len(failed)}",
        "------------------------------------------------------------\n"
    ]

    if discounted:
        lines.append("🎁 [لیست اکانت‌های دارای تخفیف]")
        for phone, amt, u in sorted(discounted, key=lambda x: x[1], reverse=True):
            lines.append(f"شماره: {phone} | تخفیف: {amt} هزار تومان | لینک: {u}")
        lines.append("")

    if no_discount:
        lines.append("➖ [لیست اکانت‌های بدون تخفیف]")
        for phone, u in no_discount:
            lines.append(f"شماره: {phone} | بدون تخفیف | لینک: {u}")
        lines.append("")

    if failed:
        lines.append("❌ [لیست اکانت‌های دارای خطا یا منقضی]")
        for phone, err, u in failed:
            lines.append(f"شماره: {phone} | وضعیت: {err} | لینک: {u}")
        lines.append("")

    txt_content = "\n".join(lines).encode("utf-8")
    doc_file = BufferedInputFile(txt_content, filename="Okala_Discount_Links.txt")

    summary_caption = (
        "✅ بررسی لینک‌ها انجام شد.\n\n"
        f"▫️ کل لینک‌ها: {len(urls)}\n"
        f"▫️ دارای تخفیف: {len(discounted)}\n"
        f"▫️ بدون تخفیف: {len(no_discount)}\n"
        f"▫️ منقضی/خطا: {len(failed)}\n\n"
        "📄 گزارش متنی (.txt) پیوست شد."
    )

    await message.answer_document(document=doc_file, caption=summary_caption)

# ==========================================
# هندلرهای تلگرام
# ==========================================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "سلام! 👋\n\n"
        "قابلیت‌های ربات:\n"
        "1️⃣ بررسی لیست لینک‌ها (متنی یا فایل .txt)\n"
        "2️⃣ بررسی فایل زیپ (.zip)\n"
        f"3️⃣ به‌روزرسانی آنلاین پروکسی‌ها با دستور:\n`/setproxy <link>`\n\n"
        f"تعداد پروکسی‌های فعال کنونی: {len(PROXY_LIST)}",
        parse_mode="Markdown"
    )

@router.message(Command("setproxy"))
async def cmd_set_proxy(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("لطفاً لینک پروکسی را وارد کنید:\n`/setproxy https://example.com/proxies.txt`", parse_mode="Markdown")
        return

    proxy_url = parts[1].strip()
    status_msg = await message.answer("در حال دریافت، پارس و نرمال‌سازی پروکسی‌ها...")

    count, err = await asyncio.to_thread(fetch_proxies_from_url, proxy_url)
    if count > 0:
        await status_msg.edit_text(
            f"✅ لیست پروکسی‌ها با موفقیت به‌روزرسانی شد!\n\n"
            f"▫️ تعداد پروکسی‌های معتبر و شناسایی‌شده: {count}\n"
            f"▫️ کلیه فرمت‌ها نرمال‌سازی شدند."
        )
    else:
        await status_msg.edit_text(f"❌ خطا در بارگذاری پروکسی‌ها: {err}")

@router.message(F.text)
async def handle_links_text(message: Message):
    urls = re.findall(r'https?://[^\s]+', message.text)
    if not urls:
        await message.answer("لینکی داخل پیام شما پیدا نشد. لطفاً لینک یا فایل ارسال کنید.")
        return
    await generate_and_send_txt_report(message, urls)

@router.message(F.document)
async def handle_document(message: Message, bot: Bot):
    file_name = message.document.file_name.lower()

    if file_name.endswith('.txt'):
        file_obj = await bot.get_file(message.document.file_id)
        downloaded = await bot.download_file(file_obj.file_path)
        content = downloaded.read().decode('utf-8', errors='ignore')
        urls = re.findall(r'https?://[^\s]+', content)

        if not urls:
            await message.answer("❌ هیچ لینکی داخل این فایل متنی پیدا نشد.")
            return

        await generate_and_send_txt_report(message, urls)
        return

    if file_name.endswith('.zip'):
        msg = await message.answer("⏳ در حال دانلود و استخراج فایل زیپ...")

        session_id = str(uuid.uuid4())
        session_dir = os.path.join(SESSION_BASE_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)

        extracted_dir = os.path.join(session_dir, "extracted")
        zip_path = os.path.join(session_dir, "uploaded.zip")

        file_info = await bot.get_file(message.document.file_id)
        await bot.download_file(file_info.file_path, zip_path)

        try:
            shutil.unpack_archive(zip_path, extracted_dir)
        except Exception:
            await msg.edit_text("❌ فایل زیپ مشکل دارد و باز نمی‌شود.")
            shutil.rmtree(session_dir, ignore_errors=True)
            return

        await msg.edit_text("⚡️ در حال بررسی اکانت‌ها با پروکسی‌های فعال...")

        categories, stats, error_msg = await asyncio.to_thread(
            process_and_categorize, extracted_dir, session_dir
        )

        if error_msg:
            await msg.edit_text(error_msg)
            shutil.rmtree(session_dir, ignore_errors=True)
            return

        await msg.delete()

        if not categories:
            await message.answer("⚠️ هیچ فایل معتبری داخل زیپ پیدا نشد.")
            shutil.rmtree(session_dir, ignore_errors=True)
            return

        await message.answer("✅ بررسی تمام شد. در حال ارسال فایل‌های زیپ...")

        for cat_id, info in categories.items():
            if info['count'] > 0:
                zip_path_base = os.path.join(session_dir, info["file_name"])
                final_zip_path = shutil.make_archive(zip_path_base, 'zip', info["path"])

                await message.answer_document(
                    document=FSInputFile(final_zip_path),
                    caption=f"{info['title']}\nتعداد: {info['count']} اکانت"
                )

        report = (
            "📊 گزارش نهایی بررسی زیپ:\n\n"
            f"📁 کل فایل‌ها: {stats['total']}\n"
            f"🎁 دارای تخفیف: {stats['discounts']}\n"
            f"➖ بدون تخفیف/منقضی/خطا: {stats['nodiscounts'] + stats['expired'] + stats['errors']}\n\n"
            "🧹 حافظه موقت پاکسازی شد."
        )
        await message.answer(report)
        shutil.rmtree(session_dir, ignore_errors=True)
        return

    await message.answer("❌ فرمت فایل پشتیبانی نمی‌شود. لطفاً فایل زیپ (.zip) یا متنی (.txt) ارسال کنید.")

# ==========================================
# استارت ربات
# ==========================================
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    test_proxy_on_startup()

    print("🤖 Bot is up and running...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
