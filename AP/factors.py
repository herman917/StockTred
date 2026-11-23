"""Quantitative multi-factor bull/bear scoring, 20-day forecast, and backtest engine."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FACTOR_META = {
  'trend_60ma': {
    'name': '趨勢濾網 (60MA/斜率)',
    'color': '#38bdf8',
    'weight': 0.28,
    'desc': '收盤價站上季線(60MA)且季線上揚',
  },
  'macd_hist': {
    'name': '動能轉折 (MACD柱)',
    'color': '#f59e0b',
    'weight': 0.22,
    'desc': 'DIF-DEA 大於 0 且較前日增強',
  },
  'vix_sentiment': {
    'name': '市場情緒 (^VIX)',
    'color': '#a855f7',
    'weight': 0.18,
    'desc': 'VIX < 25 或自 30 以上高檔回落',
  },
  'fx_twd': {
    'name': '匯率資金流 (TWD=X)',
    'color': '#ec4899',
    'weight': 0.17,
    'desc': '新台幣升值代表外資匯入(股匯雙漲)',
  },
  'chip_macro': {
    'name': '籌碼與總經 (法人/OI/景氣)',
    'color': '#14b8a6',
    'weight': 0.15,
    'desc': '三大法人買賣超、台指期淨OI與景氣燈號',
  },
}

BULL_THRESHOLD = 0.15
BEAR_THRESHOLD = -0.15


def _clip(series: pd.Series, low: float = -1.0, high: float = 1.0) -> pd.Series:
  return series.clip(lower=low, upper=high).fillna(0.0)


def compute_factors(df: pd.DataFrame, ndc_score: int = 31) -> pd.DataFrame:
  """Compute all 5 normalized quantitative factors in [-1.0, +1.0]."""
  out = df.copy()
  close = out['Close']

  # 1. Trend Filter: 60MA + 5-day slope
  ma60 = close.rolling(60, min_periods=20).mean()
  ma60_prev5 = ma60.shift(5)
  out['MA60'] = ma60
  out['MA20'] = close.rolling(20, min_periods=5).mean()

  dist_ma60 = ((close - ma60) / ma60.replace(0, np.nan)).fillna(0.0)
  slope_ma60 = ((ma60 - ma60_prev5) / ma60_prev5.replace(0, np.nan)).fillna(0.0)

  # Base score from price vs 60MA + slope confirmation
  above_ma = (close > ma60).astype(float)
  slope_up = (ma60 > ma60_prev5).astype(float)
  raw_trend = np.where(
    (above_ma == 1) & (slope_up == 1),
    0.55 + np.clip(dist_ma60 * 6.0, 0, 0.45),
    np.where(
      (above_ma == 0) & (slope_up == 0),
      -0.55 + np.clip(dist_ma60 * 6.0, -0.45, 0),
      np.clip(dist_ma60 * 5.0 + slope_ma60 * 15.0, -0.45, 0.45),
    ),
  )
  out['f_trend_60ma'] = _clip(pd.Series(raw_trend, index=out.index))

  # 2. Momentum Turn: MACD Histogram (12, 26, 9)
  ema12 = close.ewm(span=12, adjust=False).mean()
  ema26 = close.ewm(span=26, adjust=False).mean()
  dif = ema12 - ema26
  dea = dif.ewm(span=9, adjust=False).mean()
  osc = dif - dea
  out['MACD_DIF'] = dif
  out['MACD_DEA'] = dea
  out['MACD_OSC'] = osc

  osc_norm = (osc / close.replace(0, np.nan) * 100.0).fillna(0.0)
  osc_diff = osc - osc.shift(1).fillna(0.0)

  raw_macd = np.where(
    (osc > 0) & (osc_diff > 0),
    0.65 + np.clip(osc_norm * 0.8, 0, 0.35),
    np.where(
      (osc > 0) & (osc_diff <= 0),
      0.25 + np.clip(osc_norm * 0.4, 0, 0.25),
      np.where(
        (osc <= 0) & (osc_diff > 0),
        -0.20 + np.clip(osc_diff / close * 150.0, 0, 0.35),
        -0.65 + np.clip(osc_norm * 0.8, -0.35, 0),
      ),
    ),
  )
  out['f_macd_hist'] = _clip(pd.Series(raw_macd, index=out.index))

  # 3. Market Sentiment: ^VIX
  vix = out['VIX']
  vix_prev = vix.shift(1).fillna(vix)
  vix_max5 = vix.rolling(5, min_periods=1).max().shift(1).fillna(vix)

  # Panic peak reversal: VIX was >= 30 recently and is now falling
  panic_rebound = (vix_max5 >= 30.0) & (vix < vix_prev)
  raw_vix = np.where(
    panic_rebound,
    0.65,
    np.where(
      vix < 18.0,
      0.85,
      np.where(
        vix < 25.0,
        0.45 - (vix - 18.0) * 0.05,
        np.where(
          vix < 30.0,
          -0.45 - (vix - 25.0) * 0.06,
          -0.90,
        ),
      ),
    ),
  )
  out['f_vix_sentiment'] = _clip(pd.Series(raw_vix, index=out.index))

  # 4. FX Capital Flow: TWD=X (falling TWD=X = TWD appreciation = bullish)
  twd = out['TWD']
  twd_ma20 = twd.rolling(20, min_periods=5).mean()
  twd_chg5 = twd.pct_change(5).fillna(0.0)
  twd_dev = ((twd - twd_ma20) / twd_ma20.replace(0, np.nan)).fillna(0.0)

  # Negative twd_dev / twd_chg5 means TWD appreciating -> positive score
  raw_fx = -(twd_dev * 35.0 + twd_chg5 * 45.0)
  out['f_fx_twd'] = _clip(pd.Series(raw_fx, index=out.index))

  # 5. Chip & Macro: 3-Institutional 5D sum + Futures Net OI + NDC Business Score
  inst_5d = out['Inst_Total'].rolling(5, min_periods=1).sum()
  inst_std = inst_5d.rolling(60, min_periods=10).std().replace(0, np.nan).fillna(300.0)
  inst_z = np.tanh((inst_5d / inst_std).fillna(0.0))

  oi_series = out['Futures_OI']
  oi_ma20 = oi_series.rolling(20, min_periods=5).mean()
  oi_diff = (oi_series - oi_ma20) / (oi_series.abs().rolling(60, min_periods=10).mean().replace(0, np.nan).fillna(10000.0))
  oi_z = np.tanh(oi_diff.fillna(0.0))

  # NDC score: 23-31 green (mild bull +0.3), 32-37 yellow-red (+0.55), >=38 red (+0.2 overheated), <=16 blue (-0.2)
  if ndc_score >= 38:
    macro_bias = 0.20
  elif ndc_score >= 32:
    macro_bias = 0.55
  elif ndc_score >= 23:
    macro_bias = 0.30
  elif ndc_score >= 17:
    macro_bias = -0.15
  else:
    macro_bias = -0.35

  raw_chip = 0.55 * inst_z + 0.30 * oi_z + 0.15 * macro_bias
  out['f_chip_macro'] = _clip(pd.Series(raw_chip, index=out.index))

  return out


def compute_composite_and_regime(
  df: pd.DataFrame, active_factors: list[str]
) -> pd.DataFrame:
  """Aggregate active factors into smoothed composite score, state, and capital allocation."""
  out = df.copy()
  valid = [f for f in active_factors if f in FACTOR_META]
  if not valid:
    out['composite_raw'] = 0.0
    out['composite'] = 0.0
    out['regime'] = 'neutral'
    out['alloc_pct'] = 50.0
    return out

  total_w = sum(FACTOR_META[f]['weight'] for f in valid)
  weighted = sum(out[f'f_{f}'] * FACTOR_META[f]['weight'] for f in valid) / total_w

  out['composite_raw'] = _clip(weighted)
  # Light EMA(3) smoothing to filter single-day whipsaws while keeping turning points sharp
  out['composite'] = _clip(out['composite_raw'].ewm(span=3, adjust=False).mean())

  out['regime'] = np.where(
    out['composite'] > BULL_THRESHOLD,
    'bull',
    np.where(out['composite'] < BEAR_THRESHOLD, 'bear', 'neutral'),
  )

  # Recommended long equity allocation (0% to 100%) proportional to red/green bar strength
  # Maps composite [-0.65, +0.75] -> [0%, 100%]
  alloc = np.clip((out['composite'] + 0.65) / 1.40, 0.0, 1.0) * 100.0
  out['alloc_pct'] = np.round(alloc, 1)

  # Main Trend Overlay Line on Price Chart:
  # Exponentially tracks price with regime-adaptive responsiveness so it sits right on the price action
  ema_fast = out['Close'].ewm(span=10, adjust=False).mean()
  ema_slow = out['Close'].ewm(span=25, adjust=False).mean()
  blend = 0.5 + 0.4 * out['composite']  # bull tracks closer to fast, bear tracks slower/defensive
  out['trend_overlay'] = blend * ema_fast + (1.0 - blend) * ema_slow

  return out


def forecast_next_20_days(
  df: pd.DataFrame, active_factors: list[str], horizon: int = 20
) -> list[dict[str, Any]]:
  """Generate 20-trading-day forward forecast for composite score, factors, and price band."""
  last_date = df.index[-1]
  future_dates = pd.bdate_range(start=last_date + pd.Timedelta(days=1), periods=horizon)

  last_close = float(df['Close'].iloc[-1])
  last_score = float(df['composite'].iloc[-1])
  recent_slope = float(df['composite'].iloc[-1] - df['composite'].iloc[-5]) / 5.0
  vix_now = float(df['VIX'].iloc[-1])

  # Historical daily return stats conditioned on regime
  rets = df['Close'].pct_change().dropna()
  hist_vol = float(rets.tail(60).std()) if len(rets) >= 20 else 0.012
  daily_vol = max(hist_vol, (vix_now / 100.0) / np.sqrt(252.0) * 0.85, 0.006)

  bull_mu = float(rets[df['composite'].shift(1) > BULL_THRESHOLD].mean())
  bear_mu = float(rets[df['composite'].shift(1) < BEAR_THRESHOLD].mean())
  if np.isnan(bull_mu):
    bull_mu = 0.0007
  if np.isnan(bear_mu):
    bear_mu = -0.0005

  valid_factors = [f for f in active_factors if f in FACTOR_META]
  last_factors = {f: float(df[f'f_{f}'].iloc[-1]) for f in FACTOR_META}
  factor_slopes = {
    f: float(df[f'f_{f}'].iloc[-1] - df[f'f_{f}'].iloc[-4]) / 4.0 for f in FACTOR_META
  }

  forecast_rows: list[dict[str, Any]] = []
  price_mid = last_close
  score_cur = last_score
  trend_cur = float(df['trend_overlay'].iloc[-1])

  for step, dt in enumerate(future_dates, start=1):
    # Mean-reverting AR(1) + decaying momentum for each factor
    decay = np.exp(-step / 12.0)
    step_factors: dict[str, float] = {}
    for f in FACTOR_META:
      # Long-term Taiwan market slight positive drift (+0.12)
      long_mean = 0.12 if f in ('trend_60ma', 'vix_sentiment') else 0.05
      proj = (
        last_factors[f] * (0.93**step)
        + long_mean * (1.0 - 0.93**step)
        + factor_slopes[f] * step * decay * 0.45
      )
      step_factors[f] = float(np.clip(proj, -1.0, 1.0))

    if valid_factors:
      total_w = sum(FACTOR_META[f]['weight'] for f in valid_factors)
      target_score = sum(step_factors[f] * FACTOR_META[f]['weight'] for f in valid_factors) / total_w
      score_cur = float(np.clip(0.75 * target_score + 0.25 * (score_cur + recent_slope * decay), -1.0, 1.0))
    else:
      score_cur = 0.0

    # Expected daily drift based on forecasted score
    expected_mu = score_cur * max(abs(bull_mu), 0.0008)
    price_mid = price_mid * (1.0 + expected_mu)
    band_width = last_close * daily_vol * np.sqrt(step) * 1.28  # ~80% confidence band
    trend_cur = 0.25 * price_mid + 0.75 * trend_cur

    regime = (
      'bull'
      if score_cur > BULL_THRESHOLD
      else ('bear' if score_cur < BEAR_THRESHOLD else 'neutral')
    )
    alloc_pct = round(float(np.clip((score_cur + 0.65) / 1.40, 0.0, 1.0) * 100.0), 1)

    row: dict[str, Any] = {
      'date': dt.strftime('%Y-%m-%d'),
      'is_forecast': True,
      'price_mid': round(price_mid, 2),
      'price_upper': round(price_mid + band_width, 2),
      'price_lower': round(max(price_mid - band_width, 1.0), 2),
      'trend_overlay': round(trend_cur, 2),
      'composite': round(score_cur, 4),
      'regime': regime,
      'alloc_pct': alloc_pct,
      'factors': {f: round(step_factors[f], 4) for f in FACTOR_META},
    }
    forecast_rows.append(row)

  return forecast_rows


def run_backtest(df: pd.DataFrame, lookback_days: int = 252) -> dict[str, Any]:
  """Compare dynamic factor-allocation timing strategy vs Buy & Hold."""
  bt = df.tail(lookback_days).copy()
  bt['ret'] = bt['Close'].pct_change().fillna(0.0)

  # Position lagged by 1 day to avoid look-ahead bias
  bt['pos'] = (bt['alloc_pct'].shift(1).fillna(50.0)) / 100.0
  # Transaction cost 0.1% on position change
  turnover = bt['pos'].diff().abs().fillna(0.0)
  bt['strat_ret'] = bt['pos'] * bt['ret'] - turnover * 0.001

  bt['bh_equity'] = (1.0 + bt['ret']).cumprod()
  bt['strat_equity'] = (1.0 + bt['strat_ret']).cumprod()

  def _metrics(eq: pd.Series, daily_r: pd.Series) -> dict[str, float]:
    total_ret = float(eq.iloc[-1] - 1.0) * 100.0
    n_days = max(len(eq), 1)
    cagr = ((float(eq.iloc[-1]) ** (252.0 / n_days)) - 1.0) * 100.0
    roll_max = eq.cummax()
    dd = (eq / roll_max) - 1.0
    mdd = float(dd.min()) * 100.0
    std = float(daily_r.std())
    sharpe = float((daily_r.mean() / std) * np.sqrt(252.0)) if std > 1e-8 else 0.0
    return {
      'total_return_pct': round(total_ret, 2),
      'cagr_pct': round(cagr, 2),
      'mdd_pct': round(mdd, 2),
      'sharpe': round(sharpe, 2),
    }

  bh_m = _metrics(bt['bh_equity'], bt['ret'])
  st_m = _metrics(bt['strat_equity'], bt['strat_ret'])

  mdd_reduction = round(abs(bh_m['mdd_pct']) - abs(st_m['mdd_pct']), 2)
  sharpe_diff = round(st_m['sharpe'] - bh_m['sharpe'], 2)

  equity_curve = [
    {
      'date': idx.strftime('%Y-%m-%d'),
      'buy_hold': round((row['bh_equity'] - 1.0) * 100.0, 2),
      'strategy': round((row['strat_equity'] - 1.0) * 100.0, 2),
    }
    for idx, row in bt.iterrows()
  ]

  return {
    'lookback_days': len(bt),
    'buy_hold': bh_m,
    'strategy': st_m,
    'mdd_reduction_pct': mdd_reduction,
    'sharpe_improvement': sharpe_diff,
    'avg_exposure_pct': round(float(bt['pos'].mean() * 100.0), 1),
    'equity_curve': equity_curve,
  }
