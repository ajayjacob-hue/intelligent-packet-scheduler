"""
DQN Intelligent Scheduler Training Module.
Implements PyTorch Deep Q-Network agent with Replay Memory, Epsilon-Greedy exploration,
Target Network synchronization, and training performance logging.
"""

import os
import json
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
from typing import List, Tuple, Dict, Any

from environment import PacketSchedulerEnv

# Ensure directory structures exist
os.makedirs("models", exist_ok=True)
os.makedirs("results", exist_ok=True)


class QNetwork(nn.Module):
    """Deep Q-Network Model Architecture."""
    def __init__(self, state_dim: int = 13, action_dim: int = 3, hidden_dim: int = 128):
        super(QNetwork, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, action_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class ReplayBuffer:
    """Experience Replay Memory for DQN."""
    def __init__(self, capacity: int = 50000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state: np.ndarray, action: int, reward: float, next_state: np.ndarray, done: bool):
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        
        return (
            torch.tensor(np.array(states), dtype=torch.float32),
            torch.tensor(actions, dtype=torch.int64),
            torch.tensor(rewards, dtype=torch.float32),
            torch.tensor(np.array(next_states), dtype=torch.float32),
            torch.tensor(dones, dtype=torch.float32)
        )

    def __len__(self) -> int:
        return len(self.buffer)


class DQNAgent:
    """Deep Q-Learning Agent."""
    def __init__(
        self,
        state_dim: int = 13,
        action_dim: int = 3,
        lr: float = 0.0005,
        gamma: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.965,
        buffer_capacity: int = 50000,
        batch_size: int = 64,
        target_update_freq: int = 200
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        self.policy_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(capacity=buffer_capacity)
        
        self.steps_done = 0

    def select_action(self, state: np.ndarray, eval_mode: bool = False) -> int:
        """Select action using Epsilon-Greedy policy (or greedy if eval_mode=True)."""
        if not eval_mode and random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
            
        with torch.no_grad():
            state_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_t)
            return int(torch.argmax(q_values, dim=1).item())

    def update(self) -> Optional[float]:
        """Perform one step of gradient descent on replay memory batch."""
        if len(self.memory) < self.batch_size:
            return None
            
        states, actions, rewards, next_states, dones = self.memory.sample(self.batch_size)
        states = states.to(self.device)
        actions = actions.unsqueeze(1).to(self.device)
        rewards = rewards.unsqueeze(1).to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.unsqueeze(1).to(self.device)
        
        # Current Q(s, a)
        curr_q = self.policy_net(states).gather(1, actions)
        
        # Target Q(s', a') = r + gamma * max_a Q_target(s', a) * (1 - done)
        with torch.no_grad():
            max_next_q = self.target_net(next_states).max(1, keepdim=True)[0]
            target_q = rewards + (self.gamma * max_next_q * (1.0 - dones))
            
        # Huber Loss / Smooth L1 Loss
        loss = nn.SmoothL1Loss()(curr_q, target_q)
        
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), max_norm=1.0)
        self.optimizer.step()
        
        self.steps_done += 1
        if self.steps_done % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
            
        return float(loss.item())

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

    def save_model(self, filepath: str):
        torch.save(self.policy_net.state_dict(), filepath)

    def load_model(self, filepath: str):
        self.policy_net.load_state_dict(torch.load(filepath, map_location=self.device))
        self.target_net.load_state_dict(self.policy_net.state_dict())


def evaluate_greedy(agent: DQNAgent, env: PacketSchedulerEnv, num_eval_steps: int = 600) -> float:
    """Evaluates agent in pure greedy exploitation mode (eval_mode=True)."""
    env.scenario = "normal"
    state, _ = env.reset(seed=999)
    total_reward = 0.0
    for _ in range(num_eval_steps):
        action = agent.select_action(state, eval_mode=True)
        next_state, reward, terminated, truncated, _ = env.step(action)
        total_reward += reward
        state = next_state
        if terminated or truncated:
            break
    return total_reward


def train_dqn_scheduler(
    num_episodes: int = 150,
    max_steps_per_episode: int = 800,
    link_bandwidth_mbps: float = 6.0,
    save_path: str = "models/dqn_scheduler.pt",
    callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Trains the DQN intelligent scheduler agent over multiple episodes.
    Logs episode rewards and loss history.
    Saves best model based on greedy evaluation policy reward.
    """
    env = PacketSchedulerEnv(
        link_bandwidth_mbps=link_bandwidth_mbps,
        max_steps=max_steps_per_episode
    )
    
    agent = DQNAgent(state_dim=13, action_dim=3, epsilon_decay=0.965)
    
    history = {
        "episode_rewards": [],
        "avg_loss": [],
        "epsilon_history": []
    }
    
    best_greedy_reward = -float('inf')
    
    print(f"Starting DQN Agent Training for {num_episodes} episodes...")
    
    for ep in range(1, num_episodes + 1):
        scenario = random.choice(["normal", "congested", "changing"])
        env.scenario = scenario
        
        state, _ = env.reset(seed=ep + 100)
        ep_reward = 0.0
        ep_losses = []
        
        for step in range(max_steps_per_episode):
            action = agent.select_action(state, eval_mode=False)
            next_state, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
            
            agent.memory.push(state, action, reward, next_state, done)
            loss = agent.update()
            if loss is not None:
                ep_losses.append(loss)
                
            state = next_state
            ep_reward += reward
            
            if done:
                break
                
        agent.decay_epsilon()
        avg_ep_loss = float(np.mean(ep_losses)) if ep_losses else 0.0
        
        history["episode_rewards"].append(round(ep_reward, 2))
        history["avg_loss"].append(round(avg_ep_loss, 4))
        history["epsilon_history"].append(round(agent.epsilon, 4))
        
        if callback is not None:
            try:
                callback(ep, num_episodes, round(ep_reward, 2), round(avg_ep_loss, 4), round(agent.epsilon, 4), scenario)
            except Exception:
                pass
                
        # Evaluate greedy policy every 5 episodes or at the end
        if ep % 5 == 0 or ep == num_episodes:
            greedy_score = evaluate_greedy(agent, env, num_eval_steps=max_steps_per_episode)
            if greedy_score > best_greedy_reward or ep == num_episodes:
                best_greedy_reward = greedy_score
                agent.save_model(save_path)

        if ep % 10 == 0 or ep == num_episodes:
            print(f"Episode {ep}/{num_episodes} | Scenario: {scenario:9s} | Reward: {ep_reward:7.2f} | Loss: {avg_ep_loss:.4f} | Epsilon: {agent.epsilon:.3f}")

    print(f"Training completed! Best model saved to: {save_path}")
    
    # Save training log
    log_path = "results/dqn_training_log.json"
    with open(log_path, "w") as f:
        json.dump(history, f, indent=2)
        
    return history

if __name__ == "__main__":
    train_dqn_scheduler(num_episodes=150, max_steps_per_episode=800)
