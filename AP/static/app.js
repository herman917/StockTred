const state = {
  symbol: '^TWII',
  days: 126,
  activeFactors: ['trend_60ma', 'macd_hist', 'vix_sentiment', 'fx_twd', 'chip_macro'],
  zoomStart: 0,
  zoomEnd: 100,
  data: null,
}

let mainChart = null
let equityChart = null

const REGIME_LABELS = {
  bull: '偏多操作（作多）',
  neutral: '多空持平（觀望）',
  bear: '偏空避險（作空）',
}

function setLoading(flag) {
  const el = document.getElementById('loading-overlay')
  if (flag) el.classList.remove('hidden')
  else el.classList.add('hidden')
}

async function fetchAnalysis(forceRefresh = false) {
  setLoading(true)
  try {
    const factorsParam = state.activeFactors.length > 0 ? state.activeFactors.join(',') : 'none'
    const url = `/api/analyze?symbol=${encodeURIComponent(state.symbol)}&days=${state.days}&factors=${encodeURIComponent(factorsParam)}&refresh=${forceRefresh ? '1' : '0'}`
    const res = await fetch(url)
    const data = await res.json()
    if (data.error) {
      alert(`載入失敗: ${data.error}`)
      return
    }
    state.data = data
    renderAll()
  } catch (err) {
    alert(`連線錯誤: ${err.message}`)
  } finally {
    setLoading(false)
  }
}

function renderAll() {
  const d = state.data
  if (!d) return
  renderSummary(d)
  renderFactorToggles(d)
  renderMainChart(d)
  renderBacktest(d)
}

function renderSummary(d) {
  const s = d.summary
  document.getElementById('last-date-badge').textContent = d.meta.last_date
  document.getElementById('kpi-close').textContent = s.close.toLocaleString('zh-TW', { minimumFractionDigits: 2 })

  const chgEl = document.getElementById('kpi-chg')
  const sign = s.price_chg >= 0 ? '+' : ''
  chgEl.textContent = `${sign}${s.price_chg.toFixed(2)} (${sign}${s.price_chg_pct.toFixed(2)}%)`
  chgEl.className = `price-chg ${s.price_chg >= 0 ? 'pos' : 'neg'}`

  const banner = document.getElementById('regime-banner')
  banner.className = `regime-banner ${s.regime}`
  const regText = document.getElementById('kpi-regime')
  regText.textContent = `${REGIME_LABELS[s.regime]} (${s.composite >= 0 ? '+' : ''}${s.composite.toFixed(2)})`
  regText.className = `regime-text ${s.regime === 'bull' ? 'pos' : s.regime === 'bear' ? 'neg' : 'neu'}`

  // Capital allocation
  document.getElementById('kpi-alloc').textContent = `${s.alloc_pct.toFixed(0)}%`
  const fill = document.getElementById('alloc-bar-fill')
  fill.style.width = `${s.alloc_pct}%`
  if (s.alloc_pct >= 65) {
    fill.style.background = 'linear-gradient(90deg, #f97316, #ef4444)'
  } else if (s.alloc_pct >= 35) {
    fill.style.background = 'linear-gradient(90deg, #94a3b8, #cbd5e1)'
  } else {
    fill.style.background = 'linear-gradient(90deg, #16a34a, #22c55e)'
  }

  // 20-day forecast
  document.getElementById('kpi-f20-price').textContent = s.forecast_20d_mid.toLocaleString('zh-TW', { minimumFractionDigits: 2 })
  const fChgEl = document.getElementById('kpi-f20-chg')
  const fSign = s.forecast_20d_chg_pct >= 0 ? '+' : ''
  fChgEl.textContent = `${fSign}${s.forecast_20d_chg_pct.toFixed(2)}%`
  fChgEl.className = s.forecast_20d_chg_pct >= 0 ? 'pos' : 'neg'

  const fRegEl = document.getElementById('kpi-f20-regime')
  fRegEl.textContent = REGIME_LABELS[s.forecast_20d_regime].split('（')[0]
  fRegEl.className = s.forecast_20d_regime === 'bull' ? 'pos' : s.forecast_20d_regime === 'bear' ? 'neg' : 'neu'

  // Macro & chip
  document.getElementById('m-vix').textContent = s.vix.toFixed(2)
  document.getElementById('m-twd').textContent = s.twd.toFixed(3)
  const instSign = s.inst_total >= 0 ? '+' : ''
  document.getElementById('m-inst').textContent = `${instSign}${s.inst_total.toFixed(1)} 億`
  document.getElementById('m-inst').className = s.inst_total >= 0 ? 'pos' : 'neg'

  const oiSign = s.futures_oi >= 0 ? '+' : ''
  document.getElementById('m-oi').textContent = `${oiSign}${Math.round(s.futures_oi).toLocaleString()} 口`
  document.getElementById('m-oi').className = s.futures_oi >= 0 ? 'pos' : 'neg'

  const ndc = d.meta.ndc
  document.getElementById('m-ndc').textContent = `${ndc.light} (${ndc.score}分) - ${ndc.status}`
  document.getElementById('source-note').textContent = `籌碼來源: ${d.meta.chip_source} | 景氣: ${ndc.source}`
}

