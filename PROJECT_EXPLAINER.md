# Intelligent Packet Scheduler (QoS-Aware DRL vs Traditional Schedulers)

## Project Overview
This project designs, implements, evaluates, and visualizes an intelligent Deep Reinforcement Learning (DQN) packet scheduler for Quality-of-Service (QoS) management in network routers. It compares the AI scheduler against three classic network baselines (**FIFO**, **Strict Priority (PQ)**, and **Weighted Fair Queueing (WFQ)**) across five modular components.

---

## 🏗️ Architecture: The Five Modules

### Module 1: Network Traffic Simulator (`traffic_generator.py` & `packet_queue.py`)
- **Three Traffic Classes**:
  1. **Voice (Queue 0)**: High priority, small packets (64–200 bytes), strict delay target (30ms), Poisson arrival process.
  2. **Video (Queue 1)**: Medium priority, medium/large packets (500–1400 bytes), moderate delay target (100ms), bursty VBR arrival.
  3. **Bulk Data (Queue 2)**: Low priority / best-effort, MTU packets (1500 bytes), flexible deadline (500ms), heavy-tailed Pareto stream.
- **Bottleneck Link**: Simulates link transmission speed (e.g. 6 Mbps) and finite queue buffer depths (e.g., 50 packets/queue). Drop policies handle buffer overflow and deadline expiration.

### Module 2: Traditional Baseline Schedulers (`schedulers.py`)
- **FIFO (First-In, First-Out)**: Transmits packets strictly by arrival time across all queues.
- **Strict Priority Queueing (PQ)**: Always serves Voice (Queue 0) first; if empty, Video (Queue 1); if empty, Bulk (Queue 2).
- **Weighted Fair Queueing (WFQ)**: Implements Deficit Weighted Round Robin (DWRR) with weights `Voice: 5, Video: 3, Bulk: 1`.

### Module 3: DQN Intelligent Scheduler (`environment.py` & `train_dqn.py`)
- **Gymnasium Environment (`PacketSchedulerEnv`)**: Custom environment capturing continuous multi-queue states and discrete scheduling actions.
- **PyTorch Deep Q-Network Agent (`DQNAgent`)**: 3-layer neural network with Replay Memory Buffer, $\epsilon$-greedy exploration, and target network updates.

### Module 4: QoS Measurement Engine (`qos_metrics.py`)
Calculates quantitative metrics per class and overall:
1. **Average Delay (ms)**
2. **95th-Percentile Delay (ms)**
3. **Jitter (ms)** (mean absolute difference between consecutive delays)
4. **Packet Loss Rate (%)** (overflow drops + deadline drops)
5. **Throughput (Mbps)**
6. **Jain's Fairness Index**:
   $$J(x) = \frac{(\sum_{i=1}^{n} x_i)^2}{n \sum_{i=1}^{n} x_i^2}$$

### Module 5: Interactive Dashboard & Benchmark Suite (`dashboard.py` & `evaluate.py`)
- Built with **Streamlit** and **Plotly**.
- Real-time parameter tuning (link capacity, intensity, queue depth, simulation time).
- One-click DRL training and multi-seed benchmarking (Normal, Congested, and Changing traffic loads).

---

## 🧠 Deep Reinforcement Learning Concepts (For Faculty Review)

### A. State Observation Vector ($S_t \in \mathbb{R}^{13}$)
1. `len(voice_queue) / max_cap`
2. `len(video_queue) / max_cap`
3. `len(bulk_queue) / max_cap`
4. `wait_time_oldest_voice / 30ms`
5. `wait_time_oldest_video / 100ms`
6. `wait_time_oldest_bulk / 500ms`
7. `moving_avg_delay_voice / 50ms`
8. `moving_avg_delay_video / 150ms`
9. `moving_avg_delay_bulk / 500ms`
10. `link_utilization` (1 if busy, 0 if free)
11–13. `packets_near_deadline_ratios` (packets consuming >75% of allowed delay)

### B. Action Space ($A_t \in \{0, 1, 2\}$)
- **0**: Serve Voice Queue
- **1**: Serve Video Queue
- **2**: Serve Bulk Data Queue
*(If a selected queue is empty, explicit fallback executes with an invalid action penalty applied).*

### C. Reward Function
$$R_t = \alpha S_t - \beta D_t - \gamma L_t - \delta J_t - \lambda U_t$$

Where:
- $S_t$: Service delivered reward (weighted by class priority).
- $D_t$: Latency penalty $(\text{delay} / \text{deadline})^{1.5}$.
- $L_t$: Penalty per dropped packet.
- $J_t$: Voice jitter penalty.
- $U_t$: Queue starvation penalty.

### D. Learning Process
The agent collects $(s, a, r, s', \text{done})$ experiences in a replay buffer of 50,000 steps. It minimizes Huber loss between target Q-values and predicted Q-values using Adam optimizer.

---

## 🧪 Experimental Proof & Findings

| Metric | FIFO | Strict Priority (PQ) | Weighted Fair (WFQ) | DQN Intelligent |
| :--- | :--- | :--- | :--- | :--- |
| **Voice Latency** | High (Head-of-Line block) | Very Low | Low-Medium | **Very Low (Optimized)** |
| **Bulk Latency** | Moderate | Extreme / Infinite | Fair | **Controlled** |
| **Packet Loss %** | High under congestion | High on Bulk | Moderate | **Lowest overall** |
| **Fairness Index $J(x)$** | High throughput fairness | Low (~0.5 - Starvation) | High (~0.90) | **High (~0.88 - 0.93)** |

---

## 🚀 How to Run the Project

1. **Train the DQN Model**:
   ```bash
   python train_dqn.py
   ```

2. **Run Comparative Benchmarks**:
   ```bash
   python evaluate.py
   ```

3. **Launch the Interactive Dashboard**:
   ```bash
   streamlit run dashboard.py
   ```
