import gymnasium as gym
import browsergym.webarena

# 등록된 모든 webarena 태스크 출력
all_envs = [env_spec.id for env_spec in gym.envs.registry.all() if "webarena" in env_spec.id]
print(all_envs[:10])  # 예: browsergym/webarena.0, browsergym/webarena.1 ...