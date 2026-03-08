"""
Plotly chart builders for watermon dashboard.
All functions return a JSON string suitable for Plotly.react() in the browser.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

_LAYOUT = dict(
    paper_bgcolor="#1e1e2e",
    plot_bgcolor="#1e1e2e",
    font=dict(color="#cdd6f4"),
    margin=dict(l=60, r=20, t=50, b=50),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

# Distinct zone colors (catppuccin-ish palette)
_ZONE_COLORS = [
    "#89b4fa", "#a6e3a1", "#fab387", "#f38ba8",
    "#cba6f7", "#94e2d5", "#f9e2af", "#89dceb",
]


def _zone_color_map(zones):
    return {z: _ZONE_COLORS[i % len(_ZONE_COLORS)] for i, z in enumerate(sorted(zones))}


# ── 1. Monthly AquaHawk usage by year ────────────────────────────────────────

def chart_monthly_aquahawk(aq: pd.DataFrame) -> str:
    """Grouped bar chart of total monthly water usage, one bar group per year.

    Shows seasonal patterns and year-over-year changes from AquaHawk meter data.
    """
    if aq.empty:
        fig = go.Figure()
        fig.update_layout(title="Monthly Water Usage — AquaHawk (no data)", **_LAYOUT)
        return pio.to_json(fig)

    df = aq.copy()
    df["Year"] = df["Timestamp"].dt.year.astype(str)
    df["Month"] = df["Timestamp"].dt.month
    monthly = df.groupby(["Year", "Month"], as_index=False)["Gallons"].sum()

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    years = sorted(monthly["Year"].unique())
    year_colors = ["#89b4fa","#a6e3a1","#fab387","#f38ba8","#cba6f7","#94e2d5","#f9e2af"]

    fig = go.Figure()
    for i, year in enumerate(years):
        ydf = monthly[monthly["Year"] == year]
        fig.add_trace(
            go.Bar(
                x=ydf["Month"].map(lambda m: month_labels[m - 1]),
                y=ydf["Gallons"],
                name=year,
                marker_color=year_colors[i % len(year_colors)],
                hovertemplate="<b>%{fullData.name}</b><br>%{x}<br>%{y:.0f} gal<extra></extra>",
            )
        )

    fig.update_layout(
        title="Total Monthly Water Usage by Year (AquaHawk)",
        xaxis=dict(categoryorder="array", categoryarray=month_labels),
        xaxis_title="Month",
        yaxis_title="Gallons",
        barmode="group",
        **_LAYOUT,
    )
    return pio.to_json(fig)


# ── 2. Daily water usage ──────────────────────────────────────────────────────

def chart_daily_usage(aq: pd.DataFrame) -> str:
    """Bar chart of daily AquaHawk gallons."""
    if aq.empty:
        fig = go.Figure()
        fig.update_layout(title="Daily Water Usage (no data)", **_LAYOUT)
        return pio.to_json(fig)

    df = aq.copy()
    df["Date"] = df["Timestamp"].dt.normalize()
    daily = df.groupby("Date", as_index=False)["Gallons"].sum()

    fig = go.Figure(
        go.Bar(
            x=daily["Date"],
            y=daily["Gallons"],
            marker_color="#89b4fa",
            hovertemplate="%{x|%b %d, %Y}<br>%{y:.0f} gal<extra></extra>",
        )
    )
    fig.update_layout(
        title="Daily Water Usage (AquaHawk)",
        xaxis_title="Date",
        yaxis_title="Gallons",
        **_LAYOUT,
    )
    return pio.to_json(fig)


# ── 2. Rachio event timeline ──────────────────────────────────────────────────

def chart_rachio_timeline(rachio: pd.DataFrame) -> str:
    """Scatter timeline of Rachio watering events, sized by duration."""
    if rachio.empty:
        fig = go.Figure()
        fig.update_layout(title="Rachio Watering Events (no data)", **_LAYOUT)
        return pio.to_json(fig)

    zones = rachio["Zone"].unique()
    cmap = _zone_color_map(zones)

    fig = go.Figure()
    for zone in sorted(zones):
        zdf = rachio[rachio["Zone"] == zone]
        fig.add_trace(
            go.Scatter(
                x=zdf["Start"],
                y=[zone] * len(zdf),
                mode="markers",
                marker=dict(
                    size=zdf["Minutes"].clip(lower=2) ** 0.6 * 3,
                    color=cmap[zone],
                    opacity=0.8,
                    line=dict(width=0),
                ),
                name=zone,
                customdata=zdf["Minutes"].values,
                hovertemplate="<b>%{y}</b><br>%{x|%b %d %Y %H:%M}<br>%{customdata:.1f} min<extra></extra>",
            )
        )

    fig.update_layout(
        title="Rachio Watering Events (bubble size ∝ duration)",
        xaxis_title="Date",
        yaxis_title="Zone",
        **_LAYOUT,
    )
    return pio.to_json(fig)


# ── 3. Zone totals ────────────────────────────────────────────────────────────

def chart_zone_totals(attributed: pd.DataFrame) -> str:
    """Grouped bar chart: total gallons and total minutes per zone."""
    if attributed.empty or "GallonsAttributed" not in attributed.columns:
        fig = go.Figure()
        fig.update_layout(title="Zone Totals (no data)", **_LAYOUT)
        return pio.to_json(fig)

    per_zone = (
        attributed.groupby("Zone", as_index=False)
        .agg(TotalGallons=("GallonsAttributed", "sum"), TotalMinutes=("Minutes", "sum"))
        .sort_values("TotalGallons", ascending=False)
    )
    cmap = _zone_color_map(per_zone["Zone"])
    colors = [cmap[z] for z in per_zone["Zone"]]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=per_zone["Zone"],
            y=per_zone["TotalGallons"],
            name="Gallons",
            marker_color=colors,
            hovertemplate="%{x}<br>%{y:.0f} gal<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=per_zone["Zone"],
            y=per_zone["TotalMinutes"],
            name="Minutes",
            mode="markers",
            marker=dict(color="#f9e2af", size=10, symbol="diamond"),
            hovertemplate="%{x}<br>%{y:.1f} min<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_layout(title="Zone Totals — Attributed Gallons & Watering Time", **_LAYOUT)
    fig.update_yaxes(title_text="Gallons", secondary_y=False)
    fig.update_yaxes(title_text="Total Minutes", secondary_y=True)
    return pio.to_json(fig)


# ── 4. Gallons per minute by zone ─────────────────────────────────────────────

def chart_gpm(attributed: pd.DataFrame) -> str:
    """Scatter plot of gallons per minute (GPM) per zone, per event."""
    if attributed.empty or "GallonsAttributed" not in attributed.columns:
        fig = go.Figure()
        fig.update_layout(title="GPM by Zone (no data)", **_LAYOUT)
        return pio.to_json(fig)

    df = attributed[attributed["Minutes"] > 0].copy()
    df["GPM"] = df["GallonsAttributed"] / df["Minutes"]
    zones = df["Zone"].unique()
    cmap = _zone_color_map(zones)

    fig = go.Figure()
    for zone in sorted(zones):
        zdf = df[df["Zone"] == zone]
        fig.add_trace(
            go.Scatter(
                x=zdf["Start"],
                y=zdf["GPM"],
                mode="markers",
                marker=dict(color=cmap[zone], size=6, opacity=0.7),
                name=zone,
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>%{x|%b %d %Y %H:%M}"
                    "<br>%{y:.2f} GPM<extra></extra>"
                ),
            )
        )

    # Zone median GPM as horizontal reference lines
    medians = df.groupby("Zone")["GPM"].median()
    for zone, med in medians.items():
        fig.add_hline(
            y=med,
            line_dash="dot",
            line_color=cmap.get(zone, "#888"),
            annotation_text=f"{zone} median",
            annotation_position="right",
            annotation_font_size=10,
        )

    fig.update_layout(
        title="Gallons per Minute by Zone (efficiency over time)",
        xaxis_title="Date",
        yaxis_title="GPM",
        **_LAYOUT,
    )
    return pio.to_json(fig)


# ── 5. Zone usage over time ───────────────────────────────────────────────────

def chart_zone_over_time(attributed: pd.DataFrame) -> str:
    """Stacked bar chart of monthly attributed gallons per zone.

    Shows how much water each zone uses and whether that has changed over time.
    """
    if attributed.empty or "GallonsAttributed" not in attributed.columns:
        fig = go.Figure()
        fig.update_layout(title="Zone Usage Over Time (no data)", **_LAYOUT)
        return pio.to_json(fig)

    df = attributed.copy()
    # Normalize to tz-naive for period grouping
    df["Month"] = df["Start"].dt.to_period("M").dt.to_timestamp()
    monthly = (
        df.groupby(["Month", "Zone"], as_index=False)["GallonsAttributed"].sum()
    )

    zones = sorted(monthly["Zone"].unique())
    cmap = _zone_color_map(zones)

    fig = go.Figure()
    for zone in zones:
        zdf = monthly[monthly["Zone"] == zone]
        fig.add_trace(
            go.Bar(
                x=zdf["Month"],
                y=zdf["GallonsAttributed"],
                name=zone,
                marker_color=cmap[zone],
                hovertemplate="<b>%{fullData.name}</b><br>%{x|%b %Y}<br>%{y:.0f} gal<extra></extra>",
            )
        )

    fig.update_layout(
        title="Monthly Water Usage by Zone",
        xaxis_title="Month",
        yaxis_title="Gallons",
        barmode="stack",
        **_LAYOUT,
    )
    return pio.to_json(fig)


# ── 6. Timezone alignment verification ───────────────────────────────────────

def chart_alignment(aq: pd.DataFrame, rachio: pd.DataFrame) -> str:
    """Overlay AquaHawk hourly usage bars with Rachio event bands.

    If timezone handling is correct, AquaHawk usage spikes will visually
    coincide with Rachio watering events. Misalignment indicates a TZ bug.
    """
    if aq.empty and rachio.empty:
        fig = go.Figure()
        fig.update_layout(title="Timezone Alignment Check (no data)", **_LAYOUT)
        return pio.to_json(fig)

    fig = go.Figure()

    # AquaHawk hourly bars
    if not aq.empty:
        fig.add_trace(
            go.Bar(
                x=aq["Timestamp"],
                y=aq["Gallons"],
                name="AquaHawk (gallons/hr)",
                marker_color="#89b4fa",
                opacity=0.7,
                hovertemplate="%{x|%b %d %H:%M %Z}<br>%{y:.1f} gal<extra></extra>",
            )
        )

    # Rachio events as colored vertical bands (shapes)
    zones = rachio["Zone"].unique() if not rachio.empty else []
    cmap = _zone_color_map(zones)
    shapes = []
    annotations = []

    if not rachio.empty:
        # Also add scatter traces per zone so they show in legend
        for zone in sorted(zones):
            zdf = rachio[rachio["Zone"] == zone]
            fig.add_trace(
                go.Scatter(
                    x=zdf["Start"],
                    y=[0] * len(zdf),
                    mode="markers",
                    marker=dict(color=cmap[zone], size=8, symbol="triangle-up"),
                    name=zone,
                    legendgroup=zone,
                    hovertemplate=(
                        f"<b>{zone}</b><br>%{{x|%b %d %H:%M %Z}}<br>"
                        "%{customdata:.1f} min<extra></extra>"
                    ),
                    customdata=zdf["Minutes"].values,
                )
            )
            for _, row in zdf.iterrows():
                shapes.append(
                    dict(
                        type="rect",
                        xref="x",
                        yref="paper",
                        x0=row["Start"],
                        x1=row["End"],
                        y0=0,
                        y1=1,
                        fillcolor=cmap[zone],
                        opacity=0.15,
                        line_width=0,
                        layer="below",
                    )
                )

    fig.update_layout(
        title="Timezone Alignment: AquaHawk usage vs Rachio events (same axis)",
        xaxis_title=f"Time ({aq['Timestamp'].iloc[0].tzname() if not aq.empty else 'Pacific'})",
        yaxis_title="Gallons / hr",
        shapes=shapes,
        barmode="overlay",
        **_LAYOUT,
    )
    return pio.to_json(fig)
