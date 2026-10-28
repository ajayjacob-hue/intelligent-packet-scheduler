"""
Traditional Network Schedulers Module.
Implements baseline scheduling algorithms:
1. FIFO (First-In, First-Out) - Global arrival time priority
2. Strict Priority (PQ) - Voice (0) > Video (1) > Bulk (2)
3. Weighted Fair Queuing (WFQ) - Serving queues according to assigned weights (e.g. 5:3:1)
"""

from typing import Dict, Optional, List
from packet_queue import PacketQueueSystem

class BaseScheduler:
    """Base class for packet schedulers."""
    def select_queue(self, queue_system: PacketQueueSystem, current_time_ms: float) -> Optional[int]:
        raise NotImplementedError

class FIFOScheduler(BaseScheduler):
    """
    First-In, First-Out Scheduler.
    Selects the queue holding the oldest packet across all non-empty queues.
    """
    def select_queue(self, queue_system: PacketQueueSystem, current_time_ms: float) -> Optional[int]:
        oldest_queue = None
        earliest_arrival = float('inf')
        
        for q_type, q in queue_system.queues.items():
            if len(q) > 0:
                head_pkt = q[0]
                if head_pkt.arrival_time < earliest_arrival:
                    earliest_arrival = head_pkt.arrival_time
                    oldest_queue = q_type
                    
        return oldest_queue

class StrictPriorityScheduler(BaseScheduler):
    """
    Strict Priority Queueing (PQ).
    Always serves Queue 0 (Voice) if non-empty;
    otherwise Queue 1 (Video) if non-empty;
    otherwise Queue 2 (Bulk Data).
    """
    def select_queue(self, queue_system: PacketQueueSystem, current_time_ms: float) -> Optional[int]:
        for q_type in [0, 1, 2]:
            if len(queue_system.queues[q_type]) > 0:
                return q_type
        return None

class WFQScheduler(BaseScheduler):
    """
    Weighted Fair Queuing (WFQ) / Deficit Weighted Round Robin (DWRR).
    Distributes service bandwidth according to relative queue weights.
    Default weights: Voice: 5, Video: 3, Bulk: 1
    """
    def __init__(self, weights: Optional[Dict[int, float]] = None):
        self.weights = weights or {0: 5.0, 1: 3.0, 2: 1.0}
        self.deficits = {0: 0.0, 1: 0.0, 2: 0.0}
        self.quantum = 500.0  # Base bytes per weight unit
        self.current_idx = 0

    def select_queue(self, queue_system: PacketQueueSystem, current_time_ms: float) -> Optional[int]:
        # Check if all queues are empty
        non_empty = [k for k, q in queue_system.queues.items() if len(q) > 0]
        if not non_empty:
            return None
            
        # DWRR pass over queues
        for _ in range(3):
            q_type = (self.current_idx) % 3
            q = queue_system.queues[q_type]
            
            if len(q) > 0:
                head_pkt = q[0]
                needed_bytes = head_pkt.size_bytes
                
                # Add weight * quantum if deficit is 0
                if self.deficits[q_type] < needed_bytes:
                    self.deficits[q_type] += self.weights[q_type] * self.quantum
                    
                if self.deficits[q_type] >= needed_bytes:
                    self.deficits[q_type] -= needed_bytes
                    # Advance index for next round
                    self.current_idx = (q_type + 1) % 3
                    return q_type
                    
            self.current_idx = (self.current_idx + 1) % 3

        # Fallback to FIFO among non-empty if deficit round didn't pick
        fifo_sub = FIFOScheduler()
        return fifo_sub.select_queue(queue_system, current_time_ms)
