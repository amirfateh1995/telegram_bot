import requests
import time
import numpy as np
from datetime import datetime
import json
import pandas as pd

# ================== Settings ==================
TELEGRAM_TOKEN = '7613935901:AAEKb1Gx4eTbl2ebhDTDqw0XHSdoZNrpZLE'
CHAT_ID = '146323300'

REQUESTED_MARKETS = [
    'ETHUSDT', 'BTCUSDT', 'SOLUSDT', 'ADAUSDT', 'DOGEUSDT', 'XRPUSDT',
    'BNBUSDT', 'LINKUSDT', 'SHIBUSDT'
]

ERROR_LOG = 'error_log.txt'

MAX_SWINGS = 50
MAX_ERRORS = 5
SLEEP_SECONDS = 180

last_signal_time = {market: 0 for market in REQUESTED_MARKETS}

# ================== Helper Functions ==================


def check_available_markets():
    url = "https://api.coinex.com/perpetual/v1/market/list"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['code'] == 0:
            available_markets = [m['name'] for m in data['data']]
            valid_markets = [
                market for market in REQUESTED_MARKETS
                if market in available_markets
            ]
            invalid_markets = [
                market for market in REQUESTED_MARKETS
                if market not in available_markets
            ]
            print("Available markets:", valid_markets)
            if invalid_markets:
                print("Unavailable markets:", invalid_markets)
                log_error(f"Unavailable markets: {invalid_markets}")
            return valid_markets
        else:
            error_msg = f"Error getting market list: {data['message']}"
            print(error_msg)
            log_error(error_msg)
            return REQUESTED_MARKETS
    except Exception as e:
        error_msg = f"Error checking markets: {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return REQUESTED_MARKETS


def log_error(message):
    try:
        with open(ERROR_LOG, 'a') as f:
            f.write(f"{datetime.now()}: {message}\n")
    except Exception as e:
        print(f"Error logging: {str(e)}")


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, params=params, timeout=10)
        if response.status_code != 200:
            error_msg = f"Error sending to Telegram: {response.text}"
            print(error_msg)
            log_error(error_msg)
            return False
        return True
    except Exception as e:
        error_msg = f"Error sending to Telegram: {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return False


def get_klines(market, timeframe='15min', limit=200, retries=5, delay=20):
    url = f"https://api.coinex.com/perpetual/v1/market/kline?market={market}&type={timeframe}&limit={limit}"
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if data['code'] == 0 and data['data'] and isinstance(
                    data['data'], list):
                klines = [{
                    'time': int(k[0]),
                    'open': float(k[1]),
                    'close': float(k[2]),
                    'high': float(k[3]),
                    'low': float(k[4]),
                    'volume': float(k[5])
                } for k in data['data']]
                print(
                    f"Candles count for {market} ({timeframe}): {len(klines)}")
                if len(klines) >= 10:
                    return klines
                else:
                    error_msg = f"Candles count for {market} ({timeframe}) less than 10: {len(klines)}"
                    print(error_msg)
                    log_error(error_msg)
            else:
                error_msg = f"Coinex API error ({market}, {timeframe}): {data.get('message', 'Invalid data')}"
                print(error_msg)
                log_error(error_msg)
        except Exception as e:
            error_msg = f"API request error for {market} ({timeframe}): {str(e)}"
            print(error_msg)
            log_error(error_msg)
        if attempt < retries - 1:
            print(
                f"Retrying for {market} ({timeframe}) after {delay} seconds..."
            )
            time.sleep(delay)
    return None


def get_ticker(market, retries=5, delay=20):
    url = f"https://api.coinex.com/perpetual/v1/market/ticker?market={market}"
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if data['code'] == 0 and 'ticker' in data['data']:
                return float(data['data']['ticker']['last'])
            elif data['code'] == 0 and 'last' in data['data']:
                return float(data['data']['last'])
            else:
                error_msg = f"Unknown ticker structure for {market}: {data}"
                print(error_msg)
                log_error(error_msg)
        except Exception as e:
            error_msg = f"Error getting ticker for {market}: {str(e)}"
            print(error_msg)
            log_error(error_msg)
        if attempt < retries - 1:
            print(f"Retrying for {market} after {delay} seconds...")
            time.sleep(delay)
    return None


