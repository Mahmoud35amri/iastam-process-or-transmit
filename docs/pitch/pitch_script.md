# Pitch video script: "Process or Transmit?"

**Problem 1 · IASTAM 2026 · value-aware onboard decision engine**

- **Target length:** 3:00 (about 430 spoken words at ~140 words/min). Hard cap 3:30.
- **Source of every number:** the benchmark in `results/summary.csv` and `results/runs.csv`. It covers 5 scenarios × 4 strategies × 20 real days of Sentinel-2A's orbit, or 400 simulated days.

---

## Full version (3:00)

| Time | On-screen visual | Narration (spoken) | On-screen text |
|---|---|---|---|
| 0:00–0:15 | Dark text card over a slow zoom on a satellite silhouette. Two counters tick up side by side: "Generated" to 90 GB, "Downlinked" stalls at 21 GB. | Every day, a small Earth-observation satellite collects about ninety gigabytes of data. Over its ground station it can send down only about twenty. So, onboard, every thirty seconds, it has to decide: what do we keep? | **~90 GB/day generated · ~21 GB/day downlink**<br>What do you keep? |
| 0:15–0:40 | Icon strip, one icon per constraint lighting up in turn: battery with eclipse shading, CPU/GPU, memory, storage, antenna with a short pass window, a clock. | For each image, each spectral cube or each fire alert, the satellite can process it now, store it for later, or send it raw. But the battery only charges in sunlight. The GPU runs one job at a time. Storage fills within hours. The ground station is in view for a few minutes, four or five times a day. And an alert that arrives late is worth almost nothing. | Process now · Store · Transmit<br>Energy · CPU/GPU · Memory · Storage · Passes · Bandwidth · Latency |
| 0:40–1:15 | Poster "Our idea" diagram (or `docs/figures/architecture.png`). Highlight the four engine steps one by one. Show the formula on its own card: **U = EV − Σ λᵣ · useᵣ** | Our answer is a value-aware decision engine. Every item gets an expected value: its priority, the chance it is actually useful, and how fast that value decays. Then every scarce resource gets a price: downlink megabytes, battery watt-hours, GPU seconds, CPU seconds and storage. The prices rise until the plan fits the forecast passes, sunlight and disk. Each item simply picks its best net-value option: process now, store, transmit, or drop. And the whole plan is recomputed every thirty seconds. | Value-aware engine<br>Every resource has a price · every item picks its best net value<br>Re-planned every 30 s |
| 1:15–1:35 | Dashboard replay view: scrub the timeline to a ground pass, then open the decision log. | Every decision is explainable. Here, a possible wildfire detection is processed onboard: a one-megabyte alert instead of thirty-three megabytes raw, sent at the very next pass. Here, a hyperspectral cube is sent raw, because the downlink has room and raw data keeps more science. | "process now: U_proc 10.66 > U_raw 7.54; ~1 MB product vs 33 MB raw"<br>"transmit raw: U_raw 4.47 >= U_proc 2.74" |
| 1:35–1:55 | Dashboard header (Sentinel-2A TLE · CNES Toulouse), then the policy comparison view: five scenario tabs, four strategy colours. | To test it, we flew it on a real orbit: Sentinel-2A's, propagated from its current orbital elements, with real passes over Toulouse and real eclipses. We compared our engine with three baselines: a bent-pipe that sends everything raw, a process-everything strategy, and a hand-tuned rule-based operator. Five scenarios, twenty real days each: four hundred simulated days. | Real orbit: Sentinel-2A · Toulouse station<br>5 scenarios × 4 strategies × 20 days = 400 simulated days |
| 1:55–2:15 | `docs/figures/value_by_scenario.png`. Animate the blue bars rising above the others. | Result one: in four scenarios, our engine captures the most scientific value on every single day. That's three to twenty-one percent more than the rule-based operator, and six to fifty-nine percent more than processing everything. When storage is tightest, it ties the best rules, while using a third less energy. | Wins 20/20 days in 4 of 5 scenarios<br>+3% to +21% vs rule-based · +6% to +59% vs process-all · tie when storage is tightest |
| 2:15–2:35 | `docs/figures/energy_by_scenario.png`, then `docs/figures/timeline_energy_starved.png` (top panel, reserve line). | Result two: it spends less energy. That's twenty-two percent less in the nominal mission, and up to thirty-five percent less. When the solar array is degraded, processing everything runs the battery down to four percent, and it spends forty-three percent of the day below the safety reserve. Our engine's lowest charge averages thirty-five percent. | −22% energy (nominal) · up to −35%<br>Energy-starved: lowest battery 4% (process-all) vs 35% (ours) |
| 2:35–2:50 | Plain text card, calm tone. | Honest limits. The orbit is real, but the satellite's hardware and data are illustrative. And our "completion rate" is a few points lower, because we drop items that can't reach the ground in time and send raw data when bandwidth allows. We still deliver more items, and more value. | Real orbit · illustrative payload · Completion 79% vs 85% (nominal)<br>But more items delivered: 65.0% vs 63.5% |
| 2:50–3:00 | Roadmap card, then the repository QR code and team name. | Next: measure flight-realistic compute costs, run hardware-in-the-loop, learn usefulness estimates onboard, and replay real mission data. The code, dataset and dashboard are open. Let's make every downlinked megabyte count. | Next: flight compute costs · HIL · learned usefulness · real data<br>**Make every megabyte count** · [QR] |

