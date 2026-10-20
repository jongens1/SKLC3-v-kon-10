"""Plotly presentation, kept independent of Streamlit."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

COLORS = ["#2563eb", "#14b8a6", "#f97316", "#a855f7"]


def lines(frame: pd.DataFrame, columns: list[str], title: str) -> go.Figure:
    figure = px.line(frame, x="hour", y=columns, title=title,
                     color_discrete_sequence=COLORS, template="plotly_white")
    figure.update_layout(hovermode="x unified", legend_title_text="", xaxis_title="Čas začiatku hodiny", yaxis_title="Joblines")
    return figure


def backlog_chart(frame: pd.DataFrame) -> go.Figure:
    frame = frame.copy()
    frame["stav"] = "stabilný / klesajúci"
    frame.loc[frame.backlog_growing, "stav"] = "rastie"
    frame.loc[frame.backlog_risky, "stav"] = "nesplnená kumulatívna potreba"
    figure = px.bar(frame, x="hour", y="backlog_scaled", color="stav",
                    color_discrete_map={"rastie": "#f97316", "stabilný / klesajúci": "#14b8a6",
                                        "nesplnená kumulatívna potreba": "#dc2626"},
                    title="Backlog na konci hodiny · cieľový objem", template="plotly_white")
    return figure
