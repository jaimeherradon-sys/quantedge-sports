"""Streamlit viewer: factual database rows, NO BET if no documented market edge."""
import os
import json
from pathlib import Path
import pandas as pd
import streamlit as st
from sports_betting_ai.storage import connect

st.set_page_config(page_title="Sports Betting AI · Research", layout="wide")
st.title("SPORTS BETTING AI")
st.caption("Investigación cuantitativa. No ejecuta apuestas ni garantiza rentabilidad.")
path = st.sidebar.text_input("SQLite DB", os.getenv("SBAI_DB", "data/sports.db"))
if not Path(path).exists():
    st.warning("NO BET · No hay datos de proveedores cargados.")
    st.stop()
con = connect(path)
status = pd.read_sql_query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 2000", con)
projections = pd.read_sql_query("SELECT * FROM projections ORDER BY generated_at DESC LIMIT 2000", con)
metrics = pd.read_sql_query("SELECT game_date, COUNT(*) AS player_games FROM player_games GROUP BY game_date ORDER BY game_date", con)
st.subheader("Estado de la investigación")
if status.empty:
    st.warning("NO BET · Sin señales prepartido auditadas.")
else:
    current = status[status["status"] == "CANDIDATE"]
    if current.empty:
        st.warning("NO BET · Ninguna selección supera todos los filtros.")
    else:
        st.metric("Candidatas históricamente generadas", len(current))
    st.dataframe(status.rename(columns={"probability":"p_model","p_low":"uncertainty_lower"}),
                 hide_index=True, use_container_width=True)
if not projections.empty:
    st.subheader("Proyecciones (no equivalen a picks)")
    st.dataframe(projections, hide_index=True, use_container_width=True)
if not metrics.empty:
    st.subheader("Cobertura histórica")
    st.line_chart(metrics.set_index("game_date"))
validation = Path("models/validation.json")
if validation.exists():
    st.subheader("Validación temporal")
    details = json.loads(validation.read_text(encoding="utf-8"))
    for name, entry in details.items():
        st.markdown(f"**{name}** — {entry['selected']} — n={entry['test']['n']}")
        st.write({"brier": entry["test"]["brier"], "log_loss": entry["test"]["logloss"],
                  "expected_calibration_error": entry["test"]["ece"]})
        reliability = pd.DataFrame(entry["test"].get("reliability", []))
        if not reliability.empty:
            st.line_chart(reliability.set_index("predicted")[["observed"]])
from sports_betting_ai.backtest import run
st.subheader("Paper backtesting únicamente sobre señales anteriores al partido")
st.json(run(con))
st.caption("Origen NBA: BALLDONTLIE y The Odds API, solo con credenciales autorizadas. Registros fechados.")
st.caption("Football data provided by the Football-Data.org API (módulo de fútbol separado).")
con.close()
