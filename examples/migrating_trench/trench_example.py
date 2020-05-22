"""
Migrating Trench Test case
=======================

Solves the test case of a migrating trench.

[1] Clare et al. 2020. “Hydro-morphodynamics 2D Modelling Using a Discontinuous
    Galerkin Discretisation.” EarthArXiv. January 9. doi:10.31223/osf.io/tpqvy.

"""

from thetis import *
import morphological_hydro_fns_comb as morph

import numpy as np
import pandas as pd


def boundary_conditions_fn_trench(morfac=1, t_new=0, state='initial'):

    """
    Define boundary conditions for problem to be used in morphological section.

    Inputs:
    morfac - morphological scale factor used when calculating time dependent boundary conditions
    t_new - timestep model currently at used when calculating time dependent boundary conditions
    state - when 'initial' this is the initial boundary condition set; when 'update' these are the boundary
            conditions set during update forcings (ie. if fluc_bcs = True, this will be called)
    """
    left_bnd_id = 1
    right_bnd_id = 2
    left_string = ['flux']
    right_string = ['elev']

    # set boundary conditions

    swe_bnd = {}

    flux_constant = -0.22
    elev_constant2 = 0.397

    inflow_constant = [flux_constant]
    outflow_constant = [elev_constant2]
    return swe_bnd, left_bnd_id, right_bnd_id, inflow_constant, outflow_constant, left_string, right_string


## Note it is necessary to run trench_hydro first to get the hydrodynamics simulation

def run_migrating_trench(conservative, hydro):
    # define mesh
    lx = 16
    ly = 1.1
    nx = lx*5
    ny = 5
    mesh2d = RectangleMesh(nx, ny, lx, ly)

    x, y = SpatialCoordinate(mesh2d)

    # define function spaces
    V = FunctionSpace(mesh2d, 'CG', 1)
    P1_2d = FunctionSpace(mesh2d, 'DG', 1)

    # define underlying bathymetry
    bathymetry_2d = Function(V, name='Bathymetry')
    initialdepth = Constant(0.397)
    depth_riv = Constant(initialdepth - 0.397)
    depth_trench = Constant(depth_riv - 0.15)
    depth_diff = depth_trench - depth_riv

    trench = conditional(le(x, 5), depth_riv, conditional(le(x, 6.5), (1/1.5)*depth_diff*(x-6.5) + depth_trench,
                                                             conditional(le(x, 9.5), depth_trench, conditional(le(x, 11), -(1/1.5)*depth_diff*(x-11) + depth_riv,
                                                                                                                          depth_riv))))
    bathymetry_2d.interpolate(-trench)

    solver_obj, update_forcings_tracer, outputdir = morph.morphological(boundary_conditions_fn=boundary_conditions_fn_trench, morfac=100, morfac_transport=True, suspendedload=True, convectivevel=True,
                  bedload=True, angle_correction=False, slope_eff=True, seccurrent=False, wetting_and_drying = False,
                                                                        mesh2d=mesh2d, bathymetry_2d=bathymetry_2d, input_dir='hydrodynamics_trench', ks=0.025, average_size=160 * (10**(-6)), dt=0.3, final_time=15*3600, cons_tracer=conservative)#, wetting_alpha=wd_fn)

    # run model
    solver_obj.iterate(update_forcings=update_forcings_tracer)

    # record final tracer and final bathymetry
    xaxisthetis1 = []
    tracerthetis1 = []
    baththetis1 = []

    for i in np.linspace(0, 15.8, 80):
        xaxisthetis1.append(i)
        if conservative:
            d = solver_obj.fields.bathymetry_2d.at([i, 0.55]) + solver_obj.fields.elev_2d.at([i, 0.55])
            tracerthetis1.append(solver_obj.fields.tracer_2d.at([i, 0.55])/d)
            baththetis1.append(solver_obj.fields.bathymetry_2d.at([i, 0.55]))
        else:
            tracerthetis1.append(solver_obj.fields.tracer_2d.at([i, 0.55]))
            baththetis1.append(solver_obj.fields.bathymetry_2d.at([i, 0.55]))

    # check tracer conservation
    tracer_mass_int, tracer_mass_int_rerr = solver_obj.callbacks['timestep']['tracer_2d total mass']()
    print("Tracer total mass error: %11.4e" % (tracer_mass_int_rerr))

    #if conservative:
    #    assert abs(tracer_mass_int_rerr) < 8e-2, 'tracer is not conserved'
    #else:
    #    assert abs(tracer_mass_int_rerr) < 5e-1, 'tracer is not conserved'

    # check tracer and bathymetry values using previous runs
    tracer_solution = pd.read_csv('tracer.csv')
    bed_solution = pd.read_csv('bed.csv')

    assert max([abs((tracer_solution['Tracer'][i] - tracerthetis1[i])/tracer_solution['Tracer'][i]) for i in range(len(tracerthetis1))]) < 0.1, "error in tracer"

    assert max([abs((bed_solution['Bathymetry'][i] - baththetis1[i])) for i in range(len(baththetis1))]) < 0.007, "error in bed level"


def conservative_case(hydro=False):
    run_migrating_trench(True, hydro)


def non_conservative_case(hydro=False):
    run_migrating_trench(False, hydro)


if __name__ == '__main__':
    non_conservative_case(hydro=False)
