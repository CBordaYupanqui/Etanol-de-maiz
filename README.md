# Ethanol Hidratado MT Forecast

Proyecto simple para proyectar 52 semanas de etanol hidratado en Mato Grosso y cuantificar si Brent y USD/BRL ayudan.

## Que incluye

- `ethanol_mt_forecast.ipynb`: notebook reproducible.
- `src/ethanol_mt_model.py`: descarga datos, arma features, entrena Ridge con `numpy`, hace backtesting y forecast.
- `outputs/`: carpeta esperada para resultados CSV generados por el notebook o CLI.

## Fuentes

- CEPEA: indicador semanal de etanol hidratado MT.
- ANP: precios de revenda de etanol hidratado y gasolina C en MT.
- EIA: Brent semanal.
- BCB/SGS: USD/BRL PTAX, serie 1.

## Como correr

Con el Python bundled de Codex en este equipo:

```powershell
& 'C:\Users\cborda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' src\ethanol_mt_model.py --years-back 5
& 'C:\Users\cborda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' src\build_dashboard.py
& 'C:\Users\cborda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' src\build_interactive_dashboard.py
```

O abre `ethanol_mt_forecast.ipynb` y ejecuta las celdas de arriba hacia abajo.

## CEPEA historico y precios netos

El pipeline descarga la serie historica CEPEA del enlace oficial de `Série de preços` del indicador hidratado MT (`id=76`) y toma una ventana de 5 anos por defecto. Si prefieres usar un archivo propio, agrega un CSV historico en `data/cepea_mt_historico.csv` con:

```csv
date,cepea_ethanol_mt_m3
2024-01-05,3500.00
```

Luego en el notebook define:

```python
CEPEA_CSV = 'data/cepea_mt_historico.csv'
```

Sin ese archivo, el pipeline saltara CEPEA si no hay historia suficiente y seguira con ANP.

Los modelos usan precios netos estimados por defecto:

- `cepea_ethanol_mt_net_m3`
- `anp_ethanol_mt_net_l`
- `anp_gasoline_mt_net_l`

Los ajustes de ICMS, PIS/Cofins, flete y margen estan en `config/net_price_adjustments.csv`. Flete y margen quedan en cero porque no vienen observados en CEPEA/ANP; si tienes esos valores, edita ese CSV y vuelve a correr el pipeline.

## Resultados

El pipeline genera:

- `outputs/integrated_dataset.csv`: dataset semanal integrado de 5 anos.
- `outputs/cepea_historical_5y.csv`: serie historica CEPEA usada por el modelo.
- `outputs/historical_drivers_5y.csv`: ANP, gasolina, Brent y USD/BRL historicos.
- `outputs/net_price_adjustments_used.csv`: tabla de ajustes usada para convertir bruto a neto estimado.
- `outputs/backtest_metrics.csv`: MAE, RMSE, sMAPE y acierto direccional.
- `outputs/correlations.csv`: correlaciones con rezagos de gasolina, Brent y USD/BRL.
- `outputs/variable_utility.csv`: si gasolina, Brent y USD/BRL reducen error frente al bloque anterior.
- `outputs/forecasts.csv`: forecast base, alcista y bajista por 52 semanas.
- `dashboard/model_dashboard.html`: dashboard con historicos, proyecciones y correlaciones con ejes rotulados.
- `dashboard/interactive_model_dashboard.html`: dashboard interactivo con inputs manuales de Brent, USD/BRL y gasolina neta.

## Actualizacion diaria en GitHub

El repo incluye `.github/workflows/daily-update.yml`. Cuando el proyecto este publicado en GitHub, la accion corre diariamente y tambien manualmente desde `Actions > Daily model update`.

La accion:

- instala dependencias,
- actualiza datos y forecasts,
- regenera dashboards,
- commitea cambios en `outputs/` y `dashboard/`.

Por defecto no versionamos `data/cache/` porque es cache crudo descargable. Si se necesita auditoria completa de fuentes crudas, conviene guardarlas en un bucket/artefacto separado o cambiar `.gitignore`.

## Interpretacion esperada

Brent y USD/BRL no se asumen utiles por definicion. El notebook los obliga a competir contra un modelo base con rezagos y estacionalidad. Si no reducen MAE/RMSE en backtesting, quedan como variables monitoreadas, no como drivers centrales.
