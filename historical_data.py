import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime

BASE_URL = "https://hackutd2025.eog.systems/api"

st.set_page_config(page_title="CauldronWatch Time Series", layout="wide")
st.title("🧪 CauldronWatch: Potion Level Time Series & Ticket Overlay")


# ------------------------
# Load and preprocess APIs with error handling
# ------------------------
@st.cache_data
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

# Vertical markers for ticket dates
if not cauldron_tickets.empty:
    for _, row in cauldron_tickets.iterrows():
        fig.add_vline(
            x=row["date"],
            line_width=2,
            line_dash="dash",
            line_color="red",
            annotation_text=f"{row['ticket_id']} ({row['amount_collected']} L)",
            annotation_position="top right",
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
