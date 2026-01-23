import os
import subprocess
import ffmpeg

colmap_command = 'colmap'
brush_command = '/Users/cyprienlengagne/Documents/code/EPFL/ENAC/HUD/tools/brush/target/release/brush'


def main():
    root_path = 'output'
    dirs = prepare_dirs(root_path)
    print(f"Prepared directories: {dirs}")

    stream = make_frames_stream('input.mp4', dirs['images'], fps=3)
    stream.run()
    print(f"Frame extraction completed in {dirs['images']}.")

    print("Starting COLMAP reconstruction...")
    run_colmap(dirs)

    print("Starting Brush visualization...")
    run_brush(dirs)

    print("Process completed.")



def prepare_dirs(root_path: str):
    images = os.path.join(root_path, 'images')

    if not os.path.exists(images):
        os.makedirs(images)

    colmap = os.path.join(root_path, 'colmap')
    if not os.path.exists(colmap):
        os.makedirs(colmap)
    
    splats = os.path.join(root_path, 'splats')
    if not os.path.exists(splats):
        os.makedirs(splats)
    
    return {
        'images': images,
        'workspace': root_path,
        'colmap': colmap,
        'splats': splats,
    }

def make_frames_stream(input_file, output_directory, fps=5, max_size: tuple[int, int]=(1280, 720)):
    # create folder if it doesn't exist
    import os
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    
    # exports at a certain fps, and resize to 
    return (
        ffmpeg
        .input(input_file)
        .filter('scale', size=f"{max_size[0]}:{max_size[1]}", force_original_aspect_ratio='decrease')
        .filter('fps', fps=fps)
        .output(f'{output_directory}/frame_%04d.png')
    )

def run_colmap(paths: dict):
    return run([
        colmap_command, 'automatic_reconstructor',
        '--image_path', paths['images'],
        '--workspace_path', paths['colmap'],
    ])


def run_brush(paths: dict):
    # ./brush ~/Documents/code/EPFL/ENAC/HUD/tools/TestProject/south-building-images --with-viewer
    return run([
        brush_command,
        paths['workspace'],
        '--export-path', paths['splats'],
        '--with-viewer',
    ])

def run(cmd: list[str], cwd: str | None = None):
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

if __name__ == '__main__':
    main()