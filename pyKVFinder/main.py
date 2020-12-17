import os
import time
import logging
import numpy as np
from datetime import datetime
from .argparser import argparser
from .utils import read_vdw, read_pdb, calculate_frequencies, plot_frequencies, write_results, _write_parameters
from .grid import get_vertices, get_vertices_from_file, get_dimensions, get_sincos, detect, spatial, depth, constitutional, export

__all__ = ['pyKVFinder', 'pyKVFinderResults']

here = os.path.abspath(os.path.dirname(__file__))
_dictionary = os.path.join(here, "data/vdw.dat")


def cli():
    """
    pyKVFinder Command Line Interface (CLI)

    Parameters
    ----------
        None

    Returns
    -------
        None

    Example
    -------
    Usage: pyKVFinder [-h] [-v] [--version] [-b <str>] [-O <str>] [--nthreads <int>] [-d <str>] [-s <float>] [-i <float>] [-o <float>] [-V <float>] [-R <float>] [-S <str>] [--ignore_backbone]
                    [-D] [--plot_frequencies] [-B <.toml>] [-L <.pdb>] [--ligand_cutoff <float>]
                    <.pdb>
    """
    # Start time
    start_time = time.time()

    # Load pyKVFinder argument parser
    parser = argparser()

    # Parse command-line arguments
    args = parser.parse_args()

    # Get base name from pdb file if not defined by user
    if not args.base_name:
        args.base_name = os.path.basename(args.pdb.replace('.pdb', ''))

    # Create output directory
    os.makedirs(args.output_directory, exist_ok=True)

    # Print message to stdout
    print(f"[PID {os.getpid()}] Running pyKVFinder for: {args.pdb}")

    # Start logging
    logging.basicConfig(filename=f"{os.path.join(args.output_directory, 'KVFinder.log')}", level=logging.INFO, format='%(message)s')
    logging.info("=" * 80)
    logging.info(f"Date: {datetime.now().strftime('%a %d %B, %Y')}\nTime: {datetime.now().strftime('%H:%M:%S')}\n")
    logging.info(f"[ Running pyKVFinder for: {args.pdb} ]")
    logging.info(f"> vdW radii file: {args.dictionary}")

    if args.verbose:
        print("> Loading atomic dictionary file")
    vdw = read_vdw(args.dictionary)

    if args.verbose:
        print("> Reading PDB coordinates")
    resinfo, xyzr = read_pdb(args.pdb, vdw)

    if args.ligand:
        if args.verbose:
            print("> Reading ligand coordinates")
        _, lxyzr = read_pdb(args.ligand, vdw)
    else:
        lxyzr = None

    if args.verbose:
        print("> Calculating 3D grid dimensions")
    if args.box:
        # Get vertices from file
        args.vertices, resinfo, xyzr, args.sincos, nx, ny, nz = get_vertices_from_file(args.box, resinfo, xyzr, args.step, args.probe_in, args.probe_out, args.nthreads)

        # Set flag to boolean
        args.box = True
    else:
        # Get vertices from pdb
        args.vertices = get_vertices(xyzr, args.probe_out, args.step)

        # Calculate distance between points
        nx, ny, nz = get_dimensions(args.vertices, args.step)
        if args.verbose:
            print(f"Dimensions: (nx:{nx}, ny:{ny}, nz:{nz})")

        # Calculate sin and cos of angles a and b
        args.sincos = get_sincos(args.vertices)
        if args.verbose:
            print(f"sina: {args.sincos[0]:.2f}\tsinb: {args.sincos[2]:.2f}")
            print(f"cosa: {args.sincos[1]:.2f}\tcosb: {args.sincos[3]:.2f}")

        # Set flag to boolean
        args.box = False

    # Logging parameters
    logging.info(f"> Step: {args.step} \u00c5")
    logging.info(f"> Probe In: {args.probe_in} \u00c5")
    logging.info(f"> Probe Out: {args.probe_out} \u00c5")
    logging.info(f"> Voxel volume: {args.step * args.step * args.step} \u00c5\u00b3")
    logging.info(f"> Dimensions: (nx:{nx}, ny:{ny}, nz:{nz})")
    logging.info(f"> sina: {args.sincos[0]:.2f}\tcosa: {args.sincos[1]:.2f}")
    logging.info(f"> sinb: {args.sincos[2]:.2f}\tcosb: {args.sincos[3]:.2f}")

    # Cavity detection
    ncav, cavities = detect(nx, ny, nz, xyzr, args.vertices, args.sincos, args.step, args.probe_in, args.probe_out, args.removal_distance, args.volume_cutoff, lxyzr, args.ligand_cutoff, args.box, args.surface, args.nthreads, args.verbose)

    # Cavities were found
    if ncav > 0:
        # Spatial characterization
        surface, volume, area = spatial(cavities, ncav, args.step, args.nthreads, args.verbose)

        # Depth characterization
        if args.depth:
            depths, max_depth, avg_depth = depth(cavities, ncav, args.step, args.nthreads, args.verbose)
        else:
            depths, max_depth, avg_depth = None, None, None

        # Constitutional characterization
        residues = constitutional(cavities, resinfo, xyzr, args.vertices, args.sincos, ncav, args.step, args.probe_in, args.ignore_backbone, args.nthreads, args.verbose)
        frequencies = calculate_frequencies(residues)

        # Plot histograms of frequencies
        if args.plot_frequencies:
            output_plot = os.path.join(args.output_directory, f"{args.base_name}.histograms.pdf")
            plot_frequencies(frequencies, output_plot)
        
        # Map hydrophobicity scales
        if args.hydropathy:
            from .grid import hydropathy
            scales = hydropathy(surface, resinfo, xyzr, args.vertices, args.sincos, args.hydropathy, ncav, args.step, args.probe_in, args.ignore_backbone, args.nthreads, args.verbose)

        # Export cavities
        output_cavity = os.path.join(args.output_directory, f"{args.base_name}.KVFinder.output.pdb")
        export(output_cavity, cavities, surface, args.vertices, args.sincos, ncav, args.step, depths, args.nthreads)

        # Write results
        output_results = os.path.join(args.output_directory, f"{args.base_name}.KVFinder.results.toml")
        write_results(output_results, args.pdb, args.ligand, output_cavity, volume, area, max_depth, avg_depth, residues, frequencies, args.step)

        # Write parameters
        _write_parameters(args)
    else:
        print("> No cavities detected!")

    # Elapsed time
    elapsed_time = time.time() - start_time
    print(f"[ \033[1mElapsed time:\033[0m {elapsed_time:.4f} ]")
    logging.info(f"[ Elapsed time (s): {elapsed_time:.4f} ]\n")

    return True


