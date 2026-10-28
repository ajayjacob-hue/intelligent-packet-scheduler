"""
DQN Intelligent Scheduler Training Module.
Implements PyTorch Dueling Double Deep Q-Network (Double Dueling DQN) agent
with Experience Replay, Action Masking, Polyak Soft Target updates (EMA),
and training performance logging.
"""

import os
import json
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
from typing import List, Tuple, Dict, Any, Optional

from environment import PacketSchedulerEnv

# Ensure directory structures exist
os.makedirs("models", exist_ok=True)
os.makedirs("results", exist_ok=True)


class DuelingQNetwork(nn.Module):
    """
    Dueling Deep Q-Network Architecture.
    Decouples state value V(s) from action advantage A(s, a) streams:
    Q(s, a) = V(s) + (A(s, a) - mean(A(s, a)))
    """
    def __init__(self, state_dim: int = 13, action_dim: int = 3, hidden_dim: int = 128):
        super(DuelingQNetwork, self).__init__()
        
        # Shared feature representation
        self.feature_layer = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        
        # State-value stream V(s)
        self.value_stream = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1)
        )
        
        # Advantage stream A(s, a)
        self.advantage_stream = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.feature_layer(x)
        values = self.value_stream(features)
        advantages = self.advantage_stream(features)
        # Identifiability trick: subtract mean advantage
        q_values = values + (advantages - advantages.mean(dim=-1, keepdim=True))
        return q_values


# Alias for backward compatibility
QNetwork = DuelingQNetwork


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
    """
    Double Dueling Deep Q-Learning Agent (DDQN) with Polyak Soft Updates and Action Masking.
    """
    def __init__(
        self,
        state_dim: int = 13,
        action_dim: int = 3,
        lr: float = 0.0005,
        gamma: float = 0.99,
        tau: float = 0.005,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.965,
        buffer_capacity: int = 50000,
        batch_size: int = 64
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.tau = tau
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Policy Network and Target Network (Dueling Q-Networks)
        self.policy_net = DuelingQNetwork(state_dim, action_dim).to(self.device)
        self.target_net = DuelingQNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(capacity=buffer_capacity)
        
        self.steps_done = 0

    def select_action(
        self,
        state: np.ndarray,
        eval_mode: bool = False,
        action_mask: Optional[np.ndarray] = None
    ) -> int:
        """
        Select action using Epsilon-Greedy policy (or greedy if eval_mode=True),
        constrained by optional action mask to avoid empty queues.
        """
        # Exploration
        if not eval_mode and random.random() < self.epsilon:
            if action_mask is not None and np.any(action_mask):
                valid_actions = np.where(action_mask)[0]
                return int(random.choice(valid_actions))
            return random.randint(0, self.action_dim - 1)
            
        # Exploitation
        with torch.no_grad():
            state_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_t).squeeze(0)
            
            # Apply action mask: mask out invalid actions with large negative value
            if action_mask is not None and np.any(action_mask):
                mask_t = torch.tensor(action_mask, dtype=torch.bool).to(self.device)
                q_values[~mask_t] = -1e9
                
            return int(torch.argmax(q_values).item())

    def update(self) -> Optional[float]:
        """
        Perform one step of Double DQN gradient descent with Polyak target network soft update.
        """
        if len(self.memory) < self.batch_size:
            return None
            
        states, actions, rewards, next_states, dones = self.memory.sample(self.batch_size)
        states = states.to(self.device)
        actions = actions.unsqueeze(1).to(self.device)
        rewards = rewards.unsqueeze(1).to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.unsqueeze(1).to(self.device)
        
        # Current predicted Q(s, a)
        curr_q = self.policy_net(states).gather(1, actions)
        
        # Double DQN Target:
        # a* = argmax_a Q_policy(s', a)  [Action Selection with Policy Net]
        # target_Q = r + gamma * Q_target(s', a*)  [Action Evaluation with Target Net]
        with torch.no_grad():
            best_next_actions = self.policy_net(next_states).argmax(dim=1, keepdim=True)
            next_q = self.target_net(next_states).gather(1, best_next_actions)
            target_q = rewards + (self.gamma * next_q * (1.0 - dones))
            
        # Smooth L1 / Huber Loss
        loss = nn.SmoothL1Loss()(curr_q, target_q)
        
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), max_norm=1.0)
        self.optimizer.step()
        
        # Polyak Soft Target Update: theta_target = tau * theta_policy + (1 - tau) * theta_target
        for target_param, policy_param in zip(self.target_net.parameters(), self.policy_net.parameters()):
            target_param.data.copy_(self.tau * policy_param.data + (1.0 - self.tau) * target_param.data)
            
        self.steps_done += 1
        return float(loss.item())

    def decay_epsilon(self):
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)

    def save_model(self, filepath: str):
        torch.save(self.policy_net.state_dict(), filepath)

    def load_model(self, filepath: str):
        self.policy_net.load_state_dict(torch.load(filepath, map_location=self.device))
        self.target_net.load_state_dict(self.policy_net.state_dict())


def evaluate_greedy(agent: DQNAgent, env: PacketSchedulerEnv, num_eval_steps: int = 600) -> float:
    """Evaluates agent in pure greedy exploitation mode with action masking."""
    env.scenario = "normal"
    state, _ = env.reset(seed=999)
    total_reward = 0.0
    for _ in range(num_eval_steps):
        mask = env.get_action_mask()
        action = agent.select_action(state, eval_mode=True, action_mask=mask)
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
    Trains the Double Dueling DQN intelligent scheduler agent over multiple episodes.
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
    
    print(f"Starting Double Dueling DQN Agent Training for {num_episodes} episodes...")
    
    for ep in range(1, num_episodes + 1):
        scenario = random.choice(["normal", "congested", "changing"])
        env.scenario = scenario
        
        state, _ = env.reset(seed=ep + 100)
        ep_reward = 0.0
        ep_losses = []
        
        for step in range(max_steps_per_episode):
            mask = env.get_action_mask()
            action = agent.select_action(state, eval_mode=False, action_mask=mask)
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
