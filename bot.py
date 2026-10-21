import os, json, hmac, hashlib, sqlite3, time, asyncio
from urllib.parse import parse_qsl
from aiohttp import web, ClientSession
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo, MenuButtonWebApp, LabeledPrice)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
E = os.environ.get
TOKEN, URL = E("BOT_TOKEN"), E("WEBAPP_URL", "").rstrip("/")
ADMINS = {int(x) for x in E("ADMIN_IDS", "").split(",") if x.strip()}
CB, XR, SUPPORT = E("CRYPTOBOT_TOKEN"), E("XROCKET_TOKEN"), E("SUPPORT", "@support")
SHOP_NAME = E("SHOP_NAME", "TRICK | API")
CURRENCY = E("SHOP_CURRENCY", "USD")
DATA = os.path.join(os.path.dirname(__file__), "data")
db = sqlite3.connect(os.path.join(os.path.dirname(__file__), "shop.db"), check_same_thread=False); db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, balance REAL DEFAULT 0, ref INTEGER, earned REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, name TEXT, descr TEXT, cat TEXT, img TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS packs(id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, label TEXT, price REAL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, pid TEXT, label TEXT, price REAL, code TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS pays(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, prov TEXT, ext TEXT, amount REAL, status TEXT DEFAULT 'new', ts INTEGER);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stars_pending(payload TEXT PRIMARY KEY, uid INTEGER, amount REAL, ts INTEGER, credited INTEGER DEFAULT 0);
""")
if not db.execute("SELECT 1 FROM products").fetchone():
    catalog = [
      ('claude-opus-5','Claude Opus 5','Продвинутая модель для сложных задач и анализа','Текст','https://images.unsplash.com/photo-1677442136019-21780ecad995?w=320&h=320&fit=crop'),
      ('claude-sonnet-5','Claude Sonnet 5','Баланс скорости и качества для ежедневной работы','Текст','https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=320&h=320&fit=crop'),
      ('gpt-5-6-sol','GPT-5.6 Sol','Универсальный ИИ-помощник','Текст','https://images.unsplash.com/photo-1676299081847-824916de030a?w=320&h=320&fit=crop'),
      ('gpt-4-1','GPT-4.1','Модель для кода, текста и рассуждений','Текст','https://images.unsplash.com/photo-1518770660439-4636190af475?w=320&h=320&fit=crop'),
      ('gemini-25-pro','Gemini 2.5 Pro','Мультимодальная модель для сложных запросов','Текст','https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=320&h=320&fit=crop'),
      ('gemini-20-flash','Gemini 2.0 Flash','Быстрые ответы и повседневные задачи','Текст','https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=320&h=320&fit=crop'),
      ('deepseek-v3','DeepSeek V3','Модель для программирования и логики','Текст','https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=320&h=320&fit=crop'),
      ('grok-4','Grok 4','ИИ для исследования и генерации идей','Текст','https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=320&h=320&fit=crop'),
      ('flux1-pro','FLUX.1 Pro','Генерация изображений','Изображения','https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=320&h=320&fit=crop'),
      ('gpt-image-1','GPT Image 1','Создание и редактирование изображений','Изображения','https://images.unsplash.com/photo-1549490349-8643362247b5?w=320&h=320&fit=crop'),
      ('elevenlabs-v3','ElevenLabs v3','Генерация реалистичного голоса','Аудио','https://images.unsplash.com/photo-1590602847861-f357a9332bbc?w=320&h=320&fit=crop'),
      ('veo-31','Veo 3.1','Генерация видео по тексту','Видео','https://images.unsplash.com/photo-1485846234645-a62644f84728?w=320&h=320&fit=crop')]
    for item in catalog:
      db.execute('INSERT INTO products(id,name,descr,cat,img,active) VALUES(?,?,?,?,?,1)', item)
      db.executemany('INSERT INTO packs(pid,label,price) VALUES(?,?,?)', [(item[0], 'Старт', 2.5), (item[0], 'Стандарт', 4.0), (item[0], 'Профи', 7.5)])
    db.commit()
for key, value in [('pay_cryptobot','1' if CB else '0'),('pay_xrocket','1' if XR else '0'),('pay_stars','1' if TOKEN else '0'),('shop_name',SHOP_NAME),('support',SUPPORT)]:
    db.execute('INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)',(key,value))
db.commit()

def stock(pid):
    p = os.path.join(DATA, f"{pid}.txt")
    return [l.strip() for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
def pop_item(pid):
    items = stock(pid)
    if not items: return None
    open(os.path.join(DATA, f"{pid}.txt"), "w", encoding="utf-8").write("\n".join(items[1:]) + ("\n" if items[1:] else ""))
    return items[0]
lock = asyncio.Lock()

def auth(init):
    if not TOKEN or not init: return None
    d = dict(parse_qsl(init, keep_blank_values=True)); h = d.pop("hash", "")
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not h or not hmac.compare_digest(hmac.new(key, chk.encode(), hashlib.sha256).hexdigest(), h): return None
    try:
        if abs(int(time.time()) - int(d.get("auth_date", "0"))) > 86400: return None
        return json.loads(d["user"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError): return None

def ensure(u, ref=None):
    if not db.execute("SELECT 1 FROM users WHERE id=?", (u["id"],)).fetchone():
        r = ref if ref and ref != u["id"] and db.execute("SELECT 1 FROM users WHERE id=?", (ref,)).fetchone() else None
        db.execute("INSERT INTO users(id,name,ref) VALUES(?,?,?)", (u["id"], u.get("first_name", ""), r)); db.commit()

async def http(method, url, **kw):
    async with ClientSession() as s:
        async with s.request(method, url, **kw) as r: return await r.json()

async def create_invoice(prov, amount):
    if prov == "cryptobot":
        if not CB: raise ValueError("CryptoBot не настроен в .env")
        r = await http("POST", "https://pay.crypt.bot/api/createInvoice", headers={"Crypto-Pay-API-Token": CB},
            json={"currency_type": "fiat", "fiat": "USD", "amount": str(amount), "accepted_assets": "USDT,TON,BTC,ETH"})
        return str(r["result"]["invoice_id"]), r["result"]["bot_invoice_url"]
    if not XR: raise ValueError("xRocket не настроен в .env")
    client_id = f"shop_{int(time.time())}_{os.urandom(4).hex()}"
    r = await http("POST", "https://pay.api.xrocket.exchange/api/v1/invoices", headers={"Authorization": f"Bearer {XR}", "Accept": "application/json"},
        json={"priceAmount": str(amount), "priceCurrency": "USDT", "payoutCurrency": "USDT", "numPayments": 1,
              "clientInvoiceId": client_id, "description": "Shop balance top up"})
    d = r.get("data", r)
    if not d.get("id") or not d.get("links", {}).get("telegramBotLink"):
        raise ValueError(str(r.get("detail") or r.get("title") or "xRocket returned an unexpected invoice response"))
    return str(d["id"]), d["links"]["telegramBotLink"]

async def is_paid(prov, ext):
    if prov == "cryptobot":
        r = await http("GET", f"https://pay.crypt.bot/api/getInvoices?invoice_ids={ext}", headers={"Crypto-Pay-API-Token": CB})
        return bool(r.get("ok") and r.get("result",{}).get("items") and r["result"]["items"][0].get("status") == "paid")
    r = await http("GET", f"https://pay.api.xrocket.exchange/api/v1/invoice?invoiceId={ext}", headers={"Authorization": f"Bearer {XR}", "Accept": "application/json"})
    d = r.get("data", r)
    return str(d.get("status", "")).lower() == "paid"

async def api(req):
    act, body = req.match_info["a"], await req.json()
    u = auth(req.headers.get("X-Init", ""))
    if not u: return web.json_response({"error": "auth"}, status=401)
    ensure(u); uid = u["id"]; adm = uid in ADMINS
    q = lambda *a: db.execute(*a).fetchall()
    if act == "init":
        me = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        prods = [dict(p, stock=len(stock(p["id"])), packs=[dict(k) for k in q("SELECT * FROM packs WHERE pid=?", (p["id"],))])
                 for p in q("SELECT * FROM products WHERE active=1")]
        spent = db.execute("SELECT COALESCE(SUM(price),0) FROM orders WHERE uid=?", (uid,)).fetchone()[0]
        methods = {r["k"][4:]: r["v"] == "1" for r in q("SELECT * FROM settings WHERE k LIKE 'pay_%'")}
        return web.json_response({"me": dict(me), "admin": adm, "products": prods, "spent": spent, "methods": methods, "shop_name": db.execute("SELECT v FROM settings WHERE k='shop_name'").fetchone()[0],
            "keys": [dict(o) for o in q("SELECT * FROM orders WHERE uid=? ORDER BY id DESC", (uid,))],
            "invited": db.execute("SELECT COUNT(*) FROM users WHERE ref=?", (uid,)).fetchone()[0],
            "history": [dict(p) for p in q("SELECT * FROM pays WHERE uid=? ORDER BY id DESC LIMIT 20", (uid,))],
            "bot": req.app.get("bot_username", ""), "support": db.execute("SELECT v FROM settings WHERE k='support'").fetchone()[0]})
    if act == "buy":
        async with lock:
            pk = db.execute("SELECT * FROM packs WHERE id=?", (body["pack"],)).fetchone()
            bal = db.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()[0]
            if not pk or not db.execute("SELECT 1 FROM products WHERE id=? AND active=1", (pk["pid"],)).fetchone(): return web.json_response({"error": "Товар не найден"}, status=404)
            if bal < pk["price"]: return web.json_response({"error": "Недостаточно средств. Пополни баланс в профиле."}, status=400)
            code = pop_item(pk["pid"])
            if not code: return web.json_response({"error": "Out of stock"})
            db.execute("UPDATE users SET balance=balance-? WHERE id=?", (pk["price"], uid))
            db.execute("INSERT INTO orders(uid,pid,label,price,code,ts) VALUES(?,?,?,?,?,?)", (uid, pk["pid"], pk["label"], pk["price"], code, int(time.time())))
            db.commit()
        return web.json_response({"ok": 1, "code": code})
    if act == "topup":
        try: amt = round(float(body["amount"]), 2)
        except (TypeError, ValueError): return web.json_response({"error":"Некорректная сумма"}, status=400)
        prov = body.get("prov", "")
        enabled = db.execute("SELECT v FROM settings WHERE k=?", ("pay_"+prov,)).fetchone()
        if amt < 1 or amt > 10000 or prov not in ("cryptobot", "xrocket") or not enabled or enabled[0] != "1": return web.json_response({"error": "Способ оплаты отключен или сумма некорректна"}, status=400)
        try: ext, link = await create_invoice(prov, amt)
        except Exception as e: return web.json_response({"error": f"Не удалось создать платеж: {str(e)[:180]}"}, status=502)
        db.execute("INSERT INTO pays(uid,prov,ext,amount,ts) VALUES(?,?,?,?,?)", (uid, prov, ext, amt, int(time.time()))); db.commit()
        return web.json_response({"link": link})
    if act == "stars_invoice":
        enabled = db.execute("SELECT v FROM settings WHERE k='pay_stars'").fetchone()
        try: stars = int(body.get("amount", 0))
        except (TypeError, ValueError): stars = 0
        if not enabled or enabled[0] != "1" or stars < 1 or stars > 100000: return web.json_response({"error":"Оплата Stars отключена или сумма некорректна"}, status=400)
        payload = f"stars:{uid}:{int(time.time())}:{os.urandom(5).hex()}"
        db.execute("INSERT INTO stars_pending(payload,uid,amount,ts) VALUES(?,?,?,?)",(payload,uid,stars,int(time.time())))
        db.commit()
        try:
            shop_title = db.execute("SELECT v FROM settings WHERE k='shop_name'").fetchone()[0]
            link = await req.app["bot"].create_invoice_link(title=f"{shop_title[:20]} Stars", description=f"Зачисление {stars} Stars на баланс магазина", payload=payload, provider_token="", currency="XTR", prices=[LabeledPrice(label=f"{stars} Stars", amount=stars)])
        except Exception as e: return web.json_response({"error":f"Не удалось создать Stars-счет: {str(e)[:160]}"}, status=502)
        return web.json_response({"link":link})
    if act == "check":
        n = 0
        for p in q("SELECT * FROM pays WHERE uid=? AND status='new'", (uid,)):
            if await is_paid(p["prov"], p["ext"]):
                async with lock:
                    if db.execute("UPDATE pays SET status='paid' WHERE id=? AND status='new'", (p["id"],)).rowcount:
                        db.execute("UPDATE users SET balance=balance+? WHERE id=?", (p["amount"], uid))
                        r = db.execute("SELECT ref FROM users WHERE id=?", (uid,)).fetchone()[0]
                        if r: db.execute("UPDATE users SET balance=balance+?, earned=earned+? WHERE id=?", (p["amount"]*.05, p["amount"]*.05, r))
                        db.commit(); n += 1
        return web.json_response({"credited": n})
    if not adm: return web.json_response({"error": "forbidden"}, status=403)
    if act == "a_balance":
        db.execute("INSERT OR IGNORE INTO users(id,name) VALUES(?,?)", (int(body["uid"]), ""))
        db.execute("UPDATE users SET balance=balance+? WHERE id=?", (float(body["amount"]), int(body["uid"]))); db.commit()
    elif act == "a_price":
        db.execute("UPDATE packs SET price=? WHERE id=?", (float(body["price"]), int(body["pack"]))); db.commit()
    elif act == "a_product":  # add/update product + packs, optionally append stock lines
        b = body; pid = str(b.get("id", ""))
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{2,50}", pid): return web.json_response({"error":"ID должен содержать 2–50 латинских букв, цифр, дефисов или подчеркиваний"},status=400)
        name = str(b.get("name", "")).strip()[:100]
        if not name: return web.json_response({"error":"Укажи название товара"},status=400)
        img = str(b.get("img", "")).strip()[:500]
        if img and not img.startswith(("https://", "http://")): return web.json_response({"error":"Ссылка на изображение должна начинаться с http:// или https://"},status=400)
        db.execute("INSERT INTO products(id,name,descr,cat,img,active) VALUES(?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET name=excluded.name,descr=excluded.descr,cat=excluded.cat,img=excluded.img,active=1", (pid, name, str(b.get("descr", ""))[:500], str(b.get("cat", ""))[:50], img))
        if b.get("packs"):
            db.execute("DELETE FROM packs WHERE pid=?", (pid,))
            for l, price in b["packs"]:
                try: price = round(float(price), 2)
                except (TypeError, ValueError): continue
                if str(l).strip() and price > 0: db.execute("INSERT INTO packs(pid,label,price) VALUES(?,?,?)", (pid, str(l).strip()[:60], price))
        if b.get("stock"):
            lines = [line.strip() for line in str(b["stock"]).splitlines() if line.strip()]
            if lines:
                with open(os.path.join(DATA, f"{pid}.txt"), "a", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
        db.commit()
    elif act == "a_delete":
        db.execute("UPDATE products SET active=0 WHERE id=?", (body["id"],)); db.commit()
    elif act == "a_product_delete":
        pid = str(body.get("id", ""))
        db.execute("DELETE FROM packs WHERE pid=?", (pid,))
        db.execute("DELETE FROM products WHERE id=?", (pid,))
        db.commit()
    elif act == "a_payment":
        prov = body.get("prov")
        if prov not in ("cryptobot", "xrocket", "stars"): return web.json_response({"error":"Unknown method"}, status=400)
        db.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", ("pay_"+prov, "1" if body.get("enabled") else "0")); db.commit()
    elif act == "a_settings":
        name = str(body.get("shop_name", "")).strip()[:60]
        support = str(body.get("support", "")).strip()[:120]
        if name:
            db.execute("INSERT INTO settings(k,v) VALUES('shop_name',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(name,))
            try: await req.app["bot"].set_chat_menu_button(menu_button=MenuButtonWebApp(text=name[:64], web_app=WebAppInfo(url=URL)))
            except Exception: pass
        db.execute("INSERT INTO settings(k,v) VALUES('support',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(support,)); db.commit()
    elif act == "a_pack":
        pid = str(body.get("pid", "")); label = str(body.get("label", "")).strip()
        try: price = round(float(body.get("price", 0)), 2)
        except (TypeError, ValueError): price = 0
        if not db.execute("SELECT 1 FROM products WHERE id=?",(pid,)).fetchone() or not label or price <= 0: return web.json_response({"error":"Проверь товар, название пакета и цену"},status=400)
        if body.get("id"):
            db.execute("UPDATE packs SET label=?,price=? WHERE id=? AND pid=?",(label,price,int(body["id"]),pid))
        else: db.execute("INSERT INTO packs(pid,label,price) VALUES(?,?,?)",(pid,label,price))
        db.commit()
    elif act == "a_pack_delete":
        db.execute("DELETE FROM packs WHERE id=?",(int(body["id"]),)); db.commit()
    elif act == "a_broadcast":
        ok = 0
        for r in q("SELECT id FROM users"):
            try: await req.app["bot"].send_message(r["id"], body["text"]); ok += 1
            except Exception: pass
            await asyncio.sleep(.05)
        return web.json_response({"sent": ok})
    elif act == "a_stats":
        s = lambda x: db.execute(x).fetchone()[0]
        return web.json_response({"users": s("SELECT COUNT(*) FROM users"), "orders": s("SELECT COUNT(*) FROM orders"),
            "revenue": s("SELECT COALESCE(SUM(price),0) FROM orders"), "topups": s("SELECT COALESCE(SUM(amount),0) FROM pays WHERE status='paid'")})
    return web.json_response({"ok": 1})

dp = Dispatcher()
def kb(): return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text="Мои ключи"), KeyboardButton(text="Баланс")], [KeyboardButton(text="Поддержка"), KeyboardButton(text="Партнерам")]])
def shop(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть магазин", web_app=WebAppInfo(url=URL))]])
def me(m): ensure({"id": m.from_user.id, "first_name": m.from_user.first_name}); return db.execute("SELECT * FROM users WHERE id=?", (m.from_user.id,)).fetchone()

@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    a = command.args or ""; ensure({"id": m.from_user.id, "first_name": m.from_user.first_name}, int(a[4:]) if a.startswith("ref_") and a[4:].isdigit() else None)
    u = me(m); n = db.execute("SELECT COUNT(*) FROM orders WHERE uid=?", (u["id"],)).fetchone()[0]
    await m.answer(f"С возвращением, {m.from_user.first_name}.\n\nНа балансе ${u['balance']:.2f}, ключей {n}.", reply_markup=kb())
@dp.message(F.text == "Мои ключи")
async def keys(m: Message):
    n = db.execute("SELECT COUNT(*) FROM orders WHERE uid=?", (m.from_user.id,)).fetchone()[0]; me(m)
    await m.answer(f"Ключей: {n}. Список в магазине, раздел «Ключи»." if n else "Ключей пока нет. Выбери товар в магазине.", reply_markup=shop())
@dp.message(F.text == "Баланс")
async def bal(m: Message): await m.answer(f"Баланс: ${me(m)['balance']:.2f}\n\nПополнить можно через CryptoBot или xRocket в магазине.", reply_markup=shop())
@dp.message(F.text == "Поддержка")
async def sup(m: Message): await m.answer(f"Вопрос по оплате или ключу: {SUPPORT}")
@dp.message(F.text == "Партнерам")
async def ref(m: Message):
    u = me(m); inv = db.execute("SELECT COUNT(*) FROM users WHERE ref=?", (u["id"],)).fetchone()[0]; b = (await m.bot.get_me()).username
    await m.answer(f"Приводи друзей и получай 5% от каждого их пополнения.\n\nТвоя ссылка:\nhttps://t.me/{b}?start=ref_{u['id']}\n\nПриглашено: {inv}. Заработано: ${u['earned']:.2f}.", reply_markup=shop())

@dp.pre_checkout_query()
async def pre_checkout(qry):
    row = db.execute("SELECT uid,credited FROM stars_pending WHERE payload=?",(qry.invoice_payload,)).fetchone()
    if row and int(row["uid"]) == qry.from_user.id and not row["credited"]:
        await qry.answer(ok=True)
    else: await qry.answer(ok=False, error_message="Счет не найден или уже использован")

@dp.message(F.successful_payment)
async def stars_paid(m: Message):
    pay = m.successful_payment
    async with lock:
        row = db.execute("SELECT * FROM stars_pending WHERE payload=?",(pay.invoice_payload,)).fetchone()
        if row and not row["credited"] and int(row["uid"]) == m.from_user.id and pay.currency == "XTR" and int(pay.total_amount) == int(row["amount"]):
            # Stars are credited to the shop balance at a configurable conversion rate (default 1 Star = $0.01).
            rate = float(E("STAR_USD_RATE", "0.01"))
            db.execute("UPDATE users SET balance=balance+? WHERE id=?",(round(row["amount"]*rate,2),m.from_user.id))
            db.execute("UPDATE stars_pending SET credited=1 WHERE payload=?",(pay.invoice_payload,)); db.commit()
    await m.answer("Оплата Stars получена. Баланс магазина обновлен.")

async def main():
    os.makedirs(DATA, exist_ok=True)
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and configure BOT_TOKEN.")
    if not URL.startswith("https://"):
        raise RuntimeError("WEBAPP_URL must be a public HTTPS URL for Telegram Mini App.")
    bot = Bot(TOKEN); app = web.Application(); app["bot"] = bot
    # Fetch bot username once, with a timeout; never block every Mini App init request.
    app["bot_username"] = ""
    try:
        app["bot_username"] = (await asyncio.wait_for(bot.get_me(), timeout=8)).username or ""
    except Exception as e:
        print(f"Could not fetch bot username during startup: {type(e).__name__}: {e}")
    app.router.add_post("/api/{a}", api)
    app.router.add_get("/", lambda r: web.FileResponse(os.path.join(os.path.dirname(__file__), "webapp", "index.html")))
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "0.0.0.0", int(E("PORT", 8080))).start()
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=SHOP_NAME[:64], web_app=WebAppInfo(url=URL)))
    await dp.start_polling(bot)
asyncio.run(main())
