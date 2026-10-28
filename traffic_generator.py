"""
Traffic Generator Module for Network Packet Scheduler.
Generates synthetic traffic for Voice, Video, and Bulk Data traffic classes
with customizable arrival distributions, packet sizes, and QoS deadlines.
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

TRAFFIC_CLASS_NAMES = {0: "Voice", 1: "Video", 2: "Bulk Data"}

@dataclass
class Packet:
    packet_id: int
    traffic_type: int          # 0: Voice, 1: Video, 2: Bulk Data
    size_bytes: int            # Packet size in bytes
    arrival_time: float        # Simulation time when generated (ms)
    max_allowed_delay: float   # Max acceptable delay / deadline limit (ms)
    deadline: float            # Absolute deadline timestamp = arrival_time + max_allowed_delay
    
    # Dynamics tracking
    queue_entry_time: Optional[float] = None
    departure_time: Optional[float] = None
    queuing_delay: float = 0.0
    transmission_delay: float = 0.0
    total_delay: float = 0.0
    dropped: bool = False
    drop_reason: Optional[str] = None  # 'buffer_overflow' or 'deadline_exceeded'


class TrafficGenerator:
    """
    Traffic Generator supporting 3 traffic profiles:
    - Voice: High priority, small packets (64-160B), tight deadline (30ms), Poisson/periodic arrival
    - Video: Medium priority, medium/large packets (500-1200B), moderate deadline (100ms), VBR bursty arrival
    - Bulk Data: Low priority, large MTU packets (1500B), loose deadline (500ms), Pareto/TCP arrival
    """
    def __init__(self, seed: Optional[int] = None):
        self.rng = np.random.default_rng(seed)
        self.next_packet_id = 1
        
        # Base traffic configuration (mean arrival rate per ms under intensity=1.0)
        # Rates (packets per ms):
        # Voice: ~0.15 pkts/ms = 150 pkts/sec (~144 kbps)
        # Video: ~0.25 pkts/ms = 250 pkts/sec (~2.0 Mbps)
        # Bulk: ~0.40 pkts/ms = 400 pkts/sec (~4.8 Mbps)
        self.base_rates = {
            0: 0.18,  # Voice pkts/ms
            1: 0.30,  # Video pkts/ms
            2: 0.45   # Bulk pkts/ms
        }
        
    def set_seed(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.next_packet_id = 1

    def generate_packets_in_interval(
        self,
        current_time_ms: float,
        interval_ms: float,
        intensity: float = 1.0,
        scenario: str = "normal"
    ) -> List[Packet]:
        """
        Generate arriving packets for a given time interval dt.
        """
        # Adjust intensity according to scenario
        eff_intensity = intensity
        if scenario == "congested":
            eff_intensity = intensity * 1.8
        elif scenario == "changing":
            # Dynamic wave scenario (sine wave + burst pattern over time)
            cycle_phase = (current_time_ms % 10000) / 10000.0  # 10s cycle
            if cycle_phase < 0.3:
                eff_intensity = intensity * 0.6  # Low phase
            elif cycle_phase < 0.7:
                eff_intensity = intensity * 2.2  # Heavy congestion phase
            else:
                eff_intensity = intensity * 1.2  # Moderate phase
                
        packets: List[Packet] = []
        
        # --- 1. Voice Packets (Poisson process) ---
        lambda_voice = self.base_rates[0] * eff_intensity * interval_ms
        num_voice = self.rng.poisson(lambda_voice)
        for _ in range(num_voice):
            offset = self.rng.uniform(0, interval_ms)
            arr_time = current_time_ms + offset
            size = int(self.rng.choice([64, 96, 128, 160, 200]))
            max_delay = float(self.rng.uniform(25.0, 35.0))  # ~30ms target
            packets.append(Packet(
                packet_id=self.next_packet_id,
                traffic_type=0,
                size_bytes=size,
                arrival_time=arr_time,
                max_allowed_delay=max_delay,
                deadline=arr_time + max_delay
            ))
            self.next_packet_id += 1

        # --- 2. Video Packets (Bursty VBR - Markov-like burst model) ---
        lambda_video = self.base_rates[1] * eff_intensity * interval_ms
        # Introduce burst factor
        is_burst = self.rng.random() < 0.25
        if is_burst:
            lambda_video *= 2.5
            
        num_video = self.rng.poisson(lambda_video)
        for _ in range(num_video):
            offset = self.rng.uniform(0, interval_ms)
            arr_time = current_time_ms + offset
            size = int(self.rng.normal(loc=950, scale=200))
            size = int(np.clip(size, 400, 1400))
            max_delay = float(self.rng.uniform(80.0, 120.0))  # ~100ms target
            packets.append(Packet(
                packet_id=self.next_packet_id,
                traffic_type=1,
                size_bytes=size,
                arrival_time=arr_time,
                max_allowed_delay=max_delay,
                deadline=arr_time + max_delay
            ))
            self.next_packet_id += 1

        # --- 3. Bulk Data Packets (Pareto / Heavy-tailed TCP stream) ---
        lambda_bulk = self.base_rates[2] * eff_intensity * interval_ms
        num_bulk = self.rng.poisson(lambda_bulk)
        for _ in range(num_bulk):
            offset = self.rng.uniform(0, interval_ms)
            arr_time = current_time_ms + offset
            # MTU size bulk packets mostly
            size = int(self.rng.choice([512, 1024, 1500, 1500, 1500]))
            max_delay = float(self.rng.uniform(400.0, 600.0))  # ~500ms target
            packets.append(Packet(
                packet_id=self.next_packet_id,
                traffic_type=2,
                size_bytes=size,
                arrival_time=arr_time,
                max_allowed_delay=max_delay,
                deadline=arr_time + max_delay
            ))
            self.next_packet_id += 1

        # Sort packets by arrival time within the interval
        packets.sort(key=lambda p: p.arrival_time)
        return packets
