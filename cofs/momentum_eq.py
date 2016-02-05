"""
3D momentum and tracer equations for hydrostatic Boussinesq flow.

Tuomas Karna 2015-02-23
"""
from utility import *

g_grav = physical_constants['g_grav']
rho_0 = physical_constants['rho0']


class MomentumEquation(Equation):
    """3D momentum equation for hydrostatic Boussinesq flow."""
    def __init__(self, bnd_markers, bnd_len,
                 solution, eta, bathymetry, w=None,
                 w_mesh=None, dw_mesh_dz=None,
                 uv_bottom=None, bottom_drag=None, lin_drag=None,
                 viscosity_v=None, viscosity_h=None,
                 coriolis=None, source=None,
                 baroc_head=None,
                 lax_friedrichs_factor=None, uv_mag=None,
                 uv_p1=None,
                 nonlin=True):
        self.space = solution.function_space()
        self.mesh = self.space.mesh()
        self.nonlin = nonlin
        self.solution = solution
        # this dict holds all time dep. args to the equation
        self.kwargs = {'eta': eta,
                       'w': w,
                       'w_mesh': w_mesh,
                       'dw_mesh_dz': dw_mesh_dz,
                       'uv_bottom': uv_bottom,
                       'bottom_drag': bottom_drag,
                       'lin_drag': lin_drag,
                       'viscosity_v': viscosity_v,
                       'viscosity_h': viscosity_h,
                       'baroc_head': baroc_head,
                       'coriolis': coriolis,
                       'source': source,
                       'lax_friedrichs_factor': lax_friedrichs_factor,
                       'uv_mag': uv_mag,
                       'uv_p1': uv_p1,
                       }
        # time independent arg
        self.bathymetry = bathymetry

        # test and trial functions
        self.test = TestFunction(self.space)
        self.tri = TrialFunction(self.space)

        ufl_elem = self.space.ufl_element()
        if isinstance(ufl_elem, EnrichedElement):
            # get the first elem of enriched space
            ufl_elem = ufl_elem._elements[0]
        if not hasattr(ufl_elem, '_A'):
            # For HDiv elements
            ufl_elem = ufl_elem._element
        self.horizontal_dg = ufl_elem._A.family() != 'Lagrange'
        self.vertical_dg = ufl_elem._B.family() != 'Lagrange'
        self.HDiv = ufl_elem._A.family() == 'Raviart-Thomas'

        eta_elem = eta.function_space().ufl_element()
        self.eta_is_dg = eta_elem._A.family() != 'Lagrange'

        self.grad_eta_by_parts = self.eta_is_dg
        self.horiz_advection_by_parts = True

        # mesh dependent variables
        self.normal = FacetNormal(self.mesh)
        self.xyz = SpatialCoordinate(self.mesh)
        self.e_x, self.e_y, self.e_y = unit_vectors(3)

        # boundary definitions
        self.boundary_markers = bnd_markers
        self.boundary_len = bnd_len

        # boundary conditions
        # maps bnd_marker to dict of external functions e.g. {'elev':eta_ext}
        self.bnd_functions = {}

    def mass_term(self, solution):
        """All time derivative terms on the LHS, without the actual time
        derivative.

        Implements A(u) for  d(A(u_{n+1}) - A(u_{n}))/dt
        """
        return inner(solution, self.test) * dx

    def pressure_grad(self, eta, baroc_head, uv, total_h, by_parts=True,
                      **kwargs):
        if baroc_head is not None:
            head = eta + baroc_head
        else:
            head = eta
        if by_parts:
            div_test = (Dx(self.test[0], 0) +
                        Dx(self.test[1], 1))
            f = -g_grav*head*div_test*dx
            # head_star = avg(head) + 0.5*sqrt(avg(total_h)/g_grav)*jump(uv, self.normal)
            head_star = avg(head)
            jump_n_dot_test = (jump(self.test[0], self.normal[0]) +
                               jump(self.test[1], self.normal[1]))
            f += g_grav*head_star*jump_n_dot_test*(dS_v + dS_h)
            n_dot_test = (self.normal[0]*self.test[0] +
                          self.normal[1]*self.test[1])
            f += g_grav*head*n_dot_test*(ds_bottom + ds_surf)
            for bnd_marker in self.boundary_markers:
                funcs = self.bnd_functions.get(bnd_marker)
                ds_bnd = ds_v(int(bnd_marker))
                if baroc_head is not None:
                    f += g_grav*baroc_head*n_dot_test*ds_bnd
                special_eta_flux = funcs is not None and 'elev' in funcs
                if not special_eta_flux:
                    f += g_grav*eta*n_dot_test*ds_bnd
        else:
            grad_head_dot_test = (Dx(head, 0)*self.test[0] +
                                  Dx(head, 1)*self.test[1])
            f = g_grav * grad_head_dot_test * dx
        return f

    def horizontal_advection(self, solution, total_h, lax_friedrichs_factor,
                             uv_mag=None, uv_p1=None, **kwargs):
        if not self.nonlin:
            return 0
        if self.horiz_advection_by_parts:
            f = -(Dx(self.test[0], 0)*solution[0]*solution[0] +
                  Dx(self.test[0], 1)*solution[0]*solution[1] +
                  Dx(self.test[1], 0)*solution[1]*solution[0] +
                  Dx(self.test[1], 1)*solution[1]*solution[1])*dx
            uv_av = avg(solution)
            un_av = (uv_av[0]*self.normal('-')[0] +
                     uv_av[1]*self.normal('-')[1])
            s = 0.5*(sign(un_av) + 1.0)
            uv_up = solution('-')*s + solution('+')*(1-s)
            if self.horizontal_dg:
                f += (uv_up[0]*uv_av[0]*jump(self.test[0], self.normal[0]) +
                      uv_up[0]*uv_av[1]*jump(self.test[0], self.normal[1]) +
                      uv_up[1]*uv_av[0]*jump(self.test[1], self.normal[0]) +
                      uv_up[1]*uv_av[1]*jump(self.test[1], self.normal[1]))*(dS_v + dS_h)
                # Lax-Friedrichs stabilization
                if lax_friedrichs_factor is not None and uv_mag is not None:
                    if uv_p1 is not None:
                        gamma = 0.5*abs((avg(uv_p1)[0]*self.normal('-')[0] +
                                         avg(uv_p1)[1]*self.normal('-')[1]))*lax_friedrichs_factor
                    elif uv_mag is not None:
                        gamma = 0.5*avg(uv_mag)*lax_friedrichs_factor
                    else:
                        raise Exception('either uv_p1 or uv_mag must be given')
                    f += gamma*(jump(self.test[0])*jump(solution[0]) +
                                jump(self.test[1])*jump(solution[1]))*dS_v
                for bnd_marker in self.boundary_markers:
                    funcs = self.bnd_functions.get(bnd_marker)
                    ds_bnd = ds_v(int(bnd_marker))
                    if funcs is None:
                        un = dot(solution, self.normal)
                        uv_ext = solution - 2*un*self.normal
                        if lax_friedrichs_factor is not None:
                            gamma = 0.5*abs(un)*lax_friedrichs_factor
                            f += gamma*(self.test[0]*(solution[0] - uv_ext[0]) +
                                        self.test[1]*(solution[1] - uv_ext[1]))*ds_bnd
                    elif 'flux' in funcs:
                        # prescribe normal volume flux
                        sect_len = Constant(self.boundary_len[bnd_marker])
                        un_ext = funcs['flux'] / total_h / sect_len
                        if self.nonlin:
                            uv_in = solution
                            uv_ext = self.normal*un_ext
                            uv_av = 0.5*(uv_in + uv_ext)
                            un_av = uv_av[0]*self.normal[0] + uv_av[1]*self.normal[1]
                            s = 0.5*(sign(un_av) + 1.0)
                            uv_up = uv_in*s + uv_ext*(1-s)
                            f += (uv_up[0]*self.test[0]*self.normal[0]*uv_av[0] +
                                  uv_up[0]*self.test[0]*self.normal[1]*uv_av[1] +
                                  uv_up[1]*self.test[1]*self.normal[0]*uv_av[0] +
                                  uv_up[1]*self.test[1]*self.normal[1]*uv_av[1])*ds_bnd
                            # Lax-Friedrichs stabilization
                            if lax_friedrichs_factor is not None:
                                gamma = 0.5*abs(un_av)*lax_friedrichs_factor
                                f += gamma*(self.test[0]*(uv_in[0] - uv_ext[0]) +
                                            self.test[1]*(uv_in[1] - uv_ext[1]))*ds_bnd

            # surf/bottom boundary conditions: closed at bed, symmetric at surf
            f += (solution[0]*solution[0]*self.test[0]*self.normal[0] +
                  solution[0]*solution[1]*self.test[0]*self.normal[1] +
                  solution[1]*solution[0]*self.test[1]*self.normal[0] +
                  solution[1]*solution[1]*self.test[1]*self.normal[1])*(ds_surf)
        else:
            f = inner(div(outer(solution, solution)), self.test)*dx
        return f

    def rhs_implicit(self, solution, wind_stress=None, **kwargs):
        """Returns all the terms that are treated semi-implicitly.
        """
        f = 0
        return -f

    def rhs(self, solution, eta, w=None, viscosity_v=None,
            viscosity_h=None, coriolis=None, baroc_head=None,
            uv_bottom=None, bottom_drag=None, lin_drag=None,
            w_mesh=None, dw_mesh_dz=None, lax_friedrichs_factor=None,
            uv_mag=None, uv_p1=None, **kwargs):
        """Returns the right hand side of the equations.
        RHS is all terms that depend on the solution (eta,uv)"""
        f = 0  # holds all dx volume integral terms
        g = 0  # holds all ds boundary interface terms

        if self.nonlin:
            total_h = self.bathymetry + eta
        else:
            total_h = self.bathymetry

        # external pressure gradient
        f += self.pressure_grad(eta, baroc_head, solution, total_h, by_parts=self.grad_eta_by_parts)

        # Advection term
        if self.nonlin:
            f += self.horizontal_advection(solution, total_h, lax_friedrichs_factor,
                                           uv_mag=uv_mag, uv_p1=uv_p1)

            # Vertical advection term
            if w is not None:
                vertvelo = w[2]
                if w_mesh is not None:
                    vertvelo = w[2]-w_mesh
                adv_v = -(Dx(self.test[0], 2)*solution[0]*vertvelo +
                          Dx(self.test[1], 2)*solution[1]*vertvelo)
                f += adv_v * dx
                if self.vertical_dg:
                    s = 0.5*(sign(avg(w[2])*self.normal[2]('-')) + 1.0)
                    uv_up = solution('-')*s + solution('+')*(1-s)
                    w_av = avg(w[2])
                    g += (uv_up[0]*w_av*jump(self.test[0], self.normal[2]) +
                          uv_up[1]*w_av*jump(self.test[1], self.normal[2]))*dS_h
                    if lax_friedrichs_factor is not None:
                        # Lax-Friedrichs
                        gamma = 0.5*abs(w_av*self.normal('-')[2])*lax_friedrichs_factor
                        g += gamma*(jump(self.test[0])*jump(solution[0]) +
                                    jump(self.test[1])*jump(solution[1]))*dS_h
                g += (solution[0]*vertvelo*self.test[0]*self.normal[2] +
                      solution[1]*vertvelo*self.test[1]*self.normal[2])*(ds_surf)
            # NOTE bottom impermeability condition is naturally satisfied by the defition of w

        # Non-conservative ALE source term
        if dw_mesh_dz is not None:
            f += dw_mesh_dz*(solution[0]*self.test[0] +
                             solution[1]*self.test[1])*dx

        # boundary conditions
        for bnd_marker in self.boundary_markers:
            funcs = self.bnd_functions.get(bnd_marker)
            ds_bnd = ds_v(int(bnd_marker))
            un_in = (solution[0]*self.normal[0] + solution[1]*self.normal[1])
            if funcs is None:
                # assume land boundary
                continue

            elif 'elev' in funcs:
                # prescribe elevation only
                h_ext = funcs['elev']
                g += g_grav*(eta + h_ext)/2*dot(self.normal, self.test)*ds_bnd
                # symmetric term for advection
                if self.nonlin:
                    un = dot(solution, self.normal)
                    outflow = 0.5*(sign(un) + 1.0)
                    uv_in = solution*(0.75 + 0.25*outflow)
                    g += (uv_in[0]*self.test[0]*un +
                          uv_in[1]*self.test[1]*un)*ds_bnd

            elif 'un' in funcs:
                # prescribe normal volume flux
                un_ext = funcs['un']
                if self.nonlin:
                    uv_in = solution
                    uv_ext = self.normal*un_ext
                    uv_av = 0.5*(uv_in + uv_ext)
                    un_av = uv_av[0]*self.normal[0] + uv_av[1]*self.normal[1]
                    s = 0.5*(sign(un_av) + 1.0)
                    uv_up = uv_in*s + uv_ext*(1-s)
                    g += (uv_up[0]*self.test[0]*self.normal[0]*uv_in[0] +
                          uv_up[0]*self.test[0]*self.normal[1]*uv_in[1] +
                          uv_up[1]*self.test[1]*self.normal[0]*uv_in[0] +
                          uv_up[1]*self.test[1]*self.normal[1]*uv_in[1])*ds_bnd
                    # Lax-Friedrichs stabilization
                    gamma = abs(un_av)
                    g += gamma*dot(self.test, (uv_in - uv_ext)/2)*ds_bnd

            elif 'symm' in funcs:
                if self.nonlin:
                    uv_in = un_in*self.normal
                    g += (uv_in[0]*self.test[0]*self.normal[0]*uv_in[0] +
                          uv_in[0]*self.test[0]*self.normal[1]*uv_in[1] +
                          uv_in[1]*self.test[1]*self.normal[0]*uv_in[0] +
                          uv_in[1]*self.test[1]*self.normal[1]*uv_in[1])*ds_bnd

        # Coriolis
        if coriolis is not None:
            f += coriolis*(-solution[1]*self.test[0] +
                           solution[0]*self.test[1])*dx

        # horizontal viscosity
        if viscosity_h is not None:
            f_visc = viscosity_h * (Dx(solution[0], 0) * Dx(self.test[0], 0) +
                                    Dx(solution[1], 0) * Dx(self.test[1], 0) +
                                    Dx(solution[0], 1) * Dx(self.test[0], 1) +
                                    Dx(solution[1], 1) * Dx(self.test[1], 1))
            if self.horizontal_dg:
                # interface term
                mu_grad_sol = viscosity_h*nabla_grad(solution)
                f += -(avg(mu_grad_sol[0, 0])*jump(self.test[0], self.normal[0]) +
                       avg(mu_grad_sol[0, 1])*jump(self.test[1], self.normal[0]) +
                       avg(mu_grad_sol[1, 0])*jump(self.test[0], self.normal[1]) +
                       avg(mu_grad_sol[1, 1])*jump(self.test[1], self.normal[1]))*(dS_v+dS_h)
                # TODO symmetric interior penalty term
            f += f_visc * dx

        # vertical viscosity
        if viscosity_v is not None:
            f += viscosity_v*(Dx(self.test[0], 2)*Dx(solution[0], 2) +
                              Dx(self.test[1], 2)*Dx(solution[1], 2)) * dx
            if self.vertical_dg:
                int_visc_flux = (jump(self.test[0]*Dx(solution[0], 2), self.normal[2]) +
                                 jump(self.test[1]*Dx(solution[1], 2), self.normal[2]))
                g += -avg(viscosity_v) * int_visc_flux * dS_h
                # viscflux = viscosity_v*Dx(solution, 2)
                # G += -(avg(viscflux[0])*jump(self.test[0], normal[2]) +
                #        avg(viscflux[0])*jump(self.test[1], normal[2]))

        # Linear drag (consistent with drag in 2D mode)
        if lin_drag is not None:
            bottom_fri = lin_drag*inner(self.test, solution)*dx
            f += bottom_fri

        return -f - g

    def source(self, eta, w=None, viscosity_v=None,
               uv_bottom=None, bottom_drag=None, baroc_head=None,
               source=None, **kwargs):
        """Returns the right hand side of the source terms.
        These terms do not depend on the solution."""
        f = 0

        if source is not None:
            f += -inner(source, self.test)*dx

        if viscosity_v is not None:
            # bottom friction
            if bottom_drag is not None and uv_bottom is not None:
                stress = bottom_drag*sqrt(uv_bottom[0]**2 +
                                          uv_bottom[1]**2)*uv_bottom
                bot_friction = (stress[0]*self.test[0] +
                                stress[1]*self.test[1])*ds_bottom
                f += bot_friction

        return -f


