import os
import time
import json
import urllib.request
import urllib.parse
import html

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DEX = "https://api.dexscreener.com"
GECKO = "https://api.geckoterminal.com/api/v2"
RUG = "https://api.rugcheck.xyz/v1"

seen = set()
offset = 0


def get(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SolanaSniperAI/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def telegram(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def send(message, buttons=None):
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if buttons:
        data["reply_markup"] = json.dumps({
            "inline_keyboard": buttons
        })
    telegram("sendMessage", data)


def get_new_tokens():
    data = get(f"{DEX}/token-profiles/latest/v1")
    return [
        x for x in data
        if x.get("chainId") == "solana"
    ][:30]


def get_pair(mint):
    data = get(f"{DEX}/token-pairs/v1/solana/{mint}")
    if not isinstance(data, list) or not data:
        return None

    pairs = [
        p for p in data
        if p.get("liquidity", {}).get("usd", 0) >= 5000
    ]
    if not pairs:
        return None

    return max(
        pairs,
        key=lambda p: p.get("liquidity", {}).get("usd", 0)
    )


def get_candles(pool):
    url = (
        f"{GECKO}/networks/solana/pools/"
        f"{pool}/ohlcv/minute"
        "?aggregate=5&limit=30&currency=usd"
    )
    data = get(url)
    return data["data"]["attributes"]["ohlcv_list"]


def rug_check(mint):
    try:
        data = get(f"{RUG}/tokens/{mint}/report/summary")
        score = data.get("score", 999999)
        risks = data.get("risks", [])
        return score, risks
    except Exception:
        return None, []


def breakout(candles):
    if len(candles) < 15:
        return False

    candles = sorted(candles, key=lambda c: c[0])

    previous = candles[:-1]
    latest = candles[-1]

    resistance = max(c[2] for c in previous[-12:])
    close = latest[4]
    volume = latest[5]

    average_volume = sum(
        c[5] for c in previous[-10:]
    ) / 10

    strong_close = close > resistance
    volume_confirmed = volume > average_volume * 1.5

    return strong_close and volume_confirmed


def scan():
    try:
        tokens = get_new_tokens()

        for token in tokens:
            mint = token.get("tokenAddress")
            if not mint or mint in seen:
                continue

            seen.add(mint)

            pair = get_pair(mint)
            if not pair:
                continue

            liquidity = pair.get("liquidity", {}).get("usd", 0)
            market_cap = pair.get("marketCap") or pair.get("fdv") or 0
            volume = pair.get("volume", {}).get("h1", 0)

            if not (30000 <= market_cap <= 100000):
                continue

            if liquidity < 10000 or volume < 5000:
                continue

            pool = pair.get("pairAddress")
            candles = get_candles(pool)

            if not breakout(candles):
                continue

            score, risks = rug_check(mint)

            if score is None or score > 5000 or risks:
                continue

            name = html.escape(
                pair.get("baseToken", {}).get("name", "Unknown")
            )
            symbol = html.escape(
                pair.get("baseToken", {}).get("symbol", "???")
            )

            price = float(pair.get("priceUsd", 0))
            if price <= 0:
                continue

            entry = price
            stop = price * 0.90
            target = price * 1.20

            message = (
                "🚨 <b>SOLANA SNIPER AI ALERT</b>\n\n"
                f"<b>Token:</b> {name} ({symbol})\n"
                f"<b>Contract:</b>\n<code>{mint}</code>\n\n"
                f"<b>Market cap / FDV:</b> ${market_cap:,.0f}\n"
                f"<b>Liquidity:</b> ${liquidity:,.0f}\n"
                f"<b>1h volume:</b> ${volume:,.0f}\n\n"
                "<b>Breakout:</b> Candle close above recent resistance "
                "with increased volume\n"
                f"<b>Paper entry:</b> ${entry:.10f}\n"
                f"<b>Paper stop:</b> ${stop:.10f}\n"
                f"<b>Paper target:</b> ${target:.10f}\n\n"
                "Security checks passed by the configured filters. "
                "This is not a guarantee against a rug or loss.\n\n"
                "<b>Paper trade only. No real orders.</b>"
            )

            buttons = [[
                {"text": "✅ Review paper trade", "callback_data": "review"},
                {"text": "❌ Reject", "callback_data": "reject"}
            ]]

            send(message, buttons)

    except Exception as e:
        print("Scanner error:", e)


def commands():
    global offset

    result = telegram("getUpdates", {
        "offset": offset,
        "timeout": 1
    })

    for update in result.get("result", []):
        offset = update["update_id"] + 1

        msg = update.get("message", {})
        text = msg.get("text", "")
        chat = str(msg.get("chat", {}).get("id", ""))

        if chat != CHAT_ID:
            continue

        if text == "/start":
            send(
                "🤖 <b>Solana Sniper AI</b>\n"
                "Scanner is configured for paper alerts only.\n"
                "Commands: /scan /status /help"
            )
        elif text == "/scan":
            send("Scanning for qualifying Solana breakouts...")
            scan()
        elif text == "/status":
            send("Bot is running. Paper trading only.")
        elif text == "/help":
            send("/scan - scan now\n/status - bot status")


def main():
    send("🤖 Solana Sniper AI started. Paper mode only.")

    last_scan = 0

    while True:
        try:
            commands()

            if time.time() - last_scan >= 60:
                scan()
                last_scan = time.time()

        except Exception as e:
            print("Main loop error:", e)

        time.sleep(2)


if __name__ == "__main__":
    main()
