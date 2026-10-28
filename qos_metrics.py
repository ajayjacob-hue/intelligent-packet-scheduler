"""
QoS Measurement Engine Module.
Calculates key Quality of Service metrics for network scheduler evaluation:
- Average Delay (ms)
- 95th-Percentile Delay (ms)
- Jitter (ms)
- Packet Loss Rate (%)
- Throughput (Mbps)
- Jain's Fairness Index
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
from traffic_generator import Packet, TRAFFIC_CLASS_NAMES
from packet_queue import PacketQueueSystem

class QoSMetricsCalculator:
    """
    Computes per-class and aggregate QoS metrics from a completed simulation run.
    """
    @staticmethod
    def calculate_metrics(
        queue_system: PacketQueueSystem,
        simulation_duration_ms: float
    ) -> Dict[str, Any]:
        
        sim_seconds = simulation_duration_ms / 1000.0 if simulation_duration_ms > 0 else 1.0
        
        delivered = queue_system.delivered_packets
        dropped = queue_system.dropped_packets
        generated_counts = queue_system.generated_packets_count
        
        # Categorize by traffic type
        delays_by_class: Dict[int, List[float]] = {0: [], 1: [], 2: []}
        bits_by_class: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        delivered_counts: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        dropped_counts: Dict[int, int] = {0: 0, 1: 0, 2: 0}
        
        for pkt in delivered:
            t = pkt.traffic_type
            delays_by_class[t].append(pkt.total_delay)
            bits_by_class[t] += pkt.size_bytes * 8
            delivered_counts[t] += 1

        for pkt in dropped:
            t = pkt.traffic_type
            dropped_counts[t] += 1
            
        # Summary per class
        class_metrics = {}
        throughputs = []
        delivery_ratios = []
        
        for t in [0, 1, 2]:
            c_name = TRAFFIC_CLASS_NAMES[t]
            delays = np.array(delays_by_class[t]) if len(delays_by_class[t]) > 0 else np.array([0.0])
            gen_cnt = max(1, generated_counts[t])
            deliv_cnt = delivered_counts[t]
            drop_cnt = dropped_counts[t]
            
            avg_delay = float(np.mean(delays))
            p95_delay = float(np.percentile(delays, 95))
            
            # Calculate Jitter: mean absolute difference between successive packet delays
            if len(delays) > 1:
                jitter = float(np.mean(np.abs(np.diff(delays))))
            else:
                jitter = 0.0
                
            loss_rate_pct = float((drop_cnt / gen_cnt) * 100.0)
            throughput_mbps = float((bits_by_class[t] / 1e6) / sim_seconds)
            delivery_ratio = float(deliv_cnt / gen_cnt)
            
            throughputs.append(throughput_mbps)
            delivery_ratios.append(delivery_ratio)
            
            class_metrics[c_name] = {
                "avg_delay_ms": round(avg_delay, 3),
                "p95_delay_ms": round(p95_delay, 3),
                "jitter_ms": round(jitter, 3),
                "loss_rate_pct": round(loss_rate_pct, 2),
                "throughput_mbps": round(throughput_mbps, 3),
                "delivered_packets": deliv_cnt,
                "dropped_packets": drop_cnt,
                "total_generated": gen_cnt
            }

        # Calculate Overall Aggregates
        all_delays = [p.total_delay for p in delivered]
        overall_avg_delay = float(np.mean(all_delays)) if all_delays else 0.0
        overall_p95_delay = float(np.percentile(all_delays, 95)) if all_delays else 0.0
        
        if len(all_delays) > 1:
            overall_jitter = float(np.mean(np.abs(np.diff(all_delays))))
        else:
            overall_jitter = 0.0
            
        total_gen = sum(generated_counts.values())
        total_drop = len(dropped)
        total_deliv = len(delivered)
        overall_loss_rate = float((total_drop / max(1, total_gen)) * 100.0)
        overall_throughput = float(sum(throughputs))

        # Calculate Jain's Fairness Index J(x) = (sum(x_i))^2 / (n * sum(x_i^2))
        x = np.array(throughputs)
        sum_x = np.sum(x)
        sum_sq_x = np.sum(x ** 2)
        if sum_sq_x > 0:
            jains_fairness_tp = float((sum_x ** 2) / (len(x) * sum_sq_x))
        else:
            jains_fairness_tp = 1.0

        # Also delivery ratio fairness
        xr = np.array(delivery_ratios)
        sum_xr = np.sum(xr)
        sum_sq_xr = np.sum(xr ** 2)
        if sum_sq_xr > 0:
            jains_fairness_delivery = float((sum_xr ** 2) / (len(xr) * sum_sq_xr))
        else:
            jains_fairness_delivery = 1.0

        return {
            "per_class": class_metrics,
            "overall": {
                "avg_delay_ms": round(overall_avg_delay, 3),
                "p95_delay_ms": round(overall_p95_delay, 3),
                "jitter_ms": round(overall_jitter, 3),
                "loss_rate_pct": round(overall_loss_rate, 2),
                "total_throughput_mbps": round(overall_throughput, 3),
                "jains_fairness_index": round(jains_fairness_tp, 4),
                "jains_fairness_delivery_ratio": round(jains_fairness_delivery, 4),
                "total_delivered": total_deliv,
                "total_dropped": total_drop,
                "total_generated": total_gen
            }
        }

    @staticmethod
    def to_dataframe(metrics_dict: Dict[str, Any]) -> pd.DataFrame:
        """Converts class metrics to a clean summary DataFrame for display/reporting."""
        rows = []
        for c_name, data in metrics_dict["per_class"].items():
            row = {"Traffic Class": c_name}
            row.update(data)
            rows.append(row)
            
        ov = metrics_dict["overall"]
        rows.append({
            "Traffic Class": "Overall / Aggregate",
            "avg_delay_ms": ov["avg_delay_ms"],
            "p95_delay_ms": ov["p95_delay_ms"],
            "jitter_ms": ov["jitter_ms"],
            "loss_rate_pct": ov["loss_rate_pct"],
            "throughput_mbps": ov["total_throughput_mbps"],
            "delivered_packets": ov["total_delivered"],
            "dropped_packets": ov["total_dropped"],
            "total_generated": ov["total_generated"]
        })
        return pd.DataFrame(rows)