class VerticalMomentumEquation(Equation):
    """Vertical advection and diffusion terms of 3D momentum equation for
    hydrostatic Boussinesq flow."""
    def __init__(self, solution, w=None,
                 viscosity_v=None, uv_bottom=None, bottom_drag=None,
                 wind_stress=None, v_elem_size=None, source=None):
        self.space = solution.function_space()
        self.mesh = self.space.mesh()
        self.solution = solution
        self.v_elem_size = v_elem_size
        # this dict holds all time dep. args to the equation
        self.kwargs = {'w': w,
                       'viscosity_v': viscosity_v,
                       'uv_bottom': uv_bottom,
                       'bottom_drag': bottom_drag,
                       'wind_stress': wind_stress,
                       'source': source,
                       }

        # test and trial functions
        self.test = TestFunction(self.space)
        self.tri = TrialFunction(self.space)

        ufl_elem = self.space.ufl_element()
        if isinstance(ufl_elem, EnrichedElement):
            # get the first elem of enriched space
            ufl_elem = ufl_elem._elements[0]
        if not hasattr(ufl_elem, '_A'):
            # For HDiv elements
            ufl_elem = ufl_elem._element
        self.horizontal_dg = ufl_elem._A.family() != 'Lagrange'
        self.vertical_dg = ufl_elem._B.family() != 'Lagrange'

        # mesh dependent variables
        self.normal = FacetNormal(self.mesh)
        self.xyz = SpatialCoordinate(self.mesh)
        self.e_x, self.e_y, self.e_y = unit_vectors(3)

        # set boundary conditions
        # maps bnd_marker to dict of external functions e.g. {'elev':eta_ext}
        self.bnd_functions = {}

    def get_time_step(self, u_mag=Constant(1.0)):
        raise NotImplementedError('get_time_step not implemented')

    def mass_term(self, solution):
        """All time derivative terms on the LHS, without the actual time
        derivative.

        Implements A(u) for  d(A(u_{n+1}) - A(u_{n}))/dt
        """
        return inner(solution, self.test) * dx
        # return (solution[0]*self.test[0] + solution[1]*self.test[1]) * dx

    def rhs_implicit(self, solution, wind_stress=None, **kwargs):
        """Returns all the terms that are treated semi-implicitly.
        """
        f = 0
        return -f

    def rhs(self, solution, w=None, viscosity_v=None,
            uv_bottom=None, bottom_drag=None,
            **kwargs):
        """Returns the right hand side of the equations.
        Contains all terms that depend on the solution."""
        f = 0

        # Advection term
        if w is not None:
            # Vertical advection
            adv_v = -(Dx(self.test[0], 2)*solution[0]*w +
                      Dx(self.test[1], 2)*solution[1]*w)
            f += adv_v * dx
            if self.vertical_dg:
                # FIXME implement interface terms
                raise NotImplementedError('Adv term not implemented for DG')

        # vertical viscosity
        if viscosity_v is not None:
            f += viscosity_v*inner(Dx(solution, 2), Dx(self.test, 2)) * dx
            if self.vertical_dg:
                visc_flux = viscosity_v*Dx(solution, 2)
                f += -(dot(avg(visc_flux), self.test('+'))*self.normal[2]('+') +
                       dot(avg(visc_flux), self.test('-'))*self.normal[2]('-')) * dS_h
                # symmetric interior penalty stabilization
                ip_fact = Constant(1.0)
                l = avg(self.v_elem_size)
                nb_neigh = 2.
                o = 1.
                d = 3.
                sigma = Constant((o + 1.0)*(o + d)/d * nb_neigh / 2.0) / l
                gamma = sigma*avg(viscosity_v) * ip_fact
                jump_test = (self.test('+')*self.normal[2]('+') +
                             self.test('-')*self.normal[2]('-'))
                f += gamma * dot(jump(solution), jump_test) * dS_h

            # implicit bottom friction
            if bottom_drag is not None:
                z_bot = self.v_elem_size*0.5
                # compute uv_bottom implicitly
                uv_bot = solution + Dx(solution, 2)*z_bot
                uv_bot_old = uv_bottom + Dx(uv_bottom, 2)*z_bot
                uv_bot_mag = sqrt(uv_bot_old[0]**2 + uv_bot_old[1]**2)
                stress = bottom_drag*uv_bot_mag*uv_bot
                bot_friction = (stress[0]*self.test[0] +
                                stress[1]*self.test[1])*ds_bottom
                f += bot_friction

        return -f

    def source(self, w=None, viscosity_v=None,
               uv_bottom=None, bottom_drag=None,
               wind_stress=None, source=None,
               **kwargs):
        """Returns the right hand side of the source terms.
        These terms do not depend on the solution."""
        f = 0  # holds all dx volume integral terms

        if viscosity_v is not None:
            # # bottom friction
            # if bottom_drag is not None and uv_bottom is not None:
            #   stress = bottom_drag*sqrt(uv_bottom[0]**2 +
            #                             uv_bottom[1]**2)*uv_bottom
            #   BotFriction = (stress[0]*self.test[0] +
            #                  stress[1]*self.test[1])*ds_bottom
            #   #F += BotFriction
            # wind stress
            if wind_stress is not None:
                f -= (wind_stress[0]*self.test[0] +
                      wind_stress[1]*self.test[1])/rho_0*ds_surf
        if source is not None:
            f += - inner(source, self.test)*dx

        return -f
