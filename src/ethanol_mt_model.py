from __future__ import annotations

import argparse
import io
import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


CEPEA_MT_URL = "https://cepea.org.br/br/indicador/etanol-semanal-mt.aspx"
CEPEA_MT_SERIES_URL = "https://cepea.org.br/br/indicador/series/etanol-semanal-mt.aspx?id=76"
ANP_URL = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "serie-historica-de-precos-de-combustiveis"
)
EIA_BRENT_WEEKLY_URL = "https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?f=w&n=pet&s=rbrte"
BCB_USD_BRL_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?"
    "formato=json&dataInicial={start}&dataFinal={end}"
)

GROSS_PRICE_COLUMNS = ["cepea_ethanol_mt_m3", "anp_ethanol_mt_l", "anp_gasoline_mt_l"]
TARGETS = ["cepea_ethanol_mt_net_m3", "anp_ethanol_mt_net_l"]
EXOG_COLUMNS = ["anp_gasoline_mt_net_l", "brent_usd_bbl", "usd_brl"]
PARITY_COLUMNS = ["anp_parity_gross", "anp_parity_net"]
GASOLINE_EST_COL = "anp_gasoline_mt_net_l_est"
LAGS = [1, 2, 4, 8, 52]
HORIZONS = [4, 12, 26, 52]
DEFAULT_NET_ADJUSTMENTS = Path(__file__).resolve().parents[1] / "config" / "net_price_adjustments.csv"


def _download(url: str, cache_path: Path | None = None, retries: int = 3, timeout: int = 120) -> bytes:
    if cache_path is not None and cache_path.exists():
        return cache_path.read_bytes()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
            break
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                raise
            wait_seconds = min(5 * attempt, 15)
            print(f"Download failed for {url} ({exc}). Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)
    else:
        raise RuntimeError(f"Download failed for {url}: {last_error}")
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    return data


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text


def _to_float(value) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip().replace("\xa0", "")
    if not text:
        return np.nan
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def _week_end(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce", dayfirst=True)
    offsets = (4 - dates.dt.weekday) % 7
    offsets = offsets.where(dates.notna())
    return dates + pd.to_timedelta(offsets, unit="D")


def read_cepea_mt(cache_dir: Path) -> pd.DataFrame:
    series_path = cache_dir / "cepea_mt_series.xls"
    try:
        raw = _download(CEPEA_MT_SERIES_URL, series_path)
        book = pd.ExcelFile(
            io.BytesIO(raw),
            engine="xlrd",
            engine_kwargs={"ignore_workbook_corruption": True},
        )
        table = pd.read_excel(book, sheet_name=0, header=None)
        header_row = table.index[
            table.apply(lambda row: row.astype(str).str.contains("Data", case=False, na=False).any(), axis=1)
        ]
        if len(header_row):
            header_idx = int(header_row[0])
            table.columns = table.iloc[header_idx].map(_slug)
            table = table.iloc[header_idx + 1 :].copy()
            date_col = next((c for c in table.columns if c == "data"), None)
            value_col = next((c for c in table.columns if "vista_r" in c), None)
            if date_col and value_col:
                df = table[[date_col, value_col]].rename(
                    columns={date_col: "date", value_col: "cepea_ethanol_mt_m3"}
                )
                df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
                df["cepea_ethanol_mt_m3"] = pd.to_numeric(df["cepea_ethanol_mt_m3"], errors="coerce")
                df = df.dropna().drop_duplicates("date").sort_values("date")
                if not df.empty:
                    return df
    except Exception as exc:
        print(f"CEPEA historical series could not be read ({exc}). Falling back to visible table.")

    try:
        html = _download(CEPEA_MT_URL, cache_dir / "cepea_mt.html").decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"CEPEA public page could not be downloaded ({exc}). Use --cepea-csv for historical CEPEA.")
        return pd.DataFrame(columns=["date", "cepea_ethanol_mt_m3"])
    rows: list[dict[str, object]] = []

    # CEPEA renders a compact visible table. This regex intentionally uses the
    # interval end date as the weekly timestamp.
    pattern = re.compile(
        r"(?P<start>\d{2})\s*-\s*(?P<end>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})"
        r"\s*(?P<brl>\d{1,3}(?:\.\d{3})*,\d{2})",
        flags=re.S,
    )
    for match in pattern.finditer(re.sub(r"<[^>]+>", " ", html)):
        date = pd.Timestamp(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("end")),
        )
        rows.append({"date": date, "cepea_ethanol_mt_m3": _to_float(match.group("brl"))})

    if not rows:
        try:
            tables = pd.read_html(io.StringIO(html))
        except ValueError:
            tables = []
        for table in tables:
            if table.shape[1] < 2:
                continue
            table = table.copy()
            table.columns = [_slug(c) for c in table.columns]
            date_col = table.columns[0]
            value_col = table.columns[1]
            for _, row in table.iterrows():
                text = str(row[date_col])
                found = re.search(r"(\d{2})\s*-\s*(\d{2})/(\d{2})/(\d{4})", text)
                if found:
                    rows.append(
                        {
                            "date": pd.Timestamp(int(found.group(4)), int(found.group(3)), int(found.group(2))),
                            "cepea_ethanol_mt_m3": _to_float(row[value_col]),
                        }
                    )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "cepea_ethanol_mt_m3"])
    return df.dropna().drop_duplicates("date").sort_values("date")


