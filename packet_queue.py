"""
Packet Queue and Bottleneck Link Simulator Module.
Manages three distinct traffic queues (Voice, Video, Bulk) with finite capacity,
handles drops due to buffer overflow or deadline expiration, and simulates transmission
over a bottleneck link.
"""

from collections import deque
from typing import List, Dict, Tuple, Optional
from traffic_generator import Packet, TRAFFIC_CLASS_NAMES

class PacketQueueSystem:
    """
    Simulates a multi-queue buffer system attached to a single shared bottleneck link.
    """
    def __init__(
        self,
        queue_capacities: Optional[Dict[int, int]] = None, # max packets per queue
        link_bandwidth_mbps: float = 6.0,                  # Mbps
        drop_expired_packets: bool = True
    ):
        # Default capacity: 50 packets per traffic queue
        self.max_capacity = queue_capacities or {0: 50, 1: 50, 2: 50}
        self.link_bandwidth_mbps = link_bandwidth_mbps
        self.drop_expired_packets = drop_expired_packets
        
        # 3 Queues: 0 (Voice), 1 (Video), 2 (Bulk)
        self.queues: Dict[int, deque] = {
            0: deque(),
            1: deque(),
            2: deque()
        }
        
        # Link state tracking
        self.link_busy_until: float = 0.0
        self.current_packet_transmitting: Optional[Packet] = None
        self.total_bits_transmitted: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        
        # Performance history
        self.delivered_packets: List[Packet] = []
        self.dropped_packets: List[Packet] = []
        self.generated_packets_count: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        
    def reset(self):
        """Reset queue states and metrics counters."""
        for q in self.queues.values():
            q.clear()
        self.link_busy_until = 0.0
        self.current_packet_transmitting = None
        self.total_bits_transmitted = {0: 0, 1: 0, 2: 0}
        self.delivered_packets.clear()
        self.dropped_packets.clear()
        self.generated_packets_count = {0: 0, 1: 0, 2: 0}

    def enqueue_packets(self, packets: List[Packet], current_time_ms: float):
        """
        Add newly arrived packets to their respective traffic queues.
        If a queue exceeds its maximum capacity, drop arriving packet.
        """
        for pkt in packets:
            self.generated_packets_count[pkt.traffic_type] += 1
            pkt.queue_entry_time = current_time_ms
            
            q = self.queues[pkt.traffic_type]
            if len(q) < self.max_capacity[pkt.traffic_type]:
                q.append(pkt)
            else:
                # Buffer overflow drop
                pkt.dropped = True
                pkt.drop_reason = "buffer_overflow"
                pkt.departure_time = current_time_ms
                self.dropped_packets.append(pkt)

    def purge_expired_packets(self, current_time_ms: float):
        """
        Check head-of-queue packets; if any have exceeded their deadline before service,
        drop them if drop_expired_packets is enabled.
        """
        if not self.drop_expired_packets:
            return
            
        for t_type, q in self.queues.items():
            to_remove = []
            for pkt in list(q):
                if current_time_ms > pkt.deadline:
                    to_remove.append(pkt)
                    
            for pkt in to_remove:
                q.remove(pkt)
                pkt.dropped = True
                pkt.drop_reason = "deadline_exceeded"
                pkt.departure_time = current_time_ms
                pkt.queuing_delay = current_time_ms - pkt.arrival_time
                self.dropped_packets.append(pkt)

    def get_transmission_duration_ms(self, size_bytes: int) -> float:
        """
        Calculate transmission time in milliseconds for packet size over bottleneck link.
        Duration (ms) = (size_bytes * 8 bits) / (bandwidth_mbps * 1,000,000 bits/sec) * 1000 ms/sec
                      = (size_bytes * 8) / (bandwidth_mbps * 1000)
        """
        bits = size_bytes * 8
        bits_per_ms = self.link_bandwidth_mbps * 1000.0
        return bits / bits_per_ms

    def serve_queue(self, traffic_type: int, current_time_ms: float) -> Optional[Packet]:
        """
        Dequeues a packet from selected queue if link is free and queue is non-empty.
        Computes queuing delay, transmission delay, and schedules link busy time.
        """
        # Purge any expired packets first
        self.purge_expired_packets(current_time_ms)
        
        q = self.queues.get(traffic_type, deque())
        if len(q) == 0:
            return None
            
        pkt: Packet = q.popleft()
        
        # Compute delay metrics
        pkt.queuing_delay = max(0.0, current_time_ms - pkt.arrival_time)
        tx_duration = self.get_transmission_duration_ms(pkt.size_bytes)
        pkt.transmission_delay = tx_duration
        pkt.departure_time = current_time_ms + tx_duration
        pkt.total_delay = pkt.queuing_delay + tx_duration
        
        # Check deadline upon departure
        if pkt.departure_time > pkt.deadline and self.drop_expired_packets:
            pkt.dropped = True
            pkt.drop_reason = "deadline_exceeded"
            self.dropped_packets.append(pkt)
        else:
            self.delivered_packets.append(pkt)
            self.total_bits_transmitted[pkt.traffic_type] += (pkt.size_bytes * 8)
            
        self.link_busy_until = pkt.departure_time
        self.current_packet_transmitting = pkt
        return pkt

    def is_link_busy(self, current_time_ms: float) -> bool:
        return current_time_ms < self.link_busy_until

    def get_queue_lengths(self) -> Dict[int, int]:
        return {k: len(v) for k, v in self.queues.items()}

    def get_oldest_waiting_time(self, current_time_ms: float) -> Dict[int, float]:
        """Returns waiting time in ms of the oldest packet in each queue."""
        oldest = {0: 0.0, 1: 0.0, 2: 0.0}
        for k, q in self.queues.items():
            if len(q) > 0:
                oldest[k] = max(0.0, current_time_ms - q[0].arrival_time)
        return oldest

    def get_packets_near_deadline(self, current_time_ms: float, threshold_ratio: float = 0.75) -> Dict[int, int]:
        """Count packets that have consumed > 75% of their allowed delay."""
        near_dead = {0: 0, 1: 0, 2: 0}
        for k, q in self.queues.items():
            for pkt in q:
                elapsed = current_time_ms - pkt.arrival_time
                if elapsed / pkt.max_allowed_delay >= threshold_ratio:
                    near_dead[k] += 1
        return near_dead
