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


def performance_chart(day: pd.DataFrame, cap: float | None = None, limited: bool = False) -> go.Figure:
    figure = base()
    figure.add_trace(go.Bar(x=day.hour, y=day.created_scaled, name="Nové vzniky",
                            marker_color=PALE, opacity=.3))
    add_line(figure,day,"current_limited" if limited else "current_pick","Pick podľa dnešného profilu",BLUE)
    add_line(figure,day,"prepick_smoothed_scaled" if limited else "balanced_required","Vyrovnaný pick",GREEN)
    if cap is not None:
        figure.add_hline(y=cap,line_color="#ffb454",line_dash="dash",
                        annotation_text=f"Limit skladu {cap:,.0f} jl/h",annotation_position="top left")
    return figure


def inventory_chart(day: pd.DataFrame, initial: float, limited: bool = False,
                    cumulative: bool = False) -> go.Figure:
    """Boundary timestamps include the explicit 06:00 opening inventory."""
    figure = base(y="Joblines")
    x = [day.hour.iloc[0]] + (day.hour + pd.Timedelta(hours=1)).tolist()
    if cumulative:
        series = [("Vzniknuté celkom", [initial]+day.cumulative_created_scaled.tolist(), PALE),
                  ("Pick podľa dnešného profilu", [0]+day["cumulative_current_limited" if limited else "cumulative_current"].tolist(), BLUE),
                  ("Vyrovnaný pick", [0]+day["cumulative_simulated" if limited else "cumulative_balanced_required"].tolist(), GREEN)]
    else:
        series = [("Buffer · dnešný profil", [initial]+day["current_limited_backlog" if limited else "current_backlog"].tolist(), BLUE),
                  ("Buffer · vyrovnaný pick", [initial]+day["scenario_backlog" if limited else "balanced_required_backlog"].tolist(), GREEN)]
    for label, values, color in series:
        figure.add_trace(go.Scatter(x=x, y=values, name=label, mode="lines+markers",
                                    marker=dict(size=4), line=dict(color=color,width=3),
                                    hovertemplate="%{y:,.0f} jl<extra>%{fullData.name}</extra>"))
    return figure


def comparison_charts(frame: pd.DataFrame, selected: pd.Timestamp) -> tuple[go.Figure,go.Figure]:
    """Two views of exactly the same boundary balances and selected timestamp."""
    totals, buffers = base(y="Joblines celkom"), base(y="Joblines na pickovanie")
    for figure,series in [(totals,[("created","Vzniknuté joblines",PALE),
                                 ("picked_balanced","Vypickované · vyrovnaný pick",GREEN),
                                 ("picked_current","Vypickované · aktuálny výkon bez úprav",BLUE)]),
                           (buffers,[("buffer_balanced","Buffer · vyrovnaný pick",GREEN),
                                     ("buffer_current","Buffer · aktuálny výkon bez úprav",BLUE)])]:
        for column,label,color in series:
            figure.add_trace(go.Scatter(x=frame.time,y=frame[column],name=label,mode="lines+markers",
                                        marker=dict(size=5),line=dict(color=color,width=3),
                                        hovertemplate="%{y:,.0f} jl<extra>%{fullData.name}</extra>"))
        figure.add_vline(x=selected,line_color="#ffffff",line_width=1,line_dash="dot")
        figure.update_layout(legend=dict(orientation="h",y=1.2,x=0),
                             margin=dict(l=10,r=20,t=75,b=10),height=440,
                             xaxis=dict(tickformat="%H:%M",hoverformat="%d.%m. %H:%M"))
    return totals,buffers


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
