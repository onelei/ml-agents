# # Unity ML-Agents Toolkit
# ## ML-Agent Learning (Ghost Trainer)
# Contains an implementation of a 'ghost trainer' which loads
# snapshots of the agent's past selves to train against in adversarial settings.
import copy
import logging
from collections import defaultdict

# from typing import Dict

import numpy as np

from mlagents.envs.brain import BrainInfo, AllBrainInfo

# from mlagents.trainers.rl_trainer import RLTrainer, AllRewardsOutput
from mlagents.envs.action_info import ActionInfoOutputs
from mlagents.envs.action_info import ActionInfo

logger = logging.getLogger("mlagents.trainers")

""" Hacking together a ghost trainer"""


def safe_collect_from_list(l, indices):
    if len(indices) <= len(l):
        return [l[x] for x in indices]
    else:
        return []


def get_indices(brain_info):
    indices = defaultdict(list)
    for i, team_id in enumerate(brain_info.team_ids):
        indices[team_id].append(i)
    return indices


def filter_by_indices(brain_info, indices):
    return BrainInfo(
        visual_observation=safe_collect_from_list(
            brain_info.visual_observations, indices
        ),
        vector_observation=safe_collect_from_list(
            brain_info.vector_observations, indices
        ),
        text_observations=safe_collect_from_list(brain_info.text_observations, indices),
        memory=safe_collect_from_list(brain_info.memories, indices),
        reward=safe_collect_from_list(brain_info.rewards, indices),
        agents=safe_collect_from_list(brain_info.agents, indices),
        local_done=safe_collect_from_list(brain_info.local_done, indices),
        vector_action=safe_collect_from_list(
            brain_info.previous_vector_actions, indices
        ),
        text_action=safe_collect_from_list(brain_info.previous_text_actions, indices),
        max_reached=safe_collect_from_list(brain_info.max_reached, indices),
        custom_observations=safe_collect_from_list(
            brain_info.custom_observations, indices
        ),
        team_ids=safe_collect_from_list(brain_info.team_ids, indices),
        action_mask=safe_collect_from_list(brain_info.action_masks, indices),
    )


# splits brain_info into separate brain_infos per team
def split_brain_info_by_team(brain_info, teams):
    brain_infos = []
    indices = get_indices(brain_info)
    for team_id in range(teams):
        brain_infos.append(filter_by_indices(brain_info, indices[team_id]))
    return brain_infos


def create_ghost_trainer(
    trainer,
    num_ghosts,
    brain,
    reward_buff_cap,
    trainer_parameters,
    training,
    load,
    seed,
    *args,
):

    # Get trainer and policy classes
    trainer_type = trainer.__class__
    policy_type = trainer.policy.__class__

    class GhostPolicy(policy_type):
        def __init__(self, ghosts):

            super(GhostPolicy, self).__init__(
                seed, brain, trainer_parameters, training, load
            )

            self.ghosts = ghosts
            self.num_ghosts = len(ghosts)

        def get_action(self, brain_info: BrainInfo) -> ActionInfo:
            """
            Decides actions given observations information, and takes them in environment.
            :param brain_info: A dictionary of brain names and BrainInfo from environment.
            :return: an ActionInfo containing action, memories, values and an object
            to be passed to add experiences
            """
            if len(brain_info.agents) == 0:
                return ActionInfo([], [], [], None, None)

            # run_out = self.evaluate(brain_info)

            # plus 1 for number of teams since num_ghosts = teams -1
            brain_infos = []
            indices = get_indices(brain_info)
            for team_id in range(self.num_ghosts + 1):
                brain_infos.append(filter_by_indices(brain_info, indices[team_id]))
            print(brain_info.agents)
            for k in brain_info.__dict__:
                print(k)
            # current policy
            # run_out = self.evaluate(brain_infos[0])
            run_out = self.evaluate(brain_info)

            run_out_copy = copy.deepcopy(run_out)

            # ghost actions
            for ghost in range(self.num_ghosts):
                # hack for inference
                # if len(indices[ghost + 1]) > 0:
                ghost_run_out = self.ghosts[ghost].evaluate(brain_infos[ghost + 1])
                run_out_copy["action"] = np.concatenate(
                    (run_out_copy["action"], ghost_run_out["action"]), axis=0
                )
                run_out_copy["value"] = np.concatenate(
                    (run_out_copy["value"], ghost_run_out["value"]), axis=0
                )
            print(run_out_copy["action"], len(run_out_copy["action"]))

            return ActionInfo(
                action=run_out_copy.get("action"),
                memory=run_out_copy.get("memory_out"),
                text=None,
                value=run_out_copy.get("value"),
                outputs=run_out_copy,
            )

    # ghost trainer now wraps base trainer class
    class GhostTrainer(trainer_type):
        def __init__(self):
            super(GhostTrainer, self).__init__(
                brain, reward_buff_cap, trainer_parameters, training, load, seed, *args
            )

            # number of ghosts to spawn
            self.num_ghosts = num_ghosts

            # instantiate ghosts
            self.ghosts = []
            for _ in range(self.num_ghosts):
                self.ghosts.append(
                    policy_type(seed, brain, trainer_parameters, False, load)
                )
            self.policy = GhostPolicy(self.ghosts)

            self.policy_snapshots = []

        def process_experiences(
            self, current_info: AllBrainInfo, new_info: AllBrainInfo
        ) -> None:

            # Assumes that learning policy is team_id 0
            indices = get_indices(current_info[self.brain_name])[0]
            current_info[self.brain_name] = filter_by_indices(
                current_info[self.brain_name], indices
            )

            indices = get_indices(new_info[self.brain_name])[0]
            new_info[self.brain_name] = filter_by_indices(
                new_info[self.brain_name], indices
            )

            super(GhostTrainer, self).process_experiences(current_info, new_info)

        def add_experiences(
            self,
            curr_all_info: AllBrainInfo,
            next_all_info: AllBrainInfo,
            take_action_outputs: ActionInfoOutputs,
        ) -> None:

            # Assumes that learning policy is team_id 0. Writing it this way because of the structure of add_exp

            indices = get_indices(curr_all_info[self.brain_name])[0]
            curr_all_info[self.brain_name] = filter_by_indices(
                curr_all_info[self.brain_name], indices
            )

            indices = get_indices(next_all_info[self.brain_name])[0]
            next_all_info[self.brain_name] = filter_by_indices(
                next_all_info[self.brain_name], indices
            )

            super(GhostTrainer, self).add_experiences(
                curr_all_info, next_all_info, take_action_outputs
            )

        def save_snapshot(self):
            pass

        def swap_snapshot(self):
            pass

    return GhostTrainer()