# ================== Analysis Algorithm ==================


def detect_swings(market, timeframe, klines, prev_swings=None):
    if not klines or len(klines) < 5:
        error_msg = f"Insufficient data to detect swings in {market} ({timeframe}): {len(klines) if klines else 0} candles"
        print(error_msg)
        log_error(error_msg)
        return prev_swings or {'highs': [], 'lows': []}, False
    swings = prev_swings or {'highs': [], 'lows': []}
    start_idx = max(0,
                    len(klines) -
                    50) if timeframe in ['3min', '15min'] else max(
                        0,
                        len(klines) - 10)
    new_swing_detected = False
    try:
        for i in range(start_idx + 2, len(klines) - 2):
            if (klines[i]['high'] > klines[i - 1]['high']
                    and klines[i]['high'] > klines[i - 2]['high']
                    and klines[i]['high'] > klines[i + 1]['high']
                    and klines[i]['high'] > klines[i + 2]['high']):
                if not swings['highs'] or klines[i]['time'] > swings['highs'][
                        -1]['time']:
                    new_high = {
                        'time': klines[i]['time'],
                        'price': klines[i]['high']
                    }
                    if swings['highs']:
                        last_high = swings['highs'][-1]
                        has_low_between = any(
                            low['time'] > last_high['time']
                            and low['time'] < new_high['time']
                            for low in swings['lows'])
                        if not has_low_between:
                            swings['highs'].pop()
                    swings['highs'].append(new_high)
                    new_swing_detected = True
            if (klines[i]['low'] < klines[i - 1]['low']
                    and klines[i]['low'] < klines[i - 2]['low']
                    and klines[i]['low'] < klines[i + 1]['low']
                    and klines[i]['low'] < klines[i + 2]['low']):
                if not swings['lows'] or klines[i]['time'] > swings['lows'][
                        -1]['time']:
                    new_low = {
                        'time': klines[i]['time'],
                        'price': klines[i]['low']
                    }
                    if swings['lows']:
                        last_low = swings['lows'][-1]
                        has_high_between = any(
                            high['time'] > last_low['time']
                            and high['time'] < new_low['time']
                            for high in swings['highs'])
                        if not has_high_between:
                            swings['lows'].pop()
                    swings['lows'].append(new_low)
                    new_swing_detected = True
        print(
            f"Detected swings for {market} ({timeframe}): highs={len(swings['highs'])}, lows={len(swings['lows'])}"
        )
        return swings, new_swing_detected
    except Exception as e:
        error_msg = f"Error detecting swings for {market} ({timeframe}): {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return swings, False


def calculate_slope(point1, point2, timeframe_minutes):
    try:
        delta_price = point2['price'] - point1['price']
        delta_time = (point2['time'] - point1['time']) / (60 *
                                                          timeframe_minutes)
        return delta_price / delta_time if delta_time != 0 else 0
    except Exception as e:
        error_msg = f"Error calculating slope: {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return 0


def detect_trend_and_channel(market, timeframe, swings):
    try:
        if len(swings['highs']) < 2 or len(swings['lows']) < 2:
            error_msg = f"Insufficient swings to detect trend in {market} ({timeframe}): highs={len(swings['highs'])}, lows={len(swings['lows'])}"
            print(error_msg)
            log_error(error_msg)
            return None, None, None

        last_high = swings['highs'][-1]['price']
        prev_high = swings['highs'][-2]['price']
        last_low = swings['lows'][-1]['price']
        prev_low = swings['lows'][-2]['price']

        if last_low > prev_low and last_high > prev_high:
            trend = 'up trend'
        elif last_low < prev_low and last_high < prev_high:
            trend = 'down trend'
        else:
            trend = 'sideway'

        channel = {
            'support': (swings['lows'][-2], swings['lows'][-1]),
            'resistance': (swings['highs'][-2], swings['highs'][-1])
        }
        print(f"Detected trend for {market} ({timeframe}): {trend}")
        return trend, channel, trend
    except Exception as e:
        error_msg = f"Error detecting trend and channel for {market} ({timeframe}): {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return None, None, None


