from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DASHBOARD_DIR = ROOT / "dashboard"
DASHBOARD_HTML = DASHBOARD_DIR / "interactive_model_dashboard.html"


def read_csv(name: str) -> pd.DataFrame:
    path = OUTPUTS / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ["date", "origin_date", "target_date"]:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def clean_records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    cleaned = df.astype(object).where(pd.notna(df), None)
    return cleaned.to_dict("records")


def payload() -> dict:
    return {
        "paths": {
            "workspace": str(ROOT.resolve()),
            "outputs": str(OUTPUTS.resolve()),
            "dashboard": str(DASHBOARD_HTML.resolve()),
        },
        "sources": {
            "CEPEA etanol hidratado MT": "https://cepea.org.br/br/indicador/etanol-semanal-mt.aspx",
            "CEPEA serie historica MT": "https://cepea.org.br/br/indicador/series/etanol-semanal-mt.aspx?id=76",
            "ANP revenda etanol hidratado + gasolina C": "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis",
            "EIA Brent semanal": "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=w&n=pet&s=rbrte",
            "BCB SGS USD/BRL PTAX serie 1": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?formato=json",
        },
        "dataset": clean_records(read_csv("integrated_dataset.csv")),
        "forecasts": clean_records(read_csv("forecasts.csv")),
        "monthlyForecasts": clean_records(read_csv("monthly_forecasts.csv")),
        "backtestPredictions": clean_records(read_csv("backtest_predictions.csv")),
        "monthlyBacktestMetrics": clean_records(read_csv("monthly_backtest_metrics.csv")),
        "correlations": clean_records(read_csv("correlations.csv")),
    }


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dashboard interactivo - Etanol MT</title>
  <style>
    :root {
      --bg: #f4f6f1;
      --panel: #ffffff;
      --ink: #1e292d;
      --muted: #657173;
      --line: #d9dfd2;
      --base: #28737d;
      --up: #b24c3d;
      --down: #31795a;
      --brent: #bc7a20;
      --usd: #3f6d9a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, Segoe UI, Arial, sans-serif;
    }
    header {
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 20px 26px 14px;
    }
    h1 { margin: 0; font-size: 23px; letter-spacing: 0; }
    h2 { margin: 0 0 10px; font-size: 16px; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 5px; }
    main { max-width: 1480px; margin: 0 auto; padding: 16px 26px 30px; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-5 { grid-column: span 5; }
    .span-7 { grid-column: span 7; }
    .span-8 { grid-column: span 8; }
    .span-9 { grid-column: span 9; }
    .span-12 { grid-column: span 12; }
    .nav-tabs { display: flex; gap: 8px; margin-top: 14px; }
    .page-tab {
      border: 1px solid var(--line);
      background: #f7f9f4;
      color: var(--ink);
      border-radius: 6px;
      padding: 8px 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .page-tab.active { background: var(--base); border-color: var(--base); color: #fff; }
    .page { display: none; }
    .page.active { display: block; }
    label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    select, input[type="range"], input[type="number"] { width: 100%; }
    select, input[type="number"] {
      padding: 8px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
    }
    .kpi-label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .kpi-value { font-size: 25px; font-weight: 750; margin-top: 4px; }
    .chart-title { font-weight: 750; font-size: 15px; margin-bottom: 8px; }
    svg { width: 100%; height: 360px; display: block; touch-action: none; }
    svg.large-chart { height: 500px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 7px 6px; text-align: left; }
    th { color: var(--muted); font-weight: 700; }
    .hint { color: var(--muted); font-size: 12px; margin-top: 8px; }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; color: var(--muted); font-size: 12px; }
    .swatch { display:inline-block; width:10px; height:10px; margin-right:5px; vertical-align:-1px; }
    .path { font-family: Consolas, monospace; overflow-wrap: anywhere; }
    .source-list { margin: 0; padding-left: 18px; color: var(--muted); font-size: 13px; }
    .source-list li { margin: 5px 0; }
    a { color: #246b76; }
    .tooltip {
      position: fixed;
      pointer-events: none;
      background: #1f2a2e;
      color: white;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 12px;
      min-width: 190px;
      display: none;
      z-index: 5;
      box-shadow: 0 8px 24px rgba(0,0,0,0.18);
    }
    .manual-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .manual-grid small { color: var(--muted); display: block; margin-top: 4px; }
    .history-quad {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .quad-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
      background: #fbfcf9;
    }
    .quad-item .chart-title { font-size: 14px; }
    svg.quad-chart { height: 330px; }
    .badge {
      display: inline-block;
      border-radius: 999px;
      background: #eef3ed;
      padding: 3px 8px;
      color: #365648;
      font-weight: 700;
      font-size: 12px;
    }
    @media (max-width: 980px) {
      .span-3, .span-4, .span-5, .span-7, .span-8, .span-9 { grid-column: span 12; }
      svg.large-chart { height: 420px; }
      .history-quad { grid-template-columns: 1fr; }
      svg.quad-chart { height: 360px; }
      header, main { padding-left: 15px; padding-right: 15px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Etanol hidratado MT - dashboard interactivo</h1>
    <div class="sub">Precios netos estimados, Brent como variable estrategica, backtesting real vs modelo y resultados mensuales.</div>
    <nav class="nav-tabs" aria-label="Secciones del dashboard">
      <button class="page-tab active" type="button" data-page="modelPage">Modelo</button>
      <button class="page-tab" type="button" data-page="historyPage">Historicos</button>
    </nav>
  </header>
  <main>
    <section id="modelPage" class="page active">
    <div class="grid">
      <div class="panel span-3">
        <label for="targetSelect">Indicador</label>
        <select id="targetSelect">
          <option value="cepea_ethanol_mt_net_m3">CEPEA neto R$/m3</option>
          <option value="anp_ethanol_mt_net_l">ANP neto R$/litro</option>
        </select>
      </div>
      <div class="panel span-3">
        <label for="rangeSelect">Ventana historica</label>
        <select id="rangeSelect">
          <option value="5y">5 anos</option>
          <option value="3y">3 anos</option>
          <option value="2y">2 anos</option>
          <option value="1y">1 ano</option>
        </select>
      </div>
      <div class="panel span-3">
        <label for="horizonSelect">Backtest</label>
        <select id="horizonSelect">
          <option value="4">4 semanas</option>
          <option value="12">12 semanas</option>
          <option value="26">26 semanas</option>
          <option value="52">52 semanas</option>
        </select>
      </div>
      <div class="panel span-3">
        <div class="kpi-label">Lectura actual</div>
        <div class="kpi-value" id="latestKpi">n/a</div>
        <div class="sub" id="latestKpiSub">ultimo dato historico</div>
      </div>
      <div class="panel span-8">
        <h2>Inputs manuales de escenario</h2>
        <div class="manual-grid">
          <div><label for="brentInput">Brent USD/bbl</label><input id="brentInput" type="number" step="0.10"><small id="brentBaseLabel"></small></div>
          <div><label for="usdInput">USD/BRL</label><input id="usdInput" type="number" step="0.0001"><small id="usdBaseLabel"></small></div>
          <div><label for="gasInput">Gasolina neta MT R$/l</label><input id="gasInput" type="number" step="0.001"><small id="gasBaseLabel"></small></div>
        </div>
        <div class="hint">Estos inputs ajustan el escenario what-if contra la base. Hoy usan sensibilidad interpolada entre escenarios; el siguiente paso puede ser recalcular el modelo completo con esos valores.</div>
      </div>
      <div class="panel span-4">
        <div class="kpi-label">Impacto 12 meses vs base</div>
        <div class="kpi-value" id="impactKpi">n/a</div>
        <div class="sub">ultimo mes proyectado, escenario what-if</div>
      </div>
    </div>

    <div class="grid" style="margin-top:14px">
      <div class="panel span-8">
        <div class="chart-title">Historico y proyeccion neta</div>
        <svg id="mainChart"></svg>
        <div class="legend">
          <span><i class="swatch" style="background:#1f2a2e"></i>Historico real</span>
          <span><i class="swatch" style="background:var(--base)"></i>Base</span>
          <span><i class="swatch" style="background:#6f4f9b"></i>What-if Brent/USD</span>
        </div>
      </div>
      <div class="panel span-4">
        <div class="chart-title">Proyeccion mensual base y what-if</div>
        <div id="monthlyTable"></div>
      </div>
      <div class="panel span-7">
        <div class="chart-title">Backtest: real vs modelo</div>
        <svg id="backtestChart"></svg>
        <div class="hint">Comparacion fuera de muestra. Si aqui falla mucho, el forecast futuro debe leerse con mas cautela.</div>
      </div>
      <div class="panel span-12">
        <div class="chart-title">Correlaciones historicas por rezago</div>
        <div class="sub" id="corrPeriod">Periodo: n/a</div>
        <svg id="corrChart" class="large-chart"></svg>
        <div class="hint" id="corrLagLabel">Mueve el cursor sobre el grafico para leer la correlacion por rezago.</div>
      </div>
      <div class="panel span-5">
        <div class="chart-title">Validacion mensual del modelo completo</div>
        <div id="metricsTable"></div>
      </div>
      <div class="panel span-7">
        <div class="chart-title">Fuentes de datos</div>
        <ul class="source-list" id="sourcesList"></ul>
      </div>
      <div class="panel span-12">
        <div class="chart-title">Archivos</div>
        <table>
          <tbody>
            <tr><th>Workspace</th><td class="path" id="workspacePath"></td></tr>
            <tr><th>Outputs</th><td class="path" id="outputsPath"></td></tr>
            <tr><th>Dashboard</th><td class="path" id="dashboardPath"></td></tr>
          </tbody>
        </table>
      </div>
    </div>
    </section>

    <section id="historyPage" class="page">
      <div class="grid">
        <div class="panel span-3">
          <label for="historyRangeSelect">Historia visible</label>
          <select id="historyRangeSelect">
            <option value="5y">5 anos</option>
            <option value="3y">3 anos</option>
            <option value="2y">2 anos</option>
            <option value="1y">1 ano</option>
          </select>
        </div>
        <div class="panel span-9">
          <div class="kpi-label">Hoja de historicos</div>
          <div class="sub">Series en valores reales, no base 100. Los graficos comparten el cursor temporal para comparar una misma fecha entre variables.</div>
        </div>
        <div class="panel span-12">
          <div class="chart-title">Etanol hidratado MT historico</div>
          <svg id="histEthanolChart" class="large-chart"></svg>
          <div class="legend">
            <span><i class="swatch" style="background:#1f2a2e"></i>CEPEA neto R$/litro equivalente</span>
            <span><i class="swatch" style="background:var(--base)"></i>ANP etanol neto R$/litro</span>
          </div>
        </div>
        <div class="panel span-12">
          <div class="chart-title">Comparacion historica de drivers</div>
          <div class="history-quad">
            <div class="quad-item">
              <div class="chart-title">Gasolina C ANP neta MT</div>
              <svg id="histGasChart" class="quad-chart"></svg>
            </div>
            <div class="quad-item">
              <div class="chart-title">Brent historico</div>
              <svg id="histBrentChart" class="quad-chart"></svg>
            </div>
            <div class="quad-item">
              <div class="chart-title">USD/BRL historico</div>
              <svg id="histUsdChart" class="quad-chart"></svg>
            </div>
            <div class="quad-item">
              <div class="chart-title">Paridad bruta ANP etanol/gasolina C</div>
              <svg id="histParityChart" class="quad-chart"></svg>
              <div class="hint">Paridad bruta de surtidor. La linea punteada marca 0,70.</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </main>
  <div class="tooltip" id="tooltip"></div>

  <script id="payload" type="application/json">__DATA__</script>
  <script>
    const DATA = JSON.parse(document.getElementById("payload").textContent);
    const meta = {
      cepea_ethanol_mt_net_m3: { label: "CEPEA neto", unit: "R$/m3 neto", digits: 0 },
      anp_ethanol_mt_net_l: { label: "ANP neto", unit: "R$/litro neto", digits: 3 }
    };
    const colors = { actual:"#1f2a2e", base:"#28737d", whatif:"#6f4f9b", brent:"#bc7a20", usd:"#3f6d9a", gas:"#31795a", parity:"#8a5a99", parityGross:"#a7794f" };
    const modelName = "D_plus_usd_brl";

    function $(id) { return document.getElementById(id); }
    function num(v, d=2) {
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "n/a";
      return Number(v).toLocaleString("es-AR", { minimumFractionDigits:d, maximumFractionDigits:d });
    }
    function dateMs(d) { return new Date(d + "T00:00:00").getTime(); }
    function cutoffDate(range) {
      const max = Math.max(...DATA.dataset.map(r => dateMs(r.date)));
      const years = { "5y":5, "3y":3, "2y":2, "1y":1 }[range] || 5;
      const d = new Date(max);
      d.setFullYear(d.getFullYear() - years);
      return d.getTime();
    }
    function target() { return $("targetSelect").value; }
    function horizon() { return Number($("horizonSelect").value); }
    function range() { return $("rangeSelect").value; }
    function historyRange() { return $("historyRangeSelect").value; }
    function latestValue(column) {
      const rows = DATA.dataset.filter(r => r[column] !== null);
      return rows.length ? Number(rows[rows.length - 1][column]) : null;
    }
    function baselineInputs() {
      return {
        brent: latestValue("brent_usd_bbl") || 1,
        usd: latestValue("usd_brl") || 1,
        gas: latestValue("anp_gasoline_mt_net_l") || 1
      };
    }
    function shockScore() {
      const base = baselineInputs();
      const b = ((Number($("brentInput").value) / base.brent) - 1) / 0.15;
      const u = ((Number($("usdInput").value) / base.usd) - 1) / 0.08;
      const g = ((Number($("gasInput").value) / base.gas) - 1) / 0.05;
      return Math.max(-2, Math.min(2, (b + u + g) / 3));
    }
    function forecastRows(t, scenario) {
      return DATA.forecasts.filter(r => r.target === t && r.scenario === scenario).map(r => ({ date:r.date, value:Number(r.forecast) }));
    }
    function whatIfRows(t) {
      const base = forecastRows(t, "base");
      const up = forecastRows(t, "upside_macro");
      const down = forecastRows(t, "downside_macro");
      const upByDate = Object.fromEntries(up.map(r => [r.date, r.value]));
      const downByDate = Object.fromEntries(down.map(r => [r.date, r.value]));
      const score = shockScore();
      return base.map(r => {
        const ref = score >= 0 ? upByDate[r.date] : downByDate[r.date];
        const delta = (ref ?? r.value) - r.value;
        return { date:r.date, value: Math.max(0, r.value + Math.abs(score) * delta) };
      });
    }
    function selectedHistory(t) {
      const cut = cutoffDate(range());
      return DATA.dataset
        .filter(r => r[t] !== null && dateMs(r.date) >= cut)
        .map(r => ({ date:r.date, value:Number(r[t]) }));
    }
    function lineChart(svg, series, yLabel, xLabel) {
      const width = 920;
      const height = svg.classList.contains("large-chart") ? 500 : (svg.classList.contains("quad-chart") ? 330 : 360);
      const pad = { l:72, r:26, t:18, b:54 };
      const valueDigits = yLabel.includes("Etanol / Gasolina") ? 2 : (yLabel.includes("litro") ? 2 : 0);
      const all = series.flatMap(s => s.data.map(p => ({ x:dateMs(p.date), y:Number(p.value) })).filter(p => !Number.isNaN(p.y)));
      if (!all.length) { svg.innerHTML = "<text x='20' y='40' fill='#657173'>Sin datos</text>"; return; }
      const minX = Math.min(...all.map(p => p.x)), maxX = Math.max(...all.map(p => p.x));
      let minY = Math.min(...all.map(p => p.y)), maxY = Math.max(...all.map(p => p.y));
      const margin = (maxY - minY) * 0.08 || 1; minY -= margin; maxY += margin;
      const sx = x => pad.l + (x-minX)/((maxX-minX)||1)*(width-pad.l-pad.r);
      const sy = y => height-pad.b - (y-minY)/((maxY-minY)||1)*(height-pad.t-pad.b);
      const yTicks = Array.from({length:5}, (_,i) => minY + i*(maxY-minY)/4);
      const xTicks = Array.from({length:5}, (_,i) => minX + i*(maxX-minX)/4);
      let grid = "";
      yTicks.forEach(v => { const y=sy(v); grid += `<line x1="${pad.l}" y1="${y}" x2="${width-pad.r}" y2="${y}" stroke="#e4e8df"/><text x="8" y="${y+4}" font-size="11" fill="#657173">${num(v, valueDigits)}</text>`; });
      xTicks.forEach(v => { const x=sx(v); const d=new Date(v).toISOString().slice(0,7); grid += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${height-pad.b}" stroke="#f0f2ed"/><text x="${x-21}" y="${height-23}" font-size="11" fill="#657173">${d}</text>`; });
      const paths = series.map(s => {
        const pts = s.data.filter(p => p.value !== null && !Number.isNaN(Number(p.value))).map(p => `${sx(dateMs(p.date)).toFixed(1)},${sy(Number(p.value)).toFixed(1)}`).join(" ");
        const dash = s.dashed ? "stroke-dasharray='5 4'" : "";
        return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2.5}" stroke-linejoin="round" stroke-linecap="round" ${dash}/>`;
      }).join("");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = `
        <rect width="${width}" height="${height}" fill="white"/>${grid}
        <line x1="${pad.l}" y1="${height-pad.b}" x2="${width-pad.r}" y2="${height-pad.b}" stroke="#cfd8cb"/>
        <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height-pad.b}" stroke="#cfd8cb"/>
        ${paths}<line id="${svg.id}Cross" x1="-10" y1="${pad.t}" x2="-10" y2="${height-pad.b}" stroke="#7d8788" stroke-dasharray="3 3"/>
        <text x="${width/2-28}" y="${height-6}" font-size="12" fill="#445">${xLabel}</text>
        <text transform="translate(14 ${height/2+42}) rotate(-90)" font-size="12" fill="#445">${yLabel}</text>`;
      if (svg.id === "histParityChart") {
        const y70 = sy(0.70);
        if (y70 >= pad.t && y70 <= height-pad.b) {
          svg.insertAdjacentHTML("beforeend", `<line x1="${pad.l}" y1="${y70}" x2="${width-pad.r}" y2="${y70}" stroke="#9fa99a" stroke-dasharray="4 4"/><text x="${width-pad.r-35}" y="${y70-5}" font-size="11" fill="#657173">0,70</text>`);
        }
      }
      window.chartRegistry ||= {};
      window.chartRegistry[svg.id] = { minX, maxX, pad, width };
      svg.onmousemove = ev => showTooltip(ev, svg, series, sx, minX, maxX, pad, width, valueDigits);
      svg.onmouseleave = () => {
        $("tooltip").style.display = "none";
        if (!window.chartRegistry) return;
        Object.keys(window.chartRegistry).forEach(id => {
          const c = $(id)?.querySelector(`#${id}Cross`);
          if (c) c.setAttribute("x1","-10"), c.setAttribute("x2","-10");
        });
      };
    }
    function nearest(arr, ms) {
      if (!arr.length) return null;
      return arr.reduce((best, p) => Math.abs(dateMs(p.date)-ms) < Math.abs(dateMs(best.date)-ms) ? p : best, arr[0]);
    }
    function showTooltip(ev, host, series, sx, minX, maxX, pad, width, valueDigits) {
      const rect = host.getBoundingClientRect();
      const xPixel = (ev.clientX - rect.left) / rect.width * 920;
      if (xPixel < pad.l || xPixel > width-pad.r) return;
      const ms = minX + (xPixel-pad.l)/(width-pad.l-pad.r)*(maxX-minX);
      updateLinkedCrosshairs(ms);
      const lines = series.map(s => {
        const p = nearest(s.data, ms);
        if (!p) return "";
        return `<div><span style="color:${s.color}">â—</span> ${s.name}: <b>${num(p.value, valueDigits)}</b> <small>${p.date}</small></div>`;
      }).join("");
      const tip = $("tooltip");
      tip.innerHTML = lines;
      tip.style.left = `${ev.clientX + 14}px`;
      tip.style.top = `${ev.clientY + 14}px`;
      tip.style.display = "block";
    }
    function updateLinkedCrosshairs(ms) {
      if (!window.chartRegistry) return;
      Object.entries(window.chartRegistry).forEach(([id, cfg]) => {
        const host = $(id);
        const c = host?.querySelector(`#${id}Cross`);
        if (!c) return;
        const x = cfg.pad.l + (ms-cfg.minX)/((cfg.maxX-cfg.minX)||1)*(cfg.width-cfg.pad.l-cfg.pad.r);
        if (x < cfg.pad.l || x > cfg.width-cfg.pad.r) {
          c.setAttribute("x1","-10"); c.setAttribute("x2","-10");
        } else {
          c.setAttribute("x1", x); c.setAttribute("x2", x);
        }
      });
    }
    function barChart(svg, rows, xKey, yKey, groupKey, yLabel, xLabel) {
      const width=920, height=360, pad={l:72,r:26,t:18,b:58};
      rows = rows.filter(r => r[yKey] !== null && !Number.isNaN(Number(r[yKey])));
      if (!rows.length) { svg.innerHTML = "<text x='20' y='40' fill='#657173'>Sin datos</text>"; return; }
      const cats = [...new Set(rows.map(r => r[xKey]))].sort((a,b)=>Number(a)-Number(b));
      const groups = groupKey ? [...new Set(rows.map(r => r[groupKey]))] : [""];
      let minY = Math.min(0, ...rows.map(r=>Number(r[yKey]))), maxY = Math.max(0, ...rows.map(r=>Number(r[yKey])));
      const margin=(maxY-minY)*0.12||1; minY-=margin; maxY+=margin;
      const sy = y => height-pad.b - (y-minY)/((maxY-minY)||1)*(height-pad.t-pad.b);
      const zero=sy(0), cluster=(width-pad.l-pad.r)/cats.length, bw=Math.max(3, cluster/(groups.length+1.8));
      const colorFor = g => g.includes("gasoline") || g.includes("Gasolina") ? colors.gas : g.includes("brent") || g.includes("Brent") ? colors.brent : colors.usd;
      let bars="", labels="";
      cats.forEach((cat, ci) => {
        const bx=pad.l+ci*cluster+cluster*.12;
        groups.forEach((g, gi) => {
          const row=rows.find(r => r[xKey]===cat && (!groupKey || r[groupKey]===g)); if (!row) return;
          const v=Number(row[yKey]), y=v>=0?sy(v):zero, h=Math.abs(sy(v)-zero);
          bars += `<rect x="${bx+gi*bw}" y="${y}" width="${bw}" height="${h}" fill="${colorFor(g)}" rx="2"/>`;
        });
        labels += `<text x="${bx}" y="${height-28}" font-size="10" fill="#657173">${cat}</text>`;
      });
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = `<rect width="${width}" height="${height}" fill="white"/>
        <line x1="${pad.l}" y1="${zero}" x2="${width-pad.r}" y2="${zero}" stroke="#9fa99a"/>
        <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height-pad.b}" stroke="#cfd8cb"/>
        ${bars}${labels}
        <text x="${width/2-45}" y="${height-8}" font-size="12" fill="#445">${xLabel}</text>
        <text transform="translate(14 ${height/2+40}) rotate(-90)" font-size="12" fill="#445">${yLabel}</text>`;
    }
    function corrColor(name) {
      return name.includes("Gasolina") ? colors.gas : name.includes("Brent") ? colors.brent : colors.usd;
    }
    function correlationChart(svg, rows) {
      const width=920, height=500, pad={l:76,r:34,t:28,b:62};
      rows = rows.filter(r => r.correlation !== null && !Number.isNaN(Number(r.correlation)));
      if (!rows.length) { svg.innerHTML = "<text x='20' y='40' fill='#657173'>Sin datos</text>"; return; }
      const lags = [...new Set(rows.map(r => Number(r.lag_weeks)))].sort((a,b)=>a-b);
      const variables = [...new Set(rows.map(r => r.variable))];
      const minX = Math.min(...lags), maxX = Math.max(...lags);
      const minY = -1, maxY = 1;
      const sx = x => pad.l + (x-minX)/((maxX-minX)||1)*(width-pad.l-pad.r);
      const sy = y => height-pad.b - (y-minY)/(maxY-minY)*(height-pad.t-pad.b);
      let grid = "";
      [-1,-0.5,0,0.5,1].forEach(v => {
        const y=sy(v);
        grid += `<line x1="${pad.l}" y1="${y}" x2="${width-pad.r}" y2="${y}" stroke="${v===0 ? '#9fa99a' : '#e4e8df'}"/>`;
        grid += `<text x="18" y="${y+4}" font-size="11" fill="#657173">${num(v,2)}</text>`;
      });
      lags.forEach(lag => {
        const x=sx(lag);
        grid += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${height-pad.b}" stroke="#f0f2ed"/>`;
        grid += `<text x="${x-5}" y="${height-28}" font-size="11" fill="#657173">${lag}</text>`;
      });
      let marks = "";
      variables.forEach(variable => {
        const points = rows.filter(r => r.variable===variable).sort((a,b)=>Number(a.lag_weeks)-Number(b.lag_weeks));
        const poly = points.map(r => `${sx(Number(r.lag_weeks)).toFixed(1)},${sy(Number(r.correlation)).toFixed(1)}`).join(" ");
        marks += `<polyline points="${poly}" fill="none" stroke="${corrColor(variable)}" stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round"/>`;
        points.forEach(r => {
          const x=sx(Number(r.lag_weeks)), y=sy(Number(r.correlation));
          marks += `<circle cx="${x}" cy="${y}" r="4.3" fill="#fff" stroke="${corrColor(variable)}" stroke-width="2"/>`;
          if ([0,4,8,12].includes(Number(r.lag_weeks))) {
            marks += `<text x="${x+6}" y="${y-6}" font-size="10" fill="${corrColor(variable)}">${num(r.correlation,2)}</text>`;
          }
        });
      });
      const legend = variables.map((v,i) => `<text x="${pad.l + i*190}" y="18" font-size="12" fill="${corrColor(v)}">${v}</text>`).join("");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = `<rect width="${width}" height="${height}" fill="white"/>${legend}${grid}${marks}
        <line id="corrChartCross" x1="-10" y1="${pad.t}" x2="-10" y2="${height-pad.b}" stroke="#7d8788" stroke-dasharray="3 3"/>
        <text x="${width/2-70}" y="${height-8}" font-size="12" fill="#445">Rezago de la variable explicativa (semanas)</text>
        <text transform="translate(14 ${height/2+48}) rotate(-90)" font-size="12" fill="#445">Correlacion</text>`;
      svg.onmousemove = ev => {
        const rect = svg.getBoundingClientRect();
        const xPixel = (ev.clientX - rect.left) / rect.width * width;
        if (xPixel < pad.l || xPixel > width-pad.r) return;
        const rawLag = minX + (xPixel-pad.l)/(width-pad.l-pad.r)*(maxX-minX);
        const lag = lags.reduce((best, v) => Math.abs(v-rawLag) < Math.abs(best-rawLag) ? v : best, lags[0]);
        const x=sx(lag);
        const cross = svg.querySelector("#corrChartCross");
        if (cross) { cross.setAttribute("x1", x); cross.setAttribute("x2", x); }
        const selected = variables.map(v => rows.find(r => r.variable===v && Number(r.lag_weeks)===lag)).filter(Boolean);
        $("corrLagLabel").innerHTML = `Rezago seleccionado: <b>${lag} semanas</b>. ` + selected.map(r => `${r.variable}: <b>${num(r.correlation,2)}</b>`).join(" | ");
        const tip = $("tooltip");
        tip.innerHTML = selected.map(r => `<div><span style="color:${corrColor(r.variable)}">o</span> ${r.variable}: <b>${num(r.correlation,2)}</b></div>`).join("");
        tip.style.left = `${ev.clientX + 14}px`;
        tip.style.top = `${ev.clientY + 14}px`;
        tip.style.display = "block";
      };
      svg.onmouseleave = () => {
        $("tooltip").style.display = "none";
        $("corrLagLabel").textContent = "Mueve el cursor sobre el grafico para leer la correlacion por rezago.";
        const cross = svg.querySelector("#corrChartCross");
        if (cross) { cross.setAttribute("x1","-10"); cross.setAttribute("x2","-10"); }
      };
    }
    function renderMain() {
      const t = target();
      const hist = selectedHistory(t);
      const base = forecastRows(t, "base");
      const wi = whatIfRows(t);
      lineChart($("mainChart"), [
        {name:"Historico real", data:hist, color:colors.actual, width:2.8},
        {name:"Proyeccion base", data:base, color:colors.base, dashed:true},
        {name:"What-if Brent/USD", data:wi, color:colors.whatif, dashed:true}
      ], `Precio (${meta[t].unit})`, "Fecha");
      const latest = hist[hist.length-1];
      $("latestKpi").textContent = latest ? num(latest.value, meta[t].digits) : "n/a";
      $("latestKpiSub").textContent = latest ? `${latest.date} - ${meta[t].unit}` : "ultimo dato historico";
      const lastBase = base[base.length-1], lastWi = wi[wi.length-1];
      if (lastBase && lastWi) {
        const delta = lastWi.value - lastBase.value;
        $("impactKpi").textContent = `${delta >= 0 ? "+" : ""}${num(delta, meta[t].digits)}`;
      }
      renderMonthlyTable();
    }
    function renderBacktest() {
      const t=target(), h=horizon();
      const rows = DATA.backtestPredictions.filter(r => r.target===t && r.horizon_weeks===h && r.model===modelName);
      const actual = rows.map(r => ({date:r.target_date, value:Number(r.actual)}));
      const pred = rows.map(r => ({date:r.target_date, value:Number(r.prediction)}));
      lineChart($("backtestChart"), [
        {name:"Real historico", data:actual, color:colors.actual, width:2.8},
        {name:"Modelo", data:pred, color:colors.base, dashed:true}
      ], `Precio (${meta[t].unit})`, "Fecha objetivo");
      renderMetrics();
    }
    function renderCorr() {
      const rows = DATA.correlations.filter(r => r.target===target()).map(r => ({...r, variable:r.variable.replace("anp_gasoline_mt_net_l","Gasolina neta").replace("brent_usd_bbl","Brent").replace("usd_brl","USD/BRL")}));
      const hist = DATA.dataset.filter(r => r[target()] !== null);
      const start = hist.length ? hist[0].date : "n/a";
      const end = hist.length ? hist[hist.length-1].date : "n/a";
      $("corrPeriod").textContent = `Periodo usado: ${start} a ${end} (${hist.length} observaciones semanales)`;
      correlationChart($("corrChart"), rows);
    }
    function renderHistory() {
      const cut=cutoffDate(historyRange());
      const rows=DATA.dataset.filter(r => dateMs(r.date)>=cut);
      lineChart($("histEthanolChart"), [
        {name:"CEPEA etanol neto", color:colors.actual, data: rows.filter(r => r.cepea_ethanol_mt_net_m3!==null).map(r => ({date:r.date, value:Number(r.cepea_ethanol_mt_net_m3)/1000}))},
        {name:"ANP etanol neto", color:colors.base, dashed:true, data: rows.filter(r => r.anp_ethanol_mt_net_l!==null).map(r => ({date:r.date, value:Number(r.anp_ethanol_mt_net_l)}))}
      ], "Precio neto (R$/litro)", "Fecha");
      lineChart($("histGasChart"), [
        {name:"Gasolina C neta MT", color:colors.gas, data: rows.filter(r => r.anp_gasoline_mt_net_l!==null).map(r => ({date:r.date, value:Number(r.anp_gasoline_mt_net_l)}))}
      ], "Gasolina C neta (R$/litro)", "Fecha");
      lineChart($("histBrentChart"), [
        {name:"Brent", color:colors.brent, data: rows.filter(r => r.brent_usd_bbl!==null).map(r => ({date:r.date, value:Number(r.brent_usd_bbl)}))}
      ], "Brent (USD/bbl)", "Fecha");
      lineChart($("histUsdChart"), [
        {name:"USD/BRL", color:colors.usd, data: rows.filter(r => r.usd_brl!==null).map(r => ({date:r.date, value:Number(r.usd_brl)}))}
      ], "Tipo de cambio (BRL/USD)", "Fecha");
      lineChart($("histParityChart"), [
        {name:"Paridad bruta", color:colors.parityGross, data: rows.filter(r => r.anp_parity_gross!==null).map(r => ({date:r.date, value:Number(r.anp_parity_gross)}))}
      ], "Etanol / Gasolina C", "Fecha");
    }
    function renderMonthlyTable() {
      const t=target();
      const base = forecastRows(t, "base");
      const wi = whatIfRows(t);
      const monthly = {};
      function add(rows, key) {
        rows.forEach(r => {
          const m = r.date.slice(0,7); monthly[m] ||= {month:m, base:[], whatif:[]}; monthly[m][key].push(r.value);
        });
      }
      add(base, "base"); add(wi, "whatif");
      const rows = Object.values(monthly).map(r => ({
        month:r.month,
        base:r.base.reduce((a,b)=>a+b,0)/r.base.length,
        whatif:r.whatif.reduce((a,b)=>a+b,0)/r.whatif.length
      })).slice(0,14);
      $("monthlyTable").innerHTML = table(rows, [
        ["month","Mes",0], ["base","Base",meta[t].digits], ["whatif","What-if",meta[t].digits]
      ]);
    }
    function renderMetrics() {
      const t=target();
      const rows = DATA.monthlyBacktestMetrics.filter(r => r.target===t && r.model===modelName);
      $("metricsTable").innerHTML = table(rows, [
        ["horizon_weeks","Horiz.",0], ["mae","MAE",meta[t].digits], ["rmse","RMSE",meta[t].digits], ["smape","sMAPE",3], ["directional_accuracy","Dir.",2]
      ]);
    }
    function table(rows, cols) {
      if (!rows.length) return "<div class='hint'>Sin datos</div>";
      const head = `<tr>${cols.map(c=>`<th>${c[1]}</th>`).join("")}</tr>`;
      const body = rows.map(r => `<tr>${cols.map(c=>`<td>${c[2]===0 && typeof r[c[0]]==="string" ? r[c[0]] : num(r[c[0]], c[2])}</td>`).join("")}</tr>`).join("");
      return `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
    }
    function renderAll() {
      renderMain(); renderBacktest(); renderCorr(); renderHistory();
      $("workspacePath").textContent = DATA.paths.workspace;
      $("outputsPath").textContent = DATA.paths.outputs;
      $("dashboardPath").textContent = DATA.paths.dashboard;
      $("sourcesList").innerHTML = Object.entries(DATA.sources || {}).map(([label, url]) => `<li><a href="${url}" target="_blank" rel="noreferrer">${label}</a></li>`).join("");
    }
    function initInputs() {
      const base = baselineInputs();
      $("brentInput").value = base.brent.toFixed(2);
      $("usdInput").value = base.usd.toFixed(4);
      $("gasInput").value = base.gas.toFixed(3);
      $("brentBaseLabel").textContent = `base actual: ${num(base.brent, 2)}`;
      $("usdBaseLabel").textContent = `base actual: ${num(base.usd, 4)}`;
      $("gasBaseLabel").textContent = `base actual: ${num(base.gas, 3)}`;
    }
    document.querySelectorAll(".page-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".page-tab").forEach(x => x.classList.toggle("active", x === btn));
        document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.id === btn.dataset.page));
        renderAll();
      });
    });
    ["targetSelect","rangeSelect","horizonSelect","historyRangeSelect","brentInput","usdInput","gasInput"].forEach(id => $(id).addEventListener("input", renderAll));
    initInputs();
    renderAll();
  </script>
</body>
</html>
"""


def main() -> None:
    DASHBOARD_DIR.mkdir(exist_ok=True)
    data = json.dumps(payload(), ensure_ascii=True, allow_nan=False)
    DASHBOARD_HTML.write_text(HTML.replace("__DATA__", data), encoding="utf-8")
    print(DASHBOARD_HTML.resolve())


if __name__ == "__main__":
    main()