function renderFactorToggles(d) {
  const container = document.getElementById('factor-list')
  container.innerHTML = ''
  const latestFactors = d.summary.latest_factors || {}

  Object.entries(d.factor_meta).forEach(([key, meta]) => {
    const checked = state.activeFactors.includes(key)
    const val = latestFactors[key] ?? 0
    const sign = val >= 0 ? '+' : ''
    const cls = val > 0.15 ? 'pos' : val < -0.15 ? 'neg' : 'neu'

    const label = document.createElement('label')
    label.className = 'factor-item'
    label.innerHTML = `
      <div class="factor-left">
        <input type="checkbox" value="${key}" ${checked ? 'checked' : ''} />
        <div>
          <div class="factor-name">
            <span class="factor-color-dot" style="background:${meta.color}"></span>
            ${meta.name}
          </div>
          <div class="factor-desc">${meta.desc}</div>
        </div>
      </div>
      <div class="factor-score ${cls}">${sign}${val.toFixed(2)}</div>
    `
    label.querySelector('input').addEventListener('change', (e) => {
      if (e.target.checked) {
        if (!state.activeFactors.includes(key)) state.activeFactors.push(key)
      } else {
        state.activeFactors = state.activeFactors.filter((k) => k !== key)
      }
      fetchAnalysis(false)
    })
    container.appendChild(label)
  })
}

