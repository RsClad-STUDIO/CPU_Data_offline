import sys
sys.path.insert(0, '.')
from updater import _cpu_to_slug, fetch_nanoreview, _parse_specs

def main():
    tests = [
        'Intel Core i7-13700K',
        'AMD Ryzen 9 7950X',
        'Intel Core i5-12400',
    ]
    for name in tests:
        slug = _cpu_to_slug(name)
        specs = fetch_nanoreview(slug)
        if specs:
            rec = _parse_specs(name, specs, '', 0)
            print(f"{name}")
            print(f"  cores={rec['cores']}, threads={rec['threads']}")
            print(f"  base={rec['base_clock']}, boost={rec['boost_clock']}")
            print(f"  tdp={rec['tdp']}, socket={rec['socket']}, process={rec['process']}")
            print(f"  igpu={rec['igpu']}")
        else:
            print(f"{name}: 404 (スペックなし)")
        print()


if __name__ == "__main__":
    main()
