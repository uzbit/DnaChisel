from .DnaCanvas import DnaCanvas, NoSolutionFoundError
from patterns import DnaNotationPattern, homopolymer_pattern, enzyme_pattern
from .constraints import (
    DoNotModifyConstraint,
    GCContentConstraint,
    EnforcePatternConstraint,
    NoPatternConstraint,
    EnforceTranslationConstraint,
    Constraint,
    SequenceLengthConstraint,
    NoNonuniqueKmerConstraint,
    NoBlastMatchConstraint
)
from objectives import (
    CodonOptimizationObjective,
    Objective,
    GCContentObjective
)
from biotools import (
    random_dna_sequence,
    random_protein_sequence,
    reverse_complement,
    reverse_translate,
    translate
)
from .presets import PROVIDERS_CONSTRAINTS

from .utils import random_compatible_dna_sequence

from .version import __version__
