import pandas as pd
import matplotlib.pyplot as plt
import json

# Load and transform data (same as above)
with open('HackUTD-2025/Data/cauldron.json', 'r') as f:
    data = json.load(f)

records = []
for entry in data:
    timestamp = entry['timestamp']
    for cauldron_id, level in entry['cauldron_levels'].items():
        records.append({
            'timestamp': timestamp,
            'cauldron_id': cauldron_id,
            'level': level
        })

df = pd.DataFrame(records)
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Create subplots
cauldrons = sorted(df['cauldron_id'].unique())
n_cauldrons = len(cauldrons)

# Calculate grid dimensions (e.g., 4 columns, multiple rows)
n_cols = 4
n_rows = (n_cauldrons + n_cols - 1) // n_cols

fig, axes = plt.subplots(n_rows, n_cols, figsize=(20, n_rows * 3))
axes = axes.flatten()  # Make it easier to iterate

for idx, cauldron_id in enumerate(cauldrons):
    cauldron_data = df[df['cauldron_id'] == cauldron_id].sort_values('timestamp')
    
    axes[idx].plot(cauldron_data['timestamp'], 
                   cauldron_data['level'], 
                   marker='o', 
                   markersize=4,
                   linewidth=2,
                   color='#2E86AB')
    
    axes[idx].set_title(f'{cauldron_id}', fontweight='bold')
    axes[idx].set_xlabel('Time')
    axes[idx].set_ylabel('Level')
    axes[idx].grid(True, alpha=0.3)
    axes[idx].tick_params(axis='x', rotation=45)

# Hide any unused subplots
for idx in range(n_cauldrons, len(axes)):
    axes[idx].axis('off')

plt.tight_layout()
plt.show()