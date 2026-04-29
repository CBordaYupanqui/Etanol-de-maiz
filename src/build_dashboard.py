from __future__ import annotations

import html
import math
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
DASHBOARD_DIR = ROOT / "dashboard"
DASHBOARD_HTML = DASHBOARD_DIR / "model_dashboard.html"

TARGET_META = {
    "cepea_ethanol_mt_net_m3": {
        "label": "CEPEA etanol hidratado MT neto estimado",
        "unit": "R$/m3 neto",
        "color": "#245d55",
    },
    "anp_ethanol_mt_net_l": {
        "label": "ANP etanol hidratado MT neto estimado",
        "unit": "R$/litro neto",
        "color": "#2f6f9f",
    },
}

COLORS = {
    "actual": "#1f2a2e",
    "base": "#27727d",
    "upside_macro": "#b24c3d",
    "downside_macro": "#31795a",
    "anp_gasoline_mt_net_l": "#31795a",
    "brent_usd_bbl": "#bc7a20",
    "usd_brl": "#3f6d9a",
}


def read_csv(name: str) -> pd.DataFrame:
    path = OUTPUTS / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def polyline(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def line_chart(
    title: str,
    series: list[dict],
    y_label: str,
    x_label: str = "Fecha",
    width: int = 920,
    height: int = 360,
) -> str:
    pad = {"l": 70, "r": 26, "t": 34, "b": 58}
    prepared = []
    all_x: list[float] = []
    all_y: list[float] = []
    for item in series:
        frame = item["data"].dropna(subset=["date", "value"]).copy()
        if frame.empty:
            continue
        frame["x"] = frame["date"].map(pd.Timestamp.toordinal).astype(float)
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.dropna(subset=["x", "value"]).sort_values("x")
        if frame.empty:
            continue
        prepared.append({**item, "data": frame})
        all_x.extend(frame["x"].tolist())
        all_y.extend(frame["value"].tolist())

    if not prepared:
        return f"<div class='chart-empty'>Sin datos para {esc(title)}</div>"

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    y_margin = (max_y - min_y) * 0.08 or 1
    min_y -= y_margin
    max_y += y_margin

    def sx(x: float) -> float:
        return pad["l"] + (x - min_x) / ((max_x - min_x) or 1) * (width - pad["l"] - pad["r"])

    def sy(y: float) -> float:
        return height - pad["b"] - (y - min_y) / ((max_y - min_y) or 1) * (height - pad["t"] - pad["b"])

    y_ticks = [min_y + i * (max_y - min_y) / 4 for i in range(5)]
    x_ticks = [min_x + i * (max_x - min_x) / 4 for i in range(5)]

    grid = []
    for tick in y_ticks:
        y = sy(tick)
        grid.append(f"<line x1='{pad['l']}' y1='{y:.1f}' x2='{width-pad['r']}' y2='{y:.1f}' stroke='#e4e8df'/>")
        grid.append(f"<text x='10' y='{y+4:.1f}' font-size='11' fill='#667276'>{esc(fmt(tick, 1))}</text>")
    for tick in x_ticks:
        x = sx(tick)
        date = pd.Timestamp.fromordinal(int(tick)).strftime("%Y-%m")
        grid.append(f"<line x1='{x:.1f}' y1='{pad['t']}' x2='{x:.1f}' y2='{height-pad['b']}' stroke='#f0f2ed'/>")
        grid.append(f"<text x='{x-22:.1f}' y='{height-24}' font-size='11' fill='#667276'>{date}</text>")

    paths = []
    legends = []
    for i, item in enumerate(prepared):
        color = item.get("color", "#27727d")
        points = [(sx(row.x), sy(row.value)) for row in item["data"].itertuples()]
        dash = " stroke-dasharray='5 4'" if item.get("dashed") else ""
        stroke_width = item.get("stroke_width", 2.4)
        paths.append(
            f"<polyline points='{polyline(points)}' fill='none' stroke='{color}' "
            f"stroke-width='{stroke_width}' stroke-linejoin='round' stroke-linecap='round'{dash}/>"
        )
        lx = pad["l"] + (i % 4) * 185
        ly = height - 7 + (i // 4) * 15
        legends.append(
            f"<rect x='{lx}' y='{ly-9}' width='10' height='10' fill='{color}'/>"
            f"<text x='{lx+15}' y='{ly}' font-size='11' fill='#667276'>{esc(item['name'])}</text>"
        )

    return f"""
    <div class="chart-wrap">
      <div class="chart-title">{esc(title)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
        <rect x="0" y="0" width="{width}" height="{height}" fill="white"/>
        {''.join(grid)}
        <line x1="{pad['l']}" y1="{height-pad['b']}" x2="{width-pad['r']}" y2="{height-pad['b']}" stroke="#cfd8cb"/>
        <line x1="{pad['l']}" y1="{pad['t']}" x2="{pad['l']}" y2="{height-pad['b']}" stroke="#cfd8cb"/>
        {''.join(paths)}
        <text x="{width/2-28:.1f}" y="{height-6}" font-size="12" fill="#445">{esc(x_label)}</text>
        <text transform="translate(14 {height/2+40:.1f}) rotate(-90)" font-size="12" fill="#445">{esc(y_label)}</text>
        {''.join(legends)}
      </svg>
    </div>
    """


def bar_chart(
    title: str,
    rows: pd.DataFrame,
    x_col: str,
    y_col: str,
    group_col: str | None,
    y_label: str,
    x_label: str,
    width: int = 920,
    height: int = 340,
) -> str:
    rows = rows.copy()
    rows[y_col] = pd.to_numeric(rows[y_col], errors="coerce")
    rows = rows.dropna(subset=[x_col, y_col])
    if rows.empty:
        return f"<div class='chart-empty'>Sin datos para {esc(title)}</div>"

    pad = {"l": 70, "r": 24, "t": 34, "b": 64}
    y_min = min(0, rows[y_col].min())
    y_max = max(0, rows[y_col].max())
    margin = (y_max - y_min) * 0.12 or 1
    y_min -= margin
    y_max += margin

    cats = sorted(rows[x_col].unique())
    groups = sorted(rows[group_col].unique()) if group_col else [""]
    cluster_w = (width - pad["l"] - pad["r"]) / max(len(cats), 1)
    bar_w = max(3, cluster_w / (len(groups) + 1.6))

    def sy(y: float) -> float:
        return height - pad["b"] - (y - y_min) / ((y_max - y_min) or 1) * (height - pad["t"] - pad["b"])

    zero_y = sy(0)
    items = []
    for ci, cat in enumerate(cats):
        base_x = pad["l"] + ci * cluster_w + cluster_w * 0.14
        for gi, group in enumerate(groups):
            subset = rows[rows[x_col].eq(cat)]
            if group_col:
                subset = subset[subset[group_col].eq(group)]
            if subset.empty:
                continue
            val = float(subset.iloc[0][y_col])
            y = sy(max(val, 0))
            h = abs(sy(val) - zero_y)
            if val < 0:
                y = zero_y
            color = COLORS.get(str(group), ["#31795a", "#bc7a20", "#3f6d9a", "#b24c3d"][gi % 4])
            x = base_x + gi * bar_w
            items.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{h:.1f}' fill='{color}' rx='2'/>")
        label = str(cat).replace("_", " ")
        items.append(f"<text x='{base_x:.1f}' y='{height-33}' font-size='10' fill='#667276'>{esc(label)}</text>")

    y_ticks = [y_min + i * (y_max - y_min) / 4 for i in range(5)]
    grid = []
    for tick in y_ticks:
        y = sy(tick)
        grid.append(f"<line x1='{pad['l']}' y1='{y:.1f}' x2='{width-pad['r']}' y2='{y:.1f}' stroke='#e4e8df'/>")
        grid.append(f"<text x='12' y='{y+4:.1f}' font-size='11' fill='#667276'>{esc(fmt(tick, 2))}</text>")

    legend = ""
    if group_col:
        legend = "".join(
            f"<rect x='{pad['l'] + i*150}' y='{height-12}' width='10' height='10' fill='{COLORS.get(str(g), '#27727d')}'/>"
            f"<text x='{pad['l'] + i*150 + 15}' y='{height-3}' font-size='11' fill='#667276'>{esc(g)}</text>"
            for i, g in enumerate(groups)
        )

    return f"""
    <div class="chart-wrap">
      <div class="chart-title">{esc(title)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">
        <rect x="0" y="0" width="{width}" height="{height}" fill="white"/>
        {''.join(grid)}
        <line x1="{pad['l']}" y1="{zero_y:.1f}" x2="{width-pad['r']}" y2="{zero_y:.1f}" stroke="#9fa99a"/>
        <line x1="{pad['l']}" y1="{pad['t']}" x2="{pad['l']}" y2="{height-pad['b']}" stroke="#cfd8cb"/>
        {''.join(items)}
        <text x="{width/2-42:.1f}" y="{height-18}" font-size="12" fill="#445">{esc(x_label)}</text>
        <text transform="translate(14 {height/2+42:.1f}) rotate(-90)" font-size="12" fill="#445">{esc(y_label)}</text>
        {legend}
      </svg>
    </div>
    """


def table_html(df: pd.DataFrame, columns: list[tuple[str, str]], max_rows: int = 12) -> str:
    if df.empty:
        return "<div class='empty'>Sin datos</div>"
    rows = df.head(max_rows)
    head = "".join(f"<th>{esc(label)}</th>" for _, label in columns)
    body = []
    for _, row in rows.iterrows():
        cells = []
        for col, _ in columns:
            val = row.get(col, "")
            if isinstance(val, float):
                val = fmt(val, 4)
            cells.append(f"<td>{esc(val)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def monthly_summary_tables() -> str:
    monthly_forecasts = read_csv("monthly_forecasts.csv")
    monthly_metrics = read_csv("monthly_backtest_metrics.csv")

    if not monthly_forecasts.empty:
        base = monthly_forecasts[monthly_forecasts["scenario"].eq("base")].copy()
        base["target"] = base["target"].replace(
            {
                "cepea_ethanol_mt_net_m3": "CEPEA neto R$/m3",
                "anp_ethanol_mt_net_l": "ANP neto R$/litro",
            }
        )
        forecast_pivot = base.pivot(index="month", columns="target", values="forecast").reset_index()
    else:
        forecast_pivot = pd.DataFrame()

    if not monthly_metrics.empty:
        metric_rows = monthly_metrics[monthly_metrics["model"].eq("D_plus_usd_brl")].copy()
        metric_rows["target"] = metric_rows["target"].replace(
            {
                "cepea_ethanol_mt_net_m3": "CEPEA neto",
                "anp_ethanol_mt_net_l": "ANP neto",
            }
        )
        metric_rows = metric_rows.sort_values(["target", "horizon_weeks"])
    else:
        metric_rows = pd.DataFrame()

    forecast_cols = [("month", "Mes")] + [(c, c) for c in forecast_pivot.columns if c != "month"]
    return f"""
    <section class="band">
      <div class="grid">
        <div class="panel span-7">
          <h3>Proyeccion mensual base</h3>
          {table_html(forecast_pivot, forecast_cols, max_rows=14)}
        </div>
        <div class="panel span-5">
          <h3>Error mensual del modelo completo</h3>
          {table_html(metric_rows, [
              ("target", "Target"),
              ("horizon_weeks", "Horizonte"),
              ("mae", "MAE"),
              ("rmse", "RMSE"),
              ("smape", "sMAPE"),
          ], max_rows=12)}
        </div>
      </div>
    </section>
    """


def indexed_variables_chart(dataset: pd.DataFrame) -> str:
    series = []
    labels = {
        "anp_gasoline_mt_net_l": "Gasolina MT neta",
        "brent_usd_bbl": "Brent",
        "usd_brl": "USD/BRL",
    }
    for col, label in labels.items():
        frame = dataset[["date", col]].dropna().rename(columns={col: "value"})
        if frame.empty:
            continue
        base = frame["value"].iloc[0]
        if not base:
            continue
        frame["value"] = frame["value"] / base * 100
        series.append({"name": label, "data": frame, "color": COLORS[col]})
    return line_chart(
        "Variables explicativas historicas normalizadas",
        series,
        y_label="Indice base 100",
        x_label="Fecha",
    )


def actual_forecast_chart(dataset: pd.DataFrame, forecasts: pd.DataFrame, target: str) -> str:
    meta = TARGET_META[target]
    actual = dataset[["date", target]].dropna().rename(columns={target: "value"})
    series = [{"name": "Historico observado", "data": actual, "color": COLORS["actual"], "stroke_width": 2.8}]
    for scenario, color in [
        ("base", COLORS["base"]),
        ("upside_macro", COLORS["upside_macro"]),
        ("downside_macro", COLORS["downside_macro"]),
    ]:
        frame = forecasts[(forecasts["target"].eq(target)) & (forecasts["scenario"].eq(scenario))]
        if not frame.empty:
            frame = frame[["date", "forecast"]].rename(columns={"forecast": "value"})
            series.append({"name": f"Proyeccion {scenario}", "data": frame, "color": color, "dashed": True})
    return line_chart(
        f"{meta['label']}: serie historica y proyectada",
        series,
        y_label=f"Precio ({meta['unit']})",
        x_label="Fecha",
    )


def correlation_chart(correlations: pd.DataFrame, target: str) -> str:
    rows = correlations[correlations["target"].eq(target)].copy()
    rows["variable"] = rows["variable"].replace(
        {
            "anp_gasoline_mt_l": "Gasolina MT",
            "anp_gasoline_mt_net_l": "Gasolina MT neta",
            "brent_usd_bbl": "Brent",
            "usd_brl": "USD/BRL",
        }
    )
    return bar_chart(
        f"{TARGET_META[target]['label']}: correlacion historica por rezago",
        rows,
        x_col="lag_weeks",
        y_col="correlation",
        group_col="variable",
        y_label="Correlacion",
        x_label="Rezago en semanas",
    )


def mae_chart(backtest: pd.DataFrame, target: str) -> str:
    rows = (
        backtest[backtest["target"].eq(target)]
        .sort_values(["horizon_weeks", "mae"])
        .groupby("horizon_weeks", as_index=False)
        .first()
    )
    rows["model"] = rows["model"].str.replace("_", " ")
    return bar_chart(
        f"{TARGET_META[target]['label']}: menor MAE por horizonte",
        rows,
        x_col="horizon_weeks",
        y_col="mae",
        group_col=None,
        y_label=f"MAE ({TARGET_META[target]['unit']})",
        x_label="Horizonte en semanas",
    )


def build_html() -> str:
    dataset = read_csv("integrated_dataset.csv")
    backtest = read_csv("backtest_metrics.csv")
    utility = read_csv("variable_utility.csv")
    forecasts = read_csv("forecasts.csv")
    correlations = read_csv("correlations.csv")

    dataset_start = dataset["date"].min().strftime("%Y-%m-%d") if not dataset.empty else "n/a"
    dataset_end = dataset["date"].max().strftime("%Y-%m-%d") if not dataset.empty else "n/a"
    target_sections = []
    for target in TARGET_META:
        if target in dataset and dataset[target].notna().sum() >= 20:
            utility_target = utility[utility["target"].eq(target)].copy()
            utility_target = utility_target.sort_values(["horizon_weeks", "added_block"])
            target_sections.append(
                f"""
                <section class="band">
                  <div class="grid">
                    <div class="panel span-12">{actual_forecast_chart(dataset, forecasts, target)}</div>
                    <div class="panel span-12">{correlation_chart(correlations, target)}</div>
                    <div class="panel span-5">{mae_chart(backtest, target)}</div>
                    <div class="panel span-7">
                      <h3>Utilidad incremental de variables: {esc(TARGET_META[target]['label'])}</h3>
                      {table_html(utility_target, [
                          ("horizon_weeks", "Horizonte"),
                          ("added_block", "Bloque agregado"),
                          ("mae_delta_vs_previous", "Delta MAE"),
                          ("rmse_delta_vs_previous", "Delta RMSE"),
                          ("helps_mae", "Mejora MAE"),
                      ], max_rows=16)}
                    </div>
                  </div>
                </section>
                """
            )

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Etanol MT Forecast Dashboard</title>
  <style>
    :root {{
      --bg: #f5f7f2;
      --panel: #ffffff;
      --ink: #1f2a2e;
      --muted: #667276;
      --line: #d8ded2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, Segoe UI, Arial, sans-serif;
      line-height: 1.35;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 22px 28px 16px;
    }}
    main {{
      max-width: 1460px;
      margin: 0 auto;
      padding: 18px 28px 32px;
    }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 8px 0 12px; }}
    h3 {{ font-size: 15px; margin: 0 0 10px; }}
    .sub {{ color: var(--muted); font-size: 13px; margin-top: 5px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 14px;
    }}
    .band {{ margin-top: 16px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    .span-3 {{ grid-column: span 3; }}
    .span-5 {{ grid-column: span 5; }}
    .span-7 {{ grid-column: span 7; }}
    .span-12 {{ grid-column: span 12; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    .kpi-value {{ font-size: 25px; font-weight: 750; margin-top: 5px; }}
    .chart-title {{ font-weight: 750; font-size: 15px; margin: 0 0 6px; }}
    svg {{ width: 100%; height: auto; display: block; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .path {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
    .chart-empty, .empty {{ color: var(--muted); padding: 18px; }}
    @media (max-width: 980px) {{
      .span-3, .span-5, .span-7 {{ grid-column: span 12; }}
      header, main {{ padding-left: 16px; padding-right: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Etanol hidratado en Mato Grosso: historico, correlaciones y proyeccion</h1>
    <div class="sub">Ventana de referencia: 5 anos. Periodo integrado: {esc(dataset_start)} a {esc(dataset_end)}.</div>
  </header>
  <main>
    <section class="grid">
      <div class="panel span-3"><div class="kpi-label">CEPEA neto obs.</div><div class="kpi-value">{int(dataset.get('cepea_ethanol_mt_net_m3', pd.Series(dtype=float)).notna().sum())}</div><div class="sub">historico semanal</div></div>
      <div class="panel span-3"><div class="kpi-label">ANP neto obs.</div><div class="kpi-value">{int(dataset.get('anp_ethanol_mt_net_l', pd.Series(dtype=float)).notna().sum())}</div><div class="sub">historico semanal</div></div>
      <div class="panel span-3"><div class="kpi-label">Backtests</div><div class="kpi-value">{len(backtest)}</div><div class="sub">modelos evaluados</div></div>
      <div class="panel span-3"><div class="kpi-label">Forecasts</div><div class="kpi-value">{len(forecasts)}</div><div class="sub">filas proyectadas</div></div>
      <div class="panel span-12">{indexed_variables_chart(dataset)}</div>
    </section>
    {monthly_summary_tables()}
    {''.join(target_sections)}
    <section class="band">
      <div class="panel">
        <h3>Carpetas del proyecto</h3>
        <table>
          <tbody>
            <tr><th>Workspace</th><td class="path">{esc(ROOT.resolve())}</td></tr>
            <tr><th>Datos y resultados</th><td class="path">{esc(OUTPUTS.resolve())}</td></tr>
            <tr><th>Dashboard</th><td class="path">{esc(DASHBOARD_HTML.resolve())}</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    DASHBOARD_DIR.mkdir(exist_ok=True)
    DASHBOARD_HTML.write_text(build_html(), encoding="utf-8")
    print(DASHBOARD_HTML.resolve())


if __name__ == "__main__":
    main()
