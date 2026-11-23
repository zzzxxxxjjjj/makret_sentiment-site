"""Explicit failure boundary for retired collectors; no SDK or network access."""
class RetiredProviderError(RuntimeError):
    pass

def unavailable(*args, **kwargs):
    raise RetiredProviderError("RQData is permanently disabled. Use the AKShare/iFind daily pipeline; retained historical data is not a fresh update.")

class RetiredClient:
    def __getattr__(self, name):
        return unavailable

client = RetiredClient()
