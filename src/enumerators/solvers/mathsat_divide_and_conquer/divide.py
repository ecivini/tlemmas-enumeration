import math
from typing import Protocol

import mathsat
import tqdm
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver

from enumerators.solvers.mathsat_divide_and_conquer.ranking import rank_atoms_by_hub_centrality
from enumerators.solvers.mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.walkers.normalizer import NormalizerWalker


class DivideStrategy(Protocol):
    """Protocol for divide strategies that partition the search space of a formula.

    Implementations should partition ``phi`` into a list of disjoint T-SAT partial
    assignments whose extensions collectively cover the T-SAT total assignments of ``phi``.
    """

    def __call__(
        self, phi: FNode, atoms: list[FNode], norm: NormalizerWalker, **kwargs
    ) -> tuple[list[list[FNode]], list[FNode]]:
        """Partition the search space.

        Args:
            phi: Formula to partition.
            atoms: Atoms to consider for the division.
            norm: Normalizer for T-atoms in assignments and and lemmas.
            **kwargs: Additional implementation-specific parameters.

        Returns:
            A tuple ``(partial_assignments, tlemmas)`` where
            ``partial_assignments`` is a list of partial assignments covering
            the search space of ``phi``, and ``tlemmas`` are theory lemmas
            learned during the division.
        """
        ...


class DivideByPartialAllSMTStrategy(DivideStrategy):
    """Divide strategy that uses MathSAT's partial All-SMT enumeration."""

    def __call__(
        self, phi: FNode, atoms: list[FNode], norm: NormalizerWalker, **kwargs
    ) -> tuple[list[list[FNode]], list[FNode]]:
        """Partition the search space via partial All-SMT.

        Args:
            phi: Formula to partition (will be CNFized internally).
            atoms: Atoms to enumerate over.
            norm: Normalizer for T-atoms and lemmas.
            **kwargs: Ignored (present for Protocol compatibility).

        Returns:
            A tuple ``(partial_assignments, tlemmas)`` where
            ``partial_assignments`` is a list of partial assignments covering
            the search space of ``phi``, and ``tlemmas`` are theory lemmas
            learned during the division.
        """
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
    """Divide strategy that builds cubes incrementally via projected enumeration.

    Starts from the empty cube and iteratively extends it by projecting on
    batches of atoms (ranked by hub centrality).  Batch sizes are dynamically
    adjusted based on observed branching factors to reach ``min_cubes`` cubes
    efficiently.

    Args:
        min_cubes: Target number of cubes.  If ``0`` (default), it is computed
            as ``n_workers * 20`` at call time.
    """

    def __init__(self, min_cubes: int = 0):
        self._min_cubes = min_cubes

    def compute_min_cubes(self, n_workers: int) -> int:
        """Return the effective minimum number of cubes.

        If ``self._min_cubes > 0``, returns the configured value.
        Otherwise computes ``n_workers * 20``.

        Args:
            n_workers: Number of parallel workers (used only when
                ``self._min_cubes`` is ``0``).

        Returns:
            The target number of cubes.
        """
        if self._min_cubes > 0:
            return self._min_cubes
        if n_workers <= 0:
            raise ValueError(
                "One between min_cubes ({}) and n_workers ({}) must be positive!".format(self._min_cubes, n_workers)
            )
        return n_workers * 20

    def __call__(
        self,
        phi: FNode,
        atoms: list[FNode],
        norm: NormalizerWalker,
        n_workers: int = 0,
        show_progress: bool = False,
        **kwargs,
    ) -> tuple[list[list[FNode]], list[FNode]]:
        """Partition the search space via incremental projected enumeration.

        Args:
            phi: Formula to partition.
            atoms: Atoms to consider for the division.
            norm: Normalizer for T-atoms in assignments and lemmas.
            n_workers: Number of parallel workers.  Used only when the
                strategy was constructed with ``min_cubes=0`` to derive the
                target number of cubes as ``n_workers * 20``.
            show_progress: Whether to display a ``tqdm`` progress bar during
                the division.
            **kwargs: Additional implementation-specific parameters.

        Returns:
            A tuple ``(partial_assignments, tlemmas)`` where
            ``partial_assignments`` is a list of partial assignments covering
            the search space of ``phi``, and ``tlemmas`` are theory lemmas
            learned during the division.
        """
        min_cubes = self.compute_min_cubes(n_workers)
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
                for cube in tqdm.tqdm(cubes, desc="Dividing", leave=False, disable=not show_progress):
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
                batch_size = self._next_batch_size(
                    current_cubes=len(next_gen),
                    min_cubes=min_cubes,
                    last_batch_size=batch_end - batch_begin,
                    total_projected_atoms=batch_end,
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
        total_projected_atoms: int,
    ) -> int:
        """Estimate the number of atoms to project next.

        We model cube growth as:

            cubes(k) ~= current_cubes * bf_per_atom^k

        where ``bf_per_atom`` is the estimated multiplicative increase in the
        number of cubes contributed by one projected atom.

        The next batch size is chosen as the number of atoms predicted to reach
        ``min_cubes``. Since the estimate is imperfect, we cap the growth of the
        batch size to at most twice the previous batch size and re-estimate after
        every iteration.

        Args:
            current_cubes: Number of cubes currently available.
            min_cubes: Target number of cubes.
            last_batch_size: Number of atoms projected in the previous iteration.
            total_projected_atoms: Total of atoms projected so far.

        Returns:
            Number of atoms to project in the next iteration.
        """
        if current_cubes >= min_cubes:
            return 0

        # Estimate of the average branching factor contributed by a single projected atom.
        estimated_bf_per_atom = current_cubes ** (1.0 / total_projected_atoms)
        # Negligible growth: increase the projection horizon aggressively.
        if estimated_bf_per_atom <= 1.05:
            return max(1, 2 * last_batch_size)

        remaining_factor = min_cubes / current_cubes

        # Solve: current_cubes * bf_per_atom^k >= min_cubes
        # for k.
        k_needed = math.ceil(math.log(remaining_factor) / math.log(estimated_bf_per_atom))

        # The branching estimate is only approximate. Avoid sudden jumps in
        # projection size and refine the estimate at the next iteration.
        return max(
            1,
            min(k_needed, 2 * last_batch_size),
        )
