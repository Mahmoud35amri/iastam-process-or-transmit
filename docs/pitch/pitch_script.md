# Pitch video script: "Process or Transmit?"

**Problem 1 · IASTAM 2026 · value-aware onboard decision engine**

- **Target length:** 3:00 (about 430 spoken words at ~140 words/min). Hard cap 3:30.
- **Source of every number:** the benchmark in `results/summary.csv` and `results/runs.csv`. It covers 6 scenarios × 5 strategies × 20 real days of Sentinel-2A's orbit, or 600 simulated days.

---

## Full version (3:00)

| Time | On-screen visual | Narration (spoken) | On-screen text |
|---|---|---|---|
| 0:00–0:15 | Dark text card over a slow zoom on a satellite silhouette. Two counters tick up side by side: "Generated" to 90 GB, "Downlinked" stalls at 21 GB. | Every day, a small Earth-observation satellite collects about ninety gigabytes of data. Over its ground station it can send down only about twenty. So, onboard, every thirty seconds, it has to decide: what do we keep? | **~90 GB/day generated · ~21 GB/day downlink**<br>What do you keep? |
| 0:15–0:40 | Icon strip, one icon per constraint lighting up in turn: battery with eclipse shading, CPU/GPU, memory, storage, antenna with a short pass window, a clock. | For each image, each spectral cube or each fire alert, the satellite can process it now, store it for later, or send it raw. But the battery only charges in sunlight. The GPU runs one job at a time. Storage fills within hours. The ground station is in view for a few minutes, four or five times a day. And an alert that arrives late is worth almost nothing. | Process now · Store · Transmit<br>Energy · CPU/GPU · Memory · Storage · Passes · Bandwidth · Latency |
| 0:40–1:15 | Poster "Our idea" diagram. Highlight the four engine steps one by one. Show the formula on its own card: **U = EV − Σ λᵣ · useᵣ** | Our answer is a value-aware decision engine. Every item gets an expected value: its priority, the chance it is actually useful, and how fast that value decays. Then every scarce resource gets a price: downlink megabytes, battery watt-hours, GPU seconds, CPU seconds and storage. The prices rise until the plan fits the forecast passes, sunlight and disk. Each item simply picks its best net-value option: process now, store, transmit, or drop. And the whole plan is recomputed every thirty seconds. | Value-aware engine<br>Every resource has a price · every item picks its best net value<br>Re-planned every 30 s |
| 1:15–1:35 | Dashboard replay view: scrub the timeline to a ground pass, then open the decision log. | Every decision is explainable. Here, a possible wildfire detection is processed onboard: a one-megabyte alert instead of thirty-three megabytes raw, sent at the very next pass. Here, a hyperspectral cube is sent raw, because the downlink has room and raw data keeps more science. | "process now: U_proc 10.66 > U_raw 7.54; ~1 MB product vs 33 MB raw"<br>"transmit raw: U_raw 4.47 >= U_proc 2.74" |
| 1:35–1:55 | Dashboard header (Sentinel-2A TLE · CNES Toulouse), then the policy comparison view: six scenario tabs, five strategy colours. | To test it, we flew it on a real orbit: Sentinel-2A's, with real passes over Toulouse and real eclipses. We squeezed each resource in turn, to two thirds of what processing everything needs. And we compared against four baselines, including a smart bandwidth-aware rule set. Six scenarios, twenty real days each: six hundred simulated days. | Real orbit: Sentinel-2A · Toulouse station<br>6 scenarios × 5 strategies × 20 days = 600 simulated days |
| 1:55–2:15 | `docs/figures/value_by_scenario.png`. Animate the blue bars rising above the others. | Result one: in five of six scenarios, our engine captures the most scientific value, beating the best baseline on eighteen to twenty days out of twenty. That's two to twenty percent more value. When mass memory is the bottleneck, simply processing everything is still slightly better, and we report that too. | Best in 5 of 6 scenarios<br>+2% to +20% vs best baseline · process-all best when memory is tightest |
| 2:15–2:35 | `docs/figures/energy_by_scenario.png`, then `docs/figures/timeline_energy_starved.png` (top panel, reserve line). | Result two: it spends less energy, twenty-two percent less than the rule set in the nominal mission. When the solar array is degraded, processing everything drives the battery down to the power system's safety floor, and it spends more than half the day below the reserve. Our engine's lowest charge averages twenty-eight percent. | −22% energy vs rules (nominal)<br>Energy-starved: lowest battery 10% (process-all, at the floor) vs 28% (ours) |
| 2:35–2:50 | Plain text card, calm tone. | Honest limits. The orbit is real, but the satellite's hardware and data are illustrative. And our "completion rate" is a few points lower, because we drop items that can't reach the ground in time and send raw data when bandwidth allows. | Real orbit · illustrative payload · Completion 79% vs 85% (nominal)<br>But more items delivered: 65.0% vs 63.7% |
| 2:50–3:00 | Roadmap card, then the repository QR code and team name. | Next: measure flight-realistic compute costs, run hardware-in-the-loop, learn usefulness estimates onboard, and replay real mission data. The code, dataset and dashboard are open. Let's make every downlinked megabyte count. | Next: flight compute costs · HIL · learned usefulness · real data<br>**Make every megabyte count** · [QR] |

