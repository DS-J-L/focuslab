"""Project entry point; actual desktop UI is planned for PR-00."""

from focuslab import __version__


def main() -> None:
    """Show the scaffold status without opening sensors or writing user data."""
    print(f"FocusLab {__version__} - initial scaffold")
    print("Desktop UI and sensors are not implemented yet. See DEVELOPMENT_PLAN.md.")


if __name__ == "__main__":
    main()
