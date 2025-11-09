import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime

BASE_URL = "https://hackutd2025.eog.systems/api"

st.set_page_config(page_title="CauldronWatch Time Series", layout="wide")
st.title("🧪 CauldronWatch: Potion Level Time Series & Ticket Overlay")

# Add auto-refresh controls
st.sidebar.header("🔄 Auto-Refresh")
auto_refresh = st.sidebar.checkbox("Enable Auto-Refresh", value=True)
if auto_refresh:
    refresh_interval = st.sidebar.selectbox(
        "Refresh Interval",
        options=[30, 60, 120, 300],
        format_func=lambda x: f"{x} seconds",
        index=1  # Default to 60 seconds
    )
    st.sidebar.info(f"Page will refresh every {refresh_interval} seconds")
    # Auto-refresh using meta tag
    st.markdown(f'<meta http-equiv="refresh" content="{refresh_interval}">', unsafe_allow_html=True)

# Show last update time
st.sidebar.text(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
if st.sidebar.button("🔄 Refresh Now"):
    st.rerun()

# ------------------------
# Load and preprocess APIs with error handling
# ------------------------
@st.cache_data(ttl=60)  # Cache for only 60 seconds
def load_cauldron_data():
    try:
        r = requests.get(f"{BASE_URL}/Data", timeout=10)
        r.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)

        # Check if response is empty
        if not r.text.strip():
            st.error("API returned empty response for /Data endpoint")
            return pd.DataFrame()

        data = r.json()
        rows = []
        for entry in data:
            ts = pd.to_datetime(entry["timestamp"])
            for cid, level in entry["cauldron_levels"].items():
                rows.append({"timestamp": ts, "cauldron_id": cid, "volume": level})
        df = pd.DataFrame(rows)
        return df
    except requests.exceptions.RequestException as e:
        st.error(f"Network error while fetching cauldron data: {e}")
        return pd.DataFrame()
    except ValueError as e:
        st.error(f"Invalid JSON response from /Data endpoint: {e}")
        st.text(f"Response text: {r.text[:500]}")  # Show first 500 chars
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Unexpected error loading cauldron data: {e}")
        return pd.DataFrame()


@st.cache_data
def load_ticket_data():
    try:
        r = requests.get(f"{BASE_URL}/Tickets", timeout=10)
        r.raise_for_status()

        if not r.text.strip():
            st.error("API returned empty response for /Tickets endpoint")
            return pd.DataFrame()

        data = r.json()
        df = pd.DataFrame(data["transport_tickets"])
        df["date"] = pd.to_datetime(df["date"])
        return df
    except requests.exceptions.RequestException as e:
        st.error(f"Network error while fetching ticket data: {e}")
        return pd.DataFrame()
    except ValueError as e:
        st.error(f"Invalid JSON response from /Tickets endpoint: {e}")
        st.text(f"Response text: {r.text[:500]}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Unexpected error loading ticket data: {e}")
        return pd.DataFrame()


# Load data
levels_df = load_cauldron_data()
tickets_df = load_ticket_data()

# Check if data loaded successfully
if levels_df.empty:
    st.warning("⚠️ No cauldron data available. Please check the API endpoint.")
    st.stop()

if tickets_df.empty:
    st.warning(
        "⚠️ No ticket data available. The visualization will show without ticket overlays."
    )

# ------------------------
# Sidebar Controls
# ------------------------
st.sidebar.header("🎛️ Controls")
available_cauldrons = sorted(levels_df["cauldron_id"].unique())
cauldron_choice = st.sidebar.selectbox("Select Cauldron", available_cauldrons)

min_date = levels_df["timestamp"].min().to_pydatetime()
max_date = levels_df["timestamp"].max().to_pydatetime()

date_range = st.sidebar.slider(
    "Select Time Range",
    min_value=min_date,
    max_value=max_date,
    value=(min_date, max_date),
    format="YYYY-MM-DD HH:mm",
)
start, end = date_range

# ------------------------
# Filter Data
# ------------------------
subset = levels_df[
    (levels_df["cauldron_id"] == cauldron_choice)
    & (levels_df["timestamp"].between(start, end))
]

# Filter tickets if available
cauldron_tickets = pd.DataFrame()
if not tickets_df.empty:
    cauldron_tickets = tickets_df[tickets_df["cauldron_id"] == cauldron_choice]

    # Convert both to naive datetime (drop timezone info)
    start_naive = pd.Timestamp(start).tz_localize(None)
    end_naive = pd.Timestamp(end).tz_localize(None)
    cauldron_tickets["date"] = pd.to_datetime(cauldron_tickets["date"]).dt.tz_localize(
        None
    )
    cauldron_tickets = cauldron_tickets[
        (cauldron_tickets["date"] >= start_naive)
        & (cauldron_tickets["date"] <= end_naive)
    ]

# ------------------------
# Visualization
# ------------------------
fig = go.Figure()

# Line for potion levels
fig.add_trace(
    go.Scatter(
        x=subset["timestamp"],
        y=subset["volume"],
        mode="lines",
        name="Potion Volume (L)",
        line=dict(color="royalblue"),
    )
)

