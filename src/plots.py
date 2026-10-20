"""Readable blue/green charts. Interpolation never changes the underlying counts."""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go

BLUE = "#4b9fff"
GREEN = "#24d6a0"
PALE = "#9bb2cd"
TYPE_COLORS = {"Expedícia - Standard": BLUE, "Distribúcia - LC": GREEN, "Distribúcia - POB": "#6de4de"}


def base(title: str = "", y: str = "Joblines / hodinu") -> go.Figure:
    figure = go.Figure()
    figure.update_layout(title=title, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                         plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#dce8f8",size=13),
                         margin=dict(l=10,r=20,t=45,b=10), height=420,
                         hovermode="x unified", legend=dict(orientation="h",y=1.14,x=0),
                         yaxis=dict(title=y,rangemode="tozero",gridcolor="#1c2c42"),
                         xaxis=dict(title=None,tickformat="%H:%M",gridcolor="#142238"))
    return figure


def add_line(figure: go.Figure, frame: pd.DataFrame, column: str, label: str,
             color: str, dash: str = "solid", visible: bool | str = True) -> None:
    figure.add_trace(go.Scatter(x=frame.hour,y=frame[column],name=label,mode="lines+markers",
                               marker=dict(size=4),line=dict(color=color,width=3,dash=dash,shape="linear"),
                               visible=visible,hovertemplate="%{y:,.0f} jl<extra>%{fullData.name}</extra>"))


def performance_chart(day: pd.DataFrame) -> go.Figure:
    figure = base()
    if day.warehouse_picked.notna().any():
        add_line(figure,day,"warehouse_picked","Skutočný výkon skladu",BLUE)
    add_line(figure,day,"prepick_smoothed_scaled","Potrebný výkon pre cieľ",GREEN)
    return figure


def lines(frame: pd.DataFrame, columns: list[str], labels: list[str], title: str = "") -> go.Figure:
    figure = base(title,y="Joblines")
    for column,label,color in zip(columns,labels,[BLUE,GREEN,PALE,"#7cc7ff"]):
        add_line(figure,frame,column,label,color)
    return figure


def arrivals_chart(day: pd.DataFrame, initial: float, factor: float) -> go.Figure:
    figure = base(y="Joblines")
    x = ["Vstupný buffer"] + [t.strftime("%H:%M") for t in day.hour]
    figure.add_trace(go.Bar(x=x,y=[initial]+day.created_count.tolist(),name="Reálny objem",
                           marker_color=BLUE))
    if factor != 1:
        figure.add_trace(go.Scatter(x=x,y=[initial*factor]+day.created_scaled.tolist(),
                                   name="Cieľový objem",line=dict(color=GREEN,width=3)))
    figure.update_layout(xaxis=dict(type="category",tickangle=-30))
    return figure


def collection_chart(frame: pd.DataFrame, scaled: bool = False) -> go.Figure:
    figure = base(y="Joblines")
    for kind,g in frame.groupby("job_type",sort=False):
        figure.add_trace(go.Bar(x=g.hour,y=g["count_scaled" if scaled else "count"],name=kind,
                               marker_color=TYPE_COLORS.get(kind,PALE)))
    figure.update_layout(barmode="stack")
    return figure
