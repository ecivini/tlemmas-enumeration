from typing import Protocol

import mathsat
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver

from enumerators.solvers.mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    allsat_callback_store,
    get_converted_atoms,
)
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
        cls, phi: FNode, atoms, n_workers: int, norm: NormalizerWalker, min_partial_models: int = 0
    ) -> tuple[list[list[FNode]], list[FNode]]:
        if min_partial_models <= 0:
            min_partial_models = n_workers * 100
        atoms = cls._rank_atoms_by_hub_centrality(atoms, phi)
        # choose a number of atoms such that 2**|atoms| >= 10 * n_workers, so to have enough partial models to keep all workers busy
        n_atoms_to_project = min(len(atoms), (min_partial_models - 1).bit_length()) - 1
        partial_models = []
        tlemmas = []
        with Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS) as solver:
            solver.add_assertion(phi)
            converter = solver.converter
            msat_env = solver.msat_env()
            while len(partial_models) < min_partial_models and n_atoms_to_project < len(atoms):
                partial_models.clear()
                n_atoms_to_project += 1
                atoms_to_project = atoms[:n_atoms_to_project]
                solver.push()
                mathsat.msat_all_sat(
                    msat_env,
                    get_converted_atoms(atoms_to_project, converter),
                    callback=lambda model: allsat_callback_store(model, converter, partial_models),
                )
                tlemmas.extend([converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)])
                solver.pop()
        tlemmas = [norm.normalize(lemma) for lemma in tlemmas]
        partial_models = [[norm.normalize(literal) for literal in model] for model in partial_models]

        return partial_models, tlemmas

    @classmethod
    def _rank_atoms_by_hub_centrality(cls, atoms: list[FNode], phi: FNode) -> list[FNode]:
        var_freq = {}
        for atom in atoms:
            for var in atom.get_free_variables():
                var_freq[var] = var_freq.get(var, 0) + 1

        def score(atom):
            return sum(var_freq[v] for v in atom.get_free_variables())

        return sorted(atoms, key=score, reverse=True)
