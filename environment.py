"""
Gymnasium Environment for Intelligent Network Packet Scheduling.
Encapsulates the discrete network simulator, observation state vector, action space,
and QoS-oriented multi-objective reward structure.
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from collections import deque
from typing import Dict, Any, Tuple, Optional

from traffic_generator import TrafficGenerator, Packet
from packet_queue import PacketQueueSystem

class PacketSchedulerEnv(gym.Env):
    """
    Custom Gymnasium Environment for QoS Network Packet Scheduler.
    
    Observation Space (13 continuous features):
    - [0-2]: Queue length ratios (voice, video, bulk)
    - [3-5]: Oldest packet waiting time normalized
    - [6-8]: Recent exponential moving average delay per class
    - [9]: Link utilization ratio
    - [10-12]: Fraction of packets approaching deadline (>75% max_delay)
    
    Action Space (Discrete 3):
    - 0: Serve Voice Queue
    - 1: Serve Video Queue
    - 2: Serve Bulk Data Queue
    """
    metadata = {"render_modes": []}

    def __init__(
        self,
        link_bandwidth_mbps: float = 6.0,
        queue_capacities: Optional[Dict[int, int]] = None,
        traffic_intensity: float = 1.0,
        scenario: str = "normal",
        step_duration_ms: float = 1.0,
        max_steps: int = 1000,
        seed: Optional[int] = None
    ):
        super().__init__()
        
        self.link_bandwidth_mbps = link_bandwidth_mbps
        self.queue_capacities = queue_capacities or {0: 50, 1: 50, 2: 50}
        self.traffic_intensity = traffic_intensity
        self.scenario = scenario
        self.step_duration_ms = step_duration_ms
        self.max_steps = max_steps
        
        # Generator & Queue System
        self.traffic_gen = TrafficGenerator(seed=seed)
        self.queue_sys = PacketQueueSystem(
            queue_capacities=self.queue_capacities,
            link_bandwidth_mbps=self.link_bandwidth_mbps
        )
        
        # Action space: 0 (Voice), 1 (Video), 2 (Bulk)
        self.action_space = spaces.Discrete(3)
        
        # State observation vector: 13 floats bounded [0.0, 10.0]
        self.observation_space = spaces.Box(
            low=0.0,
            high=10.0,
            shape=(13,),
            dtype=np.float32
        )
        
        # Tracking internal state
        self.current_step = 0
        self.current_time_ms = 0.0
        self.recent_delays = {0: [0.0], 1: [0.0], 2: [0.0]}
        self.recent_served_classes = deque(maxlen=30)
        self.link_busy_steps = 0
        
        # Multi-objective balanced QoS reward weighting
        self.alpha = 1.0     # Delivered service & SLA compliance coefficient
        self.beta = 1.0      # Delay / SLA violation penalty coefficient
        self.gamma = 2.5     # Loss penalty coefficient (overflow + purge)
        self.delta = 0.2     # Jitter penalty coefficient
        self.lambda_u = 0.8  # Starvation prevention penalty coefficient
        self.lambda_p = 0.5  # Buffer congestion pressure penalty coefficient
        self.lambda_f = 0.6  # Fairness bonus coefficient

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            self.traffic_gen.set_seed(seed)
            
        self.queue_sys.reset()
        self.current_step = 0
        self.current_time_ms = 0.0
        self.recent_delays = {0: [0.0], 1: [0.0], 2: [0.0]}
        self.recent_served_classes.clear()
        self.link_busy_steps = 0
        
        # Pre-fill initial traffic for 5ms to warm up queues
        initial_pkts = self.traffic_gen.generate_packets_in_interval(
            current_time_ms=0.0,
            interval_ms=5.0,
            intensity=self.traffic_intensity,
            scenario=self.scenario
        )
        self.queue_sys.enqueue_packets(initial_pkts, current_time_ms=0.0)
        self.current_time_ms = 5.0
        
        obs = self._get_observation()
        return obs, {}

    def _get_observation(self) -> np.ndarray:
        q_len = self.queue_sys.get_queue_lengths()
        oldest = self.queue_sys.get_oldest_waiting_time(self.current_time_ms)
        near_dead = self.queue_sys.get_packets_near_deadline(self.current_time_ms)
        
        # Feature 0-2: Queue lengths normalized by capacity
        f0 = q_len[0] / self.queue_capacities[0]
        f1 = q_len[1] / self.queue_capacities[1]
        f2 = q_len[2] / self.queue_capacities[2]
        
        # Feature 3-5: Oldest packet wait time normalized by max expected delay
        f3 = oldest[0] / 30.0
        f4 = oldest[1] / 100.0
        f5 = oldest[2] / 500.0
        
        # Feature 6-8: Average recent delays per class
        f6 = float(np.mean(self.recent_delays[0][-10:])) / 50.0
        f7 = float(np.mean(self.recent_delays[1][-10:])) / 150.0
        f8 = float(np.mean(self.recent_delays[2][-10:])) / 500.0
        
        # Feature 9: Link utilization
        f9 = 1.0 if self.queue_sys.is_link_busy(self.current_time_ms) else 0.0
        
        # Feature 10-12: Near deadline count ratios
        f10 = near_dead[0] / self.queue_capacities[0]
        f11 = near_dead[1] / self.queue_capacities[1]
        f12 = near_dead[2] / self.queue_capacities[2]
        
        obs = np.array([f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12], dtype=np.float32)
        return np.clip(obs, 0.0, 10.0)

    def get_action_mask(self) -> np.ndarray:
        """Returns boolean mask where True indicates a queue has packets waiting."""
        q_len = self.queue_sys.get_queue_lengths()
        mask = np.array([q_len[0] > 0, q_len[1] > 0, q_len[2] > 0], dtype=bool)
        if not np.any(mask):
            return np.ones(3, dtype=bool)
        return mask

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        self.current_step += 1
        start_time = self.current_time_ms
        
        # 1. Generate new packet arrivals for this step duration
        new_pkts = self.traffic_gen.generate_packets_in_interval(
            current_time_ms=start_time,
            interval_ms=self.step_duration_ms,
            intensity=self.traffic_intensity,
            scenario=self.scenario
        )
        self.queue_sys.enqueue_packets(new_pkts, current_time_ms=start_time)
        
        # Count initial dropped packets in this step (from overflow during arrival)
        dropped_before = len(self.queue_sys.dropped_packets)
        
        # 2. Execute scheduling action
        service_reward = 0.0
        delay_penalty = 0.0
        invalid_action_penalty = 0.0
        fairness_bonus = 0.0
        served_pkt: Optional[Packet] = None
        
        # If link is free, dispatch packet according to action
        if not self.queue_sys.is_link_busy(start_time):
            target_q = action
            q_len = len(self.queue_sys.queues[target_q])
            
            # Handle empty queue: fall back to urgency (Earliest Deadline) instead of static PQ
            if q_len == 0:
                invalid_action_penalty = 0.1
                best_fq = None
                highest_urgency = -1.0
                for fq in [0, 1, 2]:
                    if len(self.queue_sys.queues[fq]) > 0:
                        head_pkt = self.queue_sys.queues[fq][0]
                        urgency = (start_time - head_pkt.arrival_time) / head_pkt.max_allowed_delay
                        if urgency > highest_urgency:
                            highest_urgency = urgency
                            best_fq = fq
                if best_fq is not None:
                    target_q = best_fq
                        
            if len(self.queue_sys.queues[target_q]) > 0:
                served_pkt = self.queue_sys.serve_queue(target_q, current_time_ms=start_time)
                if served_pkt and not served_pkt.dropped:
                    # SLA targets: Voice < 25ms, Video < 80ms, Bulk < 350ms
                    sla_targets = {0: 25.0, 1: 80.0, 2: 350.0}
                    sla_target = sla_targets[served_pkt.traffic_type]
                    
                    base_delivery = served_pkt.size_bytes / 1000.0
                    
                    if served_pkt.total_delay <= sla_target:
                        # Met SLA: reward bonus with mild delay penalty
                        sla_bonus = 1.0
                        delay_penalty = 0.15 * (served_pkt.total_delay / sla_target)
                    else:
                        # Violated SLA: progressive violation penalty
                        sla_bonus = 0.0
                        excess_ratio = (served_pkt.total_delay - sla_target) / sla_target
                        delay_penalty = 1.5 * (excess_ratio ** 1.3)
                        
                    service_reward = base_delivery + sla_bonus
                    self.recent_delays[served_pkt.traffic_type].append(served_pkt.total_delay)
                    self.recent_served_classes.append(served_pkt.traffic_type)
                    self.link_busy_steps += 1

        # Purge expired packets at current time
        self.queue_sys.purge_expired_packets(start_time)
        
        # 3. Compute loss penalty (overflows & deadline drops during step)
        dropped_after = len(self.queue_sys.dropped_packets)
        new_drops = dropped_after - dropped_before
        loss_penalty = new_drops * 2.5
        
        # 4. Compute Jitter penalty (voice delay variance)
        voice_delays = self.recent_delays[0][-5:]
        jitter_penalty = float(np.std(voice_delays)) / 20.0 if len(voice_delays) > 1 else 0.0
        
        # 5. Proactive Starvation Penalty across all queues
        oldest = self.queue_sys.get_oldest_waiting_time(start_time)
        starvation_penalty = 0.0
        if oldest[0] > 18.0:
            starvation_penalty += ((oldest[0] - 18.0) / 12.0) ** 1.5
        if oldest[1] > 60.0:
            starvation_penalty += ((oldest[1] - 60.0) / 40.0) ** 1.5
        if oldest[2] > 120.0:
            starvation_penalty += ((oldest[2] - 120.0) / 100.0) ** 1.5

        # 6. Proactive Buffer Congestion Pressure (prevent overflow before it happens)
        buffer_pressure_penalty = 0.0
        q_lens = self.queue_sys.get_queue_lengths()
        for q_i in [0, 1, 2]:
            ratio = q_lens[q_i] / self.queue_capacities[q_i]
            if ratio > 0.6:
                buffer_pressure_penalty += ((ratio - 0.6) / 0.4) ** 2.0

        # 7. Live Jain's Fairness Incentive across recent serviced packets
        if len(self.recent_served_classes) >= 10:
            counts = [self.recent_served_classes.count(c) for c in [0, 1, 2]]
            sum_c = sum(counts)
            sum_sq = sum(c * c for c in counts)
            if sum_sq > 0:
                jains_idx = (sum_c ** 2) / (3.0 * sum_sq)
                fairness_bonus = jains_idx
        
        # Total composite reward equation
        step_reward = (
            self.alpha * service_reward
            - self.beta * delay_penalty
            - self.gamma * loss_penalty
            - self.delta * jitter_penalty
            - self.lambda_u * starvation_penalty
            - self.lambda_p * buffer_pressure_penalty
            + self.lambda_f * fairness_bonus
            - invalid_action_penalty
        )
        
        self.current_time_ms += self.step_duration_ms
        obs = self._get_observation()
        
        terminated = self.current_step >= self.max_steps
        truncated = False
        
        info = {
            "step_reward": step_reward,
            "service_reward": service_reward,
            "delay_penalty": delay_penalty,
            "loss_penalty": loss_penalty,
            "jitter_penalty": jitter_penalty,
            "starvation_penalty": starvation_penalty,
            "fairness_bonus": fairness_bonus
        }
        
        return obs, float(step_reward), terminated, truncated, info