def _discover_anp_links(cache_dir: Path, start_year: int) -> list[str]:
    html = _download(ANP_URL, cache_dir / "anp_index.html").decode("utf-8", errors="ignore")
    all_links = re.findall(r'href="([^"]+)"', html)
    all_years: list[int] = []
    for link in all_links:
        all_years.extend(int(y) for y in re.findall(r"20\d{2}", urllib.parse.unquote(link)))
    current_year = max(all_years) if all_years else pd.Timestamp.today().year

    low = html.lower()
    marker = "etanol hidratado + gasolina c"
    sections = []
    for found in re.finditer(re.escape(marker), low):
        start = found.start()
        end = low.find("<h3", start + len(marker))
        sections.append(html[start:end] if end > start else html[start:])
    if not sections:
        sections = [html]
    links = []
    for section in sections:
        links.extend(re.findall(r'href="([^"]+)"', section))
    for link in all_links:
        label = urllib.parse.unquote(link).lower()
        if (".zip" in label or ".csv" in label) and "/dsas/ca/" in label:
            links.append(link)

    full_links: list[str] = []
    for link in links:
        unescaped = link.replace("&amp;", "&")
        label = urllib.parse.unquote(unescaped).lower()
        is_monthly_gasoline_ethanol = "gasolina" in label and "etanol" in label and ".csv" in label
        is_semester_auto = (".zip" in label or ".csv" in label) and "/dsas/ca/" in label
        if not (is_monthly_gasoline_ethanol or is_semester_auto):
            continue

        years = [int(y) for y in re.findall(r"20\d{2}", label)]
        if years and max(years) < start_year:
            continue
        if is_monthly_gasoline_ethanol and years and max(years) < current_year:
            continue
        full_links.append(urllib.parse.urljoin(ANP_URL, unescaped))
    return sorted(set(full_links))


def _read_anp_csv_bytes(data: bytes) -> pd.DataFrame:
    for encoding in ["utf-8-sig", "latin1"]:
        try:
            return pd.read_csv(io.BytesIO(data), sep=";", decimal=",", encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.BytesIO(data), sep=";", decimal=",", encoding="latin1", low_memory=False)


def _iter_anp_tables(cache_dir: Path, start_year: int) -> Iterable[pd.DataFrame]:
    links = _discover_anp_links(cache_dir, start_year)
    for idx, link in enumerate(links):
        years = [int(y) for y in re.findall(r"20\d{2}", link)]
        if years and max(years) < start_year:
            continue
        path_parts = [part for part in urllib.parse.urlparse(link).path.split("/") if part]
        name_source = "_".join(path_parts[-3:]) if path_parts else f"anp_{idx}"
        name = _slug(name_source)[:120]
        try:
            raw = _download(link, cache_dir / "anp_v2" / name)
            if link.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for member in zf.namelist():
                        if member.lower().endswith(".csv"):
                            yield _read_anp_csv_bytes(zf.read(member))
            elif link.lower().endswith(".csv"):
                yield _read_anp_csv_bytes(raw)
        except Exception as exc:
            print(f"ANP file skipped after download/read failure: {link} ({exc})")


