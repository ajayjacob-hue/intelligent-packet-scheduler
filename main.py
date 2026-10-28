"""
Main Execution Entry Point for Intelligent Packet Scheduler Project.
Allows executing training, comparative evaluation, or launching the dashboard.
"""

import sys
import subprocess
import argparse
from train_dqn import train_dqn_scheduler
from evaluate import run_benchmark_suite

def main():
    parser = argparse.ArgumentParser(description="QoS-Aware Intelligent Packet Scheduler")
    parser.add_argument("--mode", type=str, default="eval", choices=["train", "eval", "all", "dashboard"],
                        help="Operation mode: 'train' to train DQN model, 'eval' to run benchmarks, 'all' for both, 'dashboard' for Streamlit UI.")
    parser.add_argument("--episodes", type=int, default=120, help="Number of episodes for DQN training.")
    
    args = parser.parse_args()
    
    if args.mode in ["train", "all"]:
        print("=== Step 1: Training DQN Intelligent Scheduler ===")
        train_dqn_scheduler(num_episodes=args.episodes)
        
    if args.mode in ["eval", "all"]:
        print("\n=== Step 2: Running Baseline & DQN Comparative Evaluation Suite ===")
        run_benchmark_suite()
        print("\n[TIP] Run `python main.py --mode dashboard` or `streamlit run dashboard.py` to view the interactive web dashboard!")

    if args.mode == "dashboard":
        print("=== Step 3: Launching Interactive Streamlit Dashboard ===")
        subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py"])

if __name__ == "__main__":
    main()