def check_channel_breakout(market, timeframe, klines, channel,
                           timeframe_minutes):
    try:
        if not channel or not klines:
            print(
                f"{market} ({timeframe}): Invalid channel or candles. Stuck at breakout"
            )
            return False
        last_candle = klines[-1]
        prev_candle = klines[-2]

        support_slope = calculate_slope(channel['support'][0],
                                        channel['support'][1],
                                        timeframe_minutes)
        resistance_slope = calculate_slope(channel['resistance'][0],
                                           channel['resistance'][1],
                                           timeframe_minutes)

        time_diff = (last_candle['time'] -
                     channel['support'][1]['time']) / (60 * timeframe_minutes)
        support_price = channel['support'][1][
            'price'] + support_slope * time_diff
        resistance_price = channel['resistance'][1][
            'price'] + resistance_slope * time_diff

        if last_candle['close'] > resistance_price and prev_candle[
                'close'] <= resistance_price:
            print(
                f"{market} ({timeframe}): Channel breakout upward. Stuck at breakout"
            )
            return True
        if last_candle['close'] < support_price and prev_candle[
                'close'] >= support_price:
            print(
                f"{market} ({timeframe}): Channel breakout downward. Stuck at breakout"
            )
            return True
        return False
    except Exception as e:
        error_msg = f"Error checking channel breakout for {market} ({timeframe}): {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return False


def calculate_range_momentum(market, timeframe, swings):
    try:
        if len(swings['highs']) < 2 or len(swings['lows']) < 2:
            error_msg = f"Insufficient swings for range momentum in {market} ({timeframe}): highs={len(swings['highs'])}, lows={len(swings['lows'])}"
            print(error_msg)
            log_error(error_msg)
            return False, 'Unknown'
        action1_range = abs(swings['highs'][-2]['price'] -
                            swings['lows'][-2]['price'])
        action2_range = abs(swings['highs'][-1]['price'] -
                            swings['lows'][-1]['price'])
        strength = 'Strong' if action2_range >= action1_range else 'Weak'
        print(f"Range momentum for {market} ({timeframe}): {strength}")
        return action2_range >= action1_range, strength
    except Exception as e:
        error_msg = f"Error calculating range momentum for {market} ({timeframe}): {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return False, 'Unknown'


def check_hpta(market, trend_m15, trend_m3):
    try:
        result = (trend_m15 == 'up trend'
                  and trend_m3 == 'up trend') or (trend_m15 == 'down trend'
                                                  and trend_m3 == 'down trend')
        print(
            f"HPTA checked for {market}: M15={trend_m15}, M3={trend_m3}, Result={result}"
        )
        if not result:
            print(f"{market}: Stuck at HPTA")
        return result
    except Exception as e:
        error_msg = f"Error checking HPTA for {market}: {str(e)}"
        print(error_msg)
        log_error(error_msg)
        return False


def algo4_check(trend_m3, channel_m3, current_price, prev_swings_m3):
    if not channel_m3:
        return False, 'Neutral', False

    support = channel_m3['support'][1]['price']
    resistance = channel_m3['resistance'][1]['price']
    diameter = abs(resistance - support)
    mid = (support + resistance) / 2

    ob = mid + (diameter / 2)
    os = mid - (diameter / 2)

    new_swing = (len(prev_swings_m3.get('highs', [])) < len(
        channel_m3['resistance'][1].get('highs', []))
                 or len(prev_swings_m3.get('lows', [])) < len(
                     channel_m3['support'][1].get('lows', [])))

    if trend_m3 == 'up trend' and current_price <= os:
        return True, 'Oversold', new_swing
    elif trend_m3 == 'down trend' and current_price >= ob:
        return True, 'Overbought', new_swing
    return False, 'Neutral', new_swing


