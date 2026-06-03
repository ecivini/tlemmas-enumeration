import math
from typing import Protocol

import mathsat
import tqdm
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver

from enumerators.solvers.mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.solvers.mathsat_divide_and_conquer.ranking import rank_atoms_by_hub_centrality
from enumerators.walkers.normalizer import NormalizerWalker


class DivideStrategy(Protocol):
    @classmethod
    def divide(
        cls, phi: FNode, atoms: list[FNode], n_workers: int, norm: NormalizerWalker
    ) -> tuple[list[list[FNode]], list[FNode]]:
        """
        Partitions the search space of phi into disjoint T-SAT partial assignments.

        Args:
            phi: the formula to divide
            atoms: the atoms to consider for the division (e.g., theory atoms)
            n_workers: the number of workers that will solve the resulting partial assignments in parallel
            norm: normalizer used to normalize returned models and lemmas
        Returns:
            a list of partial assignments covering the search space of phi
            a list of theory lemmas found during the division
        """
        ...


class DivideByPartialAllSMTStrategy(DivideStrategy):
    @classmethod
    def divide(
        cls, phi: FNode, atoms: list[FNode], n_workers: int, norm: NormalizerWalker
    ) -> tuple[list[list[FNode]], list[FNode]]:
        phi = PolarityCNFizer(nnf=True, mutex_nnf_labels=True).convert_as_formula(phi)
        partial_models = []
        with Solver("msat", solver_options=MSAT_PARTIAL_ENUM_OPTIONS) as solver:
            solver.add_assertion(phi)
            converter = solver.converter
            msat_env = solver.msat_env()
            mathsat.msat_all_sat(
                msat_env,
                get_converted_atoms(atoms, converter),
                callback=lambda model: allsat_callback_store(model, converter, partial_models),
            )

            tlemmas = [norm.normalize(converter.back(lemma)) for lemma in mathsat.msat_get_theory_lemmas(msat_env)]
            partial_models = [[norm.normalize(literal) for literal in model] for model in partial_models]

        return partial_models, tlemmas


class DivideByProjectedEnumerationStrategy(DivideStrategy):
    @classmethod
    def divide(
        cls,
        phi: FNode,
        atoms: list[FNode],
        n_workers: int,
        norm: NormalizerWalker,
        min_cubes: int = 0,
    ) -> tuple[list[list[FNode]], list[FNode]]:
        if min_cubes <= 0:
            min_cubes = n_workers * 20
        atoms = rank_atoms_by_hub_centrality(atoms)

        cubes: list[list[FNode]] = [[]]
        tlemmas: set[FNode] = set()
        with Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS) as solver:
            solver.add_assertion(phi)
            converter = solver.converter
            msat_env = solver.msat_env()
            batch_begin = 0
            batch_end = max(1, min(len(atoms), (min_cubes - 1).bit_length()))
            while len(cubes) < min_cubes and batch_begin < len(atoms):
                atoms_to_project = atoms[batch_begin:batch_end]
                next_gen: list[list[FNode]] = []
                for cube in tqdm.tqdm(cubes, desc="Dividing", leave=False, disable=len(cubes) <= 1):
                    solver.push()
                    solver.add_assertions(cube)
                    cube_extensions: list[list[FNode]] = []
                    mathsat.msat_all_sat(
                        msat_env,
                        get_converted_atoms(atoms_to_project, converter),
                        callback=lambda model: allsat_callback_store(model, converter, cube_extensions),
                    )
                    tlemmas.update(mathsat.msat_get_theory_lemmas(msat_env))
                    next_gen.extend([cube + cube_ext for cube_ext in cube_extensions])
                    solver.pop()
                if not next_gen:
                    break
                bf = len(next_gen) / max(1, len(cubes))
                batch_size = cls._next_batch_size(
                    current_cubes=len(next_gen),
                    min_cubes=min_cubes,
                    last_batch_size=batch_end - batch_begin,
                    last_branching_factor=bf,
                )
                cubes = next_gen
                batch_begin = batch_end
                batch_end = batch_begin + batch_size
        normalized_tlemmas = [norm.normalize(converter.back(lemma)) for lemma in tlemmas]
        cubes = [[norm.normalize(literal) for literal in model] for model in cubes]

        return cubes, normalized_tlemmas

    @staticmethod
    def _next_batch_size(
        current_cubes: int,
        min_cubes: int,
        last_batch_size: int,
        last_branching_factor: float,
        max_overshoot: float = 2.0,
    ) -> int:
        """Estimate the number of atoms needed in the next batch."""
        if current_cubes >= min_cubes:
            return 0

        bf_per_atom = last_branching_factor ** (1.0 / last_batch_size)

        if bf_per_atom <= 1.0:
            return last_batch_size * 2

        remaining_factor = min_cubes / current_cubes
        k_needed = math.ceil(math.log(remaining_factor) / math.log(bf_per_atom))
        k_max = math.ceil(math.log(max_overshoot * min_cubes / current_cubes) / math.log(bf_per_atom))

        return max(1, min(k_needed, k_max))
