
from pathlib import Path

PROJECT_NAME = "TruthTrail"

REQUIRED_DIRECTORIES = [
    Path("data/raw"),
    Path("data/processed"),
    Path("reports"),
    Path("tests"),
]


def initialize_project():
    print("=" * 50)
    print(f"{PROJECT_NAME} - Data Detective")
    print("=" * 50)

    for directory in REQUIRED_DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Project folder ready: {directory}")


if __name__ == "__main__":
    initialize_project()