class pyKVFinderResults(object):
    f"""
    A class with pyKVFinder results

    Attributes
    ----------
        cavities (numpy.ndarray): cavities 3D grid (cavities[nx, ny, nz])
        surface (numpy.ndarray): surface points 3D grid (surface[nx, ny, nz])
        depths (numpy.ndarray): depth of cavity points (depths[nx][ny][nz])
        volume (dict): dictionary with cavity name/volume pairs
        area (dict): dictionary with cavity name/area pairs
        max_depth (dict): dictionary with cavity name/maximum depth pairs
        avg_depth (dict): dictionary with cavity name/average depth pairs
        residues (dict): dictionary with cavity name/list of interface residues pairs
        frequency (dict): dictionary containing frequencies of residues and class of residues for for each detected cavity
        _vertices (numpy.ndarray): an array of vertices coordinates (origin, Xmax, Ymax, Zmax)
        _step (float): grid spacing (A)
        _ncav (int): number of cavities
        _pdb (str): path to input PDB file
        _ligand (str): path to ligand PDB file

    Methods
    -------
        export(fn = 'cavity.pdb', nthreads = {os.cpu_count() - 1}):
            Exports cavities to PDB-formatted file
        write(fn = 'results.toml', output = None):
            Writes TOML-formatted results file
        plot_frequencies(pdf = 'histogram.pdf')
            Plot histograms of frequencies in PDF file
        export_all(fn = 'results.toml', output = 'cavity.pdb', include_frequencies_plot = False, nthreads = {os.cpu_count() - 1}):
            Exports cavities and writes results. Also includes a flag to plot histograms of frequencies (residues and classes of residues).
    """

    def __init__(self, cavities: np.ndarray, surface: np.ndarray, depths: np.ndarray, volume: dict, area: dict, max_depth: dict, avg_depth: dict, residues: dict, frequencies: dict, _vertices: np.ndarray, _step: float, _ncav: int, _pdb: str = None, _ligand: str = None):
        """
        Constructs attributes for pyKVFinderResults object

        Parameters
        ----------
            cavities (numpy.ndarray): cavities 3D grid (cavities[nx, ny, nz])
            surface (numpy.ndarray): surface points 3D grid (surface[nx, ny, nz])
            depths (numpy.ndarray): depth of cavity points (depth[nx][ny][nz])
            volume (dict): dictionary with cavity name/volume pairs
            area (dict): dictionary with cavity name/area pairs
            max_depth (dict): dictionary with cavity name/maximum depth pairs
            avg_depth (dict): dictionary with cavity name/average depth pairs
            residues (dict): dictionary with cavity name/list of interface residues pairs
            _vertices (numpy.ndarray): an array of vertices coordinates (origin, Xmax, Ymax, Zmax)
            _step (float): grid spacing (A)
            _ncav (int): number of cavities
            _pdb (str): path to input PDB file
            _ligand (str): path to ligand PDB file
        """
        self.cavities = cavities
        self.surface = surface
        self.depths = depths
        self.volume = volume
        self.area = area
        self.max_depth = max_depth
        self.avg_depth = avg_depth
        self.residues = residues
        self.frequencies = frequencies
        self._vertices = _vertices
        self._step = _step
        self._ncav = _ncav
        self._pdb = os.path.abspath(_pdb)
        self._ligand = os.path.abspath(_ligand) if _ligand else None

    def __repr__(self):
        return '<pyKVFinderResults object>'

    def export(self, output: str = 'cavity.pdb', nthreads: int = os.cpu_count() - 1) -> None:
        """
        Exports cavities to PDB-formatted file

        Parameters
        ----------
            output (str): path to cavity pdb file
            nthreads (int): number of threads

        Returns
        -------
            None
        """
        sincos = get_sincos(self._vertices)
        export(output, self.cavities, self.surface, self._vertices, sincos, self._ncav, self._step, self.depths, nthreads)

    def write(self, fn: str = 'results.toml', output: str = None) -> None:
        """
       Writes file paths and cavity characterization to TOML-formatted file

        Parameters
        ----------
            fn (str): path to results TOML-formatted file (step, volume, area, maximum depth, average depth and interface residues)
            output (str): path to cavity pdb file

        Returns
        -------
            None
        """
        output = os.path.abspath(output) if output else None
        write_results(fn, self._pdb, self._ligand, output, self.volume, self.area, self.max_depth, self.avg_depth, self.residues, self.frequencies, self._step)

    def plot_frequencies(self, pdf: str = 'histograms.pdf'):
        """
        Plot histograms of frequencies in PDF file

        Parameters
        ----------
            pdf (str): A path to a PDF file

        Returns
        -------
            None
        """
        plot_frequencies(self.frequencies, pdf)

    def export_all(self, fn: str = 'results.toml', output: str = 'cavity.pdb', include_plot_frequencies: bool = False, nthreads: int = os.cpu_count() - 1) -> None:
        """
        Exports cavities and writes results. Also includes a flag to plot histograms of frequencies (residues and classes of residues).

        Parameters
        ----------
            fn (str): path to results TOML-formatted file (step, volume, area, maximum depth, average depth and interface residues)
            output (str): path to cavity pdb file
            include_plot_frequencies (bool): whether to plot frequencies (residues and classes of residues) to PDF file
            nthreads (int): number of threads

        Returns
        -------
            None
        """
        # Export cavity PDB file
        self.export(output, nthreads)
        # Write KVFinder results TOML
        self.write(fn, output)
        # Plot histograms of frequencies
        if include_plot_frequencies:
            self.plot_frequencies()


