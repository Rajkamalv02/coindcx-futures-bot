import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from signals.indicators import build_dataframe, calculate_indicators
from signals.scanner import run_quick_backtest
from api.fetcher import get_filtered_symbols, get_historical_candles
from config.settings import BACKTEST_DAYS
import time

def optimize():
    print("=== ADX Threshold Optimization Started ===")
    print("1. Fetching symbols...")
    symbols = get_filtered_symbols(min_price=0.5, min_volume=500000)
    print(f"   Found {len(symbols)} symbols.")

    # We'll test across 60 days for a better sample
    TEST_DAYS = 60
    
    all_results = {10: [], 15: [], 20: [], 25: []}
    
    def process_symbol(symbol):
        try:
            # print(f"   Processing {symbol}...")
            candles = get_historical_candles(symbol, TEST_DAYS)
            if not candles:
                return None
            
            df = build_dataframe(candles)
            df = calculate_indicators(df, symbol=symbol)
            
            symbol_results = {}
            for threshold in [10, 15, 20, 25]:
                res = run_quick_backtest(df, adx_threshold=threshold)
                symbol_results[threshold] = res
            
            return symbol_results
        except Exception as e:
            # print(f"Error processing {symbol}: {e}")
            return None

    print(f"2. Fetching {TEST_DAYS} days of historical data for each symbol (Parallel)...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_symbol, symbols))

    print("3. Aggregating results...")
    final_stats = {}
    for threshold in [10, 15, 20, 25]:
        total_trades = 0
        total_wins = 0
        total_pnl = 0
        symbols_with_trades = 0
        
        for res in results:
            if res and threshold in res:
                r = res[threshold]
                if r['total_trades'] > 0:
                    total_trades += r['total_trades']
                    total_wins += int(r['win_rate'] * r['total_trades'])
                    total_pnl += r['net_pnl']
                    symbols_with_trades += 1
        
        win_rate = total_wins / total_trades if total_trades > 0 else 0
        final_stats[threshold] = {
            "win_rate": win_rate,
            "total_trades": total_trades,
            "net_pnl": total_pnl,
            "avg_trades_per_symbol": total_trades / len(symbols) if len(symbols) > 0 else 0
        }

    print("\n=== OPTIMIZATION RESULTS (60 Days, 15m Candles) ===")
    print(f"{'ADX Threshold':<15} | {'Win Rate':<10} | {'Total Trades':<12} | {'Net % Gain':<10}")
    print("-" * 55)
    for threshold, stats in final_stats.items():
        print(f"{threshold:<15} | {stats['win_rate']:<10.2%} | {stats['total_trades']:<12} | {stats['net_pnl']:<10.2f}%")
    print("-" * 55)
    
    # Recommendation
    best_threshold = max(final_stats.keys(), key=lambda k: final_stats[k]['net_pnl'])
    print(f"\nRecommendation: Set ADX_MIN_THRESHOLD to {best_threshold} for maximum historical profit.")

if __name__ == "__main__":
    optimize()
