from pettingzoo.test import api_test

from ibflip.env import IBFlipAECEnv


def test_ibflip_aec_env_passes_pettingzoo_api_test():
    env = IBFlipAECEnv(seed=123, max_steps=200)
    api_test(env, num_cycles=200)