# ------------------------
# DRAIN DETECTION - Detect significant downward slopes
# ------------------------
if len(subset) > 1:
    subset_sorted = subset.sort_values("timestamp").reset_index(drop=True)
    
    # Use rolling window to smooth and detect trends
    window_size = min(50, len(subset_sorted) // 20)  # Adaptive window size
    subset_sorted['volume_smooth'] = subset_sorted['volume'].rolling(window=window_size, center=True).mean()
    
    drain_periods = []  # Store as tuples of (start_idx, end_idx)
    
    in_drain = False
    min_drain_drop = 5  # Minimum total drop in liters to count as a drain
    
    for i in range(window_size, len(subset_sorted) - window_size):
        prev_smooth = subset_sorted.loc[i - 1, 'volume_smooth']
        curr_smooth = subset_sorted.loc[i, 'volume_smooth']
        
        # Check if smoothed volume is going down
        if curr_smooth < prev_smooth - 0.1:  # Small threshold
            if not in_drain:
                drain_start_idx = i
                drain_start_volume = curr_smooth
                in_drain = True
        elif in_drain:
            # Check if we've dropped enough to count this as a real drain
            total_drop = drain_start_volume - subset_sorted.loc[i - 1, 'volume_smooth']
            if total_drop >= min_drain_drop:
                drain_periods.append((drain_start_idx, i - 1))
            in_drain = False
    
    # Display debug info
    st.info(f"🔍 Detected {len(drain_periods)} significant drain periods (drops ≥ {min_drain_drop}L)")
    
    # Add drain markers - one per period with a span line
    for start_idx, end_idx in drain_periods:
        start_time = subset_sorted.loc[start_idx, "timestamp"]
        end_time = subset_sorted.loc[end_idx, "timestamp"]
        start_volume = subset_sorted.loc[start_idx, "volume"]
        end_volume = subset_sorted.loc[end_idx, "volume"]
        
        # Add a yellow shaded region for the drain period
        fig.add_vrect(
            x0=start_time,
            x1=end_time,
            fillcolor="yellow",
            opacity=0.1,
            layer="below",
            line_width=0,
        )
        
        # Add just ONE label at the start
        fig.add_annotation(
            x=start_time,
            y=start_volume,
            text="Drain Start",
            showarrow=True,
            arrowhead=2,
            arrowcolor="yellow",
            arrowsize=1,
            arrowwidth=2,
            ax=0,
            ay=-30,
            font=dict(size=9, color="yellow", family="Arial Black"),
            bgcolor="rgba(0,0,0,0.8)",
            bordercolor="yellow",
            borderwidth=1,
            borderpad=2
        )
        
        # Add just ONE label at the end
        fig.add_annotation(
            x=end_time,
            y=end_volume,
            text="Drain End",
            showarrow=True,
            arrowhead=2,
            arrowcolor="yellow",
            arrowsize=1,
            arrowwidth=2,
            ax=0,
            ay=30,
            font=dict(size=9, color="yellow", family="Arial Black"),
            bgcolor="rgba(0,0,0,0.8)",
            bordercolor="yellow",
            borderwidth=1,
            borderpad=2
        )

# Vertical markers for ticket dates
if not cauldron_tickets.empty:
    for _, row in cauldron_tickets.iterrows():
        # Convert pandas Timestamp to datetime and set to end of day (23:59:59)
        ticket_date = pd.to_datetime(row["date"]).replace(hour=23, minute=59, second=59)

        # Use add_shape instead of add_vline for better compatibility
        fig.add_shape(
            type="line",
            x0=ticket_date,
            x1=ticket_date,
            y0=0,
            y1=1,
            yref="paper",
            line=dict(color="red", width=2, dash="dash"),
        )

        # Add annotation separately
        fig.add_annotation(
            x=ticket_date,
            y=1,
            yref="paper",
            text=f"{row['ticket_id']}<br>({row['amount_collected']} L)",
            showarrow=False,
            yshift=10,
            font=dict(size=10, color="red"),
        )

fig.update_layout(
    title=f"Potion Level Time Series - {cauldron_choice}",
    xaxis_title="Time",
    yaxis_title="Volume (Liters)",
    height=500,
    template="plotly_white",
)

st.plotly_chart(fig, use_container_width=True)

# ------------------------
# Ticket Data Table
# ------------------------
st.subheader(f"📜 Transport Tickets for {cauldron_choice}")
if not cauldron_tickets.empty:
    st.dataframe(
        cauldron_tickets[["ticket_id", "courier_id", "amount_collected", "date"]]
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
    )
else:
    st.info("No transport tickets found for this cauldron in the selected time range.")

# ------------------------
# Summary Stats
# ------------------------
if not subset.empty:
    st.subheader("📈 Stats")
    col1, col2, col3 = st.columns(3)
    col1.metric("Average Level (L)", f"{subset['volume'].mean():.2f}")
    col2.metric("Max Level (L)", f"{subset['volume'].max():.2f}")
    col3.metric("Min Level (L)", f"{subset['volume'].min():.2f}")
else:
    st.warning("No data available for the selected cauldron and time range.")