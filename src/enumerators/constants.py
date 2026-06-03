"""constants"""

import os

SAT = True
UNSAT = False

LIBRARY_PATH = os.path.dirname(os.path.realpath(__file__))

TABULAR_ALLSMT_COMMAND = LIBRARY_PATH + "/bin/tabular/tabularAllSMT.bin"

# regex for tlemmas files
TLEMMAS_FILE_REGEX = "tlemma_[0-9]+.smt2"
