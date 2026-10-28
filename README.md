# Intelligent Packet Scheduler (QoS-Aware DRL vs Traditional Schedulers)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyTorch](https://img.shields.io/badge/PyTorch-EE4C2C?logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=Streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An intelligent Deep Reinforcement Learning (DQN) packet scheduler for Quality-of-Service (QoS) management in network routers. It dynamically balances latency-critical traffic against high-throughput data and benchmarks performance against classic network scheduling algorithms: **FIFO**, **Strict Priority (PQ)**, and **Weighted Fair Queueing (WFQ)**.

---

## 🌟 Key Highlights

- **Dynamic QoS Adaptation**: Uses a Deep Q-Network (DQN) agent to make per-packet scheduling decisions in real-time under changing traffic loads.
- **Multi-Class Traffic Simulation**: Simulates Poisson voice traffic (ultra-low latency), bursty VBR video streaming, and heavy-tailed Pareto bulk transfers.
- **Fairness & SLA Protection**: Prevents queue starvation for low-priority bulk traffic while guaranteeing strict delay deadlines for VoIP and video.
- **Interactive Web Dashboard**: Streamlit-based UI for live parameter tuning, step-by-step queue visualization, and performance comparisons.

---

## 🏗️ Architecture

```
                          +------------------------+
                          |   Traffic Generator    |
                          | (Voice, Video, Bulk)   |
                          +-----------+------------+
                                      |
                                      v
                          +------------------------+
                          |   Multi-Queue Buffer   |
                          | (Per-Class Deadlines)  |
                          +-----------+------------+
                                      |
                      +---------------+---------------+
                      |                               |
                      v                               v
          +-----------------------+       +-----------------------+
          | Traditional Schedulers|       |   DQN Agent (DRL)     |
          |   (FIFO / PQ / WFQ)   |       | (State -> Action)     |
          +-----------+-----------+       +-----------+-----------+
                      |                               |
                      +---------------+---------------+
                                      |
                                      v
                          +------------------------+
                          |    Bottleneck Link     |
                          +-----------+------------+
                                      |
                                      v
                          +------------------------+
                          |   QoS Metrics Engine   |
                          | (Delay, Loss, Fairness)|
                          +------------------------+
```

### Modular Components
1. **Traffic Generator & Queues (`traffic_generator.py`, `packet_queue.py`)**: Simulates voice (Queue 0), video (Queue 1), and bulk data (Queue 2) with deadline enforcement and drop policies.
2. **Traditional Baseline Schedulers (`schedulers.py`)**: FIFO, Strict Priority Queueing (PQ), and Deficit Weighted Round Robin (WFQ).
3. **DQN Agent & Gym Environment (`environment.py`, `train_dqn.py`)**: 13-dimensional continuous state space, discrete action space, and QoS-guided reward function.
4. **QoS Measurement Engine (`qos_metrics.py`)**: Computes Average & 95th-percentile Latency, Jitter, Packet Drop Rate, Throughput, and Jain's Fairness Index.
5. **Interactive Dashboard & Benchmark Suite (`dashboard.py`, `evaluate.py`)**: Comprehensive Streamlit application with Plotly analytics.

---

## 📊 Experimental Results

| Metric | FIFO | Strict Priority (PQ) | Weighted Fair (WFQ) | DQN Intelligent |
| :--- | :--- | :--- | :--- | :--- |
| **Voice Latency** | High (Head-of-Line blocking) | Ultra-low | Low–Medium | **Ultra-low (Optimized)** |
| **Bulk Latency** | Moderate | Extreme / Starvation | Fair | **Controlled** |
| **Packet Loss %** | High under congestion | High on Bulk | Moderate | **Lowest overall** |
| **Jain's Fairness Index** | High throughput fairness | Low (~0.50 Starvation) | High (~0.90) | **High (~0.88 – 0.93)** |

---

## 🚀 Quickstart

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/ajayjacob-hue/intelligent-packet-scheduler.git
cd intelligent-packet-scheduler
pip install -r requirements.txt
```

### 2. Train the DQN Model
Train the reinforcement learning agent (pre-trained checkpoint also included in `models/`):
```bash
python train_dqn.py
```

### 3. Run Benchmark Evaluation
Compare all schedulers across Normal, Congested, and Dynamic traffic loads:
```bash
python evaluate.py
```

### 4. Launch the Interactive Dashboard
```bash
streamlit run dashboard.py
```

---

## 🧠 DRL Model Specifications

- **State Vector ($S_t \in \mathbb{R}^{13}$)**: Queue occupancies, head-of-line waiting times, moving average delays, bottleneck link status, and near-deadline packet ratios.
- **Action Space ($A_t \in \{0, 1, 2\}$)**: Dispatch Voice (0), Video (1), or Bulk (2).
- **Reward Function**:
  $$R_t = \alpha S_t - \beta D_t - \gamma L_t - \delta J_t - \lambda U_t$$
  Penalizes packet drops, SLA deadline violations, voice jitter, and queue starvation.

---

## 📜 License
Distributed under the MIT License. See `LICENSE` for more information.
