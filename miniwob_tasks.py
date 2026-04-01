import gymnasium as gym
import browsergym.miniwob

# 사용 가능한 MiniWoB 태스크 목록
env_ids = [id for id in gym.envs.registry.keys() if id.startswith("browsergym/miniwob")]
print("\n--- Available MiniWoB Tasks ---\n" + "\n".join(env_ids))