def pyKVFinder(pdb: str, ligand: str = None, dictionary: str = _dictionary, box: str = None, step: float = 0.6, probe_in: float = 1.4, probe_out: float = 4.0, removal_distance: float = 2.4, volume_cutoff: float = 5.0, ligand_cutoff: float = 5.0, include_depth: bool = False, surface: str = 'SES', ignore_backbone: bool = False, nthreads: int = os.cpu_count() - 1, verbose: bool = False) -> pyKVFinderResults:
    """
    Detects and characterizes cavities (volume, area and interface residues)

    Parameters
    ----------
        pdb (str): path to input PDB file
        ligand (str): path to ligand PDB file
        dictionary (str): path to van der Waals radii file
        box (str): path to box configuration file (TOML-formatted)
        step (float): grid spacing (A)
        probe_in (float): Probe In size (A)
        probe_out (float): Probe Out size (A)
        removal_distance (float): length to be removed from the cavity-bulk frontier (A)
        volume_cutoff (float): cavities volume filter (A3)
        ligand_cutoff (float): radius value to limit a space around a ligand (A)
        include_depth (bool): whether to characterize the depth of the detected cavities
        surface (str): SES (Solvent Excluded Surface) or SAS (Solvent Accessible Surface)
        ignore_backbone (bool): whether to ignore backbone atoms (C, CA, N, O) when defining interface residues
        nthreads (int): number of threads
        verbose: print extra information to standard output

    Returns
    -------
        results (pyKVFinderResults): class that contains cavities 3D grid, surface points 3D grid, 3D grid of cavity points depth, volume, area, maximum depth and average depth and interface residues per cavity, 3D grid vertices, grid spacing and number of cavities
    """
    if verbose:
        print("> Loading atomic dictionary file")
    vdw = read_vdw(dictionary)

    if verbose:
        print("> Reading PDB coordinates")
    resinfo, xyzr = read_pdb(pdb, vdw)

    if ligand:
        if verbose:
            print("> Reading ligand coordinates")
        _, lxyzr = read_pdb(ligand, vdw)
    else:
        lxyzr = None

    if verbose:
        print("> Calculating 3D grid dimensions")
    if box:
        # Get vertices from file
        vertices, resinfo, xyzr, sincos, nx, ny, nz = get_vertices_from_file(box, resinfo, xyzr, step, probe_in, probe_out, nthreads)

        # Set flag to boolean
        box = True
    else:
        # Get vertices from pdb
        vertices = get_vertices(xyzr, probe_out, step)
        # Calculate distance between points
        nx, ny, nz = get_dimensions(vertices, step)
        if verbose:
            print(f"Dimensions: (nx:{nx}, ny:{ny}, nz:{nz})")

        # Calculate sin and cos of angles a and b
        sincos = get_sincos(vertices)
        if verbose:
            print(f"sina: {sincos[0]:.2f}\tsinb: {sincos[2]:.2f}")
            print(f"cosa: {sincos[1]:.2f}\tcosb: {sincos[3]:.2f}")

        # Set flag to boolean
        box = False

    # Cavity detection
    ncav, cavities = detect(nx, ny, nz, xyzr, vertices, sincos, step, probe_in, probe_out, removal_distance, volume_cutoff, lxyzr, ligand_cutoff, box, surface, nthreads, verbose)

    if ncav > 0:
        # Spatial characterization
        surface, volume, area = spatial(cavities, ncav, step, nthreads, verbose)

        # Depth characterization
        if include_depth:
            depths, max_depth, avg_depth = depth(cavities, ncav, step, nthreads, verbose)
        else:
            depths, max_depth, avg_depth = None, None, None

        # Constitutional characterization
        residues = constitutional(cavities, resinfo, xyzr, vertices, sincos, ncav, step, probe_in, ignore_backbone, nthreads, verbose)
        frequencies = calculate_frequencies(residues)
    else:
        volume, area, residues, depths, max_depth, avg_depth = None, None, None, None, None, None

    # Return dict
    results = pyKVFinderResults(cavities, surface, depths, volume, area, max_depth, avg_depth, residues, frequencies, vertices, step, ncav, pdb, ligand)

    return results