function renderMainChart(d) {
  if (!mainChart) {
    mainChart = echarts.init(document.getElementById('main-chart'))
    window.addEventListener('resize', () => mainChart && mainChart.resize())
  }

  const hist = d.history
  const fcst = d.forecast
  const allRows = [...hist, ...fcst]
  const dates = allRows.map((r) => r.date)
  const splitDate = hist[hist.length - 1].date

  // Grid 1: Candlestick + MA60 + Main Trend Overlay (colored by regime) + Forecast Band
  const ohlc = hist.map((r) => [r.open, r.close, r.low, r.high])
  const ma60Data = allRows.map((r) => (r.is_forecast ? null : r.ma60))

  // Colored trend overlay on price chart (history + forecast)
  const trendOverlayBull = allRows.map((r) => (r.regime === 'bull' ? r.trend_overlay : null))
  const trendOverlayNeu = allRows.map((r) => (r.regime === 'neutral' ? r.trend_overlay : null))
  const trendOverlayBear = allRows.map((r) => (r.regime === 'bear' ? r.trend_overlay : null))
  // Continuous base line so segments connect cleanly
  const trendOverlayBase = allRows.map((r) => r.trend_overlay)

  // Forecast price path & band (starts from last historical close)
  const fcstMid = allRows.map((r, i) => {
    if (i === hist.length - 1) return r.close
    return r.is_forecast ? r.price_mid : null
  })
  const fcstUpper = allRows.map((r, i) => {
    if (i === hist.length - 1) return r.close
    return r.is_forecast ? r.price_upper : null
  })
  const fcstLower = allRows.map((r, i) => {
    if (i === hist.length - 1) return r.close
    return r.is_forecast ? r.price_lower : null
  })

  // Grid 2: Composite thick line (hist & fcst) + Thin factor lines
  const compHist = allRows.map((r) => (r.is_forecast ? null : r.composite))
  const compFcst = allRows.map((r, i) => {
    if (i === hist.length - 1) return r.composite
    return r.is_forecast ? r.composite : null
  })

  // Grid 3: Bull/Bear Strength Histogram (Red positive, Green negative)
  const strengthBars = allRows.map((r) => ({
    value: Math.round(r.composite * 100),
    itemStyle: {
      color: r.composite > 0.15 ? '#ef4444' : r.composite < -0.15 ? '#22c55e' : '#e2e8f0',
      opacity: r.is_forecast ? 0.45 : 0.9,
    },
  }))

  // Factor thin lines (only active factors)
  const factorSeries = Object.entries(d.factor_meta)
    .filter(([key]) => state.activeFactors.includes(key))
    .map(([key, meta]) => ({
      name: meta.name,
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: 1,
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 1.3, color: meta.color, opacity: 0.85 },
      itemStyle: { color: meta.color },
      data: allRows.map((r) => r.factors[key]),
    }))

  const option = {
    backgroundColor: 'transparent',
    animationDuration: 250,
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      lineStyle: { color: '#64748b', width: 1, type: 'dashed' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(15, 23, 42, 0.94)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params) => {
        if (!params || !params.length) return ''
        const idx = params[0].dataIndex
        const row = allRows[idx]
        if (!row) return ''
        const tag = row.is_forecast ? '<span style="color:#38bdf8">[未來20日預測]</span>' : '[歷史日線]'
        const regColor = row.regime === 'bull' ? '#ef4444' : row.regime === 'bear' ? '#22c55e' : '#f8fafc'
        let html = `<div style="font-weight:700;margin-bottom:4px">${row.date} ${tag}</div>`
        if (!row.is_forecast) {
          html += `開: ${row.open} / 高: ${row.high} / 低: ${row.low} / <b>收: ${row.close}</b><br/>`
        } else {
          html += `預測中值: <b>${row.price_mid}</b> (${row.price_lower} ~ ${row.price_upper})<br/>`
        }
        html += `多空狀態: <b style="color:${regColor}">${REGIME_LABELS[row.regime]}</b> (${row.composite >= 0 ? '+' : ''}${row.composite.toFixed(2)})<br/>`
        html += `建議作多資金: <b style="color:#38bdf8">${row.alloc_pct.toFixed(0)}%</b>`
        return html
      },
    },
    grid: [
      { left: 58, right: 20, top: 24, height: '42%' },
      { left: 58, right: 20, top: '53%', height: '21%' },
      { left: 58, right: 20, top: '79%', height: '13%' },
    ],
    xAxis: [
      { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { show: false } },
      { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { show: false } },
      { type: 'category', gridIndex: 2, data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8', fontSize: 11 } },
    ],
    yAxis: [
      {
        scale: true,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      {
        gridIndex: 1,
        min: -1.05,
        max: 1.05,
        splitNumber: 4,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      {
        gridIndex: 2,
        min: -100,
        max: 100,
        splitNumber: 2,
        splitLine: { lineStyle: { color: '#1e293b' } },
        axisLabel: { color: '#94a3b8', fontSize: 10, formatter: '{value}%' },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: state.zoomStart,
        end: state.zoomEnd,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1, 2],
        bottom: 2,
        height: 18,
        start: state.zoomStart,
        end: state.zoomEnd,
        borderColor: '#334155',
        fillerColor: 'rgba(56, 189, 248, 0.18)',
        textStyle: { color: '#94a3b8' },
      },
    ],
    visualMap: [
      {
        show: false,
        seriesIndex: [8, 9], // Composite history & forecast thick lines
        dimension: 1,
        pieces: [
          { gt: 0.15, color: '#ef4444' },
          { gte: -0.15, lte: 0.15, color: '#f8fafc' },
          { lt: -0.15, color: '#22c55e' },
        ],
      },
    ],
    series: [
      // 0: K-line (Taiwan style: Red up, Green down)
      {
        name: 'K線',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e',
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: '#64748b', type: 'dashed', width: 1.2 },
          label: { formatter: '今日 → 未來20日預測', color: '#94a3b8', position: 'insideEndTop' },
          data: [{ xAxis: splitDate }],
        },
      },
      // 1: 60MA
      {
        name: '60MA 季線',
        type: 'line',
        data: ma60Data,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#64748b', type: 'dotted' },
      },
      // 2: Base connecting trend overlay (subtle)
      {
        name: '趨勢軌跡',
        type: 'line',
        data: trendOverlayBase,
        showSymbol: false,
        lineStyle: { width: 2.0, color: '#94a3b8', opacity: 0.35 },
      },
      // 3-5: Thick colored regime overlay segments on price chart
      {
        name: '作多趨勢線',
        type: 'line',
        data: trendOverlayBull,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 3.5, color: '#ef4444' },
      },
      {
        name: '持平趨勢線',
        type: 'line',
        data: trendOverlayNeu,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 3.5, color: '#f8fafc' },
      },
      {
        name: '作空趨勢線',
        type: 'line',
        data: trendOverlayBear,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 3.5, color: '#22c55e' },
      },
      // 6-7: Forecast Price Path & Upper/Lower Band
      {
        name: '20日預測中值',
        type: 'line',
        data: fcstMid,
        showSymbol: false,
        lineStyle: { width: 2, color: '#38bdf8', type: 'dashed' },
      },
      {
        name: '預測上緣',
        type: 'line',
        data: fcstUpper,
        showSymbol: false,
        lineStyle: { width: 1, color: '#38bdf8', opacity: 0.4, type: 'dotted' },
      },
      // 8: Composite Score Thick Line (History) - colored by visualMap
      {
        name: '綜合多空趨勢 (粗線)',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        data: compHist,
        lineStyle: { width: 3.5 },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: '#475569', type: 'dashed', width: 1 },
          data: [{ yAxis: 0.15 }, { yAxis: -0.15 }],
        },
      },
      // 9: Composite Score Thick Line (20D Forecast)
      {
        name: '綜合多空預測 (20日)',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        data: compFcst,
        lineStyle: { width: 3.5, type: 'dashed' },
      },
      // 10+: Active Factor Thin Lines
      ...factorSeries,
      // Last: Bull/Bear Strength Histogram (Grid 3)
      {
        name: '多空氣勢柱狀體',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: strengthBars,
      },
      // Forecast lower bound
      {
        name: '預測下緣',
        type: 'line',
        data: fcstLower,
        showSymbol: false,
        lineStyle: { width: 1, color: '#38bdf8', opacity: 0.4, type: 'dotted' },
      },
    ],
  }

  mainChart.setOption(option, true)
  mainChart.off('datazoom')
  mainChart.on('datazoom', (evt) => {
    const dz = evt.batch ? evt.batch[0] : evt
    if (dz && typeof dz.start === 'number') {
      state.zoomStart = dz.start
      state.zoomEnd = dz.end
    }
  })
}