**Narration word count:** 458 words, roughly 3:15 at 140 wpm (under the 3:30 cap). To reach 3:00, make two cuts. In the 1:15 scene, cut the second example sentence (the hyperspectral cube). In the 0:15 scene, cut "And an alert that arrives late is worth almost nothing." That leaves about 425 words (≈3:02).

---

## 60-second cut-down

| Time | On-screen visual | Narration | On-screen text |
|---|---|---|---|
| 0:00–0:10 | 90 GB vs 21 GB counters | A satellite collects ninety gigabytes a day and can send about twenty. Onboard, it must decide what to keep. | 90 GB vs 21 GB |
| 0:10–0:25 | Engine diagram → formula card | Our engine prices every scarce resource: downlink, battery, GPU, storage. Every item picks its best net-value option: process now, store, transmit or drop. It re-plans every thirty seconds, and every decision is explained. | U = EV − Σ λᵣ · useᵣ |
| 0:25–0:45 | `value_by_scenario.png` → `energy_by_scenario.png` | Flown on Sentinel-2A's real orbit for six hundred simulated days, it delivered the most value in five of six scenarios. That's up to twenty percent more than the best of four baselines, with up to twenty-two percent less energy. | Real orbit · best in 5 of 6 · up to +20% value · up to −22% energy |
| 0:45–1:00 | Dashboard replay → QR | Code, dataset and dashboard are open. Let's make every megabyte count. | **Make every megabyte count** · [QR] |

(102 words: roughly 45–50 s of speech plus pauses and the end card.)

---

## Recording notes

- **Tone:** confident, plain, and concrete. Avoid jargon on screen; the voice-over may say "shadow prices" once, but the on-screen text should say "every resource has a price".
- **Pacing:** about 140 wpm. Pause about half a second after each result number. Let each chart stay on screen for at least 4 seconds after its number is spoken.
- **Colours:** keep them consistent with the figures:
  - value-aware (ours): blue `#2a78d6`
  - priority rules: orange `#eb6834`
  - process-all: aqua `#1baf7a`
  - bent-pipe: yellow `#eda100`
  - bandwidth-aware rules: pink `#e87ba4`
  - text: `#0b0b0b` / `#52514e` on `#fcfcfb`
- **Screens to capture from the dashboard** (`dashboard/index.html` or its published link):
  1. **Replay view:** play the simulated day at speed, then pause on a ground pass. Show the battery, storage and cumulative-value tracks, then the decision log with the engine's explanations.
  2. **Policy comparison view:** switch between the six scenario tabs, with the value and energy bars for all five strategies visible.
  3. **Header:** the line showing "SENTINEL-2A TLE · CNES Toulouse" (proof that the orbit is real).
- **Figures to use full-screen** (all in `docs/figures/`):
  - `value_by_scenario.png`
  - `energy_by_scenario.png`
  - `timeline_energy_starved.png`
  - `outcomes.png` (optional b-roll behind the limitations card)
- **Accuracy guardrails** (do not round these differently in the edit):
  - **Orbit:** Sentinel-2A TLE of 26 Sep 2026 (CelesTrak), SGP4 via skyfield, CNES Toulouse above 10°. That gives 4.4 passes/day, eclipses of 34 min per 101-min orbit, and ~21.5 GB/day of downlink. The instruments generate 89.7 GB/day on average.
  - **Stress rule:** each stress scenario offers 2/3 of what process-all needs of its resource: a 44.8 W solar array, 2.85 GB of storage, or a 4.72× slower GPU.
  - **Value vs the best baseline:** +4.0% (nominal), +11.0% (energy), +20.3% (downlink), +7.2% (compute), +2.0% (event surge). Storage-tight: −3.9% vs process-all, and a tie with the rule set.
  - **Paired over identical days:** the engine beats the best baseline on 18–20 of 20 days in those five scenarios.
  - **Energy vs the rule set and process-all:** −2% to −22%. Nominal: −22%.
  - **Energy-starved:**

    | Strategy | Mean lowest battery | Time below reserve |
    |---|---|---|
    | Process-all | 10.0% (load-shedding floor) | 54.7% |
    | Rules | 23.1% | 4.9% |
    | Bandwidth rules | 27.1% | 2.2% |
    | Ours | 27.8% | 3.3% |

    No power failure in any run.
  - **Nominal:**

    | Measure | Ours | Rules | Bandwidth rules |
    |---|---|---|---|
    | Completion | 79.4% | 84.7% | 84.3% |
    | Items delivered | 65.0% | 63.5% | 63.7% |
    | True alerts delivered | 71.6% | 71.8% | 71.6% (same alert latency, 140 min) |

- **Captions:** burn in subtitles. Many viewers watch without sound.
