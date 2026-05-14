import os
from pathlib import Path


def symlink_filtered_contents(
    source_path: str | Path,
    target_path: str | Path,
    blacklist: list[str],
    relative_to_target: bool = True,
    files_only: bool = False,
    log: bool = True,
) -> bool:
    """
    Creates symlinks in the target directory for items in the source directory.
    - blacklist: list of filenames/foldernames to ignore.
    - files_only: if True, only symlink files; skip all directories.
    """
    source_dir = Path(source_path).resolve()
    target_dir = Path(target_path).resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory '{source_dir}' does not exist.")

    target_dir.mkdir(parents=True, exist_ok=True)
    blacklist_set = set(blacklist)

    complete = True

    for item in source_dir.iterdir():
        # Check if the item is in the manual blacklist
        if item.name in blacklist_set:
            if log:
                print(f"Skipping blacklisted item: {item.name}")
            continue

        # If files_only is True, skip any item that is a directory
        if files_only and item.is_dir():
            if log:
                print(f"Skipping directory (files_only=True): {item.name}")
            continue

        link_destination = target_dir / item.name

        if relative_to_target:
            # os.path.relpath is used to handle '..' traversals
            link_target = Path(os.path.relpath(item, start=target_dir))
        else:
            link_target = item

        try:
            link_destination.symlink_to(link_target)
            if log:
                print(f"Created symlink: {link_destination.name} -> {item}")
        except FileExistsError:
            if log:
                print(f"Skipped: '{link_destination.name}' already exists.")
        except OSError as e:
            complete = False
            if log:
                print(f"Error creating symlink for '{item.name}': {e}")

    return complete


# Example Usage:
# symlink_filtered_contents(
#     source_path="./my_source",
#     target_path="./my_target",
#     blacklist=[".DS_Store"],
#     files_only=True  # This will ignore all folders in "my_source"
# )
