import pandas as pd
import requests
import json
from datetime import datetime

# Available dates
available_dates = {
    "2025-10-30": {"start": 1761782400, "end": 1761868740},
    "2025-10-31": {"start": 1761868800, "end": 1761955140},
    "2025-11-01": {"start": 1761955200, "end": 1762041540},
    "2025-11-02": {"start": 1762041600, "end": 1762127940},
    "2025-11-03": {"start": 1762128000, "end": 1762214340},
    "2025-11-04": {"start": 1762214400, "end": 1762300740},
    "2025-11-05": {"start": 1762300800, "end": 1762387140},
}

def fetch_data_for_date(date_str, start_ts, end_ts):
    """Fetch data for a specific date"""
    url = f"https://hackutd2025.eog.systems/api/Data?start_date={start_ts}&end_date={end_ts}"
    
    try:
        print(f"Fetching data for {date_str}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        rows = []
        for entry in data:
            timestamp = pd.to_datetime(entry["timestamp"])
            for cauldron_id, level in entry["cauldron_levels"].items():
                rows.append({
                    "date": date_str,
                    "timestamp": timestamp,
                    "cauldron_id": cauldron_id,
                    "level": level
                })
        
        print(f"✓ Loaded {len(rows)} data points for {date_str}")
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"✗ Error fetching data for {date_str}: {e}")
        return pd.DataFrame()

def detect_drain_events_statistical(cauldron_data, std_multiplier=3.0, min_duration=5):
    """
    Detect drain events using statistical/adaptive method
    Returns list of drain events with start/end minutes
    """
    cauldron_data = cauldron_data.sort_values("timestamp").copy()
    cauldron_data["minute"] = range(len(cauldron_data))
    cauldron_data["level_change"] = cauldron_data["level"].diff()
    
    drains = []
    
    # Statistical detection based on deviation from normal filling
    filling_changes = cauldron_data[cauldron_data["level_change"] > 0]["level_change"]
    
    if len(filling_changes) > 10:
        mean_fill = filling_changes.mean()
        std_fill = filling_changes.std()
        threshold_stat = mean_fill - (std_multiplier * std_fill)
        is_draining = cauldron_data["level_change"] < threshold_stat
    else:
        # Fallback if not enough filling data
        is_draining = cauldron_data["level_change"] < -5.0
    
    # Group consecutive draining minutes
    cauldron_data["is_draining"] = is_draining
    cauldron_data["drain_group"] = (cauldron_data["is_draining"] != cauldron_data["is_draining"].shift()).cumsum()
    
    # Find drain events (consecutive draining periods)
    for drain_group, group_data in cauldron_data[cauldron_data["is_draining"]].groupby("drain_group"):
        if len(group_data) >= min_duration:
            start_minute = group_data["minute"].iloc[0]
            end_minute = group_data["minute"].iloc[-1]
            start_time = group_data["timestamp"].iloc[0]
            end_time = group_data["timestamp"].iloc[-1]
            
            level_before = cauldron_data[cauldron_data["minute"] == start_minute - 1]["level"].values
            level_before = level_before[0] if len(level_before) > 0 else group_data["level"].iloc[0]
            level_after = group_data["level"].iloc[-1]
            
            total_drop = level_before - level_after
            duration = end_minute - start_minute + 1
            
            drains.append({
                "start_minute": int(start_minute),
                "end_minute": int(end_minute),
                "duration_minutes": int(duration),
                "start_time": start_time,
                "end_time": end_time,
                "level_before": float(level_before),
                "level_after": float(level_after),
                "total_drop": float(total_drop),
                "avg_drop_rate": float(total_drop / duration) if duration > 0 else 0
            })
    
    return drains

