# Capped model smoke test

Two attempts only; no subsequent tuning or local training. Total wall-time cap was 240 seconds, 120 per episode. Both terminated normally, well below the cap.

Model: local `qwen3.8:27b`, Ollama 0.40.2, nvfp4 MLX. This is a quantized proxy, not the Arena weights, runner or private evaluation. Native tool calls used the environment action schema, with no reference SQL or target outputs supplied to the model.

| Identity | Seed | Terminal reward | Actions | Output tokens | Seconds |
|---|---:|---:|---:|---:|---:|
| invoices-standard | 8671 | 1.0 | 8 | 1189 | 33.13 |
| expenses-advanced | 8671 | 0.55625 | 9 | 1232 | 40.61 |

Both wrote both artifacts and explicitly submitted. These two attempts check executability and expose one imperfect outcome. They do not estimate success rates, reward variance within a task, gradient frequency, training transfer or leaderboard performance. There were no retries or family-selection changes in response to these results. Source `smoke_model.py` permits reproduction when that local model is installed.
