import math
from typing import Protocol

import mathsat
import tqdm
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.environment import Environment, get_env, pop_env, push_env
from pysmt.fnode import FNode
from pysmt.formula import FormulaContextualizer

from enumerators.solvers.mathsat_divide_and_conquer.ranking import rank_atoms_by_hub_centrality
from enumerators.solvers.mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    AtomManager,
    EncodedClause,
    EncodedModel,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.util.pysmt import SuspendTypeChecking


class DivideStrategy(Protocol):
    """Protocol for divide strategies that partition the search space of a formula.

    Implementations should partition ``phi`` into a list of disjoint T-SAT partial
    assignments whose extensions collectively cover the T-SAT total assignments of ``phi``.
    """

    def __call__(
        self, phi: FNode, proj_atoms: list[FNode], atom_manager: AtomManager, **kwargs
    ) -> tuple[list[EncodedModel], list[EncodedClause]]:
        """Partition the search space.

        Args:
            phi: Formula to partition.
            proj_atoms: Atoms to consider for the division.
            atom_manager: AtomManager for encoding models and lemmas.
            **kwargs: Additional implementation-specific parameters.

        Returns:
            A tuple ``(encoded_assignments, encoded_tlemmas)`` where
            ``encoded_assignments`` is a list of encoded partial assignments
            covering the search space of ``phi``, and ``encoded_tlemmas``
            are encoded theory lemmas learned during the division.
        """
        ...


class DivideByPartialAllSMTStrategy(DivideStrategy):
    """Divide strategy that uses MathSAT's partial All-SMT enumeration."""

    def __call__(
        self, phi: FNode, proj_atoms: list[FNode], atom_manager: AtomManager, **kwargs
    ) -> tuple[list[EncodedModel], list[EncodedClause]]:
        """Partition the search space via partial All-SMT.

        Args:
            phi: Formula to partition (will be CNFized internally).
            proj_atoms: Atoms to enumerate over.
            atom_manager: AtomManager for encoding.
            **kwargs: Ignored (present for Protocol compatibility).

        Returns:
            A tuple ``(encoded_assignments, encoded_tlemmas)`` where
            ``encoded_assignments`` is a list of encoded partial assignments
            covering the search space of ``phi``, and ``encoded_tlemmas``
            are encoded theory lemmas learned during the division.
        """
        push_env()
        env: Environment = get_env()
        contextualizer = FormulaContextualizer(env)
        with env.factory.Solver("msat", solver_options=MSAT_PARTIAL_ENUM_OPTIONS) as solver:
            converter = solver.converter

            with SuspendTypeChecking():
                phi = contextualizer.walk(phi)
                phi = PolarityCNFizer(nnf=True, mutex_nnf_labels=True, environment=env).convert_as_formula(phi)
                proj_atoms = [contextualizer.walk(atom) for atom in proj_atoms]
                all_atoms = [contextualizer.walk(atom) for atom in atom_manager.atoms]

            local_atom_manager = AtomManager(all_atoms, converter=converter, env=env)

            partial_models = []
            solver.add_assertion(phi)
            msat_env = solver.msat_env()
            mathsat.msat_all_sat(
                msat_env,
                get_converted_atoms(proj_atoms, converter),
                callback=lambda model: allsat_callback_store(model, partial_models),
            )

            tlemmas_encoded = [
                local_atom_manager.encode_clause_msat(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)
            ]
            partial_models_encoded = [local_atom_manager.encode_model_msat(model) for model in partial_models]

        pop_env()
        return partial_models_encoded, tlemmas_encoded


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
        """Return the effective minimum number of cubes."""
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
        proj_atoms: list[FNode],
        atom_manager: AtomManager,
        n_workers: int = 0,
        show_progress: bool = False,
        **kwargs,
    ) -> tuple[list[EncodedModel], list[EncodedClause]]:
        """Partition the search space via incremental projected enumeration.

        Args:
            phi: Formula to partition.
            proj_atoms: Atoms to consider for the division.
            atom_manager: AtomManager for encoding.
            n_workers: Number of parallel workers.  Used only when the
                strategy was constructed with ``min_cubes=0`` to derive the
                target number of cubes as ``n_workers * 20``.
            show_progress: Whether to display a ``tqdm`` progress bar during
                the division.
            **kwargs: Additional implementation-specific parameters.

        Returns:
            A tuple ``(encoded_assignments, encoded_tlemmas)`` where
            ``encoded_assignments`` is a list of encoded partial assignments
            covering the search space of ``phi``, and ``encoded_tlemmas``
            are encoded theory lemmas learned during the division.
        """
        push_env()
        env: Environment = get_env()
        with env.factory.Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS) as solver:
            contextualizer = FormulaContextualizer(env)

            with SuspendTypeChecking():
                phi = contextualizer.walk(phi)
                proj_atoms = [contextualizer.walk(atom) for atom in proj_atoms]
                all_atoms = [contextualizer.walk(atom) for atom in atom_manager.atoms]

            converter = solver.converter

            local_atom_manager = AtomManager(all_atoms, converter, env=env)

            min_cubes = self.compute_min_cubes(n_workers)
            proj_atoms = rank_atoms_by_hub_centrality(proj_atoms)

            cubes: list[list[mathsat.msat_term]] = [[]]
            tlemmas_raw: set[mathsat.msat_term] = set()

            solver.add_assertion(phi)

            msat_env = solver.msat_env()
            batch_begin = 0
            batch_end = max(1, min(len(proj_atoms), (min_cubes - 1).bit_length()))
            while len(cubes) < min_cubes and batch_begin < len(proj_atoms):
                atoms_to_project = proj_atoms[batch_begin:batch_end]
                next_gen: list[list[mathsat.msat_term]] = []
                desc = f"Dividing {len(cubes)}/{min_cubes} cubes | atoms {len(atoms_to_project)}"
                for cube in tqdm.tqdm(cubes, desc=desc, leave=False, disable=not show_progress):
                    solver.push()
                    for lit in cube:
                        mathsat.msat_assert_formula(msat_env, lit)
                    cube_extensions: list[list[mathsat.msat_term]] = []
                    mathsat.msat_all_sat(
                        msat_env,
                        get_converted_atoms(atoms_to_project, converter),
                        callback=lambda model: allsat_callback_store(model, cube_extensions),
                    )
                    tlemmas_raw.update(mathsat.msat_get_theory_lemmas(msat_env))
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
            tlemmas_encoded = [local_atom_manager.encode_clause_msat(lemma) for lemma in tlemmas_raw]
            cubes_encoded = [local_atom_manager.encode_model_msat(model) for model in cubes]
        pop_env()

        return cubes_encoded, tlemmas_encoded

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