function renderBacktest(d) {
  const bt = d.backtest
  document.getElementById('bt-days-badge').textContent = `近 ${bt.lookback_days} 交易日`

  const st = bt.strategy
  const bh = bt.buy_hold

  document.getElementById('bt-st-ret').textContent = `${st.total_return_pct >= 0 ? '+' : ''}${st.total_return_pct}%`
  document.getElementById('bt-bh-ret').textContent = `${bh.total_return_pct >= 0 ? '+' : ''}${bh.total_return_pct}%`
  document.getElementById('bt-exp').textContent = `平均持股 ${bt.avg_exposure_pct}%`

  document.getElementById('bt-st-mdd').textContent = `${st.mdd_pct}%`
  document.getElementById('bt-bh-mdd').textContent = `${bh.mdd_pct}%`
  const mddDiff = bt.mdd_reduction_pct
  document.getElementById('bt-mdd-diff').textContent = mddDiff >= 0 ? `回撤降低 ${mddDiff}%` : `回撤增加 ${Math.abs(mddDiff)}%`

  document.getElementById('bt-st-sharpe').textContent = st.sharpe.toFixed(2)
  document.getElementById('bt-bh-sharpe').textContent = bh.sharpe.toFixed(2)
  const shDiff = bt.sharpe_improvement
  document.getElementById('bt-sharpe-diff').textContent = `${shDiff >= 0 ? '+' : ''}${shDiff.toFixed(2)}`

  if (!equityChart) {
    equityChart = echarts.init(document.getElementById('equity-chart'))
    window.addEventListener('resize', () => equityChart && equityChart.resize())
  }

  const dates = bt.equity_curve.map((r) => r.date)
  equityChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.94)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 11 },
    },
    legend: {
      data: ['多因子擇時 (%)', '純買進持有 (%)'],
      textStyle: { color: '#94a3b8', fontSize: 11 },
      top: 0,
    },
    grid: { left: 46, right: 12, top: 28, bottom: 22 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#64748b', fontSize: 10 },
      axisLine: { lineStyle: { color: '#334155' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#94a3b8', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: [
      {
        name: '多因子擇時 (%)',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2.2, color: '#38bdf8' },
        itemStyle: { color: '#38bdf8' },
        data: bt.equity_curve.map((r) => r.strategy),
      },
      {
        name: '純買進持有 (%)',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#94a3b8', type: 'dashed' },
        itemStyle: { color: '#94a3b8' },
        data: bt.equity_curve.map((r) => r.buy_hold),
      },
    ],
  })
}