**Narration word count:** 467 words, which runs about 3:20 at 140 wpm (under the 3:30 cap). To reach 3:00, cut the second example sentence in the 1:15 scene (the hyperspectral cube) and the sentence "And an alert that arrives late is worth almost nothing." in the 0:15 scene. That leaves about 430 words (≈3:05).

---

## 60-second cut-down

| Time | On-screen visual | Narration | On-screen text |
|---|---|---|---|
| 0:00–0:10 | 90 GB vs 21 GB counters | A satellite collects ninety gigabytes a day and can send about twenty. Onboard, it must decide what to keep. | 90 GB vs 21 GB |
| 0:10–0:25 | Engine diagram → formula card | Our engine prices every scarce resource: downlink, battery, GPU, storage. Every item picks its best net-value option: process now, store, transmit or drop. It re-plans every thirty seconds, and every decision is explained. | U = EV − Σ λᵣ · useᵣ |
| 0:25–0:45 | `value_by_scenario.png` → `energy_by_scenario.png` | Flown on Sentinel-2A's real orbit for four hundred simulated days, it delivered the most value in four of five scenarios, winning every day, and tied in the fifth. That's up to twenty-one percent more than a hand-tuned operator, with up to thirty-five percent less energy. | Real orbit · best in 4/5, tie in 1 · up to +21% value · up to −35% energy |
| 0:45–1:00 | Dashboard replay → QR | Code, dataset and dashboard are open. Let's make every megabyte count. | **Make every megabyte count** · [QR] |

(108 words: roughly 50 s of speech plus pauses and the end card.)

---

## Recording notes

- **Tone:** confident, plain, and concrete. Avoid jargon on screen; the voice-over may say "shadow prices" once, but the on-screen text should say "every resource has a price".
- **Pacing:** about 140 wpm. Pause about half a second after each result number. Let each chart stay on screen for at least 4 seconds after its number is spoken.
- **Colours:** keep them consistent with the figures:
  - value-aware (ours): blue `#2a78d6`
  - priority rules: orange `#eb6834`
  - process-all: aqua `#1baf7a`
  - bent-pipe: yellow `#eda100`
  - text: `#0b0b0b` / `#52514e` on `#fcfcfb`
- **Screens to capture from the dashboard** (`dashboard/index.html` or its published link):
  1. **Replay view:** play the simulated day at speed, then pause on a ground pass. Show the battery, storage and cumulative-value tracks, then the decision log with the engine's explanations.
  2. **Policy comparison view:** switch between the five scenario tabs, with the value and energy bars for all four strategies visible.
  3. **Header:** the line showing "SENTINEL-2A TLE · CNES Toulouse" (proof that the orbit is real).
- **Figures to use full-screen** (all in `docs/figures/`):
  - `value_by_scenario.png`
  - `energy_by_scenario.png`
  - `timeline_energy_starved.png`
  - `outcomes.png` (optional b-roll behind the limitations card)
- **Accuracy guardrails** (do not round these differently in the edit):
  - **Orbit:** Sentinel-2A TLE of 26 Sep 2026 (CelesTrak), SGP4 via skyfield, CNES Toulouse above 10°, 4.4 passes/day, eclipses of 34 min per 101-min orbit, and ~21.5 GB/day of downlink. The instruments generate 89.7 GB/day on average.
  - **Value gain vs the rules:** +2.7% to +20.5% in four scenarios, and −0.3% (a statistical tie) when storage is tight. Vs process-all: +6.0% to +59.4% in the same four.
  - **Paired over identical days:** 20/20 wins against both baselines in four scenarios.
  - **Energy vs the processing baselines:** −2% to −35%. Nominal: −22% vs both the rules and process-all.
  - **Energy-starved:**

    | Strategy | Mean lowest battery charge | Time below reserve |
    |---|---|---|
    | Process-all | 4.4% | 42.6% |
    | Rules | 24.5% | 3.3% |
    | Ours | 35.0% | 1.1% |

  - **Nominal:**

    | Measure | Ours | Rules |
    |---|---|---|
    | Completion | 79.4% | 84.7% |
    | Items delivered | 65.0% | 63.5% |
    | True alerts delivered | 71.6% | 71.8% (same alert latency, 140 min) |

- **Captions:** burn in subtitles. Many viewers watch without sound.
