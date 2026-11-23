"""HTTP API & static file server for Taiwan Stock Bull/Bear Trend Predictor."""

from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from data_fetcher import build_aligned_dataset
from factors import (
  FACTOR_META,
  compute_composite_and_regime,
  compute_factors,
  forecast_next_20_days,
  run_backtest,
)

STATIC_DIR = Path(__file__).resolve().parent / 'static'


def analyze_market(
  symbol: str = '^TWII',
  display_days: int = 126,
  active_factors: list[str] | None = None,
  force_refresh: bool = False,
) -> dict[str, Any]:
  if active_factors is None:
    active_factors = list(FACTOR_META.keys())

  df, meta = build_aligned_dataset(symbol=symbol, force_refresh=force_refresh)
  ndc_score = int(meta.get('ndc', {}).get('score', 31))

  df_factors = compute_factors(df, ndc_score=ndc_score)
  df_comp = compute_composite_and_regime(df_factors, active_factors=active_factors)

  # Slice last N trading days for chart display (default 126 ~ 6 months)
  view_df = df_comp.tail(max(30, min(display_days, len(df_comp)))).copy()

  history = []
  for idx, row in view_df.iterrows():
    history.append(
      {
        'date': idx.strftime('%Y-%m-%d'),
        'is_forecast': False,
        'open': round(float(row['Open']), 2),
        'high': round(float(row['High']), 2),
        'low': round(float(row['Low']), 2),
        'close': round(float(row['Close']), 2),
        'volume': int(row['Volume']) if not _isnan(row['Volume']) else 0,
        'ma60': round(float(row['MA60']), 2) if not _isnan(row['MA60']) else None,
        'ma20': round(float(row['MA20']), 2) if not _isnan(row['MA20']) else None,
        'trend_overlay': round(float(row['trend_overlay']), 2),
        'composite': round(float(row['composite']), 4),
        'regime': str(row['regime']),
        'alloc_pct': round(float(row['alloc_pct']), 1),
        'vix': round(float(row['VIX']), 2),
        'twd': round(float(row['TWD']), 3),
        'macd_osc': round(float(row['MACD_OSC']), 2),
        'inst_total': round(float(row['Inst_Total']), 2),
        'futures_oi': round(float(row['Futures_OI']), 0),
        'factors': {
          f: round(float(row[f'f_{f}']), 4) for f in FACTOR_META
        },
      }
    )

  forecast = forecast_next_20_days(df_comp, active_factors=active_factors, horizon=20)
  backtest = run_backtest(df_comp, lookback_days=min(252, len(df_comp)))

  latest = history[-1]
  prev = history[-2] if len(history) >= 2 else latest
  price_chg = round(latest['close'] - prev['close'], 2)
  price_chg_pct = round((price_chg / prev['close']) * 100.0, 2) if prev['close'] else 0.0

  f20_end = forecast[-1]
  f20_chg_pct = round(((f20_end['price_mid'] - latest['close']) / latest['close']) * 100.0, 2)

  return {
    'meta': {
      **meta,
      'active_factors': active_factors,
      'display_days': len(history),
      'forecast_days': len(forecast),
    },
    'factor_meta': FACTOR_META,
    'summary': {
      'close': latest['close'],
      'price_chg': price_chg,
      'price_chg_pct': price_chg_pct,
      'composite': latest['composite'],
      'regime': latest['regime'],
      'alloc_pct': latest['alloc_pct'],
      'vix': latest['vix'],
      'twd': latest['twd'],
      'inst_total': latest['inst_total'],
      'futures_oi': latest['futures_oi'],
      'forecast_20d_mid': f20_end['price_mid'],
      'forecast_20d_chg_pct': f20_chg_pct,
      'forecast_20d_regime': f20_end['regime'],
      'forecast_20d_score': f20_end['composite'],
      'latest_factors': latest['factors'],
    },
    'history': history,
    'forecast': forecast,
    'backtest': backtest,
  }


def _isnan(val: Any) -> bool:
  try:
    return val != val
  except Exception:
    return True


class AppHandler(BaseHTTPRequestHandler):
  def log_message(self, format: str, *args: Any) -> None:
    # Keep console output clean
    return

  def _send_json(self, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    self.send_response(status)
    self.send_header('Content-Type', 'application/json; charset=utf-8')
    self.send_header('Content-Length', str(len(body)))
    self.send_header('Cache-Control', 'no-store')
    self.end_headers()
    self.wfile.write(body)

  def do_GET(self) -> None:
    parsed = urlparse(self.path)
    if parsed.path == '/api/analyze':
      qs = parse_qs(parsed.query)
      symbol = qs.get('symbol', ['^TWII'])[0]
      try:
        days = int(qs.get('days', ['126'])[0])
      except ValueError:
        days = 126
      factors_raw = qs.get('factors', [''])[0]
      if factors_raw == 'none':
        active_factors = []
      elif factors_raw:
        active_factors = [f.strip() for f in factors_raw.split(',') if f.strip()]
      else:
        active_factors = list(FACTOR_META.keys())
      force = qs.get('refresh', ['0'])[0] == '1'

      try:
        data = analyze_market(
          symbol=symbol,
          display_days=days,
          active_factors=active_factors,
          force_refresh=force,
        )
        self._send_json(data, 200)
      except Exception as exc:
        traceback.print_exc()
        self._send_json({'error': str(exc)}, 500)
      return

    # Serve static files
    rel_path = parsed.path.lstrip('/')
    if not rel_path or rel_path == '/':
      rel_path = 'index.html'
    file_path = (STATIC_DIR / rel_path).resolve()

    if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
      self.send_error(HTTPStatus.NOT_FOUND, 'File Not Found')
      return

    mime, _ = mimetypes.guess_type(str(file_path))
    content = file_path.read_bytes()
    self.send_response(200)
    self.send_header('Content-Type', f'{mime or "application/octet-stream"}; charset=utf-8')
    self.send_header('Content-Length', str(len(content)))
    self.end_headers()
    self.wfile.write(content)


def run_server(host: str = '127.0.0.1', port: int = 8765) -> None:
  server = ThreadingHTTPServer((host, port), AppHandler)
  print(f'股市多空趨勢預測系統已啟動: http://{host}:{port}', flush=True)
  server.serve_forever()


if __name__ == '__main__':
  port = int(os.environ.get('PORT', '8765'))
  run_server(port=port)