def read_anp_mt(cache_dir: Path, start_year: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for table in _iter_anp_tables(cache_dir, start_year):
        table = table.copy()
        table.columns = [_slug(c) for c in table.columns]
        cols = set(table.columns)
        if not {"produto", "valor_de_venda"}.issubset(cols):
            continue

        state_col = next((c for c in ["estado_sigla", "uf", "estado"] if c in cols), None)
        date_col = next((c for c in ["data_da_coleta", "data_inicial", "data"] if c in cols), None)
        if state_col is None or date_col is None:
            continue

        mt = table[table[state_col].astype(str).str.upper().eq("MT")].copy()
        if mt.empty:
            continue
        mt["produto_norm"] = mt["produto"].map(_slug)
        mt = mt[mt["produto_norm"].str.contains("etanol|gasolina", na=False)].copy()
        if mt.empty:
            continue

        mt["date"] = _week_end(mt[date_col])
        mt["valor_de_venda"] = pd.to_numeric(mt["valor_de_venda"], errors="coerce")
        mt["series"] = np.where(
            mt["produto_norm"].str.contains("etanol", na=False),
            "anp_ethanol_mt_l",
            "anp_gasoline_mt_l",
        )
        frames.append(
            mt.groupby(["date", "series"], as_index=False)["valor_de_venda"].mean()
        )

    if not frames:
        return pd.DataFrame(columns=["date", "anp_ethanol_mt_l", "anp_gasoline_mt_l"])

    data = pd.concat(frames, ignore_index=True)
    data = data.groupby(["date", "series"], as_index=False)["valor_de_venda"].mean()
    return data.pivot(index="date", columns="series", values="valor_de_venda").reset_index()


def read_brent_weekly(cache_dir: Path) -> pd.DataFrame:
    html = _download(EIA_BRENT_WEEKLY_URL, cache_dir / "eia_brent_weekly.html").decode(
        "utf-8", errors="ignore"
    )
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        tables = []
    if not tables:
        return pd.DataFrame(columns=["date", "brent_usd_bbl"])

    table = max(tables, key=len)
    rows: list[dict[str, object]] = []
    current_year: int | None = None
    current_month: int | None = None
    month_map = {m.lower(): i for i, m in enumerate(pd.date_range("2000-01-01", periods=12, freq="MS").strftime("%b"), 1)}

    for _, row in table.iterrows():
        values = [str(v).strip() for v in row.tolist() if not pd.isna(v)]
        if not values:
            continue
        first = values[0]
        ym = re.search(r"(19\d{2}|20\d{2})-([A-Za-z]{3})", first)
        if ym:
            current_year = int(ym.group(1))
            current_month = month_map.get(ym.group(2).lower())
            values = values[1:]
        if current_year is None or current_month is None:
            continue
        for date_txt, value_txt in zip(values[0::2], values[1::2]):
            if not re.match(r"\d{2}/\d{2}", date_txt):
                continue
            value = pd.to_numeric(value_txt, errors="coerce")
            if pd.isna(value):
                continue
            month, day = map(int, date_txt.split("/"))
            year = current_year
            if month == 1 and current_month == 12:
                year += 1
            rows.append({"date": pd.Timestamp(year, month, day), "brent_usd_bbl": float(value)})

    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date")


def read_usd_brl(cache_dir: Path, start: str, end: str) -> pd.DataFrame:
    url = BCB_USD_BRL_URL.format(start=start, end=end)
    raw = _download(url, cache_dir / f"bcb_usd_brl_{_slug(start)}_{_slug(end)}.json")
    records = json.loads(raw.decode("utf-8"))
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["date", "usd_brl"])
    df["date"] = pd.to_datetime(df["data"], dayfirst=True, errors="coerce")
    df["usd_brl"] = df["valor"].map(_to_float)
    df = df.dropna(subset=["date", "usd_brl"])
    df["date"] = _week_end(df["date"])
    return df.groupby("date", as_index=False)["usd_brl"].mean()


def read_net_adjustments(path: Path | None = None) -> pd.DataFrame:
    path = path or DEFAULT_NET_ADJUSTMENTS
    config = pd.read_csv(path)
    config["start_date"] = pd.to_datetime(config["start_date"], errors="coerce")
    config["end_date"] = pd.to_datetime(config["end_date"], errors="coerce")
    for col in ["icms_rate", "pis_cofins_m3", "freight_m3", "margin_m3"]:
        config[col] = pd.to_numeric(config[col], errors="coerce").fillna(0.0)
    return config


