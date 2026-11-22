"""CPU vendor classification shared by all source adapters."""

def classify_vendor(name: str) -> str:
    n = name.strip().lower()
    if n.startswith("amd") or any(x in n for x in ("ryzen", "athlon", "threadripper", "epyc", "phenom", "sempron", "opteron")):
        return "AMD"
    if n.startswith("intel") or any(x in n for x in ("core", "pentium", "celeron", "xeon", "atom", "itanium")):
        return "Intel"
    if n.startswith("apple"):
        return "Apple"
    if n.startswith(("qualcomm", "snapdragon")):
        return "Qualcomm"
    if n.startswith(("arm ", "aarch64")):
        return "ARM"
    if n.startswith("nvidia"):
        return "NVIDIA"
    if n.startswith("mediatek"):
        return "MediaTek"
    if n.startswith("ampere"):
        return "Ampere"
    return "Unknown"