def analyze_drains(dates_to_analyze, std_multiplier=3.0, min_duration=5):
    """
    Main function to analyze drain events and return JSON output
    
    Args:
        dates_to_analyze: List of date strings (e.g., ["2025-10-30", "2025-11-01"])
        std_multiplier: Standard deviations for statistical detection (default: 3.0)
        min_duration: Minimum drain duration in minutes (default: 5)
    
    Returns:
        JSON string with drain data per cauldron per date
    """
    
    # Fetch all data
    all_data = []
    for date_str in dates_to_analyze:
        if date_str not in available_dates:
            print(f"Warning: Date {date_str} not in available dates")
            continue
            
        date_info = available_dates[date_str]
        df = fetch_data_for_date(date_str, date_info["start"], date_info["end"])
        if not df.empty:
            all_data.append(df)
    
    if not all_data:
        print("No data fetched")
        return json.dumps({"error": "No data fetched"}, indent=2)
    
    combined_df = pd.concat(all_data, ignore_index=True)
    print(f"\n✓ Total data points loaded: {len(combined_df)}")
    
    # Detect drains for all cauldrons across all dates
    print(f"\nAnalyzing drain events (std_multiplier={std_multiplier}, min_duration={min_duration})...")
    
    cauldron_drain_summary = {}
    
    for date_str in dates_to_analyze:
        date_data = combined_df[combined_df["date"] == date_str]
        if date_data.empty:
            continue
            
        cauldrons = sorted(date_data["cauldron_id"].unique())
        
        for cauldron_id in cauldrons:
            cauldron_data = date_data[date_data["cauldron_id"] == cauldron_id]
            
            # Detect drains using statistical method
            drains = detect_drain_events_statistical(
                cauldron_data, 
                std_multiplier=std_multiplier, 
                min_duration=min_duration
            )
            
            # Calculate total drain volume for this cauldron on this date
            total_drain_volume = sum(drain["total_drop"] for drain in drains)
            
            # Only include if there were drains
            if total_drain_volume > 0:
                key = f"{cauldron_id}_{date_str}"
                cauldron_drain_summary[key] = {
                    "cauldron_id": cauldron_id,
                    "date_time": date_str,
                    "drain_volume": round(total_drain_volume, 2),
                    "number_of_drains": len(drains),
                    "drain_events": [
                        {
                            "start_minute": drain["start_minute"],
                            "end_minute": drain["end_minute"],
                            "duration_minutes": drain["duration_minutes"],
                            "volume": round(drain["total_drop"], 2)
                        }
                        for drain in drains
                    ]
                }
    
    # Convert to list format
    result = {
        "cauldron_data": list(cauldron_drain_summary.values()),
        "summary": {
            "total_cauldrons_analyzed": len(set(item["cauldron_id"] for item in cauldron_drain_summary.values())),
            "total_dates_analyzed": len(dates_to_analyze),
            "total_drain_events": sum(item["number_of_drains"] for item in cauldron_drain_summary.values()),
            "total_volume_drained": round(sum(item["drain_volume"] for item in cauldron_drain_summary.values()), 2)
        }
    }
    
    print(f"\n✓ Analysis complete!")
    print(f"  - Cauldrons with drains: {result['summary']['total_cauldrons_analyzed']}")
    print(f"  - Total drain events: {result['summary']['total_drain_events']}")
    print(f"  - Total volume drained: {result['summary']['total_volume_drained']}")
    
    return json.dumps(result, indent=2)

def save_to_file(json_output, filename="drain_analysis.json"):
    """Save JSON output to file"""
    with open(filename, 'w') as f:
        f.write(json_output)
    print(f"\n✓ Results saved to {filename}")

if __name__ == "__main__":
    # Configuration
    DATES_TO_ANALYZE = ["2025-10-30", "2025-10-31", "2025-11-01"]
    STD_MULTIPLIER = 3.0  # Adjust sensitivity (lower = more sensitive)
    MIN_DURATION = 5      # Minimum minutes for a drain event
    
    print("=" * 60)
    print("DRAIN DETECTION ANALYSIS - Statistical Adaptive Method")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  - Dates: {', '.join(DATES_TO_ANALYZE)}")
    print(f"  - Std Multiplier: {STD_MULTIPLIER}")
    print(f"  - Min Duration: {MIN_DURATION} minutes")
    print("\n" + "=" * 60 + "\n")
    
    # Run analysis
    json_output = analyze_drains(
        dates_to_analyze=DATES_TO_ANALYZE,
        std_multiplier=STD_MULTIPLIER,
        min_duration=MIN_DURATION
    )
    
    # Print JSON output
    print("\n" + "=" * 60)
    print("JSON OUTPUT:")
    print("=" * 60)
    print(json_output)
    
    # Save to file
    save_to_file(json_output, "drain_analysis.json")
    
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)