def add_net_price_columns(data: pd.DataFrame, adjustments: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    df["icms_rate"] = np.nan
    df["pis_cofins_m3"] = np.nan
    df["freight_m3"] = np.nan
    df["margin_m3"] = np.nan

    for _, rule in adjustments.iterrows():
        mask = df["date"].between(rule["start_date"], rule["end_date"], inclusive="both")
        for col in ["icms_rate", "pis_cofins_m3", "freight_m3", "margin_m3"]:
            df.loc[mask, col] = rule[col]

    df[["icms_rate", "pis_cofins_m3", "freight_m3", "margin_m3"]] = df[
        ["icms_rate", "pis_cofins_m3", "freight_m3", "margin_m3"]
    ].ffill().fillna(0.0)
    fixed_l = (df["pis_cofins_m3"] + df["freight_m3"] + df["margin_m3"]) / 1000.0

    df["cepea_ethanol_mt_net_m3"] = (
        df["cepea_ethanol_mt_m3"] * (1 - df["icms_rate"])
        - df["pis_cofins_m3"]
        - df["freight_m3"]
        - df["margin_m3"]
    )
    df["anp_ethanol_mt_net_l"] = df["anp_ethanol_mt_l"] * (1 - df["icms_rate"]) - fixed_l
    df["anp_gasoline_mt_net_l"] = df["anp_gasoline_mt_l"] * (1 - df["icms_rate"]) - fixed_l

    for col in ["cepea_ethanol_mt_net_m3", "anp_ethanol_mt_net_l", "anp_gasoline_mt_net_l"]:
        df[col] = df[col].clip(lower=0)
    df["anp_parity_gross"] = df["anp_ethanol_mt_l"] / df["anp_gasoline_mt_l"].replace(0, np.nan)
    df["anp_parity_net"] = df["anp_ethanol_mt_net_l"] / df["anp_gasoline_mt_net_l"].replace(0, np.nan)
    return df


def load_dataset(
    cache_dir: Path,
    start_year: int = 2021,
    start_date: str | pd.Timestamp | None = None,
    local_cepea_csv: Path | None = None,
    net_adjustments_csv: Path | None = None,
) -> pd.DataFrame:
    frames = []
    if local_cepea_csv is not None and local_cepea_csv.exists():
        cepea = pd.read_csv(local_cepea_csv)
        cepea.columns = [_slug(c) for c in cepea.columns]
        date_col = "date" if "date" in cepea.columns else cepea.columns[0]
        value_col = "cepea_ethanol_mt_m3" if "cepea_ethanol_mt_m3" in cepea.columns else cepea.columns[1]
        cepea = cepea[[date_col, value_col]].rename(columns={date_col: "date", value_col: "cepea_ethanol_mt_m3"})
        cepea["date"] = pd.to_datetime(cepea["date"], errors="coerce")
        cepea["cepea_ethanol_mt_m3"] = cepea["cepea_ethanol_mt_m3"].map(_to_float)
    else:
        cepea = read_cepea_mt(cache_dir)
    frames.append(cepea)

    anp = read_anp_mt(cache_dir, start_year=start_year)
    frames.append(anp)

    brent = read_brent_weekly(cache_dir)
    frames.append(brent)

    today = pd.Timestamp.today().normalize()
    usd = read_usd_brl(cache_dir, f"01/01/{start_year}", today.strftime("%d/%m/%Y"))
    frames.append(usd)

    base = None
    for frame in frames:
        if frame.empty:
            continue
        frame = frame.copy()
        frame["date"] = _week_end(frame["date"])
        frame = frame.groupby("date", as_index=False).mean(numeric_only=True)
        base = frame if base is None else base.merge(frame, on="date", how="outer")

    if base is None:
        return pd.DataFrame(columns=["date", *TARGETS, *EXOG_COLUMNS])

    base = base.sort_values("date").reset_index(drop=True)
    if start_date is None:
        start_date = pd.Timestamp.today().normalize() - pd.DateOffset(years=5)
    start_date = pd.Timestamp(start_date)
    base = base[base["date"].ge(start_date)]
    for col in GROSS_PRICE_COLUMNS + ["brent_usd_bbl", "usd_brl"]:
        if col not in base:
            base[col] = np.nan
    base[["anp_gasoline_mt_l", "brent_usd_bbl", "usd_brl"]] = base[
        ["anp_gasoline_mt_l", "brent_usd_bbl", "usd_brl"]
    ].ffill()
    base = add_net_price_columns(base, read_net_adjustments(net_adjustments_csv))
    return base[
        [
            "date",
            *GROSS_PRICE_COLUMNS,
            "cepea_ethanol_mt_net_m3",
            "anp_ethanol_mt_net_l",
            "anp_gasoline_mt_net_l",
            *PARITY_COLUMNS,
            "brent_usd_bbl",
            "usd_brl",
            "icms_rate",
            "pis_cofins_m3",
            "freight_m3",
            "margin_m3",
        ]
    ]


def add_features(data: pd.DataFrame, target: str, horizon: int = 0) -> tuple[pd.DataFrame, list[str], str]:
    df = data.sort_values("date").copy()
    for col in [target, *EXOG_COLUMNS]:
        if col not in df:
            df[col] = np.nan
    for lag in LAGS:
        df[f"{target}_lag_{lag}"] = df[target].shift(lag)
    df[f"{target}_ma_4"] = df[target].shift(1).rolling(4).mean()
    df[f"{target}_ma_12"] = df[target].shift(1).rolling(12).mean()
    for col in EXOG_COLUMNS:
        df[f"{col}_lag_1"] = df[col].shift(1)
        df[f"{col}_chg_4"] = df[col].pct_change(4).shift(1)

    iso = df["date"].dt.isocalendar()
    week = iso.week.astype(float)
    df["week_sin"] = np.sin(2 * np.pi * week / 52.0)
    df["week_cos"] = np.cos(2 * np.pi * week / 52.0)
    month = df["date"].dt.month.astype(float)
    df["month_sin"] = np.sin(2 * np.pi * month / 12.0)
    df["month_cos"] = np.cos(2 * np.pi * month / 12.0)
    df["safra_flag"] = df["date"].dt.month.between(4, 11).astype(int)

    y_col = f"{target}_h{horizon}" if horizon else target
    if horizon:
        df[y_col] = df[target].shift(-horizon)

    base_features = (
        [f"{target}_lag_{lag}" for lag in LAGS]
        + [f"{target}_ma_4", f"{target}_ma_12", "week_sin", "week_cos", "month_sin", "month_cos", "safra_flag"]
    )
    exog_features = [f"{col}_lag_1" for col in EXOG_COLUMNS] + [f"{col}_chg_4" for col in EXOG_COLUMNS]
    features = base_features + exog_features
    return df, features, y_col


def add_gasoline_model_features(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
    df = data.sort_values("date").copy()
    for col in ["anp_gasoline_mt_net_l", "brent_usd_bbl", "usd_brl"]:
        if col not in df:
            df[col] = np.nan
    df[["anp_gasoline_mt_net_l", "brent_usd_bbl", "usd_brl"]] = df[
        ["anp_gasoline_mt_net_l", "brent_usd_bbl", "usd_brl"]
    ].ffill()
    df["brent_brl_lag_1"] = (df["brent_usd_bbl"] * df["usd_brl"]).shift(1)
    df["brent_usd_bbl_lag_1"] = df["brent_usd_bbl"].shift(1)
    df["usd_brl_lag_1"] = df["usd_brl"].shift(1)
    df["brent_usd_bbl_chg_4"] = df["brent_usd_bbl"].pct_change(4).shift(1)
    df["usd_brl_chg_4"] = df["usd_brl"].pct_change(4).shift(1)
    for lag in [1, 4, 12]:
        df[f"anp_gasoline_mt_net_l_lag_{lag}"] = df["anp_gasoline_mt_net_l"].shift(lag)
    df["anp_gasoline_mt_net_l_ma_4"] = df["anp_gasoline_mt_net_l"].shift(1).rolling(4).mean()
    iso = df["date"].dt.isocalendar()
    week = iso.week.astype(float)
    df["week_sin"] = np.sin(2 * np.pi * week / 52.0)
    df["week_cos"] = np.cos(2 * np.pi * week / 52.0)
    month = df["date"].dt.month.astype(float)
    df["month_sin"] = np.sin(2 * np.pi * month / 12.0)
    df["month_cos"] = np.cos(2 * np.pi * month / 12.0)
    features = [
        "brent_brl_lag_1",
        "brent_usd_bbl_lag_1",
        "usd_brl_lag_1",
        "brent_usd_bbl_chg_4",
        "usd_brl_chg_4",
        "anp_gasoline_mt_net_l_lag_1",
        "anp_gasoline_mt_net_l_lag_4",
        "anp_gasoline_mt_net_l_lag_12",
        "anp_gasoline_mt_net_l_ma_4",
        "week_sin",
        "week_cos",
        "month_sin",
        "month_cos",
    ]
    return df, features, "anp_gasoline_mt_net_l"


def add_gasoline_estimates(data: pd.DataFrame) -> pd.DataFrame:
    df = data.sort_values("date").copy()
    featured, features, y_col = add_gasoline_model_features(df)
    estimates = pd.Series(np.nan, index=featured.index, dtype=float)
    try:
        model = fit_ridge(featured, features, y_col, alpha=5.0)
        valid = featured.dropna(subset=features).index
        estimates.loc[valid] = np.maximum(model.predict(featured.loc[valid]), 0.0)
    except ValueError:
        pass
    df[GASOLINE_EST_COL] = estimates.values
    return df


@dataclass
class RidgeModel:
    columns: list[str]
    x_mean: np.ndarray
    x_std: np.ndarray
    coef: np.ndarray

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        x_arr = x[self.columns].to_numpy(dtype=float)
        x_scaled = (x_arr - self.x_mean) / self.x_std
        design = np.c_[np.ones(len(x_scaled)), x_scaled]
        return design @ self.coef


def fit_ridge(train: pd.DataFrame, features: list[str], y_col: str, alpha: float = 10.0) -> RidgeModel:
    clean = train.dropna(subset=features + [y_col]).copy()
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna(subset=features + [y_col])
    if len(clean) < max(20, len(features) + 5):
        raise ValueError(f"Not enough observations for {y_col}: {len(clean)}")
    x = clean[features].to_numpy(dtype=float)
    y = clean[y_col].to_numpy(dtype=float)
    x_mean = x.mean(axis=0)
    x_std = x.std(axis=0)
    x_std[x_std == 0] = 1.0
    x_scaled = (x - x_mean) / x_std
    design = np.c_[np.ones(len(x_scaled)), x_scaled]
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    try:
        coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    except np.linalg.LinAlgError:
        coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    return RidgeModel(features, x_mean, x_std, coef)


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = ~np.isnan(y_true) & ~np.isnan(y_pred)
    y_true = y_true[mask]
    y_pred = y_pred[mask]
    if len(y_true) == 0:
        return {"n": 0, "mae": np.nan, "rmse": np.nan, "smape": np.nan, "directional_accuracy": np.nan}
    diff = y_pred - y_true
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    smape = np.nanmean(np.where(denom == 0, np.nan, np.abs(diff) / denom))
    direction = np.sign(np.diff(y_true)) == np.sign(np.diff(y_pred)) if len(y_true) > 1 else []
    return {
        "n": int(len(y_true)),
        "mae": float(np.mean(np.abs(diff))),
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "smape": float(smape),
        "directional_accuracy": float(np.mean(direction)) if len(direction) else np.nan,
    }


def metric_frame(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    if frame.empty:
        return pd.DataFrame()
    for keys, group in frame.groupby(group_cols):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update(metrics(group["actual"].to_numpy(), group["prediction"].to_numpy()))
        rows.append(row)
    return pd.DataFrame(rows)


def feature_groups(target: str) -> dict[str, list[str]]:
    base = (
        [f"{target}_lag_{lag}" for lag in LAGS]
        + [f"{target}_ma_4", f"{target}_ma_12", "week_sin", "week_cos", "month_sin", "month_cos", "safra_flag"]
    )
    gasoline = ["anp_gasoline_mt_net_l_lag_1", "anp_gasoline_mt_net_l_chg_4"]
    brent = ["brent_usd_bbl_lag_1", "brent_usd_bbl_chg_4"]
    usd = ["usd_brl_lag_1", "usd_brl_chg_4"]
    return {
        "A_target_seasonality": base,
        "B_plus_gasoline": base + gasoline,
        "C_plus_brent": base + gasoline + brent,
        "D_plus_usd_brl": base + gasoline + brent + usd,
    }


def backtest_direct(
    data: pd.DataFrame,
    target: str,
    horizons: list[int] | None = None,
    min_train: int = 90,
) -> pd.DataFrame:
    horizons = horizons or HORIZONS
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        featured, _, y_col = add_features(data, target, horizon=horizon)
        groups = feature_groups(target)
        for model_name, features in groups.items():
            preds = []
            actuals = []
            dates = []
            clean = featured.dropna(subset=features + [y_col]).reset_index(drop=True)
            if len(clean) < min_train + 8:
                continue
            step = max(1, math.ceil((len(clean) - min_train) / 24))
            for split in range(min_train, len(clean), step):
                train = clean.iloc[:split]
                test = clean.iloc[[split]]
                try:
                    model = fit_ridge(train, features, y_col)
                except ValueError:
                    continue
                preds.append(model.predict(test)[0])
                actuals.append(test[y_col].iloc[0])
                dates.append(test["date"].iloc[0])
            row = {
                "target": target,
                "horizon_weeks": horizon,
                "model": model_name,
                **metrics(np.array(actuals), np.array(preds)),
            }
            if dates:
                row["first_test_date"] = min(dates)
                row["last_test_date"] = max(dates)
            rows.append(row)
    return pd.DataFrame(rows)


def backtest_predictions_direct(
    data: pd.DataFrame,
    target: str,
    horizons: list[int] | None = None,
    min_train: int = 90,
) -> pd.DataFrame:
    horizons = horizons or HORIZONS
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        featured, _, y_col = add_features(data, target, horizon=horizon)
        groups = feature_groups(target)
        for model_name, features in groups.items():
            clean = featured.dropna(subset=features + [y_col]).reset_index(drop=True)
            if len(clean) < min_train + 8:
                continue
            step = max(1, math.ceil((len(clean) - min_train) / 24))
            for split in range(min_train, len(clean), step):
                train = clean.iloc[:split]
                test = clean.iloc[[split]]
                try:
                    model = fit_ridge(train, features, y_col)
                except ValueError:
                    continue
                prediction = float(model.predict(test)[0])
                origin_date = test["date"].iloc[0]
                rows.append(
                    {
                        "target": target,
                        "horizon_weeks": horizon,
                        "model": model_name,
                        "origin_date": origin_date,
                        "target_date": origin_date + pd.Timedelta(days=7 * horizon),
                        "actual": float(test[y_col].iloc[0]),
                        "prediction": prediction,
                        "error": prediction - float(test[y_col].iloc[0]),
                        "abs_error": abs(prediction - float(test[y_col].iloc[0])),
                    }
                )
    return pd.DataFrame(rows)


def monthly_outputs(
    dataset: pd.DataFrame,
    forecasts: pd.DataFrame,
    backtest_predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    monthly_history = dataset.copy()
    monthly_history["month"] = pd.to_datetime(monthly_history["date"]).dt.to_period("M").astype(str)
    value_cols = [col for col in monthly_history.columns if col != "date"]
    monthly_history = monthly_history.groupby("month", as_index=False)[value_cols].mean(numeric_only=True)

    monthly_forecasts = forecasts.copy()
    if not monthly_forecasts.empty:
        monthly_forecasts["month"] = pd.to_datetime(monthly_forecasts["date"]).dt.to_period("M").astype(str)
        monthly_forecasts = monthly_forecasts.groupby(
            ["target", "scenario", "month"], as_index=False
        )["forecast"].mean()

    monthly_backtest_predictions = backtest_predictions.copy()
    if not monthly_backtest_predictions.empty:
        monthly_backtest_predictions["month"] = pd.to_datetime(
            monthly_backtest_predictions["target_date"]
        ).dt.to_period("M").astype(str)
        monthly_backtest_predictions = monthly_backtest_predictions.groupby(
            ["target", "horizon_weeks", "model", "month"], as_index=False
        )[["actual", "prediction", "error", "abs_error"]].mean()

    monthly_backtest_metrics = metric_frame(
        monthly_backtest_predictions,
        ["target", "horizon_weeks", "model"],
    )
    return monthly_history, monthly_forecasts, monthly_backtest_predictions, monthly_backtest_metrics


def correlations(data: pd.DataFrame, target: str, max_lag: int = 12) -> pd.DataFrame:
    rows = []
    for variable in EXOG_COLUMNS:
        for lag in range(max_lag + 1):
            frame = pd.DataFrame({"target": data[target], "variable": data[variable].shift(lag)}).dropna()
            corr = frame["target"].corr(frame["variable"]) if len(frame) > 8 else np.nan
            rows.append({"target": target, "variable": variable, "lag_weeks": lag, "correlation": corr})
    return pd.DataFrame(rows)


def _next_row(history: pd.DataFrame, target: str, date: pd.Timestamp) -> pd.DataFrame:
    row = {"date": date}
    for col in TARGETS + EXOG_COLUMNS:
        if col in history:
            row[col] = history[col].iloc[-1]
    temp = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
    featured, features, _ = add_features(temp, target, horizon=0)
    return featured.iloc[[-1]], features


def forecast_recursive(
    data: pd.DataFrame,
    target: str,
    scenario: str,
    weeks: int = 52,
    shock_brent: float = 0.0,
    shock_usd: float = 0.0,
    shock_gasoline: float = 0.0,
) -> pd.DataFrame:
    data = data.sort_values("date").copy()
    data[EXOG_COLUMNS] = data[EXOG_COLUMNS].ffill()
    last_target_date = data.loc[data[target].notna(), "date"].max()
    history = data[data["date"].le(last_target_date)].copy()
    featured, features, y_col = add_features(history, target, horizon=0)
    features = feature_groups(target)["D_plus_usd_brl"]
    model = fit_ridge(featured, features, y_col)
    gas_featured, gas_features, gas_y_col = add_gasoline_model_features(history)
    gas_model = fit_ridge(gas_featured, gas_features, gas_y_col, alpha=5.0)

    last_date = history["date"].max()
    scenario_exog = {
        "brent_usd_bbl": history["brent_usd_bbl"].ffill().iloc[-1] * (1 + shock_brent),
        "usd_brl": history["usd_brl"].ffill().iloc[-1] * (1 + shock_usd),
    }
    outputs = []
    work = history.copy()
    work["brent_usd_bbl"] = work["brent_usd_bbl"].ffill()
    work["usd_brl"] = work["usd_brl"].ffill()
    work["anp_gasoline_mt_net_l"] = work["anp_gasoline_mt_net_l"].ffill()
    for step in range(1, weeks + 1):
        next_date = last_date + pd.Timedelta(days=7 * step)
        gas_seed = {
            "date": next_date,
            "brent_usd_bbl": scenario_exog["brent_usd_bbl"],
            "usd_brl": scenario_exog["usd_brl"],
            "anp_gasoline_mt_net_l": work["anp_gasoline_mt_net_l"].iloc[-1],
        }
        gas_work = pd.concat([work, pd.DataFrame([gas_seed])], ignore_index=True)
        gas_row, _, _ = add_gasoline_model_features(gas_work)
        gas_row = gas_row.iloc[[-1]].copy()
        brent_ref_4 = work["brent_usd_bbl"].iloc[-4] if len(work) >= 4 else work["brent_usd_bbl"].iloc[-1]
        usd_ref_4 = work["usd_brl"].iloc[-4] if len(work) >= 4 else work["usd_brl"].iloc[-1]
        gas_row["brent_usd_bbl_lag_1"] = scenario_exog["brent_usd_bbl"]
        gas_row["usd_brl_lag_1"] = scenario_exog["usd_brl"]
        gas_row["brent_brl_lag_1"] = scenario_exog["brent_usd_bbl"] * scenario_exog["usd_brl"]
        gas_row["brent_usd_bbl_chg_4"] = scenario_exog["brent_usd_bbl"] / brent_ref_4 - 1 if brent_ref_4 else 0.0
        gas_row["usd_brl_chg_4"] = scenario_exog["usd_brl"] / usd_ref_4 - 1 if usd_ref_4 else 0.0
        gasoline_est = max(float(gas_model.predict(gas_row)[0]), 0.0)

        row, _ = _next_row(work, target, next_date)
        row = row.copy()
        row["brent_usd_bbl_lag_1"] = scenario_exog["brent_usd_bbl"]
        row["usd_brl_lag_1"] = scenario_exog["usd_brl"]
        row["anp_gasoline_mt_net_l_lag_1"] = gasoline_est
        pred = max(float(model.predict(row)[0]), 0.0)

        new_record = {col: work[col].iloc[-1] if col in work else np.nan for col in TARGETS + EXOG_COLUMNS}
        new_record["date"] = next_date
        new_record[target] = pred
        new_record["brent_usd_bbl"] = scenario_exog["brent_usd_bbl"]
        new_record["usd_brl"] = scenario_exog["usd_brl"]
        new_record["anp_gasoline_mt_net_l"] = gasoline_est
        work = pd.concat([work, pd.DataFrame([new_record])], ignore_index=True)
        outputs.append(
            {
                "date": next_date,
                "target": target,
                "scenario": scenario,
                "forecast": pred,
                "brent_usd_bbl": scenario_exog["brent_usd_bbl"],
                "usd_brl": scenario_exog["usd_brl"],
                "gasoline_estimated_net_l": gasoline_est,
            }
        )
    return pd.DataFrame(outputs)


def variable_utility(backtest: pd.DataFrame) -> pd.DataFrame:
    if backtest.empty:
        return pd.DataFrame()
    rows = []
    key = ["target", "horizon_weeks"]
    for _, group in backtest.groupby(key):
        metrics_by_model = group.set_index("model")
        for model in ["B_plus_gasoline", "C_plus_brent", "D_plus_usd_brl"]:
            previous = {
                "B_plus_gasoline": "A_target_seasonality",
                "C_plus_brent": "B_plus_gasoline",
                "D_plus_usd_brl": "C_plus_brent",
            }[model]
            if model not in metrics_by_model.index or previous not in metrics_by_model.index:
                continue
            rows.append(
                {
                    "target": group["target"].iloc[0],
                    "horizon_weeks": group["horizon_weeks"].iloc[0],
                    "added_block": model,
                    "mae_delta_vs_previous": metrics_by_model.loc[model, "mae"]
                    - metrics_by_model.loc[previous, "mae"],
                    "rmse_delta_vs_previous": metrics_by_model.loc[model, "rmse"]
                    - metrics_by_model.loc[previous, "rmse"],
                    "helps_mae": bool(metrics_by_model.loc[model, "mae"] < metrics_by_model.loc[previous, "mae"]),
                    "helps_rmse": bool(metrics_by_model.loc[model, "rmse"] < metrics_by_model.loc[previous, "rmse"]),
                }
            )
    return pd.DataFrame(rows)


def run_pipeline(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    start_date = pd.Timestamp.today().normalize() - pd.DateOffset(years=args.years_back)
    dataset = load_dataset(
        cache_dir=cache_dir,
        start_year=start_date.year,
        start_date=start_date,
        local_cepea_csv=Path(args.cepea_csv) if args.cepea_csv else None,
        net_adjustments_csv=Path(args.net_adjustments) if args.net_adjustments else None,
    )
    dataset = add_gasoline_estimates(dataset)
    dataset.to_csv(output_dir / "integrated_dataset.csv", index=False)
    dataset[["date", "cepea_ethanol_mt_m3", "cepea_ethanol_mt_net_m3"]].dropna(
        subset=["cepea_ethanol_mt_net_m3"]
    ).to_csv(
        output_dir / "cepea_historical_5y.csv", index=False
    )
    dataset[
        [
            "date",
            "anp_ethanol_mt_l",
            "anp_ethanol_mt_net_l",
            "anp_gasoline_mt_l",
            "anp_gasoline_mt_net_l",
            GASOLINE_EST_COL,
            *PARITY_COLUMNS,
            "brent_usd_bbl",
            "usd_brl",
            "icms_rate",
            "pis_cofins_m3",
            "freight_m3",
            "margin_m3",
        ]
    ].to_csv(output_dir / "historical_drivers_5y.csv", index=False)
    read_net_adjustments(Path(args.net_adjustments) if args.net_adjustments else None).to_csv(
        output_dir / "net_price_adjustments_used.csv", index=False
    )

    backtests = []
    backtest_predictions = []
    corrs = []
    forecasts = []
    for target in TARGETS:
        valid_target = dataset[target].notna().sum()
        if valid_target < 110:
            print(f"Skipping {target}: only {valid_target} usable observations. Add a local historical CEPEA CSV if needed.")
            continue
        backtests.append(backtest_direct(dataset, target))
        backtest_predictions.append(backtest_predictions_direct(dataset, target))
        corrs.append(correlations(dataset, target))
        scenarios = [
            ("base", 0.0, 0.0, 0.0),
            ("upside_macro", 0.15, 0.08, 0.05),
            ("downside_macro", -0.15, -0.08, -0.05),
        ]
        for scenario, brent, usd, gasoline in scenarios:
            forecasts.append(
                forecast_recursive(dataset, target, scenario, 52, brent, usd, gasoline)
            )

    backtest_df = pd.concat(backtests, ignore_index=True) if backtests else pd.DataFrame()
    backtest_predictions_df = (
        pd.concat(backtest_predictions, ignore_index=True) if backtest_predictions else pd.DataFrame()
    )
    corr_df = pd.concat(corrs, ignore_index=True) if corrs else pd.DataFrame()
    forecast_df = pd.concat(forecasts, ignore_index=True) if forecasts else pd.DataFrame()
    utility_df = variable_utility(backtest_df)
    (
        monthly_history_df,
        monthly_forecast_df,
        monthly_backtest_predictions_df,
        monthly_backtest_metrics_df,
    ) = monthly_outputs(dataset, forecast_df, backtest_predictions_df)

    backtest_df.to_csv(output_dir / "backtest_metrics.csv", index=False)
    backtest_predictions_df.to_csv(output_dir / "backtest_predictions.csv", index=False)
    corr_df.to_csv(output_dir / "correlations.csv", index=False)
    utility_df.to_csv(output_dir / "variable_utility.csv", index=False)
    forecast_df.to_csv(output_dir / "forecasts.csv", index=False)
    monthly_history_df.to_csv(output_dir / "monthly_history.csv", index=False)
    monthly_forecast_df.to_csv(output_dir / "monthly_forecasts.csv", index=False)
    monthly_backtest_predictions_df.to_csv(output_dir / "monthly_backtest_predictions.csv", index=False)
    monthly_backtest_metrics_df.to_csv(output_dir / "monthly_backtest_metrics.csv", index=False)

    print(f"Wrote outputs to {output_dir}")
    print(
        "Rows:",
        {
            "dataset": len(dataset),
            "backtest": len(backtest_df),
            "backtest_predictions": len(backtest_predictions_df),
            "forecast": len(forecast_df),
            "monthly_forecast": len(monthly_forecast_df),
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple ethanol hydrated MT forecast model.")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--years-back", type=int, default=5)
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--cepea-csv", default="", help="Optional local CEPEA historical CSV with date,value columns.")
    parser.add_argument(
        "--net-adjustments",
        default=str(DEFAULT_NET_ADJUSTMENTS),
        help="CSV with tax/freight/margin adjustments used to estimate net prices.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run_pipeline(parse_args())
