"""Define DnaCanvas.

DnaCanvas is where the whole problem is defined: sequence,
constraints, objectives.
"""

from copy import deepcopy, copy
import ctypes
import itertools as itt

import numpy as np

from biotools import translate, reverse_translate, gc_content, read_fasta, reverse_complement
import biotables
import constraints as cst

from tqdm import tqdm

class NoSolutionFoundError(Exception):
    pass

class DnaCanvas:
    """A DNA Canvas specifies a constrained DNA optimization problem.

    The original constraints, objectives, and original sequence of the problem
    are stored in the DNA Canvas. This class also has methods to display
    reports on the constraints and objectives, as well as solving the
    constraints and objectives.

    Examples
    --------

    >>> from dnachisel import *
    >>> canvas = DnaCanvas(
    >>>     sequence = "ATGCGTGTGTGC...",
    >>>     constraints = [constraint1, constraint2, ...],
    >>>     objectives = [objective1, objective2, ...]
    >>> )
    >>> canvas.solve_all_constraints_one_by_one()
    >>> canvas.maximize_all_objectives_one_by_one()
    >>> print(canvas.constraints_summary())
    >>> print(canvas.objectives_summary())


    Parameters
    ----------

    sequence
      A string of ATGC characters (they must be upper case!), e.g. "ATTGTGTA"

    constraints
      A list of objects of type ``Constraint``.

    objectives
      A list of objects of type ``Objective`` specifying what must be optimized
      in the problem. Note that each objective has a float ``boost`` parameter.
      The larger the boost, the more the objective is taken into account during
      the optimization.

    Attributes
    ----------

    sequence
      The sequence

    constraints
      The list of constraints

    objectives
      The list of objectives

    possible_mutations
      A dictionnary indicating the possible mutations. Note that this is only
      computed the first time that canvas.possible_mutations is invoked.

    Notes
    -----

    The dictionnary ``self.possible_mutations`` is of the form
    ``{location1 : list1, location2: list2...}``
    where ``location`` is either a single index (e.g. 10) indicating the
    position of a nucleotide to be muted, or a couple ``(start, end)``
    indicating a whole segment whose sub-sequence should be replaced.
    The ``list`` s are lists of possible sequences to replace each location,
    e.g. for the mutation of a whole codon ``(3,6): ["ATT", "ACT", "AGT"]``.
    """





    def __init__(self, sequence, constraints=None, objectives=None):

        self.sequence = sequence
        self.original_sequence = sequence
        self.constraints = [] if constraints is None else constraints
        self.objectives = [] if objectives is None else objectives
        self.possible_mutations_dict = None

    def extract_subsequence(self, location):
        """Return the subsequence (a string) atthe given location).

         The ``location`` can be either an index (an integer) indicating the
         position of a single nucleotide, or a list/couple ``(start, end)``
         indicating a whole sub-segment.
        """
        if hasattr(location, "__iter__"):
            start, end = location
            return self.sequence[start:end]
        else:
            return self.sequence[location]

    # MUTATIONS

    @property
    def possible_mutations(self):
        if self.possible_mutations_dict is None:
            self.compute_possible_mutations()
        return self.possible_mutations_dict

    def compute_possible_mutations(self):
        """Compute all possible mutations that can be applied to the sequence.

        The result of the computations is stored in ``self.possible_mutations``
        (see ``DnaCanvas`` documentation).

        The possible mutations are constrained by the ``constraints`` of the
        DnaCanvas with respect to the following rules:

        - ``DoNotModify``  constraints disable mutations for the nucleotides of
          the concerned segments.
        - ``EnforceTranlation`` constraints ensure that on the concerned
          segments only codons that translate to the imposed amino-acid will
          be considered, so a triplet of nucleotides that should code for
          Asparagin will see its choices down to ["AAT", "AAC"], instead of
          the 64 possible combinations of free triplets.

        """
        self.possible_mutations_dict = {}
        unibase_mutable = np.ones(len(self.sequence))
        for constraint in self.constraints:
            if isinstance(constraint, cst.DoNotModifyConstraint):
                start, end = constraint.window
                unibase_mutable[start:end] = 0
        for constraint in self.constraints:
            if isinstance(constraint, cst.EnforceTranslationConstraint):
                start, end = constraint.window
                for i, aa in enumerate(constraint.translation):
                    if constraint.strand == 1:
                        cstart, cstop = start + 3 * i, start + 3 * (i + 1)
                        seq_codon = self.sequence[cstart:cstop]
                    else:
                        cstart, cstop = end - 3 * (i+1), end - 3 * i
                        seq_codon = reverse_complement(
                                        self.sequence[cstart:cstop])
                    possible_codons = biotables.CODONS_SEQUENCES[aa][:]
                    local_immutable_unibases = (
                        unibase_mutable[cstart:cstop] == 0
                    ).nonzero()[0]

                    def array_subsequence(seq, inds):
                        return np.array([seq[i] for i in inds])
                    if len(local_immutable_unibases):
                        reachable_possible_codons = [
                            codon
                            for codon in possible_codons
                            if all(
                                array_subsequence(
                                    seq_codon,
                                    local_immutable_unibases
                                ) ==
                                array_subsequence(
                                    codon,
                                    local_immutable_unibases
                                )
                            )
                        ]
                        if reachable_possible_codons == []:
                            raise NoSolutionFoundError(
                                "An EnforceTranslation constraint seems to"
                                " clash with a DoNotTouch constraint."
                            )
                        possible_codons = reachable_possible_codons
                    if constraint.strand == -1:
                        possible_codons = [
                            reverse_complement(possible_codon)
                            for possible_codon in possible_codons
                        ]
                    unibase_mutable[cstart:cstop] = 0

                    # if seq_codon in possible_codons:
                    #    possible_codons.remove(seq_codon)

                    #if (possible_codons != []) and possible_codons != [seq_codon]:
                    if possible_codons not in [[], [seq_codon]]:
                        self.possible_mutations_dict[(cstart, cstop)] = \
                            possible_codons
        #print unibase_mutable
        for i in unibase_mutable.nonzero()[0]:
            self.possible_mutations_dict[i] = ["A", "T", "G", "C"]

    def mutation_space_size(self):
        """Return the total number of possible sequence variants.

        The result is a float.
        """
        return np.prod([
            1.0*len(v) #+ 1.0
            for v in self.possible_mutations.values()
        ])

    def iter_mutations_space(self):
        return itt.product(*[
            #[None] +
            [(k, seq) for seq in values]
            for k, values in self.possible_mutations.items()
        ])

    def get_random_mutations(self, n_mutations=1):
        """Pick a random set of possible mutations.

        Returns a list ``[(location1, new_sequence1), ...]`` where location is
        either an index or a couple ``(start, end)`` and ``new_sequence`` is
        a DNA string like ``ATGC``, indicating that the canvas' sequence
        should be modified through mutations of the form
        ``self.sequence[location1] = new_sequence1``.
        """
        locs = self.possible_mutations.keys()
        if n_mutations == 1:
            indices = [np.random.randint(0, len(locs), 1)]
        else:
            indices = np.random.choice(range(0, len(locs)), n_mutations,
                                       replace=False)
        mutations = []
        for index in indices:
            location = locs[index]
            subsequence = self.extract_subsequence(location)
            choices = self.possible_mutations[location]
            if subsequence in choices:
                choices.remove(subsequence)
            if choices == []:
                mutations.append(None)
            else:
                choice = np.random.choice(choices)
                mutations.append((location, choice))
        return mutations

    def mutate_sequence(self, mutations):
        """Modify the canvas's sequence (inplace) through mutations.

        ``mutations`` must be a list ``[(location1, new_sequence1), ...]``
        where location is either an index or a couple ``(start, end)`` and
        ``new_sequence`` is a DNA string like ``ATGC``, indicating that the
        canvas' sequence should be modified through mutations of the form
        ``self.sequence[location1] = new_sequence1``.
        """
        sequence_buffer = ctypes.create_string_buffer(self.sequence)
        for mutation in mutations:
            if mutation is not None:
                ind, seq = mutation
                if isinstance(ind, int):
                    sequence_buffer[ind] = seq
                else:
                    start, end = ind
                    sequence_buffer[start:end] = seq
        self.sequence = sequence_buffer.value

     # CONSTRAINTS

    def all_constraints_evaluations(self):
        """Return a list of the evaluations of each constraint of the canvas.

        Returns ``[c.evaluate(self) for c in self.constraints]``
        """
        return [
            constraint.evaluate(self)
            for constraint in self.constraints
        ]

    def all_constraints_pass(self):
        """Return True if and only if the canvas meet all its constraints."""
        return all([
            evaluation.passes
            for evaluation in self.all_constraints_evaluations()
        ])

    def constraints_summary(self, failed_only=False, failed_last=True):
        """Print each constraint with a summary of its evaluation.

        This method is meant for interactive use in a terminal or IPython
        notebook.
        """
        evaluations = self.all_constraints_evaluations()
        failed_evaluations = [e for e in evaluations if not e.passes]
        if failed_only:
            evaluations = failed_evaluations
        if failed_last:
            evaluations = sorted(evaluations, key=lambda e: not e.passes)
        if failed_evaluations == []:
            message = "SUCCESS - all constraints evaluations pass"
        else:
            message = ("FAILURE: %d constraints evaluations failed" %
                       len(failed_evaluations))
        text_evaluations = "\n".join([
            "%s %s" % (evaluation.constraint, evaluation)
            for evaluation in evaluations
        ])
        return ("\n===> %s\n%s\n" % (message, text_evaluations))

    def solve_all_constraints_by_exhaustive_search(self, verbose=False,
                                                   progress_bar=False):
        """Solve all constraints by exploring the whole search space.

        This method iterates over ``self.iter_mutations_space()`` (space of
        all sequences that could be reached through successive mutations) and
        stops when it finds a sequence which meets all the constraints of the
        canvas.
        """
        mutation_space = self.iter_mutations_space()
        if progress_bar:
            mutation_space = tqdm(mutation_space, desc="Mutation", leave=False)
        for mutations in mutation_space:
            self.mutate_sequence(mutations)
            if verbose:
                print(self.constraints_summary())
            if self.all_constraints_pass():
                return
            else:
                self.sequence = self.original_sequence

        summary = self.constraints_summary()
        raise NoSolutionFoundError(
            summary +
            "Exhaustive search failed to satisfy all constraints.")

    def solve_all_constraints_by_random_mutations(self, max_iter=1000,
                                                  n_mutations=3,
                                                  verbose=False,
                                                  progress_bar=False):
        """Solve all constraints by successive sets of random mutations.

        This method modifies the canvas sequence by applying a number
        ``n_mutations`` of random mutations. The constraints are then evaluated
        on the new sequence. If all constraints pass, the new sequence becomes
        the canvas's new sequence.
        If not all constraints pass, the sum of all scores from failing
        constraints is considered. If this score is superior to the score of
        the previous sequence, the new sequence becomes the canvas's new
        sequence.

        This operation is repeated `max_iter` times at most, after which
        a ``NoSolutionFoundError`` is thrown.


        """
        #mutations_locs = self.possible_mutations.keys()
        evaluations = self.all_constraints_evaluations()
        score = sum([
            e.score
            for e in evaluations
            if not e.passes
        ])
        range_iter = range(max_iter)
        if progress_bar:
            range_iter = tqdm(range_iter, desc="Random Mutation", leave=False)
        for iteration in range_iter:
            if score == 0:
                return
            mutations = self.get_random_mutations(n_mutations)
            """
            random_mutations_inds = np.random.randint(
                0, len(mutations_locs), n_mutations)
            mutations = [
                (mutations_locs[ind],
                 np.random.choice(
                    self.possible_mutations[mutations_locs[ind]], 1
                 )[0]
                )
                for ind in random_mutations_inds
            ]
            """
            if verbose:
                print(self.constraints_summary())
            previous_sequence = self.sequence
            self.mutate_sequence(mutations)

            evaluations = self.all_constraints_evaluations()
            new_score = sum([
                e.score
                for e in evaluations
                if not e.passes
            ])
            # print "now scores with muts", map(str,evaluations), new_score, score
            if new_score > score:
                score = new_score
            else:
                self.sequence = previous_sequence
        summary = self.constraints_summary()
        raise NoSolutionFoundError(
            summary +
            "Random search hit max_iterations without finding a solution.")

    def solve_constraint_by_localization(self, constraint,
                                         randomization_threshold=10000,
                                         max_random_iters=1000, verbose=False,
                                         progress_bars=0):
        """Solve a particular constraint using local, targeted searches.

        Parameters
        ----------

        constraint
          The ``Constraint`` object for which the sequence should be solved

        randomization_threshold
          Local problems with a search space size under this threshold will be
          solved using deterministic, exhaustive search of the search space
          (see ``solve_all_constraints_by_exhaustive_search``)
          When the space size is above this threshold, local searches will use
          a randomized search algorithm
          (see ``solve_all_constraints_by_random_mutations``).

        max_random_iters
          Maximal number of iterations when performing a randomized search
          (see ``solve_all_constraints_by_random_mutations``).

        verbose
          If True, each step of each search will print in the console the
          evaluation of each constraint.

        """

        evaluation = constraint.evaluate(self)
        if evaluation.passes:
            return
        if evaluation.windows is not None:

            windows = evaluation.windows
            if progress_bars > 0:
                windows = tqdm(windows, desc="Window", leave=False)

            for window in windows:
                if verbose:
                    print(window)
                do_not_modify_window = [
                    max(0, window[0] - 5),
                    min(window[1] + 5, len(self.sequence))
                ]
                localized_constraints = [
                    _constraint.localized(do_not_modify_window)
                    for _constraint in self.constraints
                ]
                passing_localized_constraints = [
                    _constraint
                    for _constraint in localized_constraints
                    if _constraint.evaluate(self).passes
                ]
                localized_canvas = DnaCanvas(
                    sequence=self.sequence,
                    constraints=[
                        cst.DoNotModifyConstraint([0, do_not_modify_window[0]]),
                        cst.DoNotModifyConstraint([do_not_modify_window[1],
                                                   len(self.sequence)]),
                    ] + [
                        constraint.localized(do_not_modify_window)
                    ] + passing_localized_constraints
                )
                #print constraint, localized_canvas.mutation_space_size()
                #print localized_canvas.possible_mutations
                if (localized_canvas.mutation_space_size() <
                        randomization_threshold):
                    localized_canvas.solve_all_constraints_by_exhaustive_search(
                        verbose=verbose, progress_bar= progress_bars > 1)
                    self.sequence = localized_canvas.sequence
                else:
                    localized_canvas.solve_all_constraints_by_random_mutations(
                        max_iter=max_random_iters, n_mutations=1,
                        verbose=verbose, progress_bar= progress_bars > 1)
                    self.sequence = localized_canvas.sequence

    def solve_all_constraints_one_by_one(self, max_loops=1,
                                         randomization_threshold=10000,
                                         max_random_iters=1000, verbose=False,
                                         progress_bars=0):
        """Solve each of the canvas' constraints in turn, using local, targeted
        searches.

        Parameters
        ----------

        max_loops
          Number of times that the constraints will be considered one after the
          other. The function may stop sooner, as soon as all constraints pass.
          If after all these loops some constraints are still not passing, a
          ``NoSolutionFoundError`` is raised.

        randomization_threshold
          Local problems with a search space size under this threshold will be
          solved using deterministic, exhaustive search of the search space
          (see ``solve_all_constraints_by_exhaustive_search``)
          When the space size is above this threshold, local searches will use
          a randomized search algorithm
          (see ``solve_all_constraints_by_random_mutations``).

        max_random_iters
          Maximal number of iterations when performing a randomized search
          (see ``solve_all_constraints_by_random_mutations``).

        verbose
          If True, each step of each search will print in the console the
          evaluation of each constraints.

        """

        range_loops = range(max_loops)
        if progress_bars > 0:
            range_loops = tqdm(range_loops, desc="Loop", leave=False)
        for iteration in range_loops:
            evaluations = self.all_constraints_evaluations()
            failed_constraints = [
                evaluation.constraint
                for evaluation in evaluations
                if not evaluation.passes
            ]
            if failed_constraints == []:
                return
            if progress_bars > 1:
                failed_constraints = tqdm(failed_constraints, leave=False,
                                          desc="Failing Constraint")
            for constraint in failed_constraints:
                self.solve_constraint_by_localization(
                    constraint, randomization_threshold,
                    max_random_iters, verbose=verbose,
                    progress_bars=progress_bars - 2
                )
        if not self.all_constraints_pass():
            summary = self.constraints_summary(failed_only=True)
            raise NoSolutionFoundError(
                summary +
                "One-by-one could not solve all constraints before max_loops."
            )

    # OBJECTIVES

    def all_objectives_evaluations(self):
        """Return a list of the evaluation of each objective of the canvas"""
        return [
            objective.evaluate(self)
            for objective in self.objectives
        ]

    def all_objectives_score_sum(self):
        """Return the total sum of all objective evaluation's score"""
        return sum([
            objective.boost * objective.evaluate(self).score
            for objective in self.objectives
        ])

    def objectives_summary(self, failed_only=False):
        """Return a string summarizing the evaluation of all objectives"""
        score = self.all_objectives_score_sum()
        message = "TOTAL OBJECTIVES SCORE: %.02f" % score
        objectives_texts = "\n".join([
            "%s: %s" % (evaluation.objective, evaluation)
            for evaluation in self.all_objectives_evaluations()
        ])
        return "\n===> %s\n%s\n" % (message, objectives_texts)

    def maximize_objectives_by_exhaustive_search(self, verbose=False):
        """
        """
        if not self.all_constraints_pass():
            summary = self.constraints_summary(failed_only=True)
            raise NoSolutionFoundError(
                summary +
                "Optimization can only be done when all constraints are"
                "verified."
            )
        current_score = self.all_objectives_score_sum()
        current_best_sequence = self.sequence
        for mutations in self.iter_mutations_space():
            self.mutate_sequence(mutations)
            if self.all_constraints_pass():
                score = self.all_objectives_score()
                if score > current_score:
                    current_score = score
                    current_best_sequence = self.sequence
            self.sequence = self.original_sequence
        self.sequence = current_best_sequence

    def maximize_objectives_by_random_mutations(self, max_iter=1000,
                                                n_mutations=3,
                                                verbose=False,
                                                progress_bar=False):
        """
        """
        if not self.all_constraints_pass():
            summary = self.constraints_summary()
            raise ValueError(summary + "Optimization can only be done when all"
                             " constraints are verified")
        mutations_locs = self.possible_mutations.keys()
        score = self.all_objectives_score_sum()
        range_iters =  range(max_iter)
        if progress_bar:
            range_iters = tqdm(range_iters, desc="Random mutation",
                               leave=False)
        for iteration in range(max_iter):
            random_mutations_inds = np.random.randint(
                0, len(mutations_locs), n_mutations)
            mutations = [
                (mutations_locs[ind],
                 np.random.choice(
                    self.possible_mutations[mutations_locs[ind]], 1
                 )[0]
                )
                for ind in random_mutations_inds
            ]
            if verbose:
                print(self.constraints_summary())
            previous_sequence = self.sequence
            self.mutate_sequence(mutations)
            if self.all_constraints_pass():
                new_score = self.all_objectives_score_sum()
                if new_score > score:
                    score = new_score
                else:
                    self.sequence = previous_sequence
            else:
                self.sequence = previous_sequence

    def maximize_objective_by_localization(self, objective, windows=None,
        randomization_threshold=10000, max_random_iters=1000, verbose=False,
        progress_bars=False):
        """Maximize the objective via local, targeted mutations."""

        if windows is None:
            windows = objective.evaluate(self).windows
            if windows is None:
                raise ValueError(
                    "max_objective_by_localization requires either that"
                    " windows be provided or that the objective evaluation"
                    " returns windows."
                )
        if progress_bars > 0:
            windows = tqdm(windows, desc="Window", leave=False)
        for window in windows:
            if verbose:
                print(window)
            do_not_modify_window = [
                max(0, window[0] - 5),
                min(window[1] + 5, len(self.sequence))
            ]
            localized_canvas = DnaCanvas(
                sequence=self.sequence,
                constraints=[
                    _constraint.localized(do_not_modify_window)
                    for _constraint in self.constraints
                ] + [
                    cst.DoNotModifyConstraint([0, do_not_modify_window[0]]),
                    cst.DoNotModifyConstraint([do_not_modify_window[1],
                                               len(self.sequence)]),
                ],
                objectives = [
                    _objective.localized(window)
                    for _objective in self.objectives
                ]
            )

            if (localized_canvas.mutation_space_size() <
                    randomization_threshold):
                localized_canvas.maximize_objectives_by_exhaustive_search(
                    verbose=verbose, progress_bar=progress_bars > 1)
            else:
                localized_canvas.maximize_objectives_by_random_mutations(
                    max_iter=max_random_iters, n_mutations=1,
                    verbose=verbose, progress_bar=progress_bars > 1)
            self.sequence = localized_canvas.sequence


    def maximize_all_objectives_one_by_one(self, n_loops=1,
                                           randomization_threshold=10000,
                                           max_random_iters=1000,
                                           verbose=False,
                                           progress_bars=0):


        range_loops = range(n_loops)
        if progress_bars > 0:
            range_loops = tqdm(range_loops, desc="Loop", leave=False)

        for iteration in range_loops:
            objectives = self.objectives
            if progress_bars > 1:
                objectives = tqdm(objectives, desc="Objective", leave=False)
            for objective in objectives:
                self.maximize_objective_by_localization(
                    objective,
                    randomization_threshold=randomization_threshold,
                    max_random_iters=max_random_iters,
                    verbose=verbose,
                    progress_bars = (progress_bars - 2)
                )

    def include_pattern_by_successive_tries(self, pattern, window=None):
        if window is None:
            window = [0, len(self.sequence)]
        constraint = cst.EnforcePatternConstraint(pattern, window)
        self.constraints.append(constraint)
        start, end = window
        for i in range(start, end - pattern.size):
            original_sequence = self.sequence
            window = [i, i+pattern.size]
            self.mutate_sequence([(window, pattern.pattern)])
            try:
                self.solve_all_constraints_one_by_one()
                return # Success !
            except NoSolutionFoundError:
                self.sequence = original_sequence
        self.constraints.pop() # remove the pattern constraint
        raise NoSolutionFoundError("Failed to insert the pattern")