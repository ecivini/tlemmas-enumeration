from pysmt.shortcuts import get_env


class SuspendTypeChecking(object):
    """Context to disable type-checking during formula creation."""

    def __init__(self, env=None):
        if env is None:
            env = get_env()
        self.env = env
        self.mgr = env.formula_manager

    def __enter__(self):
        """Entering a Context: Disable type-checking."""
        self.mgr._do_type_check = lambda x: x
        return self.env

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exiting the Context: Re-enable type-checking."""
        self.mgr._do_type_check = self.mgr._do_type_check_real


class SuspendNodeStoring(object):
    """Context to drop PySMT nodes created inside the block."""

    def __init__(self, env=None):
        if env is None:
            env = get_env()
        self.env = env
        self.mgr = env.formula_manager
        self._snapshot = None

    def __enter__(self):
        """Snapshot formula manager nodes."""
        self._snapshot = set(self.mgr.formulae)
        return self.env

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Drop nodes created while context was active."""
        for k in self.mgr.formulae.keys() - self._snapshot:
            del self.mgr.formulae[k]
