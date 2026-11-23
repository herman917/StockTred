"""Build static JSON datasets and copy frontend assets to docs/ for GitHub Pages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from data_fetcher import build_aligned_dataset
from factors import FACTOR_META, compute_factors

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / 'static'
DOCS_DIR = ROOT_DIR / 'docs'
DATA_DIR = DOCS_DIR / 'data'

SYMBOL_FILE_MAP = {
  '^TWII': 'TWII.json',
  '0050.TW': '0050TW.json',
}


def export_symbol(symbol: str, filename: str) -> None:
  df, meta = build_aligned_dataset(symbol=symbol, force_refresh=True)
  ndc_score = int(meta.get('ndc', {}).get('score', 31))
  df_f = compute_factors(df, ndc_score=ndc_score)

  # Export up to 500 trading days (~2 years) so 3M/6M/1Y/2Y and backtest all work client-side
  df_out = df_f.tail(500).copy()
  rows = []
  for idx, row in df_out.iterrows():
    rows.append(
      {
        'date': idx.strftime('%Y-%m-%d'),
        'open': round(float(row['Open']), 2),
        'high': round(float(row['High']), 2),
        'low': round(float(row['Low']), 2),
        'close': round(float(row['Close']), 2),
        'volume': int(row['Volume']) if row['Volume'] == row['Volume'] else 0,
        'ma60': round(float(row['MA60']), 2) if row['MA60'] == row['MA60'] else None,
        'vix': round(float(row['VIX']), 2),
        'twd': round(float(row['TWD']), 3),
        'inst_total': round(float(row['Inst_Total']), 2),
        'futures_oi': round(float(row['Futures_OI']), 0),
        'factors': {
          f: round(float(row[f'f_{f}']), 4) for f in FACTOR_META
        },
      }
    )

  payload = {
    'meta': meta,
    'factor_meta': FACTOR_META,
    'rows': rows,
  }
  out_path = DATA_DIR / filename
  out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
  print(f'Exported {symbol} -> {out_path} ({len(rows)} rows, last={meta["last_date"]})')


def main() -> None:
  DOCS_DIR.mkdir(parents=True, exist_ok=True)
  DATA_DIR.mkdir(parents=True, exist_ok=True)

  for asset in ('index.html', 'styles.css', 'app.js'):
    shutil.copy2(STATIC_DIR / asset, DOCS_DIR / asset)

  for sym, fname in SYMBOL_FILE_MAP.items():
    export_symbol(sym, fname)


if __name__ == '__main__':
  main()
