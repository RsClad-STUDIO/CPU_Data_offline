"""CPU vendor classification shared by all source adapters."""
import re


def classify_vendor(name: str) -> str:
    """Classify by explicit vendor prefixes before product-family tokens."""
    n = re.sub(r"\s+", " ", name.strip().lower())
    if not n:
        return "Unknown"

    # Explicit product/vendor names take precedence over words such as "core"
    # that may occur in model suffixes or unrelated descriptions.
    prefixes = (
        ("amd", "AMD"),
        ("intel", "Intel"),
        ("apple", "Apple"),
        ("qualcomm", "Qualcomm"),
        ("snapdragon", "Qualcomm"),
        ("nvidia", "NVIDIA"),
        ("mediatek", "MediaTek"),
        ("ampere", "Ampere"),
        ("arm ", "ARM"),
        ("aarch64", "ARM"),
    )
    for prefix, vendor in prefixes:
        if n.startswith(prefix):
            return vendor

    # PassMark also contains some names that omit the vendor prefix.
    if re.search(r"\b(?:ryzen|athlon|threadripper|epyc|phenom|sempron|opteron)\b", n):
        return "AMD"
    if re.search(r"\bcore\s+(?:i[3579]|ultra\s+[3579])\b", n):
        return "Intel"
    if re.search(r"\b(?:pentium|celeron|xeon|atom|itanium)\b", n):
        return "Intel"
    return "Unknown"
