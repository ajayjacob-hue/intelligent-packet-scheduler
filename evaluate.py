"""
Evaluation & Benchmarking Engine.
Executes controlled comparative experiments across FIFO, PQ, WFQ, and DQN algorithms
under Normal, Congested, and Changing traffic scenarios with multiple random seeds.
"""

import os
import json
import torch
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

from traffic_generator import TrafficGenerator, Packet
from packet_queue import PacketQueueSystem
from schedulers import FIFOScheduler, StrictPriorityScheduler, WFQScheduler
from qos_metrics import QoSMetricsCalculator
from train_dqn import DQNAgent, QNetwork

# Schedulers list
SCHEDULERS_MAP = {
    "FIFO": FIFOScheduler(),
    "PQ": StrictPriorityScheduler(),
    "WFQ": WFQScheduler(weights={0: 5.0, 1: 3.0, 2: 1.0})
}

def run_single_simulation(
    scheduler_name: str,
    scenario: str,
    link_bandwidth_mbps: float = 6.0,
    traffic_intensity: float = 1.0,
    simulation_duration_ms: float = 1000.0,
    seed: int = 42,
    dqn_agent: Optional[DQNAgent] = None
) -> Dict[str, Any]:
    """
    Executes a single simulation run for a specified scheduler under fixed seed and scenario.
    """
    traffic_gen = TrafficGenerator(seed=seed)
    queue_sys = PacketQueueSystem(
        queue_capacities={0: 50, 1: 50, 2: 50},
        link_bandwidth_mbps=link_bandwidth_mbps
    )
    
    current_time_ms = 0.0
    dt_ms = 1.0  # 1ms step duration
    
    # State tracking for DQN if used
    recent_delays = {0: [0.0], 1: [0.0], 2: [0.0]}
    
    while current_time_ms < simulation_duration_ms:
        # 1. Generate new packet arrivals for dt
        new_pkts = traffic_gen.generate_packets_in_interval(
            current_time_ms=current_time_ms,
            interval_ms=dt_ms,
            intensity=traffic_intensity,
            scenario=scenario
        )
        queue_sys.enqueue_packets(new_pkts, current_time_ms=current_time_ms)
        
        # 2. Check if link is free to transmit
        if not queue_sys.is_link_busy(current_time_ms):
            selected_queue = None
            
            if scheduler_name in SCHEDULERS_MAP:
                selected_queue = SCHEDULERS_MAP[scheduler_name].select_queue(queue_sys, current_time_ms)
            elif "DQN" in scheduler_name and dqn_agent is not None:
                # Construct observation state vector for DQN agent
                q_len = queue_sys.get_queue_lengths()
                oldest = queue_sys.get_oldest_waiting_time(current_time_ms)
                near_dead = queue_sys.get_packets_near_deadline(current_time_ms)
                
                obs = np.array([
                    q_len[0] / 50.0, q_len[1] / 50.0, q_len[2] / 50.0,
                    oldest[0] / 30.0, oldest[1] / 100.0, oldest[2] / 500.0,
                    float(np.mean(recent_delays[0][-10:])) / 50.0,
                    float(np.mean(recent_delays[1][-10:])) / 150.0,
                    float(np.mean(recent_delays[2][-10:])) / 500.0,
                    1.0 if queue_sys.is_link_busy(current_time_ms) else 0.0,
                    near_dead[0] / 50.0, near_dead[1] / 50.0, near_dead[2] / 50.0
                ], dtype=np.float32)
                
                mask = np.array([
                    len(queue_sys.queues[0]) > 0,
                    len(queue_sys.queues[1]) > 0,
                    len(queue_sys.queues[2]) > 0
                ], dtype=bool)
                action = dqn_agent.select_action(obs, eval_mode=True, action_mask=mask)
                
                # Handle empty target queue gracefully: fall back to most urgent queue
                if len(queue_sys.queues[action]) > 0:
                    selected_queue = action
                else:
                    best_fq = None
                    highest_urgency = -1.0
                    for fq in [0, 1, 2]:
                        if len(queue_sys.queues[fq]) > 0:
                            head_pkt = queue_sys.queues[fq][0]
                            urgency = (current_time_ms - head_pkt.arrival_time) / head_pkt.max_allowed_delay
                            if urgency > highest_urgency:
                                highest_urgency = urgency
                                best_fq = fq
                    selected_queue = best_fq
                            
            if selected_queue is not None:
                pkt = queue_sys.serve_queue(selected_queue, current_time_ms)
                if pkt and not pkt.dropped:
                    recent_delays[pkt.traffic_type].append(pkt.total_delay)
                    
        # Purge expired packets
        queue_sys.purge_expired_packets(current_time_ms)
        current_time_ms += dt_ms

    # Compute final QoS metrics
    metrics = QoSMetricsCalculator.calculate_metrics(queue_sys, simulation_duration_ms)
    return metrics


