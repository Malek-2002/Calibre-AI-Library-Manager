from pywinauto.application import Application
import time


CALIBRE_EXE = "calibre.exe"
CALIBRE_EXE_PATH = "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\calibre 64bit - E-book Management"


def connect_to_calibre():
    """
    Connect to a running Calibre instance.
    """

    try:
        app = Application(backend="uia").connect(path=CALIBRE_EXE)

        print("Connected to running Calibre.")

    except Exception as e:
        print(f"Could not connect to Calibre: {e}")
        raise

    # Find the main Calibre window.
    # Calibre's title normally contains "calibre".
    main_win = app.window(title_re=".*[Cc]alibre.*")

    main_win.wait("visible", timeout=10)
    main_win.set_focus()

    print("Main Calibre window found.")
    print(f"Title: {main_win.window_text()}")

    return main_win


def print_descendants(window):
    """
    Print every UI Automation descendant of the given window.
    """

    print("\n")
    print("=" * 150)
    print("CALIBRE UI AUTOMATION DESCENDANTS")
    print("=" * 150)

    descendants = window.descendants()

    print(f"Total elements found: {len(descendants)}\n")

    print(
        f"{'Idx':<5} | "
        f"{'Type':<15} | "
        f"{'Control Type':<18} | "
        f"{'AutoID':<25} | "
        f"{'Text':<40} | "
        f"{'Bounds'}"
    )

    print("-" * 150)

    for i, ctrl in enumerate(descendants):

        try:
            # Pywinauto friendly type
            ctrl_type = ctrl.friendly_class_name()

            # UIA ControlType
            control_type = getattr(
                ctrl.element_info,
                "control_type",
                ""
            )

            # UIA AutomationId
            auto_id = getattr(
                ctrl.element_info,
                "auto_id",
                ""
            )

            # Visible text
            text = ctrl.window_text() or ""
            text = text.replace("\n", " ").strip()

            # Rectangle
            rect = ctrl.rectangle()

            bounds = (
                f"L{rect.left}, "
                f"T{rect.top}, "
                f"R{rect.right}, "
                f"B{rect.bottom}"
            )

            print(
                f"[{i:03d}] | "
                f"{ctrl_type:<15} | "
                f"{control_type:<18} | "
                f"{str(auto_id):<25} | "
                f"{text[:40]:<40} | "
                f"{bounds}"
            )

        except Exception as e:

            print(
                f"[{i:03d}] | "
                f"ERROR: {e}"
            )

    print("=" * 150)
    print("END OF DUMP")
    print("=" * 150)


def main():

    main_win = connect_to_calibre()

    print_descendants(main_win)


if __name__ == "__main__":
    main()