def calculate_stop_loss(trend_m3, channel_m3, diameter):
    if trend_m3 == 'up trend':
        return channel_m3['support'][1]['price'] - (diameter / 4)
    elif trend_m3 == 'down trend':
        return channel_m3['resistance'][1]['price'] + (diameter / 4)
    return None


def calculate_profit_targets(current_price, trend_m3, diameter, channel_m3):
    target1 = current_price + diameter if trend_m3 == 'up trend' else current_price - diameter
    target2 = current_price + (
        3 / 4 * diameter) if trend_m3 == 'up trend' else current_price - (
            3 / 4 * diameter)
    target3 = channel_m3['resistance'][1][
        'price'] if trend_m3 == 'up trend' else channel_m3['support'][1][
            'price']
    return target1, target2, target3


# ================== Main Loop ==================


def main():
    print("Starting Coinex futures monitoring...")
    if not send_telegram_message("🚀 نظارت بر ارزهای فیوچرز کوینکس شروع شد!"):
        print(
            "Error sending initial message to Telegram. Check token or chat ID."
        )

    global MARKETS
    MARKETS = check_available_markets()
    if not MARKETS:
        print("No valid markets found. Stopping program.")
        return

    state = {
        market: {
            'swings_h1': None,
            'swings_m15': None,
            'swings_m3': None
        }
        for market in MARKETS
    }
    error_counts = {market: 0 for market in MARKETS}
    max_errors = 5
    active_markets = MARKETS.copy()
    cycle_count = 0

    while True:
        state_changed = False
        cycle_count += 1
        try:
            for market in active_markets[:]:
                try:
                    print(
                        f"\n{datetime.now().strftime('%H:%M:%S')} - {market}")

                    klines_m15 = get_klines(market, '15min', 200)
                    if not klines_m15:
                        error_counts[market] += 1
                        error_msg = f"M15 data for {market} not received. Error number {error_counts[market]}."
                        print(error_msg)
                        log_error(error_msg)
                        if error_counts[market] >= max_errors:
                            print(
                                f"{market} temporarily removed from list due to repeated errors."
                            )
                            active_markets.remove(market)
                        continue
                    else:
                        error_counts[market] = 0

                    swings_m15, new_m15 = detect_swings(
                        market, '15min', klines_m15,
                        state[market]['swings_m15'])
                    trend_m15, channel_m15, pattern_m15 = detect_trend_and_channel(
                        market, '15min', swings_m15)
                    if new_m15:
                        state[market]['swings_m15'] = swings_m15
                        state_changed = True

                    if not trend_m15 or trend_m15 not in [
                            'up trend', 'down trend'
                    ]:
                        print(
                            f"M15 trend for {market} not detected or non-trending ({trend_m15}). Stuck at trend_m15"
                        )
                        continue

                    range_is_strong, range_strength = calculate_range_momentum(
                        market, '15min', swings_m15)
                    if not range_is_strong:
                        print("Weak momentum. Stuck at momentum")
                        continue

                    klines_m3 = get_klines(market, '3min', 200)
                    if not klines_m3:
                        print("M3 data not received. Continuing...")
                        continue

                    swings_m3, new_m3 = detect_swings(
                        market, '3min', klines_m3, state[market]['swings_m3'])
                    trend_m3, channel_m3, pattern_m3 = detect_trend_and_channel(
                        market, '3min', swings_m3)
                    if new_m3:
                        state[market]['swings_m3'] = swings_m3
                        state_changed = True

                    if not trend_m3:
                        print("M3 trend not detected. Stuck at trend_m3")
                        continue

                    if check_channel_breakout(market, '3min', klines_m3,
                                              channel_m3, 3):
                        print("Channel breakout in M3. Stuck at breakout")
                        continue

                    hpta_result = check_hpta(market, trend_m15, trend_m3)
                    if not hpta_result:
                        print("HPTA not aligned. Stuck at HPTA")
                        continue

                    current_price = get_ticker(market)
                    algo4_pass, zone, new_swing = algo4_check(
                        trend_m3, channel_m3, current_price,
                        state[market]['swings_m3'])
                    if not algo4_pass:
                        print(
                            f"{market}: Algo 4 condition not passed. Waiting to reach suitable zone."
                        )
                        continue

                    if new_swing:
                        print(
                            f"{market}: New SH/SL detected. Re-checking algorithms..."
                        )
                        hpta_result = check_hpta(market, trend_m15, trend_m3)
                        if hpta_result and new_m15:
                            _, channel_m15, _ = detect_trend_and_channel(
                                market, '15min', swings_m15)
                            range_is_strong, _ = calculate_range_momentum(
                                market, '15min', swings_m15)
                            if not range_is_strong:
                                print(
                                    f"{market}: Weak momentum in M15. Not continuing."
                                )
                                continue

                    klines_h1 = get_klines(market, '1hour', 200)
                    trend_h1 = 'sideway'
                    if klines_h1:
                        swings_h1, new_h1 = detect_swings(
                            market, '1hour', klines_h1,
                            state[market]['swings_h1'])
                        trend_h1_temp, channel_h1, _ = detect_trend_and_channel(
                            market, '1hour', swings_h1)
                        if new_h1:
                            state[market]['swings_h1'] = swings_h1
                            state_changed = True
                        if trend_h1_temp:
                            trend_h1 = trend_h1_temp

                    signal, risk = None, None
                    if trend_m15 == 'up trend' and trend_m3 == 'up trend':
                        signal = 'Long'
                        risk = 'Very Low' if trend_h1 == 'up trend' else 'Low' if trend_h1 == 'sideway' else 'Medium'
                    elif trend_m15 == 'down trend' and trend_m3 == 'down trend':
                        signal = 'Short'
                        risk = 'Very Low' if trend_h1 == 'down trend' else 'Low' if trend_h1 == 'sideway' else 'Medium'

                    if signal:
                        current_time = time.time()
                        if current_time - last_signal_time[market] >= 180:
                            current_price = get_ticker(market)
                            diameter = abs(
                                channel_m3['resistance'][1]['price'] -
                                channel_m3['support'][1]['price'])
                            stop_loss = calculate_stop_loss(
                                trend_m3, channel_m3, diameter)
                            target1, target2, target3 = calculate_profit_targets(
                                current_price, trend_m3, diameter, channel_m3)
                            price_str = f"${current_price:.4f}" if current_price else "نامشخص"
                            message = (
                                f"🔔 <b>سیگنال {signal} برای {market}</b>\n"
                                f"{datetime.now().strftime('%H:%M:%S')} - {market}\n"
                                f"1H = {trend_h1} ->\n"
                                f"M15 = {trend_m15} ->\n"
                                f"M3 = {trend_m3} ->\n"
                                f"مومنتوم = {'✓' if range_is_strong else '✗'}\n"
                                f"HPTA = {'✓' if hpta_result else '✗'}\n"
                                f"ناحیه: {zone}\n"
                                f"Stop Loss: {stop_loss:.4f}\n"
                                f"Profit Target 1: {target1:.4f}\n"
                                f"Profit Target 2: {target2:.4f}\n"
                                f"Profit Target 3: {target3:.4f}\n"
                                f"قیمت فعلی: {price_str}\n"
                                f"زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            if send_telegram_message(message):
                                print(f"Signal {signal} for {market} sent!")
                                last_signal_time[market] = current_time
                            else:
                                print(
                                    f"Sending signal {signal} for {market} was unsuccessful."
                                )
                        else:
                            print(
                                f"Signal for {market} rejected due to less than 3 minute interval."
                            )

                except Exception as e:
                    error_msg = f"Error processing {market}: {str(e)}"
                    print(error_msg)
                    log_error(error_msg)

            print(f"\nWaiting {SLEEP_SECONDS} seconds until next cycle...")
            time.sleep(SLEEP_SECONDS)

        except KeyboardInterrupt:
            print("\nProgram stopped by user.")
            break
        except Exception as e:
            error_msg = f"General error in main loop: {str(e)}"
            print(error_msg)
            log_error(error_msg)
            print(f"Waiting {SLEEP_SECONDS} seconds before retry...")
            time.sleep(SLEEP_SECONDS)
