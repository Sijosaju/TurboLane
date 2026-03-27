import argparse
from importlib.metadata import version, PackageNotFoundError

def main():
    parser = argparse.ArgumentParser(description="TurboLane RL-based network optimization engine")
    parser.add_argument(
        "--version", 
        action="version", 
        version=get_version()
    )
    
    args = parser.parse_args()

def get_version():
    try:
        return version("turbolane-engine")
    except PackageNotFoundError:
        return "unknown"

if __name__ == "__main__":
    main()