def run_benchmark_suite(
    seeds: List[int] = [42, 101, 2024, 777, 999],
    scenarios: List[str] = ["normal", "congested", "changing"],
    model_path: str = "models/dqn_scheduler.pt",
    simulation_duration_ms: float = 1000.0,
    link_bandwidth_mbps: float = 6.0
) -> Dict[str, Any]:
    """
    Runs the full benchmarking suite across multiple seeds and scenarios.
    Returns averaged metric results for all schedulers.
    """
    dqn_agent = DQNAgent(state_dim=13, action_dim=3)
    if os.path.exists(model_path):
        try:
            dqn_agent.load_model(model_path)
            print(f"Loaded trained DQN model from {model_path}")
        except Exception as e:
            print(f"Warning: Could not load DQN model from {model_path}: {e}")
    else:
        print("Notice: DQN model checkpoint not found. Using untrained initialization for evaluation.")

    schedulers = ["FIFO", "PQ", "WFQ", "DQN"]
    results_by_scenario: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        sc: {sch: [] for sch in schedulers} for sc in scenarios
    }

    print("\n========================================================")
    print("      RUNNING BENCHMARK EVALUATION SUITE                ")
    print("========================================================\n")

    for sc in scenarios:
        print(f"--> Evaluating Scenario: [{sc.upper()}] across {len(seeds)} seeds...")
        for seed in seeds:
            for sch in schedulers:
                res = run_single_simulation(
                    scheduler_name=sch,
                    scenario=sc,
                    link_bandwidth_mbps=link_bandwidth_mbps,
                    simulation_duration_ms=simulation_duration_ms,
                    seed=seed,
                    dqn_agent=dqn_agent if sch == "DQN" else None
                )
                results_by_scenario[sc][sch].append(res)

    # Aggregate mean results over seeds
    benchmark_summary: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for sc in scenarios:
        benchmark_summary[sc] = {}
        for sch in schedulers:
            runs = results_by_scenario[sc][sch]
            
            # Extract overall metrics across seeds
            avg_delays = [r["overall"]["avg_delay_ms"] for r in runs]
            p95_delays = [r["overall"]["p95_delay_ms"] for r in runs]
            jitters = [r["overall"]["jitter_ms"] for r in runs]
            losses = [r["overall"]["loss_rate_pct"] for r in runs]
            throughputs = [r["overall"]["total_throughput_mbps"] for r in runs]
            fairness = [r["overall"]["jains_fairness_index"] for r in runs]
            
            # Voice specific metrics (Queue 0 priority focus)
            voice_delays = [r["per_class"]["Voice"]["avg_delay_ms"] for r in runs]
            voice_losses = [r["per_class"]["Voice"]["loss_rate_pct"] for r in runs]
            
            benchmark_summary[sc][sch] = {
                "overall": {
                    "avg_delay_ms": round(float(np.mean(avg_delays)), 3),
                    "p95_delay_ms": round(float(np.mean(p95_delays)), 3),
                    "jitter_ms": round(float(np.mean(jitters)), 3),
                    "loss_rate_pct": round(float(np.mean(losses)), 2),
                    "total_throughput_mbps": round(float(np.mean(throughputs)), 3),
                    "jains_fairness_index": round(float(np.mean(fairness)), 4)
                },
                "voice_class": {
                    "avg_delay_ms": round(float(np.mean(voice_delays)), 3),
                    "loss_rate_pct": round(float(np.mean(voice_losses)), 2)
                }
            }

    # Print clean benchmark comparison table
    print("\n" + "="*85)
    print(f"{'Scenario':<12} | {'Scheduler':<10} | {'Avg Delay (ms)':<14} | {'Loss Rate (%)':<14} | {'Throughput':<12} | {'Fairness Index':<14}")
    print("="*85)
    
    for sc in scenarios:
        for sch in schedulers:
            ov = benchmark_summary[sc][sch]["overall"]
            print(f"{sc:<12} | {sch:<10} | {ov['avg_delay_ms']:<14.2f} | {ov['loss_rate_pct']:<14.2f} | {ov['total_throughput_mbps']:<12.2f} | {ov['jains_fairness_index']:<14.4f}")
        print("-" * 85)

    # Save output to results/benchmark_results.json
    os.makedirs("results", exist_ok=True)
    with open("results/benchmark_results.json", "w") as f:
        json.dump(benchmark_summary, f, indent=2)
        
    print("\nBenchmark results successfully saved to results/benchmark_results.json")
    return benchmark_summary

if __name__ == "__main__":
    run_benchmark_suite()
