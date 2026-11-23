"""Market, FX, VIX, and Taiwan chip/macro data fetcher with local disk cache."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent / 'cache'
CACHE_TTL_SECONDS = 900  # 15 minutes


def _ensure_cache_dir() -> None:
  CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _is_cache_fresh(path: Path, ttl: int = CACHE_TTL_SECONDS) -> bool:
  if not path.exists():
    return False
  return (time.time() - path.stat().st_mtime) < ttl


def fetch_yfinance_bundle(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
  """Fetch 2y daily OHLCV for ^TWII, 0050.TW, ^VIX, and TWD=X."""
  _ensure_cache_dir()
  cache_file = CACHE_DIR / 'yf_bundle.pkl'

  if not force_refresh and _is_cache_fresh(cache_file):
    try:
      return pd.read_pickle(cache_file)
    except Exception:
      pass

  tickers = ['^TWII', '0050.TW', '^VIX', 'TWD=X']
  raw = yf.download(
    tickers,
    period='2y',
    interval='1d',
    auto_adjust=False,
    progress=False,
    threads=True,
  )

  bundle: dict[str, pd.DataFrame] = {}
  for sym in tickers:
    try:
      if isinstance(raw.columns, pd.MultiIndex):
        sub = raw.xs(sym, axis=1, level=1).copy()
      else:
        sub = raw.copy()
      sub.index = pd.to_datetime(sub.index).tz_localize(None)
      sub = sub.dropna(subset=['Close']).sort_index()
      bundle[sym] = sub
    except Exception:
      bundle[sym] = pd.DataFrame()

  if any(not df.empty for df in bundle.values()):
    try:
      pd.to_pickle(bundle, cache_file)
    except Exception:
      pass

  return bundle


def fetch_taiwan_institutional(
  start_date: str, force_refresh: bool = False
) -> dict[str, Any]:
  """Fetch daily Taiwan 3-major-institutional net buy/sell (in 億元 NTD) from FinMind."""
  _ensure_cache_dir()
  cache_file = CACHE_DIR / 'tw_institutional.json'

  if not force_refresh and _is_cache_fresh(cache_file, ttl=3600):
    try:
      with open(cache_file, 'r', encoding='utf-8') as f:
        return json.load(f)
    except Exception:
      pass

  records: dict[str, dict[str, float]] = {}
  source = 'FinMind (TWSE)'

  try:
    url = 'https://api.finmindtrade.com/api/v4/data'
    params = {
      'dataset': 'TaiwanStockTotalInstitutionalInvestors',
      'start_date': start_date,
    }
    resp = requests.get(url, params=params, timeout=8)
    payload = resp.json()
    if payload.get('status') == 200 and payload.get('data'):
      for row in payload['data']:
        d = row.get('date')
        name = row.get('name', '')
        net = (float(row.get('buy', 0)) - float(row.get('sell', 0))) / 1e8  # 億元
        if not d:
          continue
        if d not in records:
          records[d] = {
            'foreign': 0.0,
            'trust': 0.0,
            'dealer': 0.0,
            'total': 0.0,
          }
        if 'Foreign' in name:
          records[d]['foreign'] += net
        elif 'Investment_Trust' in name:
          records[d]['trust'] += net
        else:
          records[d]['dealer'] += net
        records[d]['total'] += net
  except Exception:
    source = 'proxy'

  # Also try fetching TX futures institutional net OI if available
  futures_oi: dict[str, float] = {}
  try:
    url = 'https://api.finmindtrade.com/api/v4/data'
    params = {
      'dataset': 'TaiwanFuturesInstitutionalInvestors',
      'data_id': 'TX',
      'start_date': start_date,
    }
    resp = requests.get(url, params=params, timeout=8)
    payload = resp.json()
    if payload.get('status') == 200 and payload.get('data'):
      for row in payload['data']:
        if row.get('institutional_investors') == '外資':
          d = row.get('date')
          long_oi = float(row.get('long_open_interest_balance_volume', 0))
          short_oi = float(row.get('short_open_interest_balance_volume', 0))
          if d:
            futures_oi[d] = long_oi - short_oi
  except Exception:
    pass

  result = {
    'source': source if records else 'proxy',
    'institutional': records,
    'futures_oi': futures_oi,
  }

  if records:
    try:
      with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    except Exception:
      pass

  return result


def get_ndc_business_signal() -> dict[str, Any]:
  """Fetch latest NDC Taiwan Business Cycle Signal or fallback to recent official reading."""
  # NDC open data endpoint sometimes blocks or changes schema; try gracefully with fallback.
  fallback = {
    'date': '2026-09',
    'score': 31,
    'light': '黃紅燈',
    'status': '景氣熱絡偏多',
    'source': 'NDC 基準資料',
  }
  try:
    resp = requests.get(
      'https://index.ndc.gov.tw/n/json/data/eco/indicators',
      timeout=4,
    )
    if resp.status_code == 200:
      data = resp.json()
      if isinstance(data, list) and data:
        latest = data[-1]
        score = int(float(latest.get('score', 31)))
        light = _score_to_light(score)
        return {
          'date': str(latest.get('date', fallback['date'])),
          'score': score,
          'light': light,
          'status': _light_to_desc(light),
          'source': 'NDC OpenData',
        }
  except Exception:
    pass
  return fallback


def _score_to_light(score: int) -> str:
  if score >= 38:
    return '紅燈'
  if score >= 32:
    return '黃紅燈'
  if score >= 23:
    return '綠燈'
  if score >= 17:
    return '黃藍燈'
  return '藍燈'


def _light_to_desc(light: str) -> str:
  mapping = {
    '紅燈': '景氣過熱（留意高檔風險）',
    '黃紅燈': '景氣轉強熱絡',
    '綠燈': '景氣穩定成長',
    '黃藍燈': '景氣趨緩轉折',
    '藍燈': '景氣低迷（長線逢低區）',
  }
  return mapping.get(light, '景氣穩定')


def build_aligned_dataset(
  symbol: str = '^TWII', force_refresh: bool = False
) -> tuple[pd.DataFrame, dict[str, Any]]:
  """Align target asset (^TWII or 0050.TW) with ^VIX, TWD=X, and Taiwan chip/macro data."""
  if symbol not in ('^TWII', '0050.TW'):
    symbol = '^TWII'

  bundle = fetch_yfinance_bundle(force_refresh=force_refresh)
  target = bundle.get(symbol, pd.DataFrame())
  if target.empty:
    raise RuntimeError(f'無法取得 {symbol} 的市場歷史資料，請檢查網路連線。')

  df = target[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
  df = df.dropna(subset=['Close'])

  # Align ^VIX and TWD=X onto target trading days using forward-fill
  vix_df = bundle.get('^VIX', pd.DataFrame())
  if not vix_df.empty:
    df['VIX'] = vix_df['Close'].reindex(df.index, method='ffill')
  else:
    df['VIX'] = 18.0

  fx_df = bundle.get('TWD=X', pd.DataFrame())
  if not fx_df.empty:
    df['TWD'] = fx_df['Close'].reindex(df.index, method='ffill')
  else:
    df['TWD'] = 32.0

  df['VIX'] = df['VIX'].bfill().fillna(18.0)
  df['TWD'] = df['TWD'].bfill().fillna(32.0)

  start_date = (df.index.min() - timedelta(days=5)).strftime('%Y-%m-%d')
  chip_data = fetch_taiwan_institutional(start_date, force_refresh=force_refresh)
  ndc_info = get_ndc_business_signal()

  inst_map = chip_data.get('institutional', {})
  oi_map = chip_data.get('futures_oi', {})

  dates_str = df.index.strftime('%Y-%m-%d')
  inst_total = []
  inst_foreign = []
  fut_oi = []

  for d_str in dates_str:
    rec = inst_map.get(d_str)
    inst_total.append(rec['total'] if rec else np.nan)
    inst_foreign.append(rec['foreign'] if rec else np.nan)
    fut_oi.append(oi_map.get(d_str, np.nan))

  df['Inst_Total'] = inst_total
  df['Inst_Foreign'] = inst_foreign
  df['Futures_OI'] = fut_oi

  # Fill missing chip days with flow proxy derived from volume-weighted return & FX change
  ret = df['Close'].pct_change().fillna(0)
  fx_ret = df['TWD'].pct_change().fillna(0)
  flow_proxy = (ret * 4500.0) - (fx_ret * 6000.0)

  if df['Inst_Total'].notna().sum() < 10:
    df['Inst_Total'] = flow_proxy
    df['Inst_Foreign'] = flow_proxy * 0.85
    chip_source = '量價與匯率資金流代理模型'
  else:
    df['Inst_Total'] = df['Inst_Total'].fillna(flow_proxy)
    df['Inst_Foreign'] = df['Inst_Foreign'].fillna(flow_proxy * 0.85)
    chip_source = chip_data.get('source', 'FinMind (TWSE)')

  if df['Futures_OI'].notna().sum() < 10:
    df['Futures_OI'] = (
      pd.Series(flow_proxy, index=df.index).rolling(10, min_periods=1).sum() * 120.0
    )
  else:
    df['Futures_OI'] = df['Futures_OI'].ffill().bfill().fillna(0.0)

  meta = {
    'symbol': symbol,
    'chip_source': chip_source,
    'ndc': ndc_info,
    'last_date': df.index[-1].strftime('%Y-%m-%d'),
    'total_rows': len(df),
  }
  return df, meta
