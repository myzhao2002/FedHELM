"""Recovery deadline with consecutive healthy samples and intervention detection."""
def recovered(samples, elapsed, stable_since, deadline, changed=False):
    if changed or elapsed > deadline:
        return False
    return len(samples)>=3 and all(healthy(s) for s in samples[-3:]) and stable_since is not None and elapsed-stable_since>=2

def healthy(sample):
    return sample.healthy and sample.error_rate<=.05 and sample.latency_ms<=500