function bindEvents() {
  document.querySelectorAll('#symbol-switch button').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#symbol-switch button').forEach((b) => b.classList.remove('active'))
      btn.classList.add('active')
      state.symbol = btn.dataset.val
      fetchAnalysis(false)
    })
  })

  document.querySelectorAll('#range-switch button').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#range-switch button').forEach((b) => b.classList.remove('active'))
      btn.classList.add('active')
      state.days = Number(btn.dataset.val)
      state.zoomStart = 0
      state.zoomEnd = 100
      fetchAnalysis(false)
    })
  })

  document.getElementById('btn-zoom-in').addEventListener('click', () => {
    const span = state.zoomEnd - state.zoomStart
    if (span <= 12) return
    const delta = span * 0.15
    state.zoomStart = Math.min(state.zoomStart + delta, state.zoomEnd - 10)
    mainChart && mainChart.dispatchAction({ type: 'dataZoom', start: state.zoomStart, end: state.zoomEnd })
  })

  document.getElementById('btn-zoom-out').addEventListener('click', () => {
    const span = state.zoomEnd - state.zoomStart
    const delta = span * 0.2
    state.zoomStart = Math.max(0, state.zoomStart - delta)
    state.zoomEnd = Math.min(100, state.zoomEnd + delta * 0.5)
    mainChart && mainChart.dispatchAction({ type: 'dataZoom', start: state.zoomStart, end: state.zoomEnd })
  })

  document.getElementById('btn-zoom-reset').addEventListener('click', () => {
    state.zoomStart = 0
    state.zoomEnd = 100
    mainChart && mainChart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
  })

  document.getElementById('btn-refresh').addEventListener('click', () => {
    fetchAnalysis(true)
  })

  document.getElementById('btn-all-factors').addEventListener('click', () => {
    if (state.data) {
      state.activeFactors = Object.keys(state.data.factor_meta)
      fetchAnalysis(false)
    }
  })
}

bindEvents()
fetchAnalysis(